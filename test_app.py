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
if __name__=='__main__':unittest.main()
