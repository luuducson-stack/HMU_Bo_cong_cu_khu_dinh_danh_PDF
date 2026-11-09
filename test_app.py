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

 def test_batch_retry_single_and_bulk_starts_background_and_allows_opening_failed_with_review(self):
  import batch, batch_worker
  from unittest.mock import patch
  s1 = self.root / 'retry_1.pdf'
  s2 = self.root / 'retry_2.pdf'
  s1.write_bytes(self.pdf())
  s2.write_bytes(self.pdf())
  db = self.root / 'jobs' / 'batch' / 'queue.sqlite3'
  ids = batch.enqueue(db, [s1, s2])
  r1 = batch.claim_next(db)
  r2 = batch.claim_next(db)
  with patch('output_qc.ocr_pdf_pages', return_value={1: ('Clinical stable', [])}):
   res1 = batch_worker.process_job(r1, ocr_workers=1, render_workers=1)
  batch.set_stage_result(db, ids[0], expected_state='PREPARING', result={'state': 'FAILED', 'error': 'Export verify failed'})
  batch.set_stage_result(db, ids[1], expected_state='PREPARING', result={'state': 'FAILED', 'error': 'Worker crash'})
  batch.pause_queue(db)

  code, st = self.req('GET', '/batch/status')
  self.assertEqual(code, 200, st)
  by_id = {j['id']: j for j in st['jobs']}
  self.assertEqual(by_id[ids[0]]['source_path'], str(s1.resolve()))
  self.assertTrue(by_id[ids[0]]['can_open'], 'FAILED job with prepared review.json must report can_open=True')
  self.assertFalse(by_id[ids[1]]['can_open'], 'FAILED job without review.json must report can_open=False')

  # User can open FAILED job that already has review.json to inspect/test on canvas
  code, opened = self.req('POST', '/batch/open_job', {'queue_id': ids[0]})
  self.assertEqual(code, 200, opened)
  self.assertEqual(opened['queue_id'], ids[0])

  # Single retry and bulk retry both resume queue and start background coordinator
  with patch('batch.start_background', return_value=9999) as mock_bg:
   code, ret1 = self.req('POST', '/batch/retry', {'queue_id': ids[0]})
   self.assertEqual(code, 200, ret1)
   self.assertTrue(ret1.get('queued'))
   self.assertIn(ids[0], ret1.get('retried', []))
   self.assertEqual(mock_bg.call_count, 1)

   code, ret2 = self.req('POST', '/batch/retry', {'queue_ids': [ids[1]]})
   self.assertEqual(code, 200, ret2)
   self.assertEqual(ret2.get('retried'), [ids[1]])
   self.assertEqual(mock_bg.call_count, 2)

  self.assertEqual(batch.get_job(db, ids[0])['state'], 'QUEUED')
  self.assertEqual(batch.get_job(db, ids[1])['state'], 'QUEUED')

 def test_single_folder_session_saves_picked_folder_and_active_page_across_restart(self):
  from unittest.mock import patch
  case_dir = self.root / 'ca_benh_don_01'
  case_dir.mkdir(exist_ok=True)
  for idx in range(1, 3):
   doc = fitz.open()
   for pno in range(1, 4):
    page = doc.new_page(width=300, height=200)
    page.insert_text((36, 72), f'Benh nhan Nguyen Van A - File {idx} Trang {pno}')
   doc.save(case_dir / f'benh_an_{idx}.pdf')
   doc.close()
  dest_dir = self.root / 'ket_qua_xuat'
  with patch.object(app, '_pick_folder_dialog', return_value=str(case_dir)):
   code, picked = self.req('POST', '/pick_folder', {'initial_dir': str(self.root), 'target': 'localPath'})
   self.assertEqual(code, 200, picked)
  code, saved_sess = self.req('POST', '/session/save', {
   'selected_path': str(case_dir),
   'destination': str(dest_dir),
   'study_id': 'HMU_SINGLE_01',
   'whole_case': True,
   'active_page': 1,
  })
  self.assertEqual(code, 200, saved_sess)
  # Restart server BEFORE opening path -> selected_path & destination must still be restored
  restarted1 = app.create_server(self.root / 'jobs', None, 0)
  t1 = threading.Thread(target=restarted1.serve_forever, daemon=True); t1.start()
  try:
   c = http.client.HTTPConnection('127.0.0.1', restarted1.server_port, timeout=30)
   c.request('GET', '/state'); r = c.getresponse(); st1 = json.loads(r.read()); c.close()
   self.assertEqual(st1['session']['selected_path'], str(case_dir))
   self.assertEqual(st1['session']['destination'], str(dest_dir))
   self.assertEqual(st1['session']['study_id'], 'HMU_SINGLE_01')
   self.assertTrue(st1['session']['whole_case'])
  finally:
   restarted1.shutdown(); restarted1.server_close(); t1.join()
  # Open folder, switch to file 2, page 3, save page 3, then restart server
  code, opened = self.req('POST', '/open_path', {'path': str(case_dir), 'study_id': 'HMU_SINGLE_01', 'destination': str(dest_dir)})
  self.assertEqual(code, 200, opened)
  code, st_f2 = self.req('POST', '/select_file', {**self.ident(opened['review']), 'file_index': 2})
  self.assertEqual(code, 200, st_f2)
  d2 = st_f2['review']
  p3 = d2['pages'][2]
  code, saved_p3 = self.req('POST', '/save_page', {
   **self.ident(d2), 'page': 3, 'reviewed': True, 'manual_rects': [[10, 10, 80, 40]],
   'note': ' Đã duyệt trang 3 file 2',
   'selections': [{'id': q['id'], 'selected': q['selected']} for q in p3['proposals']]
  })
  self.assertEqual(code, 200, saved_p3)
  restarted2 = app.create_server(self.root / 'jobs', None, 0)
  t2 = threading.Thread(target=restarted2.serve_forever, daemon=True); t2.start()
  try:
   c = http.client.HTTPConnection('127.0.0.1', restarted2.server_port, timeout=30)
   c.request('GET', '/state'); r = c.getresponse(); st2 = json.loads(r.read()); c.close()
   self.assertEqual(st2['review']['job_id'], d2['job_id'])
   self.assertEqual(st2['session']['active_file_index'], 2)
   self.assertEqual(st2['session']['active_page'], 3)
   self.assertEqual(st2['session']['selected_path'], str(case_dir.resolve()))
  finally:
   restarted2.shutdown(); restarted2.server_close(); t2.join()

 def test_interrupted_folder_prepare_checkpoints_completed_files_and_resumes_without_reprocessing(self):
  from unittest.mock import patch
  import engine
  case_dir = self.root / 'ca_benh_3_files'
  case_dir.mkdir(exist_ok=True)
  for idx in range(1, 4):
   (case_dir / f'ho_so_{idx:02d}.pdf').write_bytes(self.pdf())
  prepared_calls = []
  orig_prepare = engine.prepare
  def flaky_prepare(pdf_file, sub_job, *args, **kwargs):
   prepared_calls.append(Path(pdf_file).name)
   if len(prepared_calls) == 3:
    raise RuntimeError('Terminal closed during file 3')
   return orig_prepare(pdf_file, sub_job, *args, **kwargs)
  with patch('engine.prepare', side_effect=flaky_prepare):
   code, err_res = self.req('POST', '/open_path', {'path': str(case_dir), 'study_id': 'RESUME_CASE'})
   self.assertEqual(code, 400, err_res)
  # 2 files were prepared before crash; checkpoint manifest & last_session must exist
  self.assertEqual(prepared_calls, ['ho_so_01.pdf', 'ho_so_02.pdf', 'ho_so_03.pdf'])
  manifests = list((self.root / 'jobs').glob('*/case/case_manifest.json'))
  self.assertEqual(len(manifests), 1)
  partial_manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
  self.assertFalse(partial_manifest.get('complete', True))
  self.assertEqual(len(partial_manifest['files']), 2)
  # Now user restarts tool and opens the same folder again -> only file 3 should be prepared!
  resumed_calls = []
  def tracking_prepare(pdf_file, sub_job, *args, **kwargs):
   resumed_calls.append(Path(pdf_file).name)
   return orig_prepare(pdf_file, sub_job, *args, **kwargs)
  with patch('engine.prepare', side_effect=tracking_prepare):
   code, ok_res = self.req('POST', '/open_path', {'path': str(case_dir), 'study_id': 'RESUME_CASE'})
   self.assertEqual(code, 200, ok_res)
  self.assertEqual(resumed_calls, ['ho_so_03.pdf'])
  self.assertEqual(len(ok_res['files']), 3)

 def test_e2e_single_folder_session_lifecycle_with_real_logs(self):
  """
  Kiểm thử tích hợp End-to-End toàn bộ vòng đời phiên làm việc Folder đơn với log thực tế:
  - Chặng 1: Sinh dữ liệu động thực tế (PDF nhiều trang với token ngẫu nhiên, không hardcode).
  - Chặng 2: Mở folder và ngắt quãng giữa chừng khi đang quét (mô phỏng crash / tắt terminal),
             kiểm chứng checkpoint manifest lưu lũy tiến (complete=False).
  - Chặng 3: Khởi động quét tiếp (resume), kiểm chứng tái sử dụng các file đã OCR trước đó
             và chỉ xử lý file còn lại (complete=True).
  - Chặng 4: Duyệt từng file, từng trang, cập nhật note/rects và session metadata -> tắt terminal ->
             lưu snapshot -> bật lại server và tự động đồng bộ khôi phục chính xác 100%.
  """
  import secrets, time, hashlib, sys
  from unittest.mock import patch
  import engine

  def log(msg):
   sys.stderr.write(f"\n[REAL-TEST-LOG] {msg}\n")
   sys.stderr.flush()

  # --- CHẶNG 1: KHỞI TẠO DỮ LIỆU ĐỘNG THỰC TẾ ---
  run_token = secrets.token_hex(4)
  case_name = f"ca_benh_dong_{run_token}"
  case_dir = self.root / case_name
  case_dir.mkdir(parents=True, exist_ok=True)
  dest_dir = self.root / f"xuat_benh_an_{run_token}"
  study_id = f"HMU_E2E_{secrets.token_hex(3).upper()}"

  file_names = [
   f"01_benh_an_{secrets.token_hex(2)}.pdf",
   f"02_xet_nghiem_{secrets.token_hex(2)}.pdf",
   f"03_chuan_doan_{secrets.token_hex(2)}.pdf"
  ]
  file_paths = []
  file_hashes = {}
  for idx, fn in enumerate(file_names, 1):
   doc = fitz.open()
   for p_idx in range(2):
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 60), f"BỆNH VIỆN ĐẠI HỌC Y HÀ NỘI - HỒ SƠ #{idx}")
    page.insert_text((40, 100), f"Bệnh nhân: Bệnh nhân {idx} - Mã: {secrets.token_hex(3)}")
    page.insert_text((40, 140), f"Trang {p_idx + 1}/2 - Thời gian tạo: {time.strftime('%Y-%m-%d %H:%M:%S')}")
   pdf_bytes = doc.tobytes()
   doc.close()
   fp = case_dir / fn
   fp.write_bytes(pdf_bytes)
   file_paths.append(fp)
   file_hashes[fn] = hashlib.sha256(pdf_bytes).hexdigest()

  log(f"[CHẶNG 1: CHỌN FOLDER DỮ LIỆU ĐỘNG]")
  log(f"  - Thư mục ca bệnh: {case_dir}")
  log(f"  - Thư mục đích dự kiến: {dest_dir}")
  log(f"  - Mã đề tài nghiên cứu: {study_id}")
  log(f"  - 3 tệp PDF tạo động thành công:")
  for fn in file_names:
   log(f"    * {fn} | SHA256: {file_hashes[fn][:16]}... | Kích thước: {len((case_dir / fn).read_bytes())} bytes")

  # --- CHẶNG 2: NGẮT QUÃNG KHI ĐANG QUÉT ---
  log(f"[CHẶNG 2: NGẮT QUÃNG GIỮA CHỪNG KHI ĐANG QUÉT]")
  prepared_order = []
  orig_prepare = engine.prepare
  def interrupted_prepare(pdf_file, sub_job, *args, **kwargs):
   pname = Path(pdf_file).name
   prepared_order.append(pname)
   if len(prepared_order) == 3:
    log(f"  - [MÔ PHỎNG] Gặp sự cố đột ngột / tắt terminal khi đang OCR tệp thứ 3: {pname}")
    raise RuntimeError(f"Terminal crash simulation on {pname}")
   return orig_prepare(pdf_file, sub_job, *args, **kwargs)

  with patch('engine.prepare', side_effect=interrupted_prepare):
   code, err_res = self.req('POST', '/open_path', {
    'path': str(case_dir),
    'study_id': study_id,
    'destination': str(dest_dir)
   })
   self.assertEqual(code, 400, err_res)
   log(f"  - Server trả về mã lỗi 400 như kỳ vọng: {err_res}")

  self.assertEqual(len(prepared_order), 3)
  manifests = list((self.root / 'jobs').glob('*/case/case_manifest.json'))
  self.assertEqual(len(manifests), 1, "Phải ghi checkpoint case_manifest.json ngay sau các file đầu")
  checkpoint = json.loads(manifests[0].read_text(encoding='utf-8'))
  self.assertFalse(checkpoint.get('complete', True), "Trạng thái complete trong checkpoint phải là False")
  self.assertEqual(len(checkpoint['files']), 2, "Checkpoint phải lưu chính xác 2 file đã hoàn thành")
  log(f"  - Checkpoint case_manifest.json đã ghi nhận:")
  log(f"    * Hoàn tất (complete): {checkpoint['complete']}")
  log(f"    * Số file đã chuẩn bị an toàn: {len(checkpoint['files'])} / {len(file_names)}")
  log(f"    * Danh sách file đã lưu checkpoint: {[f['source_name'] for f in checkpoint['files']]}")

  # --- CHẶNG 3: KHÔI PHỤC VÀ TIẾP TỤC QUÉT FOLDER ---
  log(f"[CHẶNG 3: KHÔI PHỤC VÀ TIẾP TỤC QUÉT]")
  resumed_order = []
  def tracking_prepare(pdf_file, sub_job, *args, **kwargs):
   pname = Path(pdf_file).name
   resumed_order.append(pname)
   return orig_prepare(pdf_file, sub_job, *args, **kwargs)

  with patch('engine.prepare', side_effect=tracking_prepare):
   code, ok_res = self.req('POST', '/open_path', {
    'path': str(case_dir),
    'study_id': study_id,
    'destination': str(dest_dir)
   })
   self.assertEqual(code, 200, ok_res)

  self.assertEqual(resumed_order, [file_names[2]], "Chỉ duy nhất tệp thứ 3 phải chuẩn bị lại, tệp 1 & 2 được tái sử dụng!")
  self.assertEqual(len(ok_res['files']), 3)
  final_checkpoint = json.loads(manifests[0].read_text(encoding='utf-8'))
  self.assertTrue(final_checkpoint.get('complete'), "Manifest phải được cập nhật complete = True khi kết thúc")
  log(f"  - Khôi phục mở folder thành công (code 200)")
  log(f"  - Tệp được chuẩn bị bổ sung: {resumed_order}")
  log(f"  - 2 tệp đầu được giữ nguyên vẹn từ sub_jobs trước đó, tiết kiệm 100% chi phí OCR lại.")
  log(f"  - Case manifest hoàn thiện: complete = {final_checkpoint['complete']}, tổng số tệp = {len(final_checkpoint['files'])}")

  # --- CHẶNG 4: DUYỆT TỪNG FILE/TRANG -> TẮT TERMINAL -> LƯU SNAPSHOT -> BẬT LẠI TỰ ĐỒNG BỘ ---
  log(f"[CHẶNG 4: DUYỆT TỆP/TRANG -> LƯU SNAPSHOT -> KHỞI ĐỘNG LẠI TỰ ĐỒNG BỘ]")
  # 4.1. Chuyển sang duyệt tệp 2, trang 2
  code, st_f2 = self.req('POST', '/select_file', {**self.ident(ok_res['review']), 'file_index': 2})
  self.assertEqual(code, 200, st_f2)
  d2 = st_f2['review']
  f2_name = next(f['name'] for f in st_f2.get('files', []) if f['index'] == 2)
  log(f"  - Đã chọn tệp 2 ({f2_name}), job_id: {d2['job_id']}")

  # Duyệt và lưu trang 2 của tệp 2
  p2 = d2['pages'][1]
  offline_note = f"Đã duyệt và khử định danh trang 2 tệp 2 - Token: {run_token}"
  code, saved_p2 = self.req('POST', '/save_page', {
   **self.ident(d2),
   'page': 2,
   'reviewed': True,
   'manual_rects': [[15, 25, 120, 60]],
   'note': offline_note,
   'selections': [{'id': q['id'], 'selected': q['selected']} for q in p2['proposals']]
  })
  self.assertEqual(code, 200, saved_p2)
  log(f"  - Đã lưu chỉnh sửa trang 2 (revision: {saved_p2['revision']}, reviewed: True, note: '{offline_note}')")

  # Lưu session metadata
  code, saved_sess = self.req('POST', '/session/save', {
   'selected_path': str(case_dir),
   'destination': str(dest_dir),
   'study_id': study_id,
   'active_file_index': 2,
   'active_page': 2,
   'whole_case': True
  })
  self.assertEqual(code, 200, saved_sess)
  log(f"  - Đã cập nhật metadata phiên: active_file_index=2, active_page=2, destination={dest_dir}")

  # 4.2. Giả lập tắt Terminal: dừng server hiện tại
  log(f"  - [MÔ PHỎNG] Tắt Terminal (server dừng hoạt động)...")
  self.server.shutdown()
  self.server.server_close()
  self.thread.join()

  # Mô phỏng Web client lưu snapshot vào localStorage trước khi tắt hoặc khi server mất kết nối
  client_snapshot = {
   'saved_at': time.time(),
   'selected_path': str(case_dir.resolve()),
   'destination': str(dest_dir.resolve()),
   'study_id': study_id,
   'active_file_index': 2,
   'active_page': 2,
   'page_patch': {
    'page': 2,
    'reviewed': True,
    'manual_rects': [[15, 25, 120, 60], [200, 250, 350, 280]],
    'note': f"{offline_note} (Đồng bộ bổ sung khi kết nối lại)",
    'selections': [{'id': q['id'], 'selected': q['selected']} for q in p2['proposals']]
   }
  }
  log(f"  - Client lưu snapshot an toàn vào LocalStorage (hmu_session_backup_v1)")

  # 4.3. Bật lại Server mới (mô phỏng người dùng bật lại công cụ qua MO_CONG_CU.bat)
  log(f"  - [MÔ PHỎNG] Bật lại Terminal / Server mới...")
  restarted = app.create_server(self.root / 'jobs', None, 0)
  t_restarted = threading.Thread(target=restarted.serve_forever, daemon=True)
  t_restarted.start()

  try:
   c = http.client.HTTPConnection('127.0.0.1', restarted.server_port, timeout=30)
   c.request('GET', '/state')
   r = c.getresponse()
   st_reboot = json.loads(r.read())
   new_token = st_reboot['token']
   log(f"  - Kết nối lại thành công tới Server mới (Token: {new_token[:8]}...)")

   # Kiểm tra Session tự động khôi phục chính xác
   self.assertEqual(st_reboot['session']['selected_path'], str(case_dir.resolve()))
   self.assertEqual(st_reboot['session']['destination'], str(dest_dir.resolve()))
   self.assertEqual(st_reboot['session']['study_id'], study_id)
   self.assertEqual(st_reboot['session']['active_file_index'], 2)
   self.assertEqual(st_reboot['session']['active_page'], 2)
   self.assertEqual(st_reboot['review']['job_id'], d2['job_id'])
   log(f"  - Trạng thái phiên được Server tự động phục hồi hoàn hảo:")
   log(f"    * selected_path: {st_reboot['session']['selected_path']}")
   log(f"    * destination: {st_reboot['session']['destination']}")
   log(f"    * active_file_index: {st_reboot['session']['active_file_index']}")
   log(f"    * active_page: {st_reboot['session']['active_page']}")
   log(f"    * job_id: {st_reboot['review']['job_id']}")

   # Mô phỏng Web client tự động đồng bộ (syncOfflineSnapshotIfNeeded)
   h_sync = {'X-HMU-Token': new_token}
   sync_body = json.dumps({
    'job_id': st_reboot['review']['job_id'],
    'revision': st_reboot['review']['revision'],
    **client_snapshot['page_patch']
   }).encode()
   c.request('POST', '/save_page', body=sync_body, headers=h_sync)
   r_sync = c.getresponse()
   self.assertEqual(r_sync.status, 200)
   saved_sync = json.loads(r_sync.read())
   self.assertTrue(saved_sync.get('saved'))
   log(f"  - Tự động đồng bộ snapshot từ client lên Server thành công (Revision mới: {saved_sync['revision']})")

   # Kiểm chứng lại /state cuối cùng
   c.request('GET', '/state', headers=h_sync)
   st_final = json.loads(c.getresponse().read())
   c.close()

   p2_verified = st_final['review']['pages'][1]
   self.assertEqual(len(p2_verified['manual_rects']), 2)
   self.assertIn("Đồng bộ bổ sung", p2_verified['note'])
   self.assertTrue(p2_verified['reviewed'])
   log(f"  - Xác nhận trang 2 tệp 2 đã cập nhật đầy đủ dữ liệu đồng bộ (2 manual rects, note chuẩn xác).")
  finally:
   restarted.shutdown()
   restarted.server_close()
   t_restarted.join()

  # Khôi phục server gốc cho tearDown
  self.server = app.create_server(self.root / 'jobs', None, 0)
  self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
  self.thread.start()
  log(f"[KẾT QUẢ] Hoàn thành kiểm thử tích hợp E2E vòng đời phiên Folder đơn: ĐẠT 100% TIÊU CHÍ.")

 def test_update_endpoints_check_apply_rollback_and_conflict_guard(self):
  import subprocess, time, os
  from unittest.mock import patch
  def _run_git(cwd, *args):
   p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True)
   return p.stdout.strip()

  remote_dir = self.root / 'remote.git'
  repo_dir = self.root / 'repo_clone'
  _run_git(self.root, 'init', '--bare', str(remote_dir))
  _run_git(self.root, 'clone', str(remote_dir), str(repo_dir))
  _run_git(repo_dir, 'config', 'user.email', 'hmu_test@hmu.edu.vn')
  _run_git(repo_dir, 'config', 'user.name', 'HMU Tester')
  _run_git(repo_dir, 'checkout', '-b', 'dev')
  (repo_dir / 'app.py').write_text('VERSION = "3.1.0"\n', encoding='utf-8')
  (repo_dir / 'requirements.txt').write_text('pymupdf>=1.24.0\n', encoding='utf-8')
  _run_git(repo_dir, 'add', 'app.py', 'requirements.txt')
  _run_git(repo_dir, 'commit', '-m', 'feat: initial v3.1.0 release')
  _run_git(repo_dir, 'tag', 'v3.1.0')
  _run_git(repo_dir, 'push', '-u', 'origin', 'dev', '--tags')
  v1_sha = _run_git(repo_dir, 'rev-parse', 'HEAD')

  self.server.repo_dir = repo_dir

  # 1. Kiểm tra GET /update/status
  code_403, _ = self.req('GET', '/update/status', headers={'Host': 'bad.host'})
  self.assertEqual(code_403, 403)

  code, status_data = self.req('GET', '/update/status')
  self.assertEqual(code, 200, status_data)
  self.assertEqual(status_data['current']['commit'], v1_sha)
  self.assertEqual(status_data['current']['short_commit'], v1_sha[:7])
  self.assertEqual(status_data['current']['branch'], 'dev')
  self.assertFalse(status_data['current']['can_rollback'])
  self.assertTrue(any(t['name'] == 'v3.1.0' for t in status_data['versions']['tags']))

  # 2. Kiểm tra POST /update/check
  code_bad_tok, _ = self.req('POST', '/update/check', {}, headers={'X-HMU-Token': 'wrong_token'})
  self.assertEqual(code_bad_tok, 403)

  code, check_data = self.req('POST', '/update/check', {})
  self.assertEqual(code, 200, check_data)
  self.assertEqual(check_data['check']['behind'], 0)
  self.assertFalse(check_data['check']['update_available'])

  # Peer clone push v3.2.0
  peer_dir = self.root / 'peer_clone'
  _run_git(self.root, 'clone', '-b', 'dev', str(remote_dir), str(peer_dir))
  _run_git(peer_dir, 'config', 'user.email', 'peer@hmu.edu.vn')
  _run_git(peer_dir, 'config', 'user.name', 'HMU Peer')
  (peer_dir / 'app.py').write_text('VERSION = "3.2.0"\n', encoding='utf-8')
  _run_git(peer_dir, 'add', 'app.py')
  _run_git(peer_dir, 'commit', '-m', 'feat: update v3.2.0 with updater endpoints')
  _run_git(peer_dir, 'tag', 'v3.2.0')
  _run_git(peer_dir, 'push', 'origin', 'dev', '--tags')
  v2_sha = _run_git(peer_dir, 'rev-parse', 'HEAD')

  code, check_data2 = self.req('POST', '/update/check', {})
  self.assertEqual(code, 200, check_data2)
  self.assertEqual(check_data2['check']['behind'], 1)
  self.assertTrue(check_data2['check']['update_available'])
  self.assertEqual(check_data2['check']['remote_commit'], v2_sha)
  self.assertEqual(len(check_data2['check']['incoming_commits']), 1)

  # 3. Khóa an toàn 409 Conflict
  case, state = self.open_local_case()
  d = state['review']
  started = threading.Event()
  release = threading.Event()
  original_export = app.export_reviewed_folder
  def slow_export(*args, **kwargs):
   started.set()
   release.wait(5)
   return original_export(*args, **kwargs)

  with patch.object(app, 'export_reviewed_folder', side_effect=slow_export):
   code_async, res_async = self.req('POST', '/export_folder', {**self.ident(d), 'destination': str(self.root / 'delivery_guard')}, {'X-HMU-Async': '1'})
   self.assertEqual(code_async, 202)
   self.assertTrue(started.wait(2))
   try:
    code_conflict1, err1 = self.req('POST', '/update/apply', {'target': 'latest', 'restart': False})
    self.assertEqual(code_conflict1, 409, err1)
    self.assertIn('Đang xử lý', err1.get('error', ''))
    code_conflict2, err2 = self.req('POST', '/update/rollback', {'restart': False})
    self.assertEqual(code_conflict2, 409, err2)
   finally:
    release.set()

  for _ in range(100):
   p_state = self.req('GET', '/progress?task_id=' + res_async['task_id'])[1]
   if p_state['status'] != 'running':
    break
   time.sleep(0.02)

  # Batch coordinator active > 0
  coord_file = self.root / 'jobs' / 'batch' / 'coordinator_status.json'
  coord_file.parent.mkdir(parents=True, exist_ok=True)
  coord_file.write_text(json.dumps({'active': 3, 'running': True, 'heartbeat': time.time()}), encoding='utf-8')
  try:
   code_batch_conflict, err_batch = self.req('POST', '/update/apply', {'target': 'latest', 'restart': False})
   self.assertEqual(code_batch_conflict, 409, err_batch)
   self.assertIn('Đang xử lý', err_batch.get('error', ''))
  finally:
   coord_file.write_text(json.dumps({'active': 0, 'running': False}), encoding='utf-8')

  # 4. POST /update/apply (áp dụng bản mới)
  code_apply, res_apply = self.req('POST', '/update/apply', {'target': 'latest', 'restart': False, 'run_pip': False, 'run_smoke_test': False})
  self.assertEqual(code_apply, 200, res_apply)
  self.assertEqual(res_apply['result']['status'], 'switched')
  self.assertEqual(res_apply['result']['to_commit'], v2_sha)
  self.assertFalse(res_apply['restarting'])
  self.assertEqual(_run_git(repo_dir, 'rev-parse', 'HEAD'), v2_sha)

  # Kiểm tra session_path được save_session ghi nhận
  session_file = self.root / 'jobs' / 'last_session.json'
  self.assertTrue(session_file.exists())

  # 5. POST /update/rollback
  code_rollback, res_rollback = self.req('POST', '/update/rollback', {'restart': False, 'run_pip': False, 'run_smoke_test': False})
  self.assertEqual(code_rollback, 200, res_rollback)
  self.assertEqual(res_rollback['result']['to_commit'], v1_sha)
  self.assertEqual(_run_git(repo_dir, 'rev-parse', 'HEAD'), v1_sha)

  # 6. POST /update/apply với restart=True
  with patch('threading.Timer') as mock_timer:
   code_restart_apply, res_restart = self.req('POST', '/update/apply', {'target': 'v3.2.0', 'restart': True, 'run_pip': False, 'run_smoke_test': False})
   self.assertEqual(code_restart_apply, 200)
   self.assertTrue(res_restart['restarting'])
   self.assertTrue(getattr(self.server, 'restart_requested', False))
   self.assertTrue(mock_timer.called)
   self.server.restart_requested = False

 def test_main_restart_lifecycle_exits_with_code_42(self):
  import sys
  from unittest.mock import patch, MagicMock

  mock_server = MagicMock()
  mock_server.server_port = 8765
  mock_server.restart_requested = True
  mock_server.serve_forever.return_value = None

  test_root = self.root / 'main_test_jobs'
  test_root.mkdir(parents=True, exist_ok=True)

  with patch.object(app, 'create_server', return_value=mock_server):
   with patch.object(sys, 'argv', ['app.py', '--root', str(test_root), '--no-browser']):
    with self.assertRaises(SystemExit) as ctx:
     app.main()
    self.assertEqual(ctx.exception.code, 42)

  mock_server.restart_requested = False
  with patch.object(app, 'create_server', return_value=mock_server):
   with patch.object(sys, 'argv', ['app.py', '--root', str(test_root), '--no-browser']):
    app.main()

 def test_e2e_git_update_and_rollback_lifecycle_with_real_logs(self):
  import subprocess, time, os, hashlib
  def _run_git(cwd, *args):
   p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True)
   return p.stdout.strip()

  def log(msg):
   print(f"[E2E-UPDATE-LIFECYCLE] {msg}", flush=True)

  log("================================================================================")
  log("BẮT ĐẦU KIỂM THỬ E2E: VÒNG ĐỜI CẬP NHẬT VÀ ROLLBACK GIT TRÊN MÁY NGƯỜI DÙNG")
  log("================================================================================")

  # Dọn dẹp server mặc định của setUp để chuyển sang server gắn repo clone thực tế
  self.server.shutdown()
  self.server.server_close()
  self.thread.join()

  # Thiết lập môi trường Git thật: Remote bare repo và Workstation clone
  remote_dir = self.root / 'remote.git'
  repo_dir = self.root / 'user_workstation'
  _run_git(self.root, 'init', '--bare', str(remote_dir))
  _run_git(self.root, 'clone', str(remote_dir), str(repo_dir))
  _run_git(repo_dir, 'config', 'user.email', 'bacsi_hmu@hmu.edu.vn')
  _run_git(repo_dir, 'config', 'user.name', 'BS. Nguyen Van HMU')
  _run_git(repo_dir, 'checkout', '-b', 'dev')

  # Khởi tạo commit gốc v3.1.0
  (repo_dir / 'app.py').write_text('VERSION = "3.1.0"\n# HMU App Server\n', encoding='utf-8')
  (repo_dir / 'requirements.txt').write_text('pymupdf>=1.24.0\n', encoding='utf-8')
  _run_git(repo_dir, 'add', 'app.py', 'requirements.txt')
  _run_git(repo_dir, 'commit', '-m', 'feat: v3.1.0 initial release for clinical review')
  _run_git(repo_dir, 'tag', 'v3.1.0')
  _run_git(repo_dir, 'push', '-u', 'origin', 'dev', '--tags')
  v310_sha = _run_git(repo_dir, 'rev-parse', 'HEAD')
  log(f"[GIAI ĐOẠN 1] Khởi tạo máy trạm người dùng tại phiên bản v3.1.0 (Commit: {v310_sha[:7]})")

  # Khởi tạo thư mục dữ liệu HMU_JOBS nằm ngay bên trong repo của người dùng
  jobs_dir = repo_dir / 'HMU_JOBS'
  jobs_dir.mkdir(parents=True, exist_ok=True)

  # Khởi động server gắn với repo clone và thư mục dữ liệu thực tế
  self.server = app.create_server(jobs_dir, None, 0)
  self.server.repo_dir = repo_dir
  self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
  self.thread.start()
  self.token = self.req('GET', '/state')[1]['token']
  log(f"  - Server HMU đã khởi động tại cổng {self.server.server_port}, liên kết với Git repo: {repo_dir.name}")

  try:
   # Tạo ca bệnh PDF thực tế và mở qua /open_path
   case_dir = self.root / 'benh_an_thuc_te'
   case_dir.mkdir(parents=True, exist_ok=True)
   real_pdf_path = case_dir / 'ho_so_benh_an_nguyen_van_a.pdf'
   doc = fitz.open()
   page = doc.new_page(width=595, height=842)
   page.insert_text((50, 100), "BỆNH VIỆN ĐẠI HỌC Y HÀ NỘI - KHOA CẤP CỨU")
   page.insert_text((50, 130), "Họ và tên bệnh nhân: Nguyễn Văn A  -  Năm sinh: 1985")
   page.insert_text((50, 160), "Chẩn đoán ban đầu: Viêm phổi thùy cấp tính")
   page.insert_text((50, 190), "Bác sĩ chỉ định: PGS.TS Trần Văn B")
   doc.save(str(real_pdf_path))
   doc.close()

   log(f"[GIAI ĐOẠN 2] Bác sĩ đang duyệt 1 hồ sơ PDF thực tế: {real_pdf_path.name}")
   code, open_res = self.req('POST', '/open_path', {'path': str(case_dir), 'study_id': 'BENH_AN_001'})
   self.assertEqual(code, 200, open_res)
   init_review = open_res['review']
   initial_job_id = init_review['job_id']
   log(f"  - Đã nạp thành công ca bệnh: job_id = {initial_job_id}")

   # Bác sĩ thực hiện khử định danh trên trang 1 và lưu lại
   clinical_note = "Đã che thông tin định danh họ tên bệnh nhân và bác sĩ chỉ định"
   code, save_res = self.req('POST', '/save_page', {
    **self.ident(init_review),
    'page': 1,
    'reviewed': True,
    'manual_rects': [[50, 120, 350, 140], [50, 180, 300, 200]],
    'note': clinical_note,
    'selections': [],
   })
   self.assertEqual(code, 200, save_res)
   log(f"  - Bác sĩ đã lưu duyệt trang 1 (revision {save_res['revision']}): manual_rects = 2 vùng, note = '{clinical_note}'")

   # Đọc trạng thái ban đầu của ca bệnh và dữ liệu trong HMU_JOBS
   code, state_before = self.req('GET', '/state')
   self.assertEqual(code, 200)
   self.assertEqual(state_before['review']['job_id'], initial_job_id)
   self.assertEqual(state_before['review']['pages'][0]['reviewed'], True)
   files_before = {p.relative_to(jobs_dir): p.stat().st_size for p in jobs_dir.rglob('*') if p.is_file()}
   log(f"  - Snapshot dữ liệu HMU_JOBS/ ban đầu: {len(files_before)} tệp ghi nhận (bệnh án, manifest, SQLite DB)")

   # Giai đoạn 3: Developer đẩy v3.1.1 và v3.2.0 lên Git remote
   log(f"[GIAI ĐOẠN 3] Developer push 2 phiên bản v3.1.1 và v3.2.0 lên remote Git")
   dev_dir = self.root / 'dev_workstation'
   _run_git(self.root, 'clone', '-b', 'dev', str(remote_dir), str(dev_dir))
   _run_git(dev_dir, 'config', 'user.email', 'dev_team@hmu.edu.vn')
   _run_git(dev_dir, 'config', 'user.name', 'HMU Dev Team')

   # Commit & Tag v3.1.1
   (dev_dir / 'app.py').write_text('VERSION = "3.1.1"\n# HMU App Server - v3.1.1 patch release\n', encoding='utf-8')
   (dev_dir / 'release_v311.txt').write_text('Bản vá lỗi v3.1.1: Tối ưu bộ nhớ đệm OCR\n', encoding='utf-8')
   _run_git(dev_dir, 'add', 'app.py', 'release_v311.txt')
   _run_git(dev_dir, 'commit', '-m', 'fix: patch release v3.1.1 cache optimization')
   _run_git(dev_dir, 'tag', 'v3.1.1')
   _run_git(dev_dir, 'push', 'origin', 'dev', '--tags')
   v311_sha = _run_git(dev_dir, 'rev-parse', 'HEAD')
   log(f"  - Đã push Tag v3.1.1 (Commit: {v311_sha[:7]})")

   # Commit & Tag v3.2.0
   (dev_dir / 'app.py').write_text('VERSION = "3.2.0"\n# HMU App Server - v3.2.0 major release\n', encoding='utf-8')
   (dev_dir / 'release_v320.txt').write_text('Phiên bản v3.2.0: Hệ thống xử lý hàng loạt Batch Queue đa tiến trình\n', encoding='utf-8')
   _run_git(dev_dir, 'add', 'app.py', 'release_v320.txt')
   _run_git(dev_dir, 'commit', '-m', 'feat: major release v3.2.0 multi-process batch coordinator')
   _run_git(dev_dir, 'tag', 'v3.2.0')
   _run_git(dev_dir, 'push', 'origin', 'dev', '--tags')
   v320_sha = _run_git(dev_dir, 'rev-parse', 'HEAD')
   log(f"  - Đã push Tag v3.2.0 (Commit: {v320_sha[:7]} - latest dev HEAD)")

   # Giai đoạn 4: Máy người dùng phát sinh chỉnh sửa cục bộ (dirty files), gọi /update/check
   log(f"[GIAI ĐOẠN 4] Máy người dùng phát sinh chỉnh sửa cục bộ và kiểm tra cập nhật")
   (repo_dir / 'app.py').write_text('VERSION = "3.1.0"\n# Bac si sua file cuc bo tren may tram\n', encoding='utf-8')
   (repo_dir / 'bac_si_ghi_chu.txt').write_text('Ghi chú cục bộ chưa được commit\n', encoding='utf-8')
   log(f"  - Đã tạo thay đổi bẩn (dirty): sửa app.py và thêm bac_si_ghi_chu.txt")

   code, check_res = self.req('POST', '/update/check', {})
   self.assertEqual(code, 200, check_res)
   check_info = check_res['check']
   self.assertTrue(check_info['update_available'], "Hệ thống phải phát hiện có bản cập nhật mới")
   self.assertEqual(check_info['behind'], 2, "Hệ thống phải phát hiện đang đi sau 2 commits")
   self.assertTrue(check_info['current']['dirty'], "Hệ thống phải nhận diện được working tree đang dirty")
   self.assertEqual(len(check_info['incoming_commits']), 2)
   tag_names = [t['name'] for t in check_res['versions']['tags']]
   self.assertIn('v3.1.1', tag_names)
   self.assertIn('v3.2.0', tag_names)
   log(f"  - /update/check phản hồi: behind = {check_info['behind']}, update_available = {check_info['update_available']}")
   log(f"  - Danh sách commits mới: {[c['subject'] for c in check_info['incoming_commits']]}")
   log(f"  - Danh sách tags: {tag_names}")

   # Giai đoạn 5: Áp dụng bản cập nhật v3.1.1 theo Tag
   log(f"[GIAI ĐOẠN 5] Cập nhật lên Tag v3.1.1 (/update/apply)")
   code, apply_311 = self.req('POST', '/update/apply', {
    'target': 'v3.1.1',
    'restart': False,
    'run_pip': False,
    'run_smoke_test': False,
   })
   self.assertEqual(code, 200, apply_311)
   self.assertEqual(apply_311['result']['status'], 'switched')
   self.assertEqual(apply_311['result']['to_commit'], v311_sha)
   self.assertTrue(apply_311['result']['stashed'], "Phải tự động stash các thay đổi bẩn cục bộ")
   self.assertEqual(_run_git(repo_dir, 'rev-parse', 'HEAD'), v311_sha)
   self.assertTrue((repo_dir / 'release_v311.txt').exists())
   self.assertFalse((repo_dir / 'release_v320.txt').exists())
   log(f"  - Chuyển thành công sang Tag v3.1.1 (Commit: {v311_sha[:7]}), file release_v311.txt xuất hiện")

   # Giai đoạn 6: Cập nhật lên bản mới nhất v3.2.0 (target='latest')
   log(f"[GIAI ĐOẠN 6] Cập nhật lên bản mới nhất latest / v3.2.0 (/update/apply)")
   code, apply_latest = self.req('POST', '/update/apply', {
    'target': 'latest',
    'restart': False,
    'run_pip': False,
    'run_smoke_test': False,
   })
   self.assertEqual(code, 200, apply_latest)
   self.assertEqual(apply_latest['result']['status'], 'switched')
   self.assertEqual(apply_latest['result']['to_commit'], v320_sha)
   self.assertEqual(_run_git(repo_dir, 'rev-parse', 'HEAD'), v320_sha)
   self.assertEqual(_run_git(repo_dir, 'rev-parse', '--abbrev-ref', 'HEAD'), 'dev', "Phải thoát Detached HEAD về nhánh dev")
   self.assertTrue((repo_dir / 'release_v320.txt').exists())
   log(f"  - Cập nhật thành công lên latest v3.2.0 (Commit: {v320_sha[:7]}), nhánh: dev, release_v320.txt xuất hiện")

   # Giai đoạn 7: Quay lui (Rollback) lùi về v3.1.1
   log(f"[GIAI ĐOẠN 7] Quay lui (Rollback) lùi về phiên bản trước đó v3.1.1 (/update/rollback)")
   code, rollback_res = self.req('POST', '/update/rollback', {
    'restart': False,
    'run_pip': False,
    'run_smoke_test': False,
   })
   self.assertEqual(code, 200, rollback_res)
   self.assertEqual(rollback_res['result']['to_commit'], v311_sha, "Rollback phải lùi về chính xác commit của v3.1.1")
   self.assertEqual(_run_git(repo_dir, 'rev-parse', 'HEAD'), v311_sha)
   self.assertTrue((repo_dir / 'release_v311.txt').exists())
   self.assertFalse((repo_dir / 'release_v320.txt').exists(), "File phiên bản v3.2.0 phải biến mất sau khi rollback")
   log(f"  - Rollback thành công về v3.1.1 (Commit: {v311_sha[:7]}), release_v320.txt đã gỡ bỏ an toàn")

   # Giai đoạn 8: Kiểm chứng 100% toàn vẹn dữ liệu ca bệnh và phiên làm việc
   log(f"[GIAI ĐOẠN 8] Xác nhận tính toàn vẹn 100% dữ liệu ca bệnh trong HMU_JOBS/ và phiên GET /state")
   code, state_after = self.req('GET', '/state')
   self.assertEqual(code, 200, state_after)
   self.assertIsNotNone(state_after.get('review'), "Phiên duyệt bệnh án phải còn nguyên vẹn")
   self.assertEqual(state_after['review']['job_id'], initial_job_id)
   self.assertEqual(state_after['review']['pages'][0]['reviewed'], True)
   self.assertEqual(state_after['review']['pages'][0]['note'], clinical_note)
   self.assertEqual(state_after['review']['pages'][0]['manual_rects'], [[50, 120, 350, 140], [50, 180, 300, 200]])

   # Kiểm tra các file quan trọng trong HMU_JOBS/
   updater_state_file = jobs_dir / 'updater_state.json'
   self.assertTrue(updater_state_file.exists(), "Tệp updater_state.json phải tồn tại trong HMU_JOBS/")
   up_data = json.loads(updater_state_file.read_text(encoding='utf-8'))
   self.assertEqual(up_data['current_commit'], v311_sha)
   self.assertEqual(len(up_data.get('history', [])), 3, "Lịch sử cập nhật phải ghi nhận đủ 3 lần chuyển: v3.1.1 -> v3.2.0 -> rollback v3.1.1")

   session_file = jobs_dir / 'last_session.json'
   self.assertTrue(session_file.exists(), "Tệp last_session.json phải tồn tại trong HMU_JOBS/")

   case_manifests = list(jobs_dir.rglob('case_manifest.json'))
   self.assertTrue(len(case_manifests) >= 1, "case_manifest.json phải nguyên vẹn trong HMU_JOBS/")

   # Đảm bảo không có bất kỳ file PDF hay ảnh nào của bệnh nhân trong HMU_JOBS/ bị thất thoát
   for rel_p, orig_size in files_before.items():
    if rel_p.name in {'last_session.json', 'updater_state.json'}:
     continue
    cur_p = jobs_dir / rel_p
    self.assertTrue(cur_p.exists(), f"Tệp ca bệnh {rel_p} bị mất trong HMU_JOBS/!")
    self.assertEqual(cur_p.stat().st_size, orig_size, f"Kích thước tệp ca bệnh {rel_p} bị biến đổi!")

   log(f"  - Toàn bộ {len(files_before)} tệp ca bệnh gốc, ảnh trang và manifest được bảo toàn 100%.")
   log(f"  - Phiên duyệt bệnh án (job_id: {initial_job_id}, ghi chú, vùng che) khớp 100% với trước khi cập nhật.")
   log(f"  - Lịch sử updater_state.json: {len(up_data['history'])} lượt chuyển giao an toàn.")
   log("================================================================================")
   log("KẾT LUẬN: BÀI TEST E2E ĐẠT 100% TIÊU CHÍ VÒNG ĐỜI UPDATE/ROLLBACK TRÊN DỮ LIỆU THẬT")
   log("================================================================================")

  finally:
   # Dọn dẹp và khôi phục server gốc cho tearDown
   try:
    self.server.shutdown()
    self.server.server_close()
    self.thread.join()
   except Exception:
    pass
   self.server = app.create_server(self.root / 'jobs', None, 0)
   self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
   self.thread.start()



if __name__=='__main__':unittest.main()
