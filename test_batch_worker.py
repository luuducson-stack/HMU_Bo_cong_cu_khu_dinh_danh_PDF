import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import batch


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('batch_worker'),'Per-file pipeline worker is missing')
        import batch_worker
        self.worker=batch_worker
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'queue'/'queue.sqlite3'
        source=self.root/'source.pdf'
        with fitz.open() as doc:
            page=doc.new_page(width=240,height=180);page.insert_text((20,40),'Clinical stable glucose 5.2');doc.save(source)
        self.ident=batch.enqueue(self.db,[source])[0];self.row=batch.claim_next(self.db)

    def test_worker_exports_individual_draft_without_waiting_for_human(self):
        with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable glucose 5.2',[])}):
            result=self.worker.process_job(self.row,ocr_workers=1,render_workers=1)
        self.assertEqual(result['state'],'NEEDS_REVIEW')
        self.assertTrue(Path(result['output']).is_file())
        self.assertEqual(result['verification']['pages_checked'],1)
        review=json.loads((Path(self.row['job_dir'])/'review'/'review.json').read_text(encoding='utf8'))
        self.assertFalse(any(p['reviewed'] for p in review['pages']))
        self.assertGreater(result['machine_seconds'],0)

    def test_resume_uses_complete_prepare_checkpoint(self):
        with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable glucose 5.2',[])}):
            first=self.worker.process_job(self.row,ocr_workers=1,render_workers=1)
        with patch('engine.prepare',side_effect=AssertionError('valid prepare must not run twice')):
            second=self.worker.process_job(self.row,ocr_workers=1,render_workers=1)
        self.assertEqual(first['output'],second['output'])
        self.assertEqual(first['verification']['pdf_sha256'],second['verification']['pdf_sha256'])

    def completed(self):
        with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable glucose 5.2',[])}):
            result=self.worker.process_job(self.row,ocr_workers=1,render_workers=1)
        batch.set_stage_result(self.db,self.ident,expected_state='PREPARING',result=result)
        return result,Path(self.row['job_dir'])/'review'

    def test_release_requires_human_review_and_keeps_package_private_data_out(self):
        import engine
        result,job=self.completed()
        with self.assertRaisesRegex(ValueError,'duyệt'):
            batch.release_job(self.db,self.ident,expected_revision=0,destination=self.root/'delivered')
        reviewed=engine.approve_all_pages(job)
        previous=self.root/'delivered'/f"{self.ident}_r{reviewed['revision']}_{result['verification']['pdf_sha256'][:12]}"
        previous.mkdir(parents=True)
        old_pdf=previous/('CASE_'+self.ident[:16]+'_REDACTED.pdf')
        old_pdf.write_bytes(Path(result['output']).read_bytes())
        released=batch.release_job(self.db,self.ident,expected_revision=reviewed['revision'],destination=self.root/'delivered')
        self.assertEqual(Path(released['output']).name,self.row['source_name'])
        self.assertEqual(engine.sha(old_pdf),result['verification']['pdf_sha256'])
        self.assertEqual(batch.get_job(self.db,self.ident)['state'],'READY')
        package=Path(released['directory'])
        self.assertEqual(len(list(package.iterdir())),3)
        manifest=json.loads((package/'manifest.json').read_text(encoding='utf8'))
        self.assertNotIn('source_path',manifest)
        self.assertNotIn('source_name',manifest)
        self.assertEqual(engine.sha(Path(released['output'])),result['verification']['pdf_sha256'])
        self.assertEqual(batch.release_job(self.db,self.ident,expected_revision=reviewed['revision'],destination=self.root/'delivered'),released)

    def test_mask_edit_blocks_stale_qc_and_reprocess_releases_review_slot(self):
        import engine
        result,job=self.completed()
        data=engine.approve_all_pages(job);data['pages'][0]['manual_rects']=[[5,5,15,15]]
        engine.save_json(job/'review.json',data)
        with self.assertRaisesRegex(ValueError,'khử|QC'):
            batch.release_job(self.db,self.ident,expected_revision=data['revision'],destination=self.root/'delivered')
        batch.reprocess_job(self.db,self.ident,expected_revision=data['revision'])
        self.assertEqual(batch.get_job(self.db,self.ident)['state'],'QUEUED')
        self.assertTrue((job/'review.json').exists())

    def test_resume_after_publish_before_queue_commit(self):
        import engine
        self.row['attempt_id']='a1'
        root=Path(self.row['job_dir']);root.mkdir(parents=True)
        engine.save_json(root/'request_a1.json',dict(job=self.row))
        with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable glucose 5.2',[])}):
            self.worker.process_job(self.row,ocr_workers=1,render_workers=1)
        batch.recover_queue(self.db)
        self.assertEqual(batch.get_job(self.db,self.ident)['state'],'NEEDS_REVIEW')
        batch.recover_queue(self.db)
        self.assertEqual(batch.get_job(self.db,self.ident)['attempts'],1)

    def test_retry_keeps_valid_review_edits(self):
        import engine
        result,job=self.completed()
        data=engine.ensure_job(job);data['pages'][0]['manual_rects']=[[5,5,15,15]];data['revision']+=1
        engine.save_json(job/'review.json',data)
        batch.set_stage_result(self.db,self.ident,expected_state='NEEDS_REVIEW',result={'state':'FAILED','revision':1})
        batch.retry_job(self.db,self.ident)
        self.assertEqual(batch.get_job(self.db,self.ident)['job_dir'],self.row['job_dir'])
        self.assertEqual(engine.ensure_job(job)['pages'][0]['manual_rects'],[[5,5,15,15]])

    def test_unresolved_warning_blocks_release_until_explicit_adjudication(self):
        import engine,output_qc
        result,job=self.completed();data=engine.approve_all_pages(job)
        qc=json.loads((job/'output_verification_private.json').read_text(encoding='utf8'))
        qc['findings']=[dict(id='warning1',page=1,kind='PERSON_NAME',text='fake clinical phrase',rects=[])];qc['status']='NEEDS_REVIEW'
        engine.save_json(job/'output_verification_private.json',qc)
        with self.assertRaisesRegex(ValueError,'cảnh báo'):
            batch.release_job(self.db,self.ident,expected_revision=data['revision'],destination=self.root/'out')
        batch.resolve_finding(self.db,self.ident,expected_revision=data['revision'],finding_id='warning1',reason='Verified non-person clinical text',reviewer='test reviewer')
        batch.release_job(self.db,self.ident,expected_revision=data['revision'],destination=self.root/'out')
        self.assertEqual(batch.get_job(self.db,self.ident)['state'],'READY')

    @unittest.skipUnless(os.name=='nt','Windows process ownership')
    def test_two_workers_finish_per_file_and_review_backlog_does_not_block_third(self):
        self.assertTrue(hasattr(batch,'run_queue'),'Concurrent coordinator is missing')
        sources=[]
        for i,count in enumerate((1,3)):
            path=self.root/f'next{i}.pdf'
            with fitz.open() as doc:
                for n in range(count):doc.new_page(width=240,height=180).insert_text((20,40),f'Clinical stable glucose {i}.{n}')
                doc.save(path)
            sources.append(path)
        ids=[self.ident]+batch.enqueue(self.db,sources)
        batch.recover_queue(self.db)
        gib=1024**3
        with patch('batch_runtime.resources',return_value=dict(total_ram=12*gib,available_ram=8*gib,batch_rss=100000000,free_disk=20*gib)):
            result=batch.run_queue(self.db,jobs=2,ocr_workers=1,render_workers=1)
        self.assertEqual(result['max_active_jobs'],2)
        rows=[batch.get_job(self.db,i) for i in ids]
        self.assertTrue(all(r['state']=='NEEDS_REVIEW' for r in rows),rows)
        self.assertTrue(all(Path(r['result']['output']).is_file() for r in rows))
        self.assertTrue(all(not p['reviewed'] for r in rows for p in json.loads((Path(r['job_dir'])/'review'/'review.json').read_text(encoding='utf8'))['pages']))

    @unittest.skipUnless(os.name=='nt','Windows process ownership')
    def test_unreadable_progress_does_not_kill_valid_worker(self):
        read_text=Path.read_text;gib=1024**3
        for n,error in enumerate((PermissionError('file busy'),FileNotFoundError('replaced'),json.JSONDecodeError('partial','{',1))):
            with self.subTest(error=type(error).__name__):
                db=self.root/f'busy{n}'/'queue.sqlite3';ident=batch.enqueue(db,[self.root/'source.pdf'])[0];denied=[]
                def read(path,*args,**kwargs):
                    if path.name=='progress.json':denied.append(path);raise error
                    return read_text(path,*args,**kwargs)
                with patch.object(Path,'read_text',read),patch('batch_runtime.resources',return_value=dict(total_ram=12*gib,available_ram=8*gib,batch_rss=100000000,free_disk=20*gib)):
                    result=batch.run_queue(db,jobs=2,ocr_workers=1,render_workers=1)
                self.assertTrue(denied,'Must exercise a running worker progress read')
                row=batch.get_job(db,ident)
                self.assertEqual(row['state'],'NEEDS_REVIEW');self.assertEqual(row['attempts'],1)
                self.assertTrue(Path(row['result']['output']).is_file());self.assertEqual(result['states']['READY'],0)

    def test_record_error_event_file_error_classification_and_persistence(self):
        from error_pipeline import record_error_event
        err=record_error_event(
            self.root,
            ValueError('PDF hỏng, trống hoặc có mật khẩu; cần kiểm tra nguồn.'),
            stage='BATCH_ENQUEUE',
            source_file='corrupt.pdf',
            queue_id='q1',
        )
        self.assertEqual(err['category'],'FILE_ERROR')
        self.assertEqual(err['stage'],'BATCH_ENQUEUE')
        self.assertEqual(err['source_file'],'corrupt.pdf')
        self.assertEqual(err['queue_id'],'q1')
        self.assertIn('PDF hỏng',err['message'])
        self.assertIn('iso_time',err)
        self.assertIn('timestamp',err)
        report_path=self.root/'error_report.json'
        self.assertTrue(report_path.is_file())
        report=json.loads(report_path.read_text(encoding='utf8'))
        self.assertEqual(report['total_errors'],1)
        self.assertEqual(report['errors'][0]['id'],err['id'])

    def test_record_error_event_code_error_traceback_extraction(self):
        from error_pipeline import record_error_event
        def failing_operation():
            raise TypeError("Invalid operation in engine pipeline")
        try:
            failing_operation()
        except Exception as exc:
            err=record_error_event(self.root,exc,stage='BATCH_WORKER',job_id='job_abc')
        self.assertEqual(err['category'],'CODE_ERROR')
        self.assertEqual(err['stage'],'BATCH_WORKER')
        self.assertEqual(err['job_id'],'job_abc')
        self.assertEqual(err['error_type'],'TypeError')
        self.assertIsNotNone(err['code_location'])
        self.assertEqual(err['code_location']['function'],'failing_operation')
        self.assertEqual(err['code_location']['file'],'test_batch_worker.py')
        self.assertIsInstance(err['code_location']['line'],int)

    def test_worker_main_persists_distinct_root_cause_error_json_without_type_error(self):
        import io
        import engine
        jobs_root = self.root / 'hmu_jobs'
        db = jobs_root / 'batch' / 'queue.sqlite3'
        s1 = self.root / 'err1.pdf'
        s2 = self.root / 'err2.pdf'
        for p, txt in ((s1, 'Case 1'), (s2, 'Case 2')):
            with fitz.open() as doc:
                doc.new_page().insert_text((20, 40), txt)
                doc.save(p)
        ids = batch.enqueue(db, [s1, s2])
        r1 = batch.claim_next(db)
        r2 = batch.claim_next(db)
        r1['attempt_id'] = 'att_one'
        r2['attempt_id'] = 'att_two'
        req1 = Path(r1['job_dir']) / 'request_att_one.json'
        req2 = Path(r2['job_dir']) / 'request_att_two.json'
        req1.parent.mkdir(parents=True, exist_ok=True)
        req2.parent.mkdir(parents=True, exist_ok=True)
        engine.save_json(req1, {'job': r1, 'ocr_workers': 1, 'render_workers': 1})
        engine.save_json(req2, {'job': r2, 'ocr_workers': 1, 'render_workers': 1})

        def fail_one(*args, **kwargs):
            try:
                raise KeyError('missing_font_xref_77')
            except KeyError as cause:
                raise ValueError('Failed to rebuild page 3 redaction') from cause

        def fail_two(*args, **kwargs):
            raise RuntimeError('OCR engine failed on page 5: corrupt image stream')

        with patch.object(self.worker, 'process_job', side_effect=fail_one), \
             patch('sys.argv', ['batch_worker.py', '--request', str(req1)]), \
             patch('sys.stdin', io.StringIO('START\n')):
            with self.assertRaises(ValueError):
                self.worker.main()

        with patch.object(self.worker, 'process_job', side_effect=fail_two), \
             patch('sys.argv', ['batch_worker.py', '--request', str(req2)]), \
             patch('sys.stdin', io.StringIO('START\n')):
            with self.assertRaises(RuntimeError):
                self.worker.main()

        err_file_1 = Path(r1['job_dir']) / 'error_att_one.json'
        err_file_2 = Path(r2['job_dir']) / 'error_att_two.json'
        self.assertTrue(err_file_1.is_file(), 'error_att_one.json must be written by batch_worker.main()')
        self.assertTrue(err_file_2.is_file(), 'error_att_two.json must be written by batch_worker.main()')
        e1 = json.loads(err_file_1.read_text(encoding='utf8'))
        e2 = json.loads(err_file_2.read_text(encoding='utf8'))
        self.assertNotEqual(e1['message'], e2['message'])
        self.assertIn('Failed to rebuild page 3 redaction', e1['message'])
        self.assertIn('missing_font_xref_77', e1.get('root_cause', ''))
        self.assertIn('OCR engine failed on page 5', e2['message'])
        self.assertEqual(e1['error_type'], 'ValueError')
        self.assertEqual(e2['error_type'], 'RuntimeError')
        self.assertTrue((jobs_root / 'error_report.json').is_file(), 'error_report.json must be saved at jobs_root')


if __name__=='__main__':unittest.main()
