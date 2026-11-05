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


if __name__=='__main__':unittest.main()
