import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import batch


class QueueFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'queue'/'queue.sqlite3'

    def source(self,name,text='Clinical stable'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        with fitz.open() as doc:
            doc.new_page(width=240,height=180).insert_text((20,40),text);doc.save(path)
        return path

    def enqueue(self,name,text='Clinical stable'):
        path=self.source(name,text);ident=batch.enqueue(self.db,[path])[0]
        row=batch.get_job(self.db,ident);work=Path(row['job_dir']);work.mkdir(parents=True)
        (work/'private.txt').write_text('private working data',encoding='utf8')
        return ident,path,work


class QueueDeletionTests(QueueFixture):
    def test_delete_bulk_removes_work_and_rows_but_preserves_sources_delivery_and_other_job(self):
        a,src,work=self.enqueue('a.pdf');b,src2,work2=self.enqueue('b.pdf','Other clinical')
        source_bytes=src.read_bytes();keep_bytes=src2.read_bytes()
        delivered=self.db.parent/'delivered'/'a.pdf';delivered.parent.mkdir();delivered.write_bytes(b'already delivered')
        result=batch.delete_jobs(self.db,[a,a])
        self.assertEqual(result['deleted'],[a]);self.assertEqual(result['skipped'],[])
        self.assertFalse(work.exists());self.assertEqual(src.read_bytes(),source_bytes)
        self.assertEqual(delivered.read_bytes(),b'already delivered');self.assertEqual(src2.read_bytes(),keep_bytes)
        self.assertEqual([r['id'] for r in batch.list_jobs(self.db)],[b]);self.assertTrue(work2.exists())
        self.assertNotEqual(batch.enqueue(self.db,[src])[0],a)

    def test_bulk_skips_active_and_cancelling_without_deleting_their_work(self):
        a,_,work=self.enqueue('a.pdf');b,_,work2=self.enqueue('b.pdf','Other clinical')
        batch.claim_next(self.db);batch.cancel_job(self.db,a)
        result=batch.delete_jobs(self.db,[a,b])
        self.assertEqual(result['deleted'],[b]);self.assertEqual(result['skipped'][0]['id'],a)
        self.assertTrue(work.exists());self.assertFalse(work2.exists())
        batch.finish_worker(self.db,a,{'state':'NEEDS_REVIEW'})
        self.assertEqual(batch.delete_jobs(self.db,[a])['deleted'],[a])

    def test_deleting_original_and_selected_duplicates_promotes_only_survivor(self):
        a,src,_=self.enqueue('a.pdf');copies=[]
        for name in ('b.pdf','c.pdf','d.pdf'):
            p=self.root/name;p.write_bytes(src.read_bytes());copies.append(p)
        b,c,d=batch.enqueue(self.db,copies)
        result=batch.delete_jobs(self.db,[a,b])
        self.assertEqual(set(result['deleted']),{a,b})
        remaining=[batch.get_job(self.db,i) for i in (c,d)]
        primary=next(r for r in remaining if r['state']=='QUEUED')
        duplicate=next(r for r in remaining if r['state']=='DUPLICATE')
        self.assertIsNone(primary['duplicate_of']);self.assertEqual(duplicate['duplicate_of'],primary['id'])
        self.assertEqual(batch.claim_next(self.db)['id'],primary['id']);self.assertIsNone(batch.claim_next(self.db))

    def test_failed_disk_cleanup_is_retryable_and_cannot_be_claimed(self):
        ident,src,work=self.enqueue('a.pdf')
        with patch('batch.shutil.rmtree',side_effect=PermissionError('file busy')):
            result=batch.delete_jobs(self.db,[ident])
        self.assertEqual(result['deleted'],[]);self.assertTrue(result['skipped'])
        self.assertEqual(batch.get_job(self.db,ident)['state'],'DELETING');self.assertIsNone(batch.claim_next(self.db))
        with self.assertRaises(ValueError):batch.retry_job(self.db,ident)
        self.assertEqual(batch.delete_jobs(self.db,[ident])['deleted'],[ident]);self.assertFalse(work.exists());self.assertTrue(src.exists())

    def test_rejects_external_job_directory_and_preserves_every_byte(self):
        ident,_,work=self.enqueue('a.pdf');outside=self.root/'keep';outside.mkdir();p=outside/'keep.txt';p.write_bytes(b'keep')
        with batch._db(self.db) as con:con.execute('UPDATE jobs SET job_dir=? WHERE id=?',(str(outside),ident))
        result=batch.delete_jobs(self.db,[ident])
        self.assertEqual(result['deleted'],[]);self.assertTrue(result['skipped']);self.assertEqual(p.read_bytes(),b'keep')
        self.assertTrue(work.exists());self.assertEqual(batch.get_job(self.db,ident)['state'],'QUEUED')

    def test_refuses_delete_when_another_reviewer_owns_lock(self):
        ident,_,work=self.enqueue('a.pdf')
        with batch.queue_lock(work/'review_operation'):
            result=batch.delete_jobs(self.db,[ident])
        self.assertEqual(result['deleted'],[]);self.assertTrue(work.exists())
        self.assertEqual(batch.get_job(self.db,ident)['state'],'QUEUED')

    def test_rejects_source_or_delivered_package_inside_work_tree(self):
        ident,_,work=self.enqueue('a.pdf');protected=work/'keep.pdf';protected.write_bytes(b'keep')
        for column,value in (('source_path',str(protected)),('result_json',json.dumps({'release':{'directory':str(work),'output':str(protected)}}))):
            with self.subTest(column=column):
                with batch._db(self.db) as con:
                    old=con.execute(f'SELECT {column} FROM jobs WHERE id=?',(ident,)).fetchone()[0]
                    con.execute(f'UPDATE jobs SET {column}=? WHERE id=?',(value,ident))
                self.assertEqual(batch.delete_jobs(self.db,[ident])['deleted'],[])
                self.assertEqual(protected.read_bytes(),b'keep')
                with batch._db(self.db) as con:con.execute(f'UPDATE jobs SET {column}=? WHERE id=?',(old,ident))

    def test_rejects_junction_descendant_without_deleting_target(self):
        import os,subprocess
        ident,_,work=self.enqueue('a.pdf');outside=self.root/'outside';outside.mkdir();p=outside/'keep.txt';p.write_bytes(b'keep')
        link=work/'linked'
        if os.name=='nt':
            subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True)
        else:link.symlink_to(outside,target_is_directory=True)
        self.addCleanup(lambda:link.rmdir() if os.name=='nt' and link.exists() else (link.unlink() if link.is_symlink() else None))
        result=batch.delete_jobs(self.db,[ident])
        self.assertEqual(result['deleted'],[]);self.assertEqual(p.read_bytes(),b'keep');self.assertTrue(work.exists())

    def test_invalid_id_does_not_partially_delete_selection(self):
        ident,_,work=self.enqueue('a.pdf')
        for ids in ([],[ident,'../escape'],[ident,3],'not a list'):
            with self.subTest(ids=ids),self.assertRaises(ValueError):batch.delete_jobs(self.db,ids)
        self.assertTrue(work.exists());self.assertEqual(batch.get_job(self.db,ident)['state'],'QUEUED')

    def test_delete_cleans_old_generations_of_same_job_only(self):
        ident,source,original=self.enqueue('a.pdf')
        current=original.with_name(ident+'_0123456789abcdef');current.mkdir();(current/'cache.txt').write_bytes(b'new cache')
        other=original.with_name(ident+'_not_a_generation');other.mkdir();(other/'keep.txt').write_bytes(b'keep')
        with batch._db(self.db) as con:con.execute('UPDATE jobs SET job_dir=? WHERE id=?',(str(current),ident))
        self.assertEqual(batch.delete_jobs(self.db,[ident])['deleted'],[ident])
        self.assertFalse(original.exists());self.assertFalse(current.exists());self.assertTrue(other.exists());self.assertTrue(source.exists())

    def test_enqueue_during_cleanup_never_links_new_duplicate_to_deleting_job(self):
        ident,source,work=self.enqueue('a.pdf');copy=self.root/'copy.pdf';copy.write_bytes(source.read_bytes())
        with patch('batch.shutil.rmtree',side_effect=PermissionError('file busy')):batch.delete_jobs(self.db,[ident])
        other=batch.enqueue(self.db,[copy])[0]
        self.assertEqual(batch.get_job(self.db,other)['state'],'QUEUED')
        self.assertIsNone(batch.get_job(self.db,other)['duplicate_of'])
        with self.assertRaises(ValueError):batch.enqueue(self.db,[source])

    def test_worker_cannot_publish_deleting_state(self):
        ident,_,_=self.enqueue('a.pdf');batch.claim_next(self.db)
        with self.assertRaises(ValueError):batch.set_stage_result(self.db,ident,expected_state='PREPARING',result={'state':'DELETING'})

    def test_cancel_cannot_revive_partially_deleted_work(self):
        ident,_,_=self.enqueue('a.pdf')
        with patch('batch.shutil.rmtree',side_effect=PermissionError('file busy')):batch.delete_jobs(self.db,[ident])
        with self.assertRaises(ValueError):batch.cancel_job(self.db,ident)
        with self.assertRaises(ValueError):batch.retry_job(self.db,ident)
        self.assertEqual(batch.get_job(self.db,ident)['state'],'DELETING');self.assertIsNone(batch.claim_next(self.db))

    def test_cancel_during_removal_cannot_leave_a_ghost_row(self):
        ident,_,work=self.enqueue('a.pdf');remove=batch.shutil.rmtree;cancelled=[]
        def concurrent_cancel(path):
            try:batch.cancel_job(self.db,ident);cancelled.append('accepted')
            except ValueError:cancelled.append('blocked')
            remove(path)
        with patch('batch.shutil.rmtree',side_effect=concurrent_cancel):result=batch.delete_jobs(self.db,[ident])
        self.assertEqual(cancelled,['blocked']);self.assertEqual(result['deleted'],[ident])
        self.assertEqual(batch.list_jobs(self.db),[]);self.assertFalse(work.exists())


class QueueReleaseTests(QueueFixture):
    def completed(self,name='input/a.pdf',*,approve=True,text='Clinical stable'):
        import batch_worker,engine
        source=self.source(name,text);ident=batch.enqueue(self.db,[source])[0];row=batch.claim_next(self.db)
        self.assertEqual(row['id'],ident)
        with patch('output_qc.ocr_pdf_pages',return_value={1:(text,[])}):
            result=batch_worker.process_job(row,ocr_workers=1,render_workers=1)
        batch.finish_worker(self.db,ident,result);job=Path(row['job_dir'])/'review'
        if approve:engine.approve_all_pages(job)
        return ident,source,job,result

    def test_export_mixed_folder_releases_reviewed_pdf_reports_pending_and_preserves_source(self):
        a,source,job,result=self.completed('input/Kết quả.pdf');b,_,_,_=self.completed('input/b.pdf',approve=False,text='Other clinical')
        original=source.read_bytes();out=batch.release_folder(self.db,[str(source.parent)],self.root/'delivery')
        folder=Path(out['directory']);pdfs=list(folder.glob('*.pdf'))
        self.assertEqual([p.name for p in pdfs],[source.name]);self.assertEqual(out['exported'][0]['id'],a)
        self.assertEqual(out['pending'][0]['id'],b);self.assertEqual(out['pending'][0]['source_name'],'b.pdf')
        self.assertEqual(batch._sha(pdfs[0]),result['verification']['pdf_sha256'])
        with fitz.open(pdfs[0]) as doc:self.assertEqual(len(doc),1)
        self.assertEqual(source.read_bytes(),original);self.assertTrue((job/'review.json').exists())
        self.assertEqual(batch.get_job(self.db,a)['state'],'READY');self.assertEqual(batch.get_job(self.db,b)['state'],'NEEDS_REVIEW')
        public=''.join(p.read_text(encoding='utf8') for p in folder.glob('*.json'))
        self.assertNotIn(str(source),public);self.assertNotIn('source_name',public);self.assertIn(source.name,public)

    def test_reviewing_pending_then_exporting_again_includes_all_without_overwrite(self):
        import engine
        a,source,_,_=self.completed();b,_,job,_=self.completed('input/b.pdf',approve=False,text='Other clinical')
        first=batch.release_folder(self.db,[str(source.parent)],self.root/'delivery');old=Path(first['directory'])
        hashes={p.name:batch._sha(p) for p in old.iterdir()}
        engine.approve_all_pages(job)
        second=batch.release_folder(self.db,[str(source.parent)],self.root/'delivery')
        self.assertEqual(len(second['exported']),2);self.assertEqual(second['pending'],[])
        self.assertNotEqual(first['directory'],second['directory'])
        self.assertEqual({p.name:batch._sha(p) for p in old.iterdir()},hashes)

    def test_scope_keeps_other_folders_out_and_preserves_duplicate_names(self):
        a,src,_,_=self.completed('input/one/same.pdf');b,_,_,_=self.completed('input/two/same.pdf',text='Different clinical')
        c,_,_,_=self.completed('elsewhere/same.pdf',text='Third clinical')
        out=batch.release_folder(self.db,[str(self.root/'input'),str(src)],self.root/'delivery')
        self.assertEqual({x['id'] for x in out['exported']},{a,b});self.assertEqual(out['pending'],[])
        outputs=[Path(item['output']) for item in out['exported']]
        self.assertEqual([p.name for p in outputs],['same.pdf','same.pdf'])
        self.assertNotEqual(outputs[0].parent,outputs[1].parent)
        self.assertTrue(all(p.is_file() for p in outputs))
        self.assertEqual(batch.get_job(self.db,c)['state'],'NEEDS_REVIEW')

    def test_warning_unreadable_and_incomplete_qc_block_group_delivery(self):
        import engine
        a,src,job,_=self.completed();qc_path=job/'output_verification_private.json'
        original=json.loads(qc_path.read_text(encoding='utf8'))
        for change in ({'findings':[{'id':'f1','page':1,'kind':'PERSON','text':'test warning','rects':[]}]},
                       {'unreadable_pages':[1]},{'pages_checked':0},{'structural_ok':False}):
            with self.subTest(change=change):
                engine.save_json(qc_path,{**original,**change})
                out=batch.release_folder(self.db,[str(src)],self.root/'delivery')
                self.assertIsNone(out['directory']);self.assertEqual(out['exported'],[]);self.assertEqual(out['pending'][0]['id'],a)
                self.assertEqual(batch.get_job(self.db,a)['state'],'NEEDS_REVIEW')
        self.assertFalse((self.root/'delivery').exists())

    def test_stale_mask_or_tampered_output_is_not_delivered(self):
        import engine
        a,src,job,result=self.completed();review=engine.ensure_job(job)
        review['pages'][0]['manual_rects']=[[1,1,9,9]];engine.save_json(job/'review.json',review)
        out=batch.release_folder(self.db,[str(src)],self.root/'delivery')
        self.assertEqual(out['exported'],[]);self.assertTrue(out['pending'])
        review['pages'][0]['manual_rects']=[];engine.save_json(job/'review.json',review)
        Path(result['output']).write_bytes(b'tampered')
        self.assertEqual(batch.release_folder(self.db,[str(src)],self.root/'delivery')['exported'],[])

    def test_destination_inside_source_or_internal_cache_is_refused(self):
        a,src,job,_=self.completed()
        for dest in (src.parent/'output',job/'output',self.db.parent/'jobs'/'output'):
            with self.subTest(dest=dest),self.assertRaises(ValueError):batch.release_folder(self.db,[str(src)],dest)
            self.assertFalse(dest.exists())
        self.assertEqual(batch.get_job(self.db,a)['state'],'NEEDS_REVIEW')

    def test_copy_failure_never_publishes_partial_batch_or_marks_ready(self):
        a,src,_,_=self.completed()
        for fake in (PermissionError('disk full'),None):
            with self.subTest(fake=fake):
                def bad_copy(source,target):
                    Path(target).write_bytes(b'corrupt')
                    if fake:raise fake
                with patch('batch.shutil.copyfile',side_effect=bad_copy),self.assertRaises((OSError,ValueError)):
                    batch.release_folder(self.db,[str(src)],self.root/'delivery')
                self.assertEqual(list((self.root/'delivery').iterdir()),[])
                self.assertEqual(batch.get_job(self.db,a)['state'],'NEEDS_REVIEW')

    def test_delete_after_group_delivery_keeps_group_pdf_and_manifest(self):
        a,src,job,_=self.completed();out=batch.release_folder(self.db,[str(src)],self.root/'delivery');folder=Path(out['directory'])
        hashes={p.name:batch._sha(p) for p in folder.iterdir()}
        self.assertEqual(batch.delete_jobs(self.db,[a])['deleted'],[a])
        self.assertFalse(job.exists());self.assertTrue(src.exists())
        self.assertEqual({p.name:batch._sha(p) for p in folder.iterdir()},hashes)

    def test_export_requires_nonempty_valid_scope_and_destination(self):
        _,src,_,_=self.completed()
        for paths,dest in (([],self.root/'out'),([str(src)],''),([''],self.root/'out')):
            with self.subTest(paths=paths),self.assertRaises(ValueError):batch.release_folder(self.db,paths,dest)


if __name__=='__main__':unittest.main()
