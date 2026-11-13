import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import fitz


class BatchTests(unittest.TestCase):
    def test_polling_summary_does_not_load_private_findings_for_every_completed_job(self):
        ident=self.batch.enqueue(self.db,[self.pdf()])[0];self.batch.claim_next(self.db)
        self.batch.set_stage_result(self.db,ident,expected_state='PREPARING',result={'state':'NEEDS_REVIEW',
            'output':'private.pdf','machine_seconds':10,'verification':{'status':'NEEDS_REVIEW',
                'findings':[{'text':'FAKE PRIVATE NAME'*20} for _ in range(100)],'unreadable_pages':[1]}})
        summary=self.batch.list_jobs(self.db,details=False)[0]
        self.assertEqual(summary['result']['verification']['finding_count'],100)
        self.assertEqual(summary['result']['verification']['unreadable_count'],1)
        self.assertEqual(summary['result']['machine_seconds'],10)
        self.assertNotIn('FAKE PRIVATE NAME',json.dumps(summary))
    def test_retry_waits_for_running_cancellation_acknowledgement(self):
        ident=self.batch.enqueue(self.db,[self.pdf()])[0];self.batch.claim_next(self.db)
        self.batch.cancel_job(self.db,ident)
        self.assertEqual(self.batch.get_job(self.db,ident)['state'],'CANCELLING')
        with self.assertRaises(ValueError):self.batch.retry_job(self.db,ident)
        self.assertIsNone(self.batch.claim_next(self.db))
        self.batch.recover_queue(self.db)
        self.assertEqual(self.batch.get_job(self.db,ident)['state'],'CANCELLED')
        self.batch.retry_job(self.db,ident)
        self.assertEqual(self.batch.claim_next(self.db)['id'],ident)

    def test_cancel_wins_when_completion_races_after_worker_teardown(self):
        ident=self.batch.enqueue(self.db,[self.pdf()])[0];self.batch.claim_next(self.db)
        self.batch.cancel_job(self.db,ident)
        self.batch.finish_worker(self.db,ident,{'state':'NEEDS_REVIEW','revision':0})
        self.assertEqual(self.batch.get_job(self.db,ident)['state'],'CANCELLED')

    def test_disk_reserve_keeps_active_unfinished_bytes(self):
        ids=self.batch.enqueue(self.db,[self.pdf(f'{i}.pdf',f'Clinical {i}') for i in range(2)])
        row=self.batch.claim_next(self.db)
        all_rows=self.batch.list_jobs(self.db)
        required=self.batch.disk_reservation(all_rows)
        pending=self.batch.disk_reservation([r for r in all_rows if r['state']=='QUEUED'])
        self.assertGreater(required,pending)
        folder=Path(row['job_dir']);folder.mkdir(parents=True)
        (folder/'partial').write_bytes(b'x'*1024)
        self.assertEqual(self.batch.disk_reservation(self.batch.list_jobs(self.db)),required-1024)

    def test_unsuitable_power_defers_admission(self):
        gib=1024**3
        self.assertFalse(self.batch.can_admit(total_ram=12*gib,available_ram=8*gib,batch_rss=0,
            next_peak=gib,free_disk=10*gib,reserved_disk=gib,power_ok=False))
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('batch'), 'Durable independent-file queue is missing')
        import batch
        self.batch = batch
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root/'queue'/'queue.sqlite3'

    def pdf(self, name='source.pdf', text='Clinical C34 glucose 5.2'):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open() as doc:
            doc.new_page().insert_text((40, 60), text)
            doc.save(path)
        return path

    def test_enqueue_persists_and_does_not_merge_independent_patients(self):
        a=self.pdf('a/same.pdf', 'Ho ten: NGUYEN VAN AN')
        b=self.pdf('b/same.pdf', 'Ho ten: TRAN THI BINH')
        ids=self.batch.enqueue(self.db, [a,b])
        self.assertEqual(len(set(ids)),2)
        rows=[self.batch.get_job(self.db,i) for i in ids]
        self.assertNotEqual(rows[0]['job_dir'],rows[1]['job_dir'])
        self.assertEqual([r['state'] for r in rows],['QUEUED','QUEUED'])
        self.assertTrue(all(r['pages']==1 for r in rows))
        self.assertEqual(self.batch.enqueue(self.db,[a]),[ids[0]])

    def test_duplicate_bytes_are_explicit_and_do_not_consume_worker(self):
        a=self.pdf(); b=self.root/'copy.pdf'; b.write_bytes(a.read_bytes())
        ids=self.batch.enqueue(self.db,[a,b])
        second=self.batch.get_job(self.db,ids[1])
        self.assertEqual(second['state'],'DUPLICATE')
        self.assertEqual(second['duplicate_of'],ids[0])
        self.assertEqual(self.batch.claim_next(self.db)['id'],ids[0])
        self.assertIsNone(self.batch.claim_next(self.db))

    def test_claim_is_exclusive_and_review_backlog_never_blocks_next_file(self):
        ids=self.batch.enqueue(self.db,[self.pdf(f'{i}.pdf',f'Clinical {i}') for i in range(3)])
        first=self.batch.claim_next(self.db); second=self.batch.claim_next(self.db)
        self.assertNotEqual(first['id'],second['id'])
        self.batch.set_stage_result(self.db,first['id'],expected_state='PREPARING',result={'state':'NEEDS_REVIEW','revision':0})
        self.assertEqual(self.batch.claim_next(self.db)['id'],ids[2])
        self.assertEqual(self.batch.get_job(self.db,ids[0])['state'],'NEEDS_REVIEW')

    def test_pause_stops_admission_but_keeps_completed_review_jobs(self):
        ident=self.batch.enqueue(self.db,[self.pdf()])[0]
        self.batch.pause_queue(self.db)
        self.assertIsNone(self.batch.claim_next(self.db))
        self.batch.resume_queue(self.db)
        self.assertEqual(self.batch.claim_next(self.db)['id'],ident)

    def test_stale_stage_result_cannot_overwrite_new_revision(self):
        ident=self.batch.enqueue(self.db,[self.pdf()])[0]
        self.batch.claim_next(self.db)
        self.batch.set_stage_result(self.db,ident,expected_state='PREPARING',result={'state':'NEEDS_REVIEW','revision':2})
        with self.assertRaises(ValueError):
            self.batch.set_stage_result(self.db,ident,expected_state='PREPARING',result={'state':'READY','revision':0})
        self.assertEqual(self.batch.get_job(self.db,ident)['revision'],2)

    def test_worker_cannot_mark_unreviewed_output_ready(self):
        ident=self.batch.enqueue(self.db,[self.pdf()])[0];self.batch.claim_next(self.db)
        with self.assertRaises(ValueError):
            self.batch.set_stage_result(self.db,ident,expected_state='PREPARING',result={'state':'READY','revision':0})

    def test_recovery_keeps_review_backlog_and_requeues_interrupted_work(self):
        ids=self.batch.enqueue(self.db,[self.pdf(f'{i}.pdf',f'Clinical {i}') for i in range(2)])
        for ident in ids:self.batch.claim_next(self.db)
        self.batch.set_stage_result(self.db,ids[0],expected_state='PREPARING',result={'state':'NEEDS_REVIEW','revision':1})
        self.batch.recover_queue(self.db)
        self.batch.recover_queue(self.db)
        self.assertEqual(self.batch.get_job(self.db,ids[0])['state'],'NEEDS_REVIEW')
        self.assertEqual(self.batch.get_job(self.db,ids[1])['state'],'QUEUED')

    def test_bad_pdf_is_recorded_without_losing_other_files(self):
        bad=self.root/'broken.pdf';bad.write_bytes(b'broken')
        ids=self.batch.enqueue(self.db,[bad,self.pdf()])
        self.assertEqual(len(ids),2)
        self.assertEqual(self.batch.get_job(self.db,ids[0])['state'],'FAILED')
        self.assertEqual(self.batch.claim_next(self.db)['id'],ids[1])

    def test_job_lookup_rejects_paths_and_sql_fragments(self):
        self.batch.enqueue(self.db,[self.pdf()])
        for value in ('../source', "' OR 1=1 --",'', '0'*32):
            with self.assertRaises(ValueError):self.batch.get_job(self.db,value)

    def test_source_change_is_not_silently_reused(self):
        source=self.pdf();ident=self.batch.enqueue(self.db,[source])[0]
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.batch.snapshot_source(self.batch.get_job(self.db,ident))
        self.assertEqual(source.read_bytes(),b'changed')

    def test_private_snapshot_does_not_import_parent_case_seeds(self):
        source=self.pdf('NGUYEN VAN KHAC/2600000001 TRAN THI BINH.pdf')
        ident=self.batch.enqueue(self.db,[source])[0]
        row=self.batch.get_job(self.db,ident)
        private=self.batch.snapshot_source(row)
        from hmu_recognizers import extract_case_seeds
        seeds=extract_case_seeds(private,source_name=source.name,xml_index=[])
        self.assertEqual(seeds.get('PATIENT_NAME'),['TRAN THI BINH'])

    def test_resource_pressure_defers_admission(self):
        gib=1024**3
        self.assertTrue(self.batch.can_admit(available_ram=4*gib,batch_rss=gib,next_peak=gib,free_disk=10*gib,reserved_disk=gib,total_ram=12*gib))
        self.assertFalse(self.batch.can_admit(available_ram=gib,batch_rss=gib,next_peak=gib,free_disk=10*gib,reserved_disk=gib,total_ram=12*gib))
        self.assertFalse(self.batch.can_admit(available_ram=4*gib,batch_rss=gib,next_peak=gib,free_disk=2*gib,reserved_disk=gib,total_ram=12*gib))

    def test_two_coordinators_cannot_own_same_queue(self):
        self.batch.enqueue(self.db,[self.pdf()])
        with self.batch.queue_lock(self.db):
            with self.assertRaises(RuntimeError):
                with self.batch.queue_lock(self.db):pass

    def test_discovery_excludes_queue_and_resolved_paths_outside_root(self):
        src=self.root/'inputs';src.mkdir();self.pdf('inputs/ok.pdf')
        self.pdf('inputs/HMU_JOBS/private.pdf')
        found=self.batch.discover_sources(src)
        self.assertEqual([p.name for p in found],['ok.pdf'])

    def test_worker_budget_reaches_render_and_ocr(self):
        import inspect
        import engine
        from unittest.mock import patch
        self.assertIn('ocr_workers',inspect.signature(engine.prepare).parameters)
        self.assertIn('render_workers',inspect.signature(engine.prepare).parameters)
        source=self.root/'scan.pdf'
        with fitz.open() as d:
            p=d.new_page(width=100,height=100)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(255)
            p.insert_image(p.rect,pixmap=pix);d.save(source)
        with patch.object(engine,'ocr_pdf_pages',return_value={1:('',[])}) as ocr, patch.object(engine,'_render_scan_pages',wraps=engine._render_scan_pages) as render:
            engine.prepare(source,self.root/'budget_job',case_xml_index=[],ocr_workers=2,render_workers=1)
        self.assertEqual(ocr.call_args.kwargs['max_workers'],2)
        self.assertEqual(render.call_args.kwargs['max_workers'],1)

    def test_preclone_folders_on_enqueue_and_schema_migration(self):
        import sqlite3
        import delivery

        data_root = self.root / 'Data_Root'
        data_deidentified = self.root / 'Data_Deidentified'
        ba1_dir = data_root / 'BA001_NguyenVanA'
        ba2_dir = data_root / 'BA002_TranThiB'
        ba1_dir.mkdir(parents=True, exist_ok=True)
        ba2_dir.mkdir(parents=True, exist_ok=True)

        to_bia = ba1_dir / 'to_bia.pdf'
        xet_nghiem = ba2_dir / 'xet_nghiem.pdf'
        with fitz.open() as d:
            d.new_page().insert_text((50, 50), "Benh an BA001")
            d.save(to_bia)
        with fitz.open() as d:
            d.new_page().insert_text((50, 50), "Benh an BA002")
            d.save(xet_nghiem)

        # 1. Test delivery.preclone_patient_folders
        clone_info = delivery.preclone_patient_folders([data_root], data_deidentified, data_root=data_root)
        self.assertIn('cloned_folders', clone_info)
        self.assertTrue((data_deidentified / 'BA001_NguyenVanA').is_dir())
        self.assertTrue((data_deidentified / 'BA002_TranThiB').is_dir())
        self.assertEqual(len(list((data_deidentified / 'BA001_NguyenVanA').iterdir())), 0)
        self.assertEqual(len(list((data_deidentified / 'BA002_TranThiB').iterdir())), 0)

        # Check mapping
        self.assertEqual(clone_info[str(to_bia.resolve())], str((data_deidentified / 'BA001_NguyenVanA').resolve()))
        self.assertEqual(clone_info[str(xet_nghiem.resolve())], str((data_deidentified / 'BA002_TranThiB').resolve()))

        # 2. Test batch.enqueue with target_folders
        ids = self.batch.enqueue(self.db, [to_bia, xet_nghiem], target_folders=clone_info.get('mappings', clone_info))
        self.assertEqual(len(ids), 2)

        # Verify target_folder in sqlite jobs table
        with sqlite3.connect(self.db) as con:
            con.row_factory = sqlite3.Row
            row1 = con.execute("SELECT target_folder FROM jobs WHERE source_path=?", (str(to_bia.resolve()),)).fetchone()
            self.assertIsNotNone(row1)
            self.assertEqual(row1['target_folder'], str((data_deidentified / 'BA001_NguyenVanA').resolve()))

            row2 = con.execute("SELECT target_folder FROM jobs WHERE source_path=?", (str(xet_nghiem.resolve()),)).fetchone()
            self.assertIsNotNone(row2)
            self.assertEqual(row2['target_folder'], str((data_deidentified / 'BA002_TranThiB').resolve()))

        # 3. Test schema migration on legacy database without target_folder column
        legacy_db = self.root / 'legacy' / 'queue.sqlite3'
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(legacy_db) as con:
            con.execute('''CREATE TABLE jobs (
                id TEXT PRIMARY KEY, source_path TEXT NOT NULL, source_name TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, pages INTEGER NOT NULL, state TEXT NOT NULL,
                job_dir TEXT NOT NULL, duplicate_of TEXT, revision INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL, updated REAL NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(source_path, source_sha256))''')
            con.commit()

        # Enqueue into legacy_db should auto migrate
        legacy_ids = self.batch.enqueue(legacy_db, [to_bia], target_folders={str(to_bia.resolve()): str(data_deidentified / 'BA001_NguyenVanA')})
        self.assertEqual(len(legacy_ids), 1)
        job = self.batch.get_job(legacy_db, legacy_ids[0])
        self.assertEqual(job.get('target_folder'), str((data_deidentified / 'BA001_NguyenVanA').resolve()))

    def test_release_folder_routes_to_cloned_patient_folders_without_mixing_and_handles_collision(self):
        import json, fitz, batch_worker, engine, delivery
        from unittest.mock import patch

        data_root = self.root / 'Test_Data_Root'
        data_deid = self.root / 'Test_Data_Deidentified'
        ba1 = data_root / 'BN_01'
        ba2 = data_root / 'BN_02'
        ba1.mkdir(parents=True, exist_ok=True)
        ba2.mkdir(parents=True, exist_ok=True)

        to_bia_1 = ba1 / 'to_bia.pdf'
        to_bia_2 = ba2 / 'to_bia.pdf'
        with fitz.open() as d:
            d.new_page().insert_text((50, 50), "Benh nhan so 1")
            d.save(to_bia_1)
        with fitz.open() as d:
            d.new_page().insert_text((50, 50), "Benh nhan so 2")
            d.save(to_bia_2)

        # 1. Pre-clone
        clone_res = delivery.preclone_patient_folders([data_root], data_deid, data_root=data_root)
        self.assertTrue((data_deid / 'BN_01').is_dir())
        self.assertTrue((data_deid / 'BN_02').is_dir())
        self.assertEqual(len(list((data_deid / 'BN_01').iterdir())), 0)
        self.assertEqual(len(list((data_deid / 'BN_02').iterdir())), 0)

        # 2. Enqueue
        ids = self.batch.enqueue(self.db, [to_bia_1, to_bia_2], target_folders=clone_res['mappings'])

        # 3. Process jobs
        for ident, text in [(ids[0], "Benh nhan so 1"), (ids[1], "Benh nhan so 2")]:
            row = self.batch.claim_next(self.db)
            self.assertEqual(row['id'], ident)
            with patch('output_qc.ocr_pdf_pages', return_value={1: (text, [])}):
                res = batch_worker.process_job(row, ocr_workers=1, render_workers=1)
            self.batch.finish_worker(self.db, ident, res)
            engine.approve_all_pages(Path(row['job_dir']) / 'review')

        # 4. Xuất hàng loạt lần 1
        out = self.batch.release_folder(self.db, [str(data_root)], data_deid)
        self.assertEqual(len(out['exported']), 2)
        self.assertEqual(out['pending'], [])

        # Kiểm tra file đổ đúng folder đã clone, KHÔNG trộn lẫn, KHÔNG có subfolder hex id
        out_ba1 = data_deid / 'BN_01' / 'to_bia.pdf'
        out_ba2 = data_deid / 'BN_02' / 'to_bia.pdf'
        self.assertTrue(out_ba1.is_file())
        self.assertTrue(out_ba2.is_file())

        # Kiểm tra manifest và qc riêng của từng bệnh án
        self.assertTrue((data_deid / 'BN_01' / 'manifest.json').is_file())
        self.assertTrue((data_deid / 'BN_01' / 'qc.json').is_file())
        self.assertTrue((data_deid / 'BN_02' / 'manifest.json').is_file())
        self.assertTrue((data_deid / 'BN_02' / 'qc.json').is_file())

        m1 = json.loads((data_deid / 'BN_01' / 'manifest.json').read_text(encoding='utf-8'))
        m2 = json.loads((data_deid / 'BN_02' / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(m1['files']), 1)
        self.assertEqual(len(m2['files']), 1)
        self.assertEqual(m1['files'][0]['file'], 'to_bia.pdf')
        self.assertEqual(m2['files'][0]['file'], 'to_bia.pdf')
        self.assertNotEqual(m1['files'][0]['output_hash'], m2['files'][0]['output_hash'])

        # 5. Xuất hàng loạt lần 2 -> tạo bản sao _Copy1 cho cả 2 folder bệnh án
        out2 = self.batch.release_folder(self.db, [str(data_root)], data_deid)
        self.assertEqual(len(out2['exported']), 2)
        self.assertTrue(len(out2.get('comparisons', [])) >= 2)

        out_ba1_copy = data_deid / 'BN_01_Copy1' / 'to_bia.pdf'
        out_ba2_copy = data_deid / 'BN_02_Copy1' / 'to_bia.pdf'
        self.assertTrue(out_ba1_copy.is_file())
        self.assertTrue(out_ba2_copy.is_file())
        # Bản cũ vẫn nguyên vẹn
        self.assertTrue(out_ba1.is_file())
        self.assertTrue(out_ba2.is_file())

    def test_reap_active_workers_records_error_when_worker_crashes_without_error_json(self):
        from unittest.mock import MagicMock
        self.db = self.root / 'jobs' / 'batch' / 'queue.sqlite3'
        ident = self.batch.enqueue(self.db, [self.pdf()])[0]
        row = self.batch.claim_next(self.db)
        # Advance attempts to MAX_ATTEMPTS so it transitions directly to FAILED
        with self.batch._db(self.db) as con:
            con.execute('UPDATE jobs SET attempts=? WHERE id=?', (self.batch.QueueLimits.MAX_ATTEMPTS, ident))
        row = self.batch.get_job(self.db, ident)

        fake_proc = MagicMock()
        fake_proc.process.poll.return_value = 137  # OOM / SIGKILL exit code, no error_{attempt_id}.json written
        active = {
            ident: {
                'process': fake_proc,
                'attempt_id': 'deadbeef1234',
                'started': 0.0,
            }
        }
        mutated = self.batch._reap_active_workers(self.db, active, {ident: row}, timeout_seconds=900)
        self.assertTrue(mutated)
        self.assertEqual(active, {})
        updated_job = self.batch.get_job(self.db, ident)
        self.assertEqual(updated_job['state'], 'FAILED')
        self.assertIn('Worker stopped with exit 137', updated_job['error'])
        self.assertEqual(updated_job['result']['error_detail']['stage'], 'BATCH_WORKER')
        self.assertTrue((self.root / 'jobs' / 'error_report.json').is_file())

    def test_summary_fields_include_error_detail_for_failed_jobs(self):
        ident = self.batch.enqueue(self.db, [self.pdf()])[0]
        self.batch.claim_next(self.db)
        err_detail = {
            'id': 'err_01',
            'category': 'CODE_ERROR',
            'stage': 'BATCH_WORKER',
            'message': 'Worker stopped with exit 1',
            'source_file': 'source.pdf',
            'code_location': {'file': 'batch_worker.py', 'line': 42, 'function': 'run'},
        }
        self.batch.set_stage_result(
            self.db,
            ident,
            expected_state='PREPARING',
            result={'state': 'FAILED', 'error': 'Worker stopped with exit 1', 'error_detail': err_detail},
        )
        summary = self.batch.list_jobs(self.db, details=False)[0]
        self.assertEqual(summary['result'].get('error_detail'), err_detail)

    def test_enqueue_batches_multiple_files_in_single_db_transaction(self):
        from unittest.mock import patch
        p1 = self.pdf('batch1.pdf', 'Patient 1')
        p2 = self.pdf('batch2.pdf', 'Patient 2')
        p3 = self.root / 'batch3_dup.pdf'
        p3.write_bytes(p1.read_bytes())
        p4 = self.root / 'batch4_bad.pdf'
        p4.write_bytes(b'corrupt pdf bytes')

        with patch.object(self.batch, '_db', wraps=self.batch._db) as mock_db:
            ids = self.batch.enqueue(self.db, [p1, p2, p3, p4])
            self.assertEqual(mock_db.call_count, 1)

        self.assertEqual(len(ids), 4)
        self.assertEqual(self.batch.get_job(self.db, ids[0])['state'], 'QUEUED')
        self.assertEqual(self.batch.get_job(self.db, ids[1])['state'], 'QUEUED')
        self.assertEqual(self.batch.get_job(self.db, ids[2])['state'], 'DUPLICATE')
        self.assertEqual(self.batch.get_job(self.db, ids[2])['duplicate_of'], ids[0])
        self.assertEqual(self.batch.get_job(self.db, ids[3])['state'], 'FAILED')

    def test_enqueue_failed_files_preserve_distinct_root_causes_and_error_detail(self):
        self.db = self.root / 'jobs' / 'batch' / 'queue.sqlite3'
        corrupt = self.root / 'corrupt.pdf'
        corrupt.write_bytes(b'not a pdf at all')
        empty = self.root / 'empty.pdf'
        empty.write_bytes(b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF')
        encrypted = self.root / 'encrypted.pdf'
        with fitz.open() as doc:
            doc.new_page().insert_text((20, 40), 'Secret')
            doc.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='own', user_pw='usr')

        ids = self.batch.enqueue(self.db, [corrupt, empty, encrypted])
        summaries = {r['id']: r for r in self.batch.list_jobs(self.db, details=False)}
        errors = [summaries[i]['error'] for i in ids]
        self.assertEqual(len(set(errors)), 3, f'Expected 3 distinct errors, got: {errors}')
        for i in ids:
            detail = summaries[i]['result'].get('error_detail')
            self.assertIsNotNone(detail, f'Missing error_detail in summary for {i}')
            self.assertTrue(detail.get('root_cause'), f'Missing root_cause in error_detail for {i}')
        self.assertIn('Empty PDF', summaries[ids[1]]['error'])
        self.assertIn('Encrypted PDF', summaries[ids[2]]['error'])
        self.assertTrue((self.root / 'jobs' / 'error_report.json').is_file())

    def test_reap_active_workers_extracts_worker_log_tail_when_error_json_missing(self):
        from unittest.mock import MagicMock
        self.db = self.root / 'jobs' / 'batch' / 'queue.sqlite3'
        ident = self.batch.enqueue(self.db, [self.pdf()])[0]
        row = self.batch.claim_next(self.db)
        with self.batch._db(self.db) as con:
            con.execute('UPDATE jobs SET attempts=? WHERE id=?', (self.batch.QueueLimits.MAX_ATTEMPTS, ident))
        row = self.batch.get_job(self.db, ident)
        work_dir = Path(row['job_dir'])
        work_dir.mkdir(parents=True, exist_ok=True)
        log_file = work_dir / 'worker_crashlog123.log'
        log_file.write_text(
            'Traceback (most recent call last):\n'
            '  File "batch_worker.py", line 85, in main\n'
            'MemoryError: Unable to allocate 512 MiB for pixmap buffer\n',
            encoding='utf8',
        )
        fake_proc = MagicMock()
        fake_proc.process.poll.return_value = 1
        active = {ident: {'process': fake_proc, 'attempt_id': 'crashlog123', 'started': 0.0}}
        self.batch._reap_active_workers(self.db, active, {ident: row}, timeout_seconds=900)
        updated = self.batch.get_job(self.db, ident)
        self.assertEqual(updated['state'], 'FAILED')
        self.assertIn('MemoryError: Unable to allocate 512 MiB for pixmap buffer', updated['error'])
        self.assertIn('MemoryError', updated['result']['error_detail'].get('root_cause', ''))

    def test_retry_job_and_retry_jobs_handle_repaired_file_and_update_pages(self):
        broken = self.root / 'repaired_later.pdf'
        broken.write_bytes(b'corrupt initial bytes')
        ident = self.batch.enqueue(self.db, [broken])[0]
        self.assertEqual(self.batch.get_job(self.db, ident)['state'], 'FAILED')
        self.assertEqual(self.batch.get_job(self.db, ident)['pages'], 0)

        # User repairs the file on disk and retries via bulk retry_jobs
        with fitz.open() as doc:
            doc.new_page().insert_text((20, 40), 'Page 1 repaired')
            doc.new_page().insert_text((20, 40), 'Page 2 repaired')
            doc.save(broken)

        res = self.batch.retry_jobs(self.db, [ident])
        self.assertEqual(res['retried'], [ident])
        retried_row = self.batch.get_job(self.db, ident)
        self.assertEqual(retried_row['state'], 'QUEUED')
        self.assertEqual(retried_row['pages'], 2)
        self.assertEqual(retried_row['error'], '')
        claimed = self.batch.claim_next(self.db)
        self.assertEqual(claimed['id'], ident)
        # Ensure snapshot_source succeeds with updated sha256
        snap = self.batch.snapshot_source(claimed)
        self.assertTrue(snap.is_file())


if __name__=='__main__':unittest.main()
