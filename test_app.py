import unittest,tempfile,json,threading,http.client
from pathlib import Path
import fitz
import app
import delivery
class AppTests(unittest.TestCase):
 def test_review_page_embeds_current_assets_and_has_one_folder_export(self):
  code,html=self.req('GET','/');self.assertEqual(code,200)
  self.assertEqual(html.count(b'id="exportFolder"'),1)
  self.assertEqual(html.count(b'id="folderDestination"'),1)
  self.assertEqual(html.count(b'id="pickLocalFolder"'),1)
  self.assertEqual(html.count(b'id="pickBatchFolder"'),1)
  self.assertEqual(html.count(b'id="pickDestFolder"'),1)
  self.assertEqual(html.count(b'id="prevFile"'),1)
  self.assertEqual(html.count(b'id="nextFile"'),1)
  self.assertEqual(html.count(b'id="toastContainer"'),1)
  self.assertNotIn(b'href="/ui/',html)
  self.assertNotIn(b'src="/ui/',html)
  from ui.build_review import render_review
  self.assertEqual(html.decode('utf8').replace('\r\n','\n'),render_review())
  self.assertNotEqual(self.req('GET','/ui/delivery.py')[0],200)
 def open_local_case(self):
  case=self.root/'local_case';case.mkdir()
  for i in range(2):(case/f'private_name_{i}.pdf').write_bytes(self.pdf())
  code,state=self.req('POST','/open_path',{'path':str(case),'study_id':'LOCAL'})
  self.assertEqual(code,200,state);return case,state
 def test_local_path_folder_export_partial_then_all_preserves_source_and_old_delivery(self):
  import hashlib
  case,state=self.open_local_case();originals={p.name:p.read_bytes() for p in case.iterdir()}
  d=state['review'];code,result=self.req('POST','/approve_all',self.ident(d));self.assertEqual(code,200,result);d=result['review']
  dest=self.root/'local_delivery';body={**self.ident(d),'destination':str(dest)}
  self.assertEqual(self.req('POST','/export_folder',body,{'X-HMU-Token':'bad'})[0],403)
  self.assertEqual(self.req('POST','/export_folder',{**body,'revision':-1})[0],409)
  code,result=self.req('POST','/export_folder',body);self.assertEqual(code,200,result)
  first=Path(result['directory']);self.assertEqual(result['count'],1)
  self.assertEqual([(p['index'],p['source_name']) for p in result['pending']],[(2,'private_name_1.pdf')])
  pdf=next(first.glob('*.pdf'));self.assertEqual(pdf.name,'private_name_0.pdf')
  with fitz.open(pdf) as doc:self.assertEqual(len(doc),1);self.assertTrue(doc[0].get_pixmap().samples);self.assertEqual(doc[0].get_text(),'')
  public=''.join(p.read_text(encoding='utf8') for p in first.glob('*.json'))
  self.assertIn('private_name_0.pdf',public);self.assertNotIn('private_name_1.pdf',public);self.assertNotIn(str(case),public)
  old={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in first.iterdir()}
  code,state=self.req('POST','/select_file',{**self.ident(d),'file_index':2});self.assertEqual(code,200,state)
  code,state=self.req('POST','/approve_all',self.ident(state['review']));self.assertEqual(code,200,state)
  code,result=self.req('POST','/export_folder',{**self.ident(state['review']),'destination':str(dest)});self.assertEqual(code,200,result)
  self.assertEqual(result['count'],2);self.assertEqual(result['pending'],[]);self.assertNotEqual(Path(result['directory']),first)
  self.assertEqual({p.name for p in Path(result['directory']).glob('*.pdf')},set(originals))
  self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in first.iterdir()},old)
  self.assertEqual({p.name:p.read_bytes() for p in case.iterdir()},originals)
 def test_local_folder_export_without_approved_files_creates_no_empty_delivery(self):
  _,state=self.open_local_case();dest=self.root/'delivery'
  code,result=self.req('POST','/export_folder',{**self.ident(state['review']),'destination':str(dest)})
  self.assertEqual(code,200,result);self.assertEqual(result['count'],0);self.assertIsNone(result['directory'])
  self.assertEqual(len(result['pending']),2);self.assertFalse(dest.exists())
 def test_local_folder_export_single_pdf_and_rejects_cache_destination(self):
  source=self.root/'single.pdf';source.write_bytes(self.pdf())
  code,state=self.req('POST','/open_path',{'path':str(source),'study_id':'SINGLE'});self.assertEqual(code,200,state)
  code,state=self.req('POST','/approve_all',self.ident(state['review']));self.assertEqual(code,200,state);ident=self.ident(state['review'])
  for dest in ('',str(self.root/'jobs'/'bad_output')):
   self.assertEqual(self.req('POST','/export_folder',{**ident,'destination':dest})[0],400)
  code,result=self.req('POST','/export_folder',{**ident,'destination':str(self.root/'delivery')})
  self.assertEqual(code,200,result);self.assertEqual(result['count'],1);self.assertEqual(result['pending'],[]);self.assertTrue(source.exists())
  self.assertEqual(Path(result['outputs'][0]).name,source.name)
 def test_local_folder_export_failure_does_not_publish_partial_output(self):
  from unittest.mock import patch
  _,state=self.open_local_case();self.req('POST','/approve_all',self.ident(state['review']))
  state=self.req('GET','/state')[1];dest=self.root/'delivery'
  with patch.object(delivery,'export',side_effect=OSError('disk full')):
   code,result=self.req('POST','/export_folder',{**self.ident(state['review']),'destination':str(dest)})
  self.assertEqual(code,400,result);self.assertFalse(list(dest.glob('BAN_GIAO_*')));self.assertFalse(list(dest.glob('.pending_*')))
 def test_local_folder_export_bad_hash_does_not_replace_existing_single_export(self):
  from unittest.mock import patch
  d=self.upload();d=self.req('POST','/approve_all',self.ident(d))[1]['review']
  code,first=self.req('POST','/export',{**self.ident(d),'draft':False});self.assertEqual(code,200,first)
  output=self.req('GET','/download?job_id='+d['job_id'])[1];original_export=delivery.export
  def corrupt(*args,**kwargs):
   pdf,qc=original_export(*args,**kwargs);pdf.write_bytes(b'corrupt');return pdf,qc
  dest=self.root/'delivery'
  with patch.object(delivery,'export',side_effect=corrupt):
   code,result=self.req('POST','/export_folder',{**self.ident(d),'destination':str(dest)})
  self.assertEqual(code,400,result);self.assertFalse(list(dest.iterdir()))
  self.assertEqual(self.req('GET','/download?job_id='+d['job_id'])[1],output)
 def test_local_folder_export_preserves_uploaded_unicode_filename(self):
  from urllib.parse import quote
  name='Kết quả xét nghiệm (2).PDF'
  d=self.upload(quote(name));d=self.req('POST','/approve_all',self.ident(d))[1]['review']
  code,result=self.req('POST','/export_folder',{**self.ident(d),'destination':str(self.root/'delivery')})
  self.assertEqual(code,200,result);self.assertEqual(Path(result['outputs'][0]).name,name)
 def test_local_folder_export_refuses_unsafe_source_filename(self):
  _,state=self.open_local_case();d=self.req('POST','/approve_all',self.ident(state['review']))[1]['review']
  manifest=next((self.root/'jobs').rglob('case_manifest.json'));data=json.loads(manifest.read_text(encoding='utf8'))
  for name in ('../escape.pdf','file.pdf:stream.pdf','NUL.pdf'):
   with self.subTest(name=name):
    data['files'][0]['source_name']=name;manifest.write_text(json.dumps(data),encoding='utf8')
    dest=self.root/'delivery';code,result=self.req('POST','/export_folder',{**self.ident(d),'destination':str(dest)})
    self.assertEqual(code,400,result);self.assertFalse(dest.exists())
 def test_local_folder_export_rejects_case_manifest_path_outside_owner(self):
  _,state=self.open_local_case()
  manifest=next((self.root/'jobs').rglob('case_manifest.json'));data=json.loads(manifest.read_text(encoding='utf8'))
  data['files'][1]['sub_job']='../../elsewhere';manifest.write_text(json.dumps(data),encoding='utf8')
  code,result=self.req('POST','/export_folder',{**self.ident(state['review']),'destination':str(self.root/'delivery')})
  self.assertEqual(code,400,result);self.assertFalse((self.root/'delivery').exists())
 def test_local_folder_async_export_blocks_case_switch_until_complete(self):
  import time
  from unittest.mock import patch
  _,state=self.open_local_case();d=state['review'];started=threading.Event();release=threading.Event()
  original=app.export_reviewed_folder
  def slow(*args,**kwargs):started.set();release.wait(5);return original(*args,**kwargs)
  with patch.object(app,'export_reviewed_folder',side_effect=slow):
   code,result=self.req('POST','/export_folder',{**self.ident(d),'destination':str(self.root/'delivery')},{'X-HMU-Async':'1'})
   self.assertEqual(code,202,result);self.assertTrue(started.wait(2))
   try:self.assertEqual(self.req('POST','/select_file',{**self.ident(d),'file_index':2})[0],409)
   finally:release.set()
   for _ in range(100):
    progress=self.req('GET','/progress?task_id='+result['task_id'])[1]
    if progress['status']!='running':break
    time.sleep(.02)
   self.assertEqual(progress['status'],'done',progress);self.assertEqual(len(progress['result']['pending']),2)
   self.assertEqual(self.req('GET','/state')[1]['review']['job_id'],d['job_id'])
 def test_batch_delete_requires_token_clears_active_and_keeps_original(self):
  import batch,batch_worker
  from unittest.mock import patch
  source=self.root/'queue_input.pdf';source.write_bytes(self.pdf())
  db=self.root/'jobs'/'batch'/'queue.sqlite3';ident=batch.enqueue(db,[source])[0];row=batch.claim_next(db)
  with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable',[])}):result=batch_worker.process_job(row,ocr_workers=1,render_workers=1)
  batch.finish_worker(db,ident,result)
  self.assertEqual(self.req('POST','/batch/open_job',{'queue_id':ident})[0],200)
  self.assertEqual(self.req('POST','/batch/delete',{'queue_ids':[ident]},{'X-HMU-Token':'bad'})[0],403)
  code,result=self.req('POST','/batch/delete',{'queue_ids':[ident]});self.assertEqual(code,200,result)
  self.assertEqual(result['deleted'],[ident]);self.assertTrue(result['active_deleted'])
  self.assertEqual(self.req('GET','/batch/status')[1]['jobs'],[])
  self.assertIsNone(self.req('GET','/state')[1]['review']);self.assertTrue(source.exists())
  self.assertFalse(Path(row['job_dir']).exists())
 def test_folder_release_route_exports_reviewed_and_lists_unreviewed_without_private_package_names(self):
  import batch,batch_worker,engine
  from unittest.mock import patch
  db=self.root/'jobs'/'batch'/'queue.sqlite3';sources=[];ids=[]
  for n in range(2):
   source=self.root/'inputs'/f'patient{n}.pdf';source.parent.mkdir(exist_ok=True)
   with fitz.open() as doc:doc.new_page(width=240,height=180).insert_text((20,40),f'Clinical stable {n}');doc.save(source)
   ident=batch.enqueue(db,[source])[0];row=batch.claim_next(db)
   with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable',[])}):result=batch_worker.process_job(row,ocr_workers=1,render_workers=1)
   batch.finish_worker(db,ident,result)
   if n==0:engine.approve_all_pages(Path(row['job_dir'])/'review')
   sources.append(source);ids.append(ident)
  body={'paths':[str(sources[0].parent)],'destination':str(self.root/'hand_off')}
  self.assertEqual(self.req('POST','/batch/release_folder',body,{'X-HMU-Token':'bad'})[0],403)
  code,result=self.req('POST','/batch/release_folder',body);self.assertEqual(code,200,result)
  self.assertEqual([r['id'] for r in result['exported']],[ids[0]])
  self.assertEqual(result['pending'][0]['source_name'],'patient1.pdf');self.assertTrue(result['pending'][0]['reason'])
  self.assertEqual(len(list(Path(result['directory']).glob('*.pdf'))),1)
  self.assertTrue(all(p.exists() for p in sources))
 def test_forbidden_small_body_is_drained_without_parsing_or_unbounded_reads(self):
  import io
  from unittest.mock import Mock
  for length,expected in [('8',8),('999999999',0)]:
   h=object.__new__(self.server.RequestHandlerClass)
   h.headers={'Host':f'127.0.0.1:{self.server.server_port}','X-HMU-Token':'bad','Content-Length':length}
   h.server=self.server;h.connection=Mock();h.rfile=io.BytesIO(b'not_json');sent=[]
   h.send=lambda code,data:sent.append(code)
   h.do_POST()
   self.assertEqual(sent,[403]);self.assertEqual(h.rfile.tell(),expected)
 def test_batch_enqueue_token_and_running_job_cannot_be_opened(self):
  source=self.root/'batch.pdf';source.write_bytes(self.pdf())
  self.assertEqual(self.req('POST','/batch/enqueue',{'paths':[str(source)]},{'X-HMU-Token':'bad'})[0],403)
  code,result=self.req('POST','/batch/enqueue',{'paths':[str(source)]});self.assertEqual(code,200,result)
  ident=result['ids'][0]
  self.assertEqual(self.req('GET','/batch/status')[1]['jobs'][0]['state'],'QUEUED')
  self.assertEqual(self.req('POST','/batch/open_job',{'queue_id':ident})[0],400)
 def test_batch_review_is_available_while_another_file_is_preparing(self):
  import batch,batch_worker
  from unittest.mock import patch
  sources=[]
  for i in range(2):
   source=self.root/f'case{i}.pdf'
   with fitz.open() as doc:
    doc.new_page(width=300,height=250).insert_text((20,50),f'Clinical stable {i}');doc.save(source)
   sources.append(source)
  db=self.root/'jobs'/'batch'/'queue.sqlite3';ids=batch.enqueue(db,sources);row=batch.claim_next(db)
  with patch('output_qc.ocr_pdf_pages',return_value={1:('Clinical stable',[])}):result=batch_worker.process_job(row,ocr_workers=1,render_workers=1)
  batch.set_stage_result(db,ids[0],expected_state='PREPARING',result=result);batch.claim_next(db)
  code,state=self.req('POST','/batch/open_job',{'queue_id':ids[0]});self.assertEqual(code,200,state)
  self.assertEqual(state['queue_id'],ids[0]);d=state['review']
  d['pages'][0]['reviewed']=True
  code,saved=self.req('POST','/save',d);self.assertEqual(code,200,saved)
  self.assertEqual(batch.get_job(db,ids[1])['state'],'PREPARING')
  self.assertEqual(self.req('POST','/export',{**self.ident(d),'revision':saved['revision'],'draft':False})[0],400)
  self.assertEqual(self.req('POST','/export_folder',{**self.ident(d),'revision':saved['revision'],'destination':str(self.root/'wrong_delivery')})[0],400)
  code,released=self.req('POST','/batch/release',{'queue_id':ids[0],'revision':saved['revision']});self.assertEqual(code,200,released)
  self.assertEqual(batch.get_job(db,ids[0])['state'],'READY')
  code,qc=self.req('GET',f"/batch/qc?queue_id={ids[0]}&revision={saved['revision']}")
  self.assertEqual(code,200,qc);self.assertEqual(qc['filename'],Path(released['output']).name)
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
  self.server=app.create_server(self.root/'jobs',None,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.token=self.req('GET','/state')[1]['token']
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def req(self,method,path,body=None,headers=None):
  h={'X-HMU-Token':getattr(self,'token','')};h.update(headers or {})
  if isinstance(body,dict):body=json.dumps(body).encode()
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30);c.request(method,path,body=body,headers=h);r=c.getresponse();raw=r.read();code=r.status;ctype=r.getheader('Content-Type','');c.close()
  return code,json.loads(raw) if 'json' in ctype else raw
 def pdf(self):
  d=fitz.open();p=d.new_page(width=500,height=300);p.insert_text((30,50),'Ho ten: Nguyen Van An');b=d.tobytes();d.close();return b
 def upload(self,name='input.pdf'):
  code,r=self.req('POST','/upload',self.pdf(),{'X-Original-Filename':name});self.assertEqual(code,200,r);return r['review']
 def ident(self,d):return {'job_id':d['job_id'],'revision':d['revision']}
 def test_sync_task_allows_progress_from_worker_threads(self):
  from unittest.mock import patch
  original=app.prepare
  def prepare(*args,**kwargs):
   done=threading.Event()
   def report():kwargs['progress_cb']('worker progress');done.set()
   worker=threading.Thread(target=report,daemon=True);worker.start()
   if not done.wait(.5):raise RuntimeError('Progress blocked by request lock')
   worker.join();return original(*args,**kwargs)
  with patch.object(app,'prepare',side_effect=prepare):
   code,result=self.req('POST','/upload',self.pdf())
  self.assertEqual(code,200,result)
 def test_audit_get_is_blocked_while_export_runs(self):
  from unittest.mock import patch
  data=self.upload();started=threading.Event();release=threading.Event()
  def export(job,**kwargs):
   started.set();release.wait(5);return Path(job)/'result.pdf',{'pages':1}
  with patch.object(app,'export',side_effect=export):
   code,result=self.req('POST','/export',{**self.ident(data),'draft':True},{'X-HMU-Async':'1'})
   self.assertEqual(code,202);self.assertTrue(started.wait(2))
   try:self.assertEqual(self.req('GET','/audit?job_id='+data['job_id']+'&revision='+str(data['revision']))[0],409)
   finally:release.set()
 def test_server_factory_uses_bound_port(self):
  self.assertEqual(self.req('GET','/state')[0],200)
  self.assertEqual(self.req('GET','/state',headers={'Host':'evil.test'})[0],403)
  self.assertEqual(self.req('POST','/upload',b'x',{'X-HMU-Token':'bad'})[0],403)
 def test_upload_filename_cannot_escape_job(self):
  for name in ('../outside.pdf','C:%5Coutside.pdf','%2E%2E%2Foutside.pdf'):
   self.upload(name)
  self.assertFalse((self.root/'outside.pdf').exists());self.assertEqual(len(list((self.root/'jobs').glob('*/source_private.pdf'))),3)
 def test_stale_tab_cannot_save_other_job(self):
  old=self.upload();new=self.upload();old['pages'][0]['note']='wrong'
  self.assertEqual(self.req('POST','/save',old)[0],409)
  self.assertEqual(self.req('GET','/state')[1]['review']['job_id'],new['job_id'])
 def test_revision_conflict_preserves_latest_save(self):
  d=self.upload();code,r=self.req('POST','/save',d);self.assertEqual(code,200,r)
  self.assertEqual(self.req('POST','/save',d)[0],409)
 def test_cached_job_policy_change_is_refused(self):
  d=self.upload()
  self.assertEqual(self.req('GET','/state')[0],200)
  review=next((self.root/'jobs').glob('*/review/review.json'))
  stored=json.loads(review.read_text(encoding='utf8'));stored['policy']='old_keep_age';review.write_text(json.dumps(stored),encoding='utf8')
  code,result=self.req('GET','/state');self.assertEqual(code,400);self.assertIn('policy',result['error'])
 def test_save_page_changes_only_target_page(self):
  d=self.upload();p=d['pages'][0];req={**self.ident(d),'page':1,'reviewed':False,'manual_rects':[],'note':'saved','selections':[{'id':q['id'],'selected':q['selected']} for q in p['proposals']]}
  code,r=self.req('POST','/save_page',req);self.assertEqual(code,200,r)
  self.assertEqual(self.req('GET','/state')[1]['review']['pages'][0]['note'],'saved')
 def test_page_and_download_reject_wrong_job(self):
  d=self.upload();self.assertEqual(self.req('GET','/page/1?job_id=wrong')[0],409);self.assertEqual(self.req('GET','/download?job_id=wrong')[0],409)
 def test_open_case_does_not_export_or_approve(self):
  case=self.root/'case';case.mkdir()
  for i in range(2):(case/f'{i}.pdf').write_bytes(self.pdf())
  code,r=self.req('POST','/open_path',{'path':str(case),'study_id':'CASE'});self.assertEqual(code,200,r)
  self.assertEqual(len(r['files']),2);self.assertFalse(r['review']['pages'][0]['reviewed']);self.assertFalse(list((self.root/'jobs').rglob('last_export.json')))
  d=r['review'];code,r=self.req('POST','/select_file',{**self.ident(d),'file_index':2});self.assertEqual(code,200,r);self.assertNotEqual(d['job_id'],r['review']['job_id'])
  self.assertEqual(self.req('POST','/export',{**self.ident(r['review']),'scope':'case','draft':False})[0],400)
 def test_progress_result_is_not_consumed_by_other_tab(self):
  code,r=self.req('POST','/upload',self.pdf(),{'X-HMU-Async':'1'});self.assertEqual(code,202)
  import time
  for _ in range(100):
   state=self.req('GET','/progress?task_id='+r['task_id'])[1]
   if state['status']!='running':break
   time.sleep(.05)
  self.assertEqual(state['status'],'done',state);self.assertEqual(self.req('GET','/progress?task_id='+r['task_id'])[1],state)
 def test_occupied_port_does_not_stop_listener(self):
  with self.assertRaises(OSError):app.create_server(self.root/'another',None,self.server.server_port)
  self.assertEqual(self.req('GET','/state')[0],200)
 def test_page_patch_requires_revision_and_valid_geometry(self):
  d=self.upload();p=d['pages'][0];req={**self.ident(d),'page':1,'reviewed':False,'manual_rects':[[-1,0,20,20]],'selections':[{'id':q['id'],'selected':q['selected']} for q in p['proposals']]}
  self.assertEqual(self.req('POST','/save_page',req)[0],400)
  self.assertEqual(self.req('GET','/state')[1]['review']['revision'],d['revision'])
  req['manual_rects']=[];req['selections'][0]['id']='other';self.assertEqual(self.req('POST','/save_page',req)[0],400)
 def test_export_captures_job_and_blocks_conflicting_edits(self):
  from unittest.mock import patch
  d=self.upload();started=threading.Event();release=threading.Event()
  def fake_export(job,**kwargs):
   started.set();release.wait(10);return Path(job)/'result.pdf',{'pages':1}
  with patch('app.export',side_effect=fake_export):
   code,r=self.req('POST','/export',{**self.ident(d),'draft':True},{'X-HMU-Async':'1'});self.assertEqual(code,202);self.assertTrue(started.wait(5))
   try:
    self.assertEqual(self.req('POST','/save',d)[0],409)
    self.assertEqual(self.req('POST','/upload',self.pdf())[0],409)
   finally:release.set()
   import time
   for _ in range(100):
    state=self.req('GET','/progress?task_id='+r['task_id'])[1]
    if state['status']!='running':break
    time.sleep(.02)
   self.assertEqual(state['status'],'done',state)
   self.assertEqual(self.req('GET','/state')[1]['review']['job_id'],d['job_id'])
 def test_http_review_export_download_and_audit(self):
  d=self.upload();code,r=self.req('POST','/approve_all',self.ident(d));self.assertEqual(code,200,r);d=r['review']
  code,r=self.req('POST','/export',{**self.ident(d),'draft':False});self.assertEqual(code,200,r)
  code,raw=self.req('GET','/download?job_id='+d['job_id']);self.assertEqual(code,200);self.assertTrue(raw.startswith(b'%PDF'))
  code,audit=self.req('GET','/audit?job_id='+d['job_id']+'&revision='+str(d['revision']));self.assertEqual(code,200,audit);self.assertIn('markdown',audit)
 def test_repeated_state_reads_do_not_revalidate_entire_pdf(self):
  from unittest.mock import patch
  import engine
  with patch('engine.ensure_job',wraps=engine.ensure_job) as check:
   self.upload()
   for _ in range(5):self.assertEqual(self.req('GET','/state')[0],200)
   self.assertEqual(check.call_count,1)
 def test_open_path_reuses_existing_case_progress_and_restores_last_session(self):
  case,state1=self.open_local_case()
  d1=state1['review'];first_job_id=d1['job_id']
  p1=d1['pages'][0]
  req_save={**self.ident(d1),'page':1,'reviewed':True,'manual_rects':[],'note':'reviewed file 1','selections':[{'id':q['id'],'selected':q['selected']} for q in p1['proposals']]}
  code,saved=self.req('POST','/save_page',req_save);self.assertEqual(code,200,saved)
  code,state2=self.req('POST','/select_file',{'job_id':first_job_id,'revision':saved['revision'],'file_index':2})
  self.assertEqual(code,200,state2)
  second_job_id=state2['review']['job_id']
  self.assertNotEqual(first_job_id,second_job_id)
  # Restart server on the same jobs root -> should restore from last_session.json (still on file 2 with file 1 reviewed)
  restarted=app.create_server(self.root/'jobs',None,0)
  t=threading.Thread(target=restarted.serve_forever,daemon=True);t.start()
  try:
   c=http.client.HTTPConnection('127.0.0.1',restarted.server_port,timeout=30)
   c.request('GET','/state');r=c.getresponse();restored=json.loads(r.read());c.close()
   self.assertIsNotNone(restored['review'])
   self.assertEqual(restored['review']['job_id'],second_job_id)
   self.assertEqual([f['reviewed'] for f in restored['files']],[1,0])
  finally:
   restarted.shutdown();restarted.server_close();t.join()
  # Calling POST /open_path a second time on the same case directory reuses existing progress
  code,reopened=self.req('POST','/open_path',{'path':str(case),'study_id':'LOCAL'})
  self.assertEqual(code,200,reopened)
  self.assertEqual([f['reviewed'] for f in reopened['files']],[1,0])
  self.assertEqual(reopened['files'][0]['job_id'],first_job_id)
  self.assertEqual(reopened['review']['job_id'],second_job_id)
  # Unless force_reprepare=True is explicitly requested
  code,fresh=self.req('POST','/open_path',{'path':str(case),'study_id':'LOCAL','force_reprepare':True})
  self.assertEqual(code,200,fresh)
  self.assertEqual([f['reviewed'] for f in fresh['files']],[0,0])
  self.assertNotEqual(fresh['files'][0]['job_id'],first_job_id)
 def test_pick_folder_requires_token_and_returns_selected_or_cancelled(self):
  from unittest.mock import patch
  self.assertEqual(self.req('POST','/pick_folder',{},{'X-HMU-Token':'bad'})[0],403)
  chosen=str(self.root/'chosen_case')
  with patch.object(app,'_pick_folder_dialog',return_value=chosen) as mock_pick:
   code,result=self.req('POST','/pick_folder',{'initial_dir':str(self.root)})
   self.assertEqual(code,200,result)
   self.assertEqual(result,{'path':chosen})
   mock_pick.assert_called_once_with(str(self.root))
  with patch.object(app,'_pick_folder_dialog',return_value=None):
   code,result=self.req('POST','/pick_folder',{})
   self.assertEqual(code,200,result)
   self.assertEqual(result,{'path':None,'cancelled':True})
 def test_open_path_file_error_classification_and_report_json(self):
  bad_path=str(self.root/'nonexistent_case.pdf')
  code,result=self.req('POST','/open_path',{'path':bad_path,'study_id':'LOCAL'})
  self.assertEqual(code,400)
  self.assertIn('error',result)
  self.assertIn('error_detail',result)
  detail=result['error_detail']
  self.assertEqual(detail['category'],'FILE_ERROR')
  self.assertEqual(detail['stage'],'OPEN_PATH')
  report_file=self.root/'jobs'/'error_report.json'
  self.assertTrue(report_file.is_file(),'error_report.json must be persisted in root')
  report=json.loads(report_file.read_text(encoding='utf8'))
  self.assertGreaterEqual(report['total_errors'],1)
  self.assertEqual(report['errors'][-1]['id'],detail['id'])
  self.assertEqual(report['errors'][-1]['category'],'FILE_ERROR')
 def test_async_task_code_error_traceback_extraction(self):
  from unittest.mock import patch
  def buggy_export(*args,**kwargs):
   raise RuntimeError("Simulated crash in export engine")
  d=self.upload()
  with patch('app.export_reviewed_folder',side_effect=buggy_export):
   code,result=self.req('POST','/export_folder',{**self.ident(d),'destination':str(self.root/'out')},{'X-HMU-Async':'1'})
   self.assertEqual(code,202)
   import time
   deadline=time.monotonic()+5
   prog=None
   while time.monotonic()<deadline:
    _,prog=self.req('GET','/progress?task_id='+result['task_id'])
    if prog.get('status')=='error':break
    time.sleep(0.05)
   self.assertEqual(prog.get('status'),'error')
   self.assertIn('error_detail',prog)
   detail=prog['error_detail']
   self.assertEqual(detail['category'],'CODE_ERROR')
   self.assertIn('Simulated crash in export engine',detail['message'])
   self.assertIsNotNone(detail.get('code_location'))
   self.assertEqual(detail['code_location']['function'],'buggy_export')
   self.assertIn('test_app.py',detail['code_location']['file'])
   self.assertIsInstance(detail['code_location']['line'],int)
 def test_get_errors_report_endpoint(self):
  code,report=self.req('GET','/errors/report')
  self.assertEqual(code,200)
  self.assertIn('session_started_at',report)
  self.assertIn('total_errors',report)
  self.assertIsInstance(report['errors'],list)
  self.req('POST','/open_path',{'path':str(self.root/'missing.pdf'),'study_id':'LOCAL'})
  code,report2=self.req('GET','/errors/report')
  self.assertEqual(code,200)
  self.assertGreaterEqual(report2['total_errors'],1)
  self.assertEqual(len(report2['errors']),report2['total_errors'])
 def test_main_startup_error_records_report(self):
  import io, sys
  from unittest.mock import patch
  err_root = self.root / 'startup_err_root'
  err_root.mkdir(parents=True, exist_ok=True)
  with patch('sys.argv', ['app.py', '--root', str(err_root), '--port', str(self.server.server_port)]):
   with patch('app._is_hmu_server_running', return_value=False):
    out = io.StringIO()
    with patch('sys.stdout', out):
     with self.assertRaises(SystemExit):
      app.main()
  report_file = err_root / 'error_report.json'
  self.assertTrue(report_file.is_file())
  report = json.loads(report_file.read_text(encoding='utf-8'))
  self.assertEqual(report['errors'][-1]['stage'], 'STARTUP')
  self.assertIn('[HMU LỖI]', out.getvalue())
  self.assertIn('[HMU BÁO LỖI]', out.getvalue())
 def test_main_shutdown_summarizes_errors(self):
  import io, sys
  from unittest.mock import patch
  sum_root = self.root / 'shutdown_sum_root'
  sum_root.mkdir(parents=True, exist_ok=True)
  from error_pipeline import record_error_event
  record_error_event(sum_root, ValueError('Test error during session'), stage='HTTP_API')
  with patch('sys.argv', ['app.py', '--root', str(sum_root), '--port', '8769', '--no-browser']):
   with patch('app.create_server') as mock_create:
    mock_server = mock_create.return_value
    mock_server.server_port = 8769
    mock_server.serve_forever.side_effect = KeyboardInterrupt
    out = io.StringIO()
    with patch('sys.stdout', out):
     app.main()
    mock_server.server_close.assert_called_once()
    self.assertIn('[HMU BÁO LỖI] Phiên làm việc ghi nhận 1 lỗi.', out.getvalue())
    self.assertIn(str((sum_root / 'error_report.json').resolve()), out.getvalue())
 def test_workspace_init_creates_folders_and_persists_config(self):
  desktop_dir = self.root / "fake_desktop"
  desktop_dir.mkdir(parents=True, exist_ok=True)
  # 1. Gọi POST /workspace/init với workspace_name="BenhAn_Dot01"
  code, resp = self.req('POST', '/workspace/init', {
      'workspace_name': 'BenhAn_Dot01',
      'desktop_base': str(desktop_dir)
  })
  self.assertEqual(code, 200, resp)
  self.assertEqual(resp['workspace_name'], 'BenhAn_Dot01')
  self.assertEqual(resp['workspace_dir'], str((desktop_dir / 'BenhAn_Dot01').resolve()))
  self.assertEqual(resp['data_root'], str((desktop_dir / 'BenhAn_Dot01' / 'Data_Root').resolve()))
  self.assertEqual(resp['data_deidentified'], str((desktop_dir / 'BenhAn_Dot01' / 'Data_Deidentified').resolve()))

  self.assertTrue((desktop_dir / 'BenhAn_Dot01' / 'Data_Root').is_dir())
  self.assertTrue((desktop_dir / 'BenhAn_Dot01' / 'Data_Deidentified').is_dir())

  cfg_file = self.root / 'jobs' / 'workspace_config.json'
  self.assertTrue(cfg_file.is_file())
  cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
  self.assertEqual(cfg['workspace_name'], 'BenhAn_Dot01')
  self.assertEqual(cfg['data_root'], str((desktop_dir / 'BenhAn_Dot01' / 'Data_Root').resolve()))
  self.assertEqual(cfg['data_deidentified'], str((desktop_dir / 'BenhAn_Dot01' / 'Data_Deidentified').resolve()))

  # 2. Tên chứa ký tự không hợp lệ trên Windows (<>:"/\|?* hoặc ..) bị chặn với mã lỗi 400 (FILE_ERROR)
  for invalid_name in ['BenhAn/Dot01', 'BenhAn\\Dot01', 'Dot:01', 'Dot*01', 'Dot?01', 'Dot<01>', 'Dot"01', 'Dot|01', '..', 'Dot..01', 'CON', 'PRN', ' ']:
      c, err = self.req('POST', '/workspace/init', {'workspace_name': invalid_name, 'desktop_base': str(desktop_dir)})
      self.assertEqual(c, 400, f"Expected 400 for name: {invalid_name}")
      self.assertEqual(err.get('error_detail', {}).get('category'), 'FILE_ERROR', f"Expected FILE_ERROR for {invalid_name}: {err}")

  # 3. GET /state trả về đúng cấu hình workspace đã lưu khi mở lại phiên làm việc
  c, state = self.req('GET', '/state')
  self.assertEqual(c, 200)
  self.assertIn('workspace', state)
  self.assertIsNotNone(state['workspace'])
  self.assertEqual(state['workspace']['workspace_name'], 'BenhAn_Dot01')
  self.assertEqual(state['workspace']['data_root'], str((desktop_dir / 'BenhAn_Dot01' / 'Data_Root').resolve()))

  # Test /workspace/state
  c, ws_state = self.req('GET', '/workspace/state')
  self.assertEqual(c, 200)
  self.assertEqual(ws_state.get('workspace_name'), 'BenhAn_Dot01')

  # Test /workspace/open_explorer
  c, exp_res = self.req('POST', '/workspace/open_explorer', {'target': 'data_root'})
  self.assertEqual(c, 200)
  self.assertEqual(exp_res.get('status'), 'ok')
  self.assertEqual(exp_res.get('opened'), str((desktop_dir / 'BenhAn_Dot01' / 'Data_Root').resolve()))

 def test_preclone_on_batch_enqueue_and_open_path(self):
  desktop_dir = self.root / "fake_desktop_preclone"
  desktop_dir.mkdir(parents=True, exist_ok=True)
  code, ws_init = self.req('POST', '/workspace/init', {
      'workspace_name': 'HMU_Dot1_Preclone',
      'desktop_base': str(desktop_dir)
  })
  self.assertEqual(code, 200, ws_init)
  data_root = Path(ws_init['data_root'])
  data_deidentified = Path(ws_init['data_deidentified'])

  # 1. Tạo 2 folder bệnh án thật trong Data_Root:
  ba1 = data_root / 'BA001_NguyenVanA'
  ba2 = data_root / 'BA002_TranThiB'
  ba1.mkdir(parents=True, exist_ok=True)
  ba2.mkdir(parents=True, exist_ok=True)

  to_bia = ba1 / 'to_bia.pdf'
  xet_nghiem = ba2 / 'xet_nghiem.pdf'
  with fitz.open() as d:
      d.new_page().insert_text((50, 50), "Benh an BA001")
      d.save(to_bia)
  with fitz.open() as d:
      d.new_page().insert_text((50, 50), "Benh an BA002")
      d.save(xet_nghiem)

  # 2. Gọi POST /batch/enqueue với đường dẫn Data_Root:
  code, enq_res = self.req('POST', '/batch/enqueue', {'paths': [str(data_root)]})
  self.assertEqual(code, 200, enq_res)
  self.assertIn('cloned_folders', enq_res)

  # Ngay lập tức trong Data_Deidentified xuất hiện 2 folder trống
  self.assertTrue((data_deidentified / 'BA001_NguyenVanA').is_dir())
  self.assertTrue((data_deidentified / 'BA002_TranThiB').is_dir())
  self.assertEqual(len(list((data_deidentified / 'BA001_NguyenVanA').iterdir())), 0)
  self.assertEqual(len(list((data_deidentified / 'BA002_TranThiB').iterdir())), 0)

  # 3. Kiểm tra trong SQLite jobs: bản ghi to_bia trỏ đúng vào BA001, xet_nghiem trỏ đúng vào BA002
  import sqlite3
  db_path = self.root / 'jobs' / 'batch' / 'queue.sqlite3'
  with sqlite3.connect(db_path) as con:
      con.row_factory = sqlite3.Row
      r1 = con.execute("SELECT target_folder FROM jobs WHERE source_path=?", (str(to_bia.resolve()),)).fetchone()
      self.assertIsNotNone(r1)
      self.assertEqual(r1['target_folder'], str((data_deidentified / 'BA001_NguyenVanA').resolve()))

      r2 = con.execute("SELECT target_folder FROM jobs WHERE source_path=?", (str(xet_nghiem.resolve()),)).fetchone()
      self.assertIsNotNone(r2)
      self.assertEqual(r2['target_folder'], str((data_deidentified / 'BA002_TranThiB').resolve()))

  # 4. Kiểm tra /open_path với folder bệnh án:
  code, open_res = self.req('POST', '/open_path', {'path': str(ba1), 'study_id': 'CASE_BA1'})
  self.assertEqual(code, 200, open_res)
  self.assertIn('cloned_folders', open_res)
  self.assertIn(str((data_deidentified / 'BA001_NguyenVanA').resolve()), open_res['cloned_folders'])

  # Kiểm tra case_manifest.json lưu target_folder
  manifest_files = list(self.root.glob('**/case_manifest.json'))
  self.assertTrue(len(manifest_files) > 0)
  manifest = json.loads(manifest_files[-1].read_text(encoding='utf-8'))
  self.assertEqual(manifest.get('target_folder'), str((data_deidentified / 'BA001_NguyenVanA').resolve()))

 def test_local_path_folder_export_direct_to_cloned_folder_and_creates_copy_on_collision(self):
  import delivery
  base_dest = self.root / 'test_resolve_dest'
  base_dest.mkdir(parents=True, exist_ok=True)
  # 1. Unit test delivery.resolve_target_folder_with_copy
  p1, copied1, from1 = delivery.resolve_target_folder_with_copy(base_dest, 'BA_ALPHA', ['doc.pdf'])
  self.assertEqual(p1, (base_dest / 'BA_ALPHA').resolve())
  self.assertFalse(copied1)
  self.assertIsNone(from1)

  # Tạo pre-clone rỗng
  p1.mkdir(parents=True, exist_ok=True)
  p1_again, copied1_again, _ = delivery.resolve_target_folder_with_copy(base_dest, 'BA_ALPHA', ['doc.pdf'])
  self.assertEqual(p1_again, p1)
  self.assertFalse(copied1_again)

  # Giả lập đã xuất PDF hoặc manifest
  (p1 / 'manifest.json').write_text('{}', encoding='utf-8')
  p2, copied2, from2 = delivery.resolve_target_folder_with_copy(base_dest, 'BA_ALPHA', ['doc.pdf'])
  self.assertEqual(p2, (base_dest / 'BA_ALPHA_Copy1').resolve())
  self.assertTrue(copied2)
  self.assertEqual(from2, str(p1))

  # Giả lập Copy1 cũng đã xuất
  p2.mkdir(parents=True, exist_ok=True)
  (p2 / 'doc.pdf').write_bytes(b'%PDF-1.4 mock')
  p3, copied3, from3 = delivery.resolve_target_folder_with_copy(base_dest, 'BA_ALPHA', ['doc.pdf'])
  self.assertEqual(p3, (base_dest / 'BA_ALPHA_Copy2').resolve())
  self.assertTrue(copied3)
  self.assertEqual(from3, str(p1))

  # 2. Integration test qua HTTP endpoint /export_folder
  case_dir = self.root / 'BN_TEST_COLLISION'
  case_dir.mkdir(parents=True, exist_ok=True)
  (case_dir / 'file1.pdf').write_bytes(self.pdf())
  (case_dir / 'file2.pdf').write_bytes(self.pdf())

  deid_root = self.root / 'Data_Deidentified'
  deid_root.mkdir(parents=True, exist_ok=True)

  code, open_res = self.req('POST', '/open_path', {'path': str(case_dir), 'study_id': 'COLLISION', 'destination': str(deid_root)})
  self.assertEqual(code, 200, open_res)
  code, app_res = self.req('POST', '/approve_all', self.ident(open_res['review']))
  self.assertEqual(code, 200, app_res)

  # Xuất lần 1: đổ thẳng vào Data_Deidentified/BN_TEST_COLLISION (đã clone)
  code, exp1 = self.req('POST', '/export_folder', {**self.ident(app_res['review']), 'destination': str(deid_root)})
  self.assertEqual(code, 200, exp1)
  target_patient = deid_root / 'BN_TEST_COLLISION'
  self.assertEqual(Path(exp1['directory']).resolve(), target_patient.resolve())
  self.assertNotIn('BAN_GIAO_', exp1['directory'])
  self.assertFalse(exp1.get('copied_for_comparison', False))
  self.assertIsNone(exp1.get('original_directory'))
  self.assertTrue((target_patient / 'file1.pdf').exists())
  self.assertTrue((target_patient / 'manifest.json').exists())

  # Xuất lần 2: phát hiện trùng, giữ nguyên bản cũ, tạo BN_TEST_COLLISION_Copy1
  code, exp2 = self.req('POST', '/export_folder', {**self.ident(app_res['review']), 'destination': str(deid_root)})
  self.assertEqual(code, 200, exp2)
  copy1_patient = deid_root / 'BN_TEST_COLLISION_Copy1'
  self.assertEqual(Path(exp2['directory']).resolve(), copy1_patient.resolve())
  self.assertTrue(exp2.get('copied_for_comparison'))
  self.assertEqual(exp2.get('original_directory'), str(target_patient.resolve()))
  self.assertTrue((target_patient / 'file1.pdf').exists()) # Bản cũ vẫn nguyên vẹn
  self.assertTrue((copy1_patient / 'file1.pdf').exists())

  # Xuất lần 3: tạo BN_TEST_COLLISION_Copy2
  code, exp3 = self.req('POST', '/export_folder', {**self.ident(app_res['review']), 'destination': str(deid_root)})
  self.assertEqual(code, 200, exp3)
  copy2_patient = deid_root / 'BN_TEST_COLLISION_Copy2'
  self.assertEqual(Path(exp3['directory']).resolve(), copy2_patient.resolve())
  self.assertTrue(exp3.get('copied_for_comparison'))
  self.assertEqual(exp3.get('original_directory'), str(target_patient.resolve()))

 def test_windows_batch_files_crlf_and_safe_syntax(self):
  repo_root = Path(__file__).resolve().parent
  for bat_name in ('CAI_DAT_WINDOWS.bat', 'MO_CONG_CU.bat'):
   bat_path = repo_root / bat_name
   raw = bat_path.read_bytes()
   self.assertFalse(raw.startswith((b'\xff\xfe', b'\xfe\xff', b'\xef\xbb\xbf')), f'{bat_name} must not have BOM')
   text = raw.decode('utf-8')
   crlf_count = raw.count(b'\r\n')
   lf_only_count = raw.count(b'\n') - crlf_count
   self.assertGreater(crlf_count, 0, f'{bat_name} must have CRLF line endings')
   self.assertEqual(lf_only_count, 0, f'{bat_name} must use CRLF on every line for cmd.exe compatibility')
   for line in text.splitlines():
    stripped = line.strip()
    self.assertFalse(
     stripped.startswith('if ') and stripped.endswith('('),
     f'{bat_name} must use goto labels instead of parenthesized if-blocks: {stripped}'
    )
  for py_path in repo_root.glob('*.py'):
   raw = py_path.read_bytes()
   self.assertNotIn(b'\x00', raw, f'{py_path.name} contains null bytes')
   self.assertFalse(raw.startswith(b'\xff'), f'{py_path.name} starts with 0xFF')
   raw.decode('utf-8')

 def test_batch_status_includes_updated_and_error_detail(self):
  import batch
  source = self.root / 'fail_case.pdf'
  source.write_bytes(self.pdf())
  db = self.root / 'jobs' / 'batch' / 'queue.sqlite3'
  ident = batch.enqueue(db, [source])[0]
  batch.claim_next(db)
  err_detail = {
   'id': 'err_test_99',
   'category': 'FILE_ERROR',
   'stage': 'BATCH_WORKER',
   'message': 'Tệp PDF bị hỏng cấu trúc',
   'source_file': 'fail_case.pdf',
  }
  batch.set_stage_result(
   db,
   ident,
   expected_state='PREPARING',
   result={'state': 'FAILED', 'error': 'Tệp PDF bị hỏng cấu trúc', 'error_detail': err_detail},
  )
  code, status = self.req('GET', '/batch/status')
  self.assertEqual(code, 200, status)
  self.assertEqual(len(status['jobs']), 1)
  item = status['jobs'][0]
  self.assertEqual(item['id'], ident)
  self.assertEqual(item['state'], 'FAILED')
  self.assertIn('updated', item)
  self.assertIsInstance(item['updated'], (int, float))
  self.assertEqual(item.get('error_detail'), err_detail)

 def test_create_server_recovers_stuck_batch_queue_when_unlocked(self):
  import batch
  custom_root = self.root / 'recover_jobs'
  db = custom_root / 'batch' / 'queue.sqlite3'
  s1 = self.root / 'stuck1.pdf'
  s2 = self.root / 'stuck2.pdf'
  s1.write_bytes(self.pdf())
  s2.write_bytes(self.pdf())
  ids = batch.enqueue(db, [s1, s2])
  batch.claim_next(db)  # ids[0] -> PREPARING
  batch.claim_next(db)  # ids[1] -> PREPARING
  batch.cancel_job(db, ids[1])  # ids[1] -> CANCELLING

  # 1. If coordinator holds queue_lock, create_server must not block or fail, and leaves states untouched
  with batch.queue_lock(db):
   srv_locked = app.create_server(custom_root, None, 0)
   srv_locked.server_close()
  self.assertEqual(batch.get_job(db, ids[0])['state'], 'PREPARING')
  self.assertEqual(batch.get_job(db, ids[1])['state'], 'CANCELLING')

  # 2. When no coordinator holds queue_lock, create_server automatically recovers stuck jobs
  srv_unlocked = app.create_server(custom_root, None, 0)
  srv_unlocked.server_close()
  self.assertEqual(batch.get_job(db, ids[0])['state'], 'QUEUED')
  self.assertEqual(batch.get_job(db, ids[1])['state'], 'CANCELLED')

 def test_state_returns_active_task_when_running(self):
  import time
  from unittest.mock import patch
  d = self.upload()
  # When idle, active_task is None (or not running)
  _, idle_state = self.req('GET', '/state')
  self.assertIsNone(idle_state.get('active_task'))

  started = threading.Event()
  release = threading.Event()
  original = app.export_reviewed_folder
  def slow(*args, **kwargs):
   kwargs['progress_cb']('Đang xuất 1/1')
   started.set()
   release.wait(5)
   return original(*args, **kwargs)
  with patch.object(app, 'export_reviewed_folder', side_effect=slow):
   code, result = self.req('POST', '/export_folder', {**self.ident(d), 'destination': str(self.root / 'out_state_task')}, {'X-HMU-Async': '1'})
   self.assertEqual(code, 202, result)
   self.assertTrue(started.wait(2))
   try:
    code, running_state = self.req('GET', '/state')
    self.assertEqual(code, 200, running_state)
    self.assertIsNotNone(running_state.get('active_task'))
    self.assertEqual(running_state['active_task']['status'], 'running')
    self.assertEqual(running_state['active_task']['task_id'], result['task_id'])
    self.assertEqual(running_state['active_task']['progress'], 'Đang xuất 1/1')
   finally:
    release.set()
   for _ in range(100):
    prog = self.req('GET', '/progress?task_id=' + result['task_id'])[1]
    if prog['status'] != 'running':
     break
    time.sleep(0.02)
   _, done_state = self.req('GET', '/state')
   self.assertIsNone(done_state.get('active_task'))

 def test_configure_windows_console_disables_quick_edit_and_sets_title(self):
  from unittest.mock import patch, MagicMock
  fake_kernel32 = MagicMock()
  fake_kernel32.GetStdHandle.return_value = 42
  def fake_get_mode(handle, mode_ptr):
   mode_ptr._obj.value = 0x0040 | 0x0080 | 0x0001
   return 1
  fake_kernel32.GetConsoleMode.side_effect = fake_get_mode
  fake_kernel32.SetConsoleMode.return_value = 1
  with patch('app.os.name', 'nt'), patch('ctypes.windll', create=True) as mock_windll:
   mock_windll.kernel32 = fake_kernel32
   app._configure_windows_console()
  fake_kernel32.GetStdHandle.assert_called_once_with(-10)
  fake_kernel32.SetConsoleMode.assert_called_once()
  handle_arg, new_mode_arg = fake_kernel32.SetConsoleMode.call_args[0]
  self.assertEqual(handle_arg, 42)
  self.assertEqual(new_mode_arg & 0x0040, 0)
  self.assertEqual(new_mode_arg & 0x0080, 0x0080)
  fake_kernel32.SetConsoleTitleW.assert_called_once()

 def test_is_hmu_server_running_detects_live_instance(self):
  self.assertTrue(app._is_hmu_server_running(self.server.server_port))
  self.assertFalse(app._is_hmu_server_running(9))

 def test_main_reopens_browser_and_exits_zero_when_hmu_server_already_running(self):
  import io
  from unittest.mock import patch
  reuse_root = self.root / 'reuse_session_root'
  reuse_root.mkdir(parents=True, exist_ok=True)
  with patch('sys.argv', ['app.py', '--root', str(reuse_root), '--port', str(self.server.server_port)]):
   with patch('webbrowser.open') as mock_open:
    out = io.StringIO()
    with patch('sys.stdout', out):
     with self.assertRaises(SystemExit) as cm:
      app.main()
     self.assertEqual(cm.exception.code, 0)
    mock_open.assert_called_once_with(f'http://127.0.0.1:{self.server.server_port}')
  self.assertFalse((reuse_root / 'error_report.json').exists())
  self.assertIn(f'http://127.0.0.1:{self.server.server_port}', out.getvalue())

 def test_main_startup_error_records_report_when_port_occupied_by_non_hmu(self):
  import io
  from unittest.mock import patch
  err_root = self.root / 'non_hmu_err_root'
  err_root.mkdir(parents=True, exist_ok=True)
  with patch('sys.argv', ['app.py', '--root', str(err_root), '--port', str(self.server.server_port)]):
   with patch('app._is_hmu_server_running', return_value=False):
    out = io.StringIO()
    with patch('sys.stdout', out):
     with self.assertRaises(SystemExit) as cm:
      app.main()
     self.assertNotEqual(cm.exception.code, 0)
  self.assertTrue((err_root / 'error_report.json').is_file())

 def test_main_prints_do_not_close_warning_banner_on_startup(self):
  import io
  from unittest.mock import patch
  banner_root = self.root / 'banner_root'
  banner_root.mkdir(parents=True, exist_ok=True)
  with patch('sys.argv', ['app.py', '--root', str(banner_root), '--port', '8771', '--no-browser']):
   with patch('app.create_server') as mock_create:
    mock_server = mock_create.return_value
    mock_server.server_port = 8771
    mock_server.serve_forever.side_effect = KeyboardInterrupt
    out = io.StringIO()
    with patch('sys.stdout', out):
     app.main()
    self.assertIn('LƯU Ý: KHÔNG ĐÓNG CỬA SỔ ĐEN NÀY KHI ĐANG DUYỆT BỆNH ÁN (Hãy thu nhỏ xuống thanh Taskbar)', out.getvalue())

 def test_static_assets_do_not_block_on_server_lock(self):
  from unittest.mock import patch
  entered = threading.Event()
  release = threading.Event()
  orig_get_ws = app.get_workspace_config
  def slow_ws(*args, **kwargs):
   entered.set()
   release.wait(2.0)
   return orig_get_ws(*args, **kwargs)
  with patch.object(app, 'get_workspace_config', side_effect=slow_ws):
   holder = threading.Thread(target=lambda: self.req('GET', '/workspace/state'), daemon=True)
   holder.start()
   self.assertTrue(entered.wait(1.0))
   try:
    for asset_path in ('/', '/ui/review.js', '/ui/review.css'):
     c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=0.3)
     try:
      c.request('GET', asset_path, headers={'Host': f'127.0.0.1:{self.server.server_port}'})
      r = c.getresponse()
      r.read()
      self.assertEqual(r.status, 200, asset_path)
     finally:
      c.close()
   finally:
    release.set()
    holder.join(timeout=2.0)


if __name__=='__main__':unittest.main()
