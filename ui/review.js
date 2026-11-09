let workspaceMode='local';
const folderDestinations={local:'',batch:''};
let queueId=null,batchRows=[],batchIssues=[],previewOutput=false;
const batchSelected=new Set(),retryingIds=new Set(),autoOpenedRetries=new Set();
const batchLabels={QUEUED:'Chờ xử lý',PREPARING:'Đang phân tích',EXPORTING:'Đang khử / xuất',VERIFYING:'Đang kiểm PDF',NEEDS_REVIEW:'Chờ duyệt',READY:'Đã bàn giao',FAILED:'Lỗi',CANCELLING:'Đang dừng tiến trình',CANCELLED:'Đã hủy',DUPLICATE:'Trùng nội dung',DELETING:'Xóa chưa xong — thử Xóa lại'};
let token='',data=null,pn=0,img=new Image(),manual=false,start=null,preview=null,files=[],dirty=false,editVersion=0,working=false;
let saveQueue=Promise.resolve();
function identity(){return {job_id:data.job_id,revision:data.revision}}
function acceptState(r,preservePage){
 data=r.review;
 queueId=r.queue_id||null;
 batchIssues=[];
 previewOutput=false;
 if(r.files)files=r.files;
 setMode(queueId?'batch':'local');
 if(r.session){
  if($('localPath')&&r.session.selected_path)$('localPath').value=r.session.selected_path;
  if($('folderDestination')&&r.session.destination)$('folderDestination').value=r.session.destination;
  if($('sid')&&r.session.study_id)$('sid').value=r.session.study_id;
  if($('wholeCase')&&r.session.whole_case!==undefined)$('wholeCase').checked=!!r.session.whole_case;
 }
 if(typeof preservePage==='number'){
  pn=Math.max(0,Math.min((data?.pages?.length||1)-1,preservePage));
 }else if(!queueId&&r.session&&typeof r.session.active_page==='number'&&r.session.active_page>=1){
  pn=Math.max(0,Math.min((data?.pages?.length||1)-1,r.session.active_page-1));
 }else if(preservePage===true&&data&&data.pages){
  pn=Math.max(0,Math.min(data.pages.length-1,pn));
 }else{
  pn=0;
 }
 dirty=false;
 clearTimeout(timer);
 $('download').classList.add('hide');
 $('auditModal').classList.add('hide');
 $('auditModal').textContent='';
 show();
 if(queueId)loadBatchQc();
}
function setWorking(on){working=on;document.querySelectorAll('button,input,select,textarea').forEach(e=>e.disabled=on);renderBatch();updateWorkspace()}
function setMode(mode){
 if(workspaceMode!==mode){
  const destination=$('folderDestination');
  folderDestinations[workspaceMode]=destination.value;
  destination.value=folderDestinations[mode];
  $('folderResult').replaceChildren();
  $('auditModal').classList.add('hide');
 }
 workspaceMode=mode;
 updateWorkspace();
 if(!data)status(mode==='batch'?'Nhập đường dẫn để thêm PDF vào hàng đợi':'Chọn PDF hoặc nhập đường dẫn của một ca');
}
function queueReviewRows(){return batchRows.filter(r=>r.id===queueId||!r.state||['NEEDS_REVIEW','READY'].includes(r.state))}
function updateFileNav(){
 const list=queueId?queueReviewRows():files;
 const idx=!data?-1:queueId?list.findIndex(r=>r.id===queueId):list.findIndex(f=>f.job_id===data.job_id);
 const multi=!!data&&list.length>1&&idx>=0;
 $('prevFile').classList.toggle('hide',!multi);
 $('nextFile').classList.toggle('hide',!multi);
 $('filePos').classList.toggle('hide',!multi);
 $('prevFile').disabled=working||!multi||idx<=0;
 $('nextFile').disabled=working||!multi||idx>=list.length-1;
 $('filePos').textContent=multi?'File '+(idx+1)+'/'+list.length:'';
}
function updateWorkspace(){
 const batch=workspaceMode==='batch';
 const reviewing=!!data && batch===!!queueId;
 $('localMode').setAttribute('aria-pressed',String(!batch));
 $('batchMode').setAttribute('aria-pressed',String(batch));
 $('batchPanel').classList.toggle('hide',!batch);
 $('upload').classList.toggle('hide',batch||$('uploadInputs').classList.contains('hide'));
 $('workflow').classList.toggle('hide',!reviewing);
 $('batchReview').classList.toggle('hide',!reviewing||!batch);
 $('folderPanel').classList.toggle('hide',!batch&&!reviewing);
 $('exportFolder').disabled=working||(!batch&&!reviewing);
 $('folderScope').textContent=batch
  ? 'Phạm vi theo đường dẫn hàng đợi ở trên. Chỉ xuất PDF đủ điều kiện QC.'
  : 'Xuất từ công việc đang mở ('+(files.length||1)+' PDF), giữ tên file gốc.';
 updateFileNav();
 if(typeof syncShortcutHints==='function')syncShortcutHints();
}
window.addEventListener('beforeunload',e=>{if(dirty||working){e.preventDefault();e.returnValue=''}});
const $=id=>document.getElementById(id),canvas=$('canvas'),ctx=canvas.getContext('2d');
let currentWorkspace=null;
function applyWorkspace(ws){
 if(!ws)return;
 currentWorkspace=ws;
 if($('workspaceName')&&ws.workspace_name)$('workspaceName').value=ws.workspace_name;
 if($('workspaceDataRoot'))$('workspaceDataRoot').textContent=ws.data_root||'Chưa kết nối';
 if($('workspaceDataDeidentified'))$('workspaceDataDeidentified').textContent=ws.data_deidentified||'Chưa kết nối';
 if(ws.data_deidentified){
  if($('folderDestination'))$('folderDestination').value=ws.data_deidentified;
  folderDestinations.local=ws.data_deidentified;
  folderDestinations.batch=ws.data_deidentified;
 }
}
$('initWorkspace').onclick=async()=>{
 const name=($('workspaceName').value||'').trim();
 if(!name){status('Nhập tên Workspace ngoài Desktop',true);notify('Vui lòng nhập tên Workspace ngoài Desktop','err');return}
 try{
  setWorking(true);
  const r=await request('/workspace/init',JSON.stringify({workspace_name:name}));
  applyWorkspace(r);
  const msg='Đã kết nối Workspace: '+r.workspace_name;
  status(msg);
  notify(msg,'success');
 }catch(e){status('Lỗi: '+e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}
};
$('scanWorkspaceRoot').onclick=()=>{
 if(!currentWorkspace||!currentWorkspace.data_root){
  status('Chưa khởi tạo Workspace. Vui lòng bấm Tạo / Kết nối Workspace trước.',true);
  notify('Chưa khởi tạo Workspace. Vui lòng bấm Tạo / Kết nối Workspace trước.','err');
  return;
 }
 setMode('batch');
 $('batchPaths').value=currentWorkspace.data_root;
 notify('Đã nạp đường dẫn Data_Root vào hàng đợi: '+currentWorkspace.data_root,'info');
};
$('localMode').onclick=()=>setMode('local');
$('batchMode').onclick=()=>setMode('batch');
async function request(path,body,headers={}){
 try{
  const r=await fetch(path,{method:'POST',headers:{'X-HMU-Token':token,...headers},body});
  const d=await r.json();
  if(!r.ok){const err=Error(d.error||'Không thực hiện được');err.detail=d.error_detail;throw err}
  return d;
 }catch(e){
  if(e instanceof TypeError||e.message==='Failed to fetch'||(e.message&&e.message.includes('fetch'))){
   showOfflineModal();
  }
  throw e;
 }
}
function status(t,isErr=false){$('status').textContent=t;$('status').classList.toggle('err',!!isErr)}
function notify(msg,type='info',duration=10000){
 const box=$('toastContainer');
 if(!box||!document.createElement)return;
 const t=document.createElement('div');
 t.className='pill-toast '+type;
 t.classList?.add('pill-toast');
 t.classList?.add(type);
 t.textContent=msg;
 box.append(t);
 setTimeout(()=>{t.classList?.add('out');setTimeout(()=>t.remove?.(),280)},duration);
}
function formatErrorToast(errOrDetail,fallbackFile){
 if(!errOrDetail)return 'Đã xảy ra lỗi không xác định';
 const detail=(errOrDetail&&typeof errOrDetail==='object'&&errOrDetail.category)?errOrDetail:(errOrDetail?.detail||null);
 let msg=(detail&&detail.message)||errOrDetail.message||String(errOrDetail);
 if(typeof msg==='string'){
  if(msg.startsWith('Error: '))msg=msg.slice(7);
  if(msg.startsWith('Lỗi: '))msg=msg.slice(5).trim();
  if(msg.startsWith('[Lỗi File:')||msg.startsWith('[Lỗi Code:')||msg.startsWith('[Lỗi Xung đột]'))return msg;
 }
 const src=(detail&&detail.source_file)||fallbackFile||null;
 const loc=detail&&detail.code_location;
 let out=msg;
 if(detail&&detail.category==='CODE_ERROR'&&loc&&loc.file){
  out='[Lỗi Code: '+loc.file+':'+loc.line+'] '+msg;
  if(src&&!out.includes(src))out+=' · File: '+src;
 }else if(src||(detail&&detail.category==='FILE_ERROR')){
  out='[Lỗi File: '+(src||'Tệp')+'] '+msg;
 }else if(detail&&detail.category==='CONFLICT_ERROR'){
  out='[Lỗi Xung đột] '+msg;
 }
 if(detail&&detail.root_cause&&!out.includes(detail.root_cause)){
  out+=' · Gốc lỗi: '+detail.root_cause;
 }else if(detail&&detail.error_type&&detail.error_type!=='Error'&&!out.includes(detail.error_type)){
  out+=' ('+detail.error_type+')';
 }
 return out;
}
function formatBatchRowError(r){
 const d=r.error_detail;
 let msg=r.error||(d&&d.message)||'';
 if(!msg&&!d)return '';
 if(d&&d.root_cause&&!msg.includes(d.root_cause)){
  msg=(msg?msg+' · ':'')+'Gốc lỗi: '+d.root_cause;
 }
 if(d&&d.error_type&&d.error_type!=='Error'&&!msg.includes(d.error_type)){
  msg+=' ['+d.error_type+']';
 }
 if(d&&d.code_location&&d.code_location.file&&!msg.includes(d.code_location.file)){
  msg+=' @ '+d.code_location.file+':'+d.code_location.line;
 }
 return msg;
}
const seenFailedJobs=new Map();
let serverOffline=false;
function getStorage(){
 try{
  if(typeof window!=='undefined'&&window.localStorage)return window.localStorage;
  if(typeof localStorage!=='undefined')return localStorage;
 }catch(_){}
 return null;
}
function showOfflineModal(reason){
 serverOffline=true;
 const modal=$('offlineModal');
 if(modal){
  modal.classList.remove('hide');
  if(reason&&$('offlineMessage'))$('offlineMessage').textContent=reason;
 }
}
function dismissOfflinePrompt(){
 const modal=$('offlineModal');
 if(modal)modal.classList.add('hide');
}
function getCurrentPagePatch(){
 if(!data||!data.pages||!data.pages[pn])return null;
 const p=page();
 return {
  page:p.page,
  reviewed:!!p.reviewed,
  manual_rects:structuredClone(p.manual_rects||[]),
  note:p.note||'',
  selections:(p.proposals||[]).map(q=>({id:q.id,selected:q.selected}))
 };
}
function saveOfflineSnapshot(){
 try{
  const patch=getCurrentPagePatch();
  const curFile=files.find(f=>f.job_id===data?.job_id);
  const snapshot={
   saved_at:new Date().toISOString(),
   selected_path:$('localPath')?.value?.trim()||'',
   destination:$('folderDestination')?.value?.trim()||'',
   study_id:$('sid')?.value?.trim()||'',
   whole_case:$('wholeCase')?.checked||false,
   job_id:data?data.job_id:null,
   file_index:curFile?curFile.index:(files[0]?.index||1),
   active_page:(pn||0)+1,
   page_patch:patch
  };
  const store=getStorage();
  if(store){
   store.setItem('hmu_session_backup_v1',JSON.stringify(snapshot));
  }
  const msg='Đã lưu bản sao phiên làm việc vào trình duyệt';
  if($('offlineMessage'))$('offlineMessage').textContent=msg+'. Bạn có thể bật lại Terminal bất cứ lúc nào; giao diện sẽ tự động đồng bộ.';
  notify(msg,'success');
 }catch(err){
  notify('Không thể lưu phiên tạm: '+err.message,'err');
 }
}
async function syncOfflineSnapshotIfNeeded(serverState){
 const store=getStorage();
 if(!store)return;
 const raw=store.getItem('hmu_session_backup_v1');
 if(!raw)return;
 try{
  const backup=JSON.parse(raw);
  if(backup.job_id){
   if(serverState&&serverState.review&&serverState.review.job_id!==backup.job_id&&backup.file_index){
    try{
     const sel=await request('/select_file',JSON.stringify({job_id:serverState.review.job_id,revision:serverState.review.revision,file_index:backup.file_index}));
     if(sel&&sel.review){
      serverState.review=sel.review;
      if(sel.files)serverState.files=sel.files;
     }
    }catch(_){}
   }
   if(backup.page_patch){
    const rev=(serverState&&serverState.review&&serverState.review.job_id===backup.job_id)?serverState.review.revision:0;
    const saveRes=await request('/save_page',JSON.stringify({
     job_id:backup.job_id,
     revision:rev,
     ...backup.page_patch
    }));
    if(saveRes&&saveRes.revision&&serverState&&serverState.review){
     serverState.review.revision=saveRes.revision;
    }
    if(serverState&&serverState.review&&serverState.review.pages){
     const pIdx=serverState.review.pages.findIndex(p=>p.page===backup.page_patch.page);
     if(pIdx>=0){
      const pg=serverState.review.pages[pIdx];
      pg.reviewed=backup.page_patch.reviewed;
      pg.manual_rects=structuredClone(backup.page_patch.manual_rects||[]);
      pg.note=backup.page_patch.note||'';
      if(backup.page_patch.selections){
       backup.page_patch.selections.forEach(sel=>{
        const prop=(pg.proposals||[]).find(q=>q.id===sel.id);
        if(prop)prop.selected=sel.selected;
       });
      }
     }
    }
   }
   try{
    await request('/session/save',JSON.stringify({
     selected_path:backup.selected_path,
     destination:backup.destination,
     study_id:backup.study_id,
     whole_case:backup.whole_case,
     active_file_index:backup.file_index,
     active_page:backup.active_page
    }));
   }catch(_){}
   if(serverState){
    if(!serverState.session)serverState.session={};
    serverState.session.active_page=backup.active_page;
    if(backup.selected_path)serverState.session.selected_path=backup.selected_path;
    if(backup.destination)serverState.session.destination=backup.destination;
    if(backup.study_id)serverState.session.study_id=backup.study_id;
    if(backup.whole_case!==undefined)serverState.session.whole_case=backup.whole_case;
   }
  }
  store.removeItem('hmu_session_backup_v1');
  notify('Đã tự động khôi phục và đồng bộ phiên làm việc trước đó','success');
 }catch(err){
  console.warn('Lỗi đồng bộ snapshot:',err);
 }
}
function pushSessionMeta(){
 if(workspaceMode!=='local'||queueId)return Promise.resolve();
 const selected=$('localPath')?.value?.trim()||'';
 if(!selected)return Promise.resolve();
 const curFile=files.find(f=>f.job_id===data?.job_id);
 const payload={
  selected_path:selected,
  destination:$('folderDestination')?.value?.trim()||'',
  study_id:$('sid')?.value?.trim()||'',
  whole_case:$('wholeCase')?.checked||false,
  active_file_index:curFile?curFile.index:(files[0]?.index||1),
  active_page:(pn||0)+1
 };
 return request('/session/save',JSON.stringify(payload)).catch(()=>{});
}
function addInputListener(el,fn){
 if(!el)return;
 if(typeof el.addEventListener==='function')el.addEventListener('change',fn);
 else el.onchange=fn;
}
async function requestAsync(path,body,headers={},fallback='Đang xử lý bất đồng bộ…'){
 status('⏳ '+fallback);
 let r;
 try{
  r=await fetch(path,{method:'POST',headers:{'X-HMU-Token':token,'X-HMU-Async':'1',...headers},body});
 }catch(e){
  if(e instanceof TypeError||e.message==='Failed to fetch'||(e.message&&e.message.includes('fetch'))){
   showOfflineModal();
  }
  throw e;
 }
 const init=await r.json();
 if(r.status===404&&path==='/export_folder')throw Error('Phiên HMU đang chạy chưa hỗ trợ xuất thư mục. Lưu công việc rồi mở lại đúng công việc bằng bản mới.');
 if(!r.ok){const err=Error(init.error||'Không thực hiện được');err.detail=init.error_detail;throw err}
 if(!init.async)return init;
 while(true){
  await new Promise(res=>setTimeout(res,350));
  let pr;
  try{
   pr=await fetch('/progress?task_id='+encodeURIComponent(init.task_id));
  }catch(e){
   if(e instanceof TypeError||e.message==='Failed to fetch'||(e.message&&e.message.includes('fetch'))){
    showOfflineModal();
   }
   throw e;
  }
  const pd=await pr.json();
  if(!pr.ok){const err=Error(pd.error||'Không lấy được trạng thái tác vụ');err.detail=pd.error_detail;throw err}
  if(pd.status==='error'){const err=Error(pd.error||'Lỗi xử lý bất đồng bộ');err.detail=pd.error_detail;throw err}
  if(pd.status==='done')return pd.result;
  if(pd.progress)status('⏳ '+pd.progress+(pd.elapsed?' ('+pd.elapsed+'s)':''));
 }
}
async function resumeTask(taskId){
 setWorking(true);
 status('⏳ Đang khôi phục tiến trình xử lý bất đồng bộ…');
 try{
  while(true){
   await new Promise(res=>setTimeout(res,350));
   const pr=await fetch('/progress?task_id='+encodeURIComponent(taskId));
   const pd=await pr.json();
   if(!pr.ok){const err=Error(pd.error||'Không lấy được trạng thái tác vụ');err.detail=pd.error_detail;throw err}
   if(pd.status==='error'){const err=Error(pd.error||'Lỗi xử lý bất đồng bộ');err.detail=pd.error_detail;throw err}
   if(pd.status==='done'){
    const sr=await fetch('/state');
    if(sr.ok){
     const s=await sr.json();
     if(s.token)token=s.token;
     if(s.workspace)applyWorkspace(s.workspace);
     acceptState(s);
    }
    notify('Tác vụ xử lý nền đã hoàn tất','success');
    return pd.result;
   }
   if(pd.progress)status('⏳ '+pd.progress+(pd.elapsed?' ('+pd.elapsed+'s)':''));
  }
 }catch(e){
  status('Lỗi: '+e.message,true);
  notify(formatErrorToast(e),'err');
 }finally{
  setWorking(false);
 }
}
function page(){return data.pages[pn]}
let framePending=false;function draw(){if(!framePending){framePending=true;requestAnimationFrame(()=>{framePending=false;paint()})}}
function paint(){if(!data||!img.complete)return;if(canvas.width!==img.naturalWidth)canvas.width=img.naturalWidth;if(canvas.height!==img.naturalHeight)canvas.height=img.naturalHeight;ctx.drawImage(img,0,0);if(previewOutput)return;const sx=canvas.width/page().width,sy=canvas.height/page().height;
 const rect=(r,color,fill)=>{ctx.strokeStyle=color;ctx.lineWidth=2;ctx.strokeRect(r[0]*sx,r[1]*sy,(r[2]-r[0])*sx,(r[3]-r[1])*sy);if(fill){ctx.fillStyle=color+'22';ctx.fillRect(r[0]*sx,r[1]*sy,(r[2]-r[0])*sx,(r[3]-r[1])*sy)}};
 page().proposals.forEach(q=>q.rects.forEach(r=>rect(r,q.selected?'#cc3333':'#bb8800',q.selected)));page().manual_rects.forEach(r=>rect(r,'#cc3333',true));if(preview)rect(preview,'#0055ff',false)
}
function list(){const box=$('items');box.replaceChildren();page().proposals.forEach((q,i)=>{const row=document.createElement('label');row.className='item';const cb=document.createElement('input');cb.type='checkbox';cb.checked=q.selected;cb.onchange=()=>{q.selected=cb.checked;page().reviewed=false;draw();saveSoon()};const t=document.createElement('span'),b=document.createElement('strong');b.textContent=q.kind+(q.clinical_overlap?' ⚠ Trùng mã chuyên môn':'');t.append(b,document.createTextNode(q.text));if(q.rule||q.provenance){const detail=document.createElement('small');detail.style.display='block';detail.textContent='Nguồn: '+(q.provenance||q.rule);t.append(detail)}row.append(cb,t);box.append(row)});
page().manual_rects.forEach((r,i)=>{const row=document.createElement('div');row.className='item';const b=document.createElement('button');b.textContent='Bỏ';b.onclick=()=>{page().manual_rects.splice(i,1);page().reviewed=false;list();draw();saveSoon()};row.append(b,document.createTextNode('Vùng bổ sung '+(i+1)));box.append(row)})}
function show(){if(!data)return;files=files.map(f=>f.job_id===data.job_id?{...f,reviewed:data.pages.filter(p=>p.reviewed).length}:f);const picker=$('caseFile');picker.replaceChildren();files.forEach(f=>{const o=document.createElement('option');o.value=f.index;o.textContent=f.name+' ('+f.reviewed+'/'+f.pages+')';o.selected=f.job_id===data.job_id;picker.append(o)});picker.classList.toggle('hide',!files.length);$('caseScope').classList.toggle('hide',!files.length);$('uploadInputs').classList.toggle('hide',!queueId);updateWorkspace();$('pageNo').value=pn+1;$('pageNo').max=data.pages.length;$('pageTotal').textContent='/ '+data.pages.length;$('note').value=page().note||'';img.onload=draw;img.onerror=()=>status('Không mở được ảnh PDF; có thể cần xuất và kiểm lại sau khi sửa vùng khử',true);img.src=previewOutput&&queueId?'/batch/preview?queue_id='+queueId+'&revision='+data.revision+'&page='+(pn+1):'/page/'+(pn+1)+'?job_id='+encodeURIComponent(data.job_id);$('compareOutput').textContent=previewOutput?'Xem ảnh nguồn':'Xem PDF đã khử';renderIssues();list();status('Đã duyệt '+data.pages.filter(p=>p.reviewed).length+'/'+data.pages.length+' trang · Trang '+(pn+1)+(page().reviewed?' đã duyệt':' chưa duyệt')+' · OCR: '+(data.ocr_pages_count||0)+' trang · Watermark bóc riêng: '+data.watermarks_removed.length)}
let timer;function saveSoon(){dirty=true;editVersion++;clearTimeout(timer);timer=setTimeout(()=>save().catch(e=>{status(e.message,true);notify(formatErrorToast(e),'err')}),400)}
function save(force=false){clearTimeout(timer);if(!data||(!dirty&&!force))return saveQueue;const job=data.job_id,version=editVersion,p=page();const patch={page:p.page,reviewed:p.reviewed,manual_rects:structuredClone(p.manual_rects),note:p.note||'',selections:p.proposals.map(q=>({id:q.id,selected:q.selected}))};saveQueue=saveQueue.catch(()=>{}).then(async()=>{if(!data||data.job_id!==job)throw Error('Công việc đã thay đổi');const r=await request('/save_page',JSON.stringify({...identity(),...patch}));data.revision=r.revision;if(editVersion===version)dirty=false;const msg='Đã lưu · Đã duyệt '+data.pages.filter(p=>p.reviewed).length+'/'+data.pages.length+' trang';status(msg);if(force)notify(msg,'success')});return saveQueue}
async function flush(){setWorking(true);try{do{await save()}while(dirty)}finally{setWorking(false)}}
async function navigate(n){try{await flush();pn=Math.max(0,Math.min(data.pages.length-1,n));show();pushSessionMeta()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}}
async function openCaseFile(i){try{await flush();setWorking(true);acceptState(await request('/select_file',JSON.stringify({...identity(),file_index:i})));const cur=files.find(f=>f.job_id===data?.job_id);notify('Đã chuyển sang file '+(cur?cur.name:'#'+i),'info')}catch(e){status(e.message,true);notify(formatErrorToast(e,files.find(f=>f.index===i)?.name),'err')}finally{setWorking(false)}}
function stepFile(delta){
 if(!data)return;
 if(queueId){
  const list=queueReviewRows();
  const idx=list.findIndex(r=>r.id===queueId)+delta;
  if(idx>=0&&idx<list.length)return openBatch(list[idx].id);
 }else{
  const idx=files.findIndex(f=>f.job_id===data.job_id)+delta;
  if(idx>=0&&idx<files.length)return openCaseFile(files[idx].index);
 }
}
$('caseFile').onchange=()=>openCaseFile(Number($('caseFile').value));
$('prevFile').onclick=()=>stepFile(-1);
$('nextFile').onclick=()=>stepFile(1);
function point(e){const r=canvas.getBoundingClientRect();return[(e.clientX-r.left)/r.width*page().width,(e.clientY-r.top)/r.height*page().height]}
canvas.onpointerdown=e=>{if(working||previewOutput)return;canvas.setPointerCapture(e.pointerId);start=point(e)};
canvas.onpointermove=e=>{if(manual&&start){let q=point(e);preview=[Math.min(start[0],q[0]),Math.min(start[1],q[1]),Math.max(start[0],q[0]),Math.max(start[1],q[1])];draw()}};
canvas.onpointerup=e=>{if(working||previewOutput)return;const q=point(e);if(manual&&preview&&preview[2]-preview[0]>2&&preview[3]-preview[1]>2){page().manual_rects.push(preview);page().reviewed=false}else if(!manual){const hit=page().proposals.find(x=>x.rects.some(r=>q[0]>=r[0]&&q[0]<=r[2]&&q[1]>=r[1]&&q[1]<=r[3]));if(hit){hit.selected=!hit.selected;page().reviewed=false}}start=null;preview=null;list();draw();saveSoon()};
$('mode').onclick=()=>{manual=!manual;$('mode').textContent=manual?'Đang khoanh — nhấp để dừng':'Khoanh thêm vùng xóa';if(typeof syncShortcutHints==='function')syncShortcutHints()};
$('prev').onclick=()=>navigate(pn-1);$('next').onclick=()=>navigate(pn+1);$('pageNo').onchange=()=>navigate(Number($('pageNo').value)-1);
$('note').onchange=()=>{page().note=$('note').value;saveSoon()};$('done').onclick=async()=>{const donePage=pn+1;page().reviewed=true;saveSoon();await flush();pn=Math.min(data.pages.length-1,pn+1);show();notify('Đã duyệt trang '+donePage,'success')};$('save').onclick=()=>save(true).catch(e=>{status(e.message,true);notify(formatErrorToast(e),'err')});
$('approveAll').onclick=async()=>{try{await flush();setWorking(true);const r=await request('/approve_all',JSON.stringify(identity()));data=r.review;show();const msg='Đã duyệt toàn bộ '+data.pages.length+'/'+data.pages.length+' trang! Bạn có thể bấm Xuất PDF chính thức.';status(msg);notify(msg,'success')}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}};
$('viewAudit').onclick=async()=>{const box=$('auditModal');if(!box.classList.contains('hide')){box.classList.add('hide');return}try{await flush();const job=data.job_id,revision=data.revision;const r=await fetch('/audit?job_id='+encodeURIComponent(job)+'&revision='+revision);if(!r.ok)throw Error('Trạng thái đã đổi; tải lại trang');const d=await r.json();if(!data||data.job_id!==job||data.revision!==revision)throw Error('Trạng thái đã đổi; mở lại báo cáo');box.textContent=d.markdown||'Chưa có báo cáo Markdown';box.classList.remove('hide')}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}};
$('newCase').onclick=async()=>{try{await flush()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err');return}$('uploadInputs').classList.remove('hide');setMode('local');status('Chọn tệp PDF mới hoặc nhập đường dẫn ca bệnh bên trên')};
async function output(draft){try{await flush();setWorking(true);const scope=files.length&&$('wholeCase').checked?'case':'file';const r=await requestAsync('/export',JSON.stringify({...identity(),draft,scope}),{'Content-Type':'application/json'},'Đang xóa và dựng lại PDF…');$('download').classList.remove('hide');$('download').href='/download?job_id='+encodeURIComponent(data.job_id)+'&scope='+scope;$('download').download=r.file;const msg='Đã xuất '+(r.count||1)+' PDF · '+(draft?'Bản thử cần kiểm tra':'Cần QC bản đầu ra');status(msg);notify(msg,'success');$('busy').textContent='Sản phẩm đã kiểm tra nằm tại: '+r.directory}catch(e){status('Lỗi: '+e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}}
$('draft').onclick=()=>queueId?batchReprocess():output(true);$('export').onclick=()=>queueId?batchRelease():output(false);
$('load').onclick=async()=>{const f=$('file').files[0];if(!f){status('Chọn tệp PDF trước',true);return}try{await flush();setWorking(true);$('busy').textContent='';const r=await requestAsync('/upload',f,{'Content-Type':'application/pdf','X-Study-ID':$('sid').value,'X-Original-Filename':encodeURIComponent(f.name)},'Đang đọc PDF (và chạy OCR bất đồng bộ nếu trang scan/vector)…');$('folderResult').replaceChildren();acceptState(r)}catch(e){status('Lỗi: '+e.message,true);notify(formatErrorToast(e,f.name),'err')}finally{setWorking(false)}};
$('loadPath').onclick=async()=>{
 const p=$('localPath').value.trim();
 if(!p){status('Nhập đường dẫn tệp PDF hoặc thư mục ca bệnh',true);return}
 try{
  await flush();
  setWorking(true);
  $('busy').textContent='';
  const dest=$('folderDestination').value.trim();
  const payload={path:p,study_id:$('sid').value};
  if(dest)payload.destination=dest;
  const r=await requestAsync('/open_path',JSON.stringify(payload),{'Content-Type':'application/json'},'Đang xử lý tự động bất đồng bộ (kèm OCR & XML seeds)…');
  $('folderResult').replaceChildren();
  acceptState(r);
  if(r.cloned_folders&&r.cloned_folders.length){
   notify('Đã tạo sẵn '+r.cloned_folders.length+' thư mục bệnh án trống trong Data_Deidentified','info');
  }
  if(r.batch_case){$('busy').textContent='Đã chuẩn bị '+r.files.length+' file PDF. Chọn từng file để duyệt rồi bấm Xuất thư mục các PDF đã duyệt tại khối phía trên.'}
  else if(r.resolved_path){$('busy').textContent='Đã mở ca bệnh (kèm XML seeds): '+r.resolved_path}
 }catch(e){status('Lỗi: '+e.message,true);notify(formatErrorToast(e,p.split(/[\\/]/).pop()),'err')}finally{setWorking(false)}
};
function batchButton(label,action){const b=document.createElement('button');b.textContent=label;b.onclick=action;b.disabled=working;return b}
function filteredBatchRows(){const filter=$('batchFilter').value;return batchRows.filter(r=>!filter||r.state===filter||(filter==='RUNNING'&&['PREPARING','EXPORTING','VERIFYING'].includes(r.state))||(filter==='FAILED'&&retryingIds.has(r.id)))}
function renderBatch(){
 const box=$('batchList');box.replaceChildren();
 filteredBatchRows().forEach(r=>{
  const row=document.createElement('div');row.className='item';
  const check=document.createElement('input');check.type='checkbox';check.checked=batchSelected.has(r.id);check.disabled=working;check.setAttribute('aria-label','Chọn '+r.source_name);
  check.onchange=()=>{if(check.checked)batchSelected.add(r.id);else batchSelected.delete(r.id);renderBatch()};
  const errText=formatBatchRowError(r);
  const t=document.createElement('span');t.textContent=r.source_name+' · '+r.pages+' trang · '+batchLabels[r.state]+(r.qc_status?' · QC: '+r.qc_status+' ('+r.warnings+' cảnh báo)':'')+(errText?' · '+errText:'');row.append(check,t);
  if(['NEEDS_REVIEW','READY'].includes(r.state))row.append(batchButton('Mở / duyệt',()=>openBatch(r.id)));
  if(['FAILED','CANCELLED'].includes(r.state)){
   row.append(batchButton('Thử lại',()=>retryBatch([r.id])));
   if(r.can_open||r.source_path)row.append(batchButton(r.can_open?'Mở / duyệt':'Mở thử',()=>testFailedBatchFile(r)));
  }
  if(['QUEUED','PREPARING','EXPORTING','VERIFYING'].includes(r.state))row.append(batchButton('Hủy xử lý',()=>batchAction('/batch/cancel',{queue_id:r.id})));
  if(r.state==='DUPLICATE')row.append(batchButton('Mở bản gốc',()=>openBatch(r.duplicate_of)));
  row.append(batchButton('Xóa',()=>deleteBatch([r.id])));box.append(row);
 });
 const hasRetryableSelected=[...batchSelected].some(id=>{const row=batchRows.find(x=>x.id===id);return row&&['FAILED','CANCELLED'].includes(row.state)});
 $('batchSelectedCount').textContent=batchSelected.size+' đã chọn';
 if($('batchRetrySelected'))$('batchRetrySelected').disabled=working||!hasRetryableSelected;
 $('batchDeleteSelected').disabled=working||!batchSelected.size;
 updateFileNav();
 if(typeof syncShortcutHints==='function')syncShortcutHints();
}
async function refreshBatch(){
 try{
  const response=await fetch('/batch/status');
  const r=await response.json();
  if(!response.ok)throw Error(r.error);
  if(serverOffline){
   serverOffline=false;
   const offlineModal=$('offlineModal');
   if(offlineModal)offlineModal.classList.add('hide');
   try{
    const sr=await fetch('/state');
    if(sr.ok){
     const s=await sr.json();
     if(s.token)token=s.token;
     if(s.workspace)applyWorkspace(s.workspace);
     await syncOfflineSnapshotIfNeeded(s);
     acceptState(s,true);
    }
   }catch(_){}
   status('Đã kết nối lại máy chủ HMU thành công');
   notify('Đã kết nối lại máy chủ HMU thành công!','success');
  }
  batchRows=r.jobs||[];
  const ids=new Set(batchRows.map(x=>x.id));
  for(const id of batchSelected)if(!ids.has(id))batchSelected.delete(id);
  for(const id of retryingIds)if(!ids.has(id))retryingIds.delete(id);
  for(const id of autoOpenedRetries)if(!ids.has(id))autoOpenedRetries.delete(id);
  for(const id of seenFailedJobs.keys())if(!ids.has(id))seenFailedJobs.delete(id);
  let autoOpenId=null;
  for(const j of batchRows){
   if(j.state==='FAILED'){
    const lastUpdated=seenFailedJobs.get(j.id);
    if(lastUpdated!==j.updated){
     seenFailedJobs.set(j.id,j.updated);
     notify(formatErrorToast(j.error_detail||j.error,j.source_name),'err');
    }
   }else if(retryingIds.has(j.id)&&j.state==='NEEDS_REVIEW'&&!autoOpenedRetries.has(j.id)){
    autoOpenedRetries.add(j.id);
    if(!autoOpenId)autoOpenId=j.id;
   }
  }
  renderBatch();
  const pending=batchRows.filter(x=>x.state==='NEEDS_REVIEW').length,ready=batchRows.filter(x=>x.state==='READY').length;
  $('batchStatus').textContent=batchRows.length+' file · '+(r.coordinator.active||0)+' đang chạy · '+pending+' chờ duyệt · '+ready+' đã bàn giao. '+(r.coordinator.message||'');
  if(autoOpenId&&!dirty&&!working){
   await openBatch(autoOpenId);
  }
 }catch(e){
  $('batchStatus').textContent='Mất kết nối máy chủ ('+e.message+'). Hãy bật lại MO_CONG_CU.bat';
  const wasOffline=serverOffline;
  showOfflineModal('Mất kết nối máy chủ ('+e.message+'). Hãy bật lại MO_CONG_CU.bat');
  if(!wasOffline){
   notify('Mất kết nối tới máy chủ HMU! Vui lòng bật lại MO_CONG_CU.bat để tiếp tục.','err');
  }
 }
}
async function pollBatch(){await refreshBatch();setTimeout(pollBatch,2000)}
async function batchAction(path,body={}){try{const r=await request(path,JSON.stringify(body));await refreshBatch();if(r&&r.cloned_folders&&r.cloned_folders.length){notify('Đã tạo sẵn '+r.cloned_folders.length+' thư mục bệnh án trống trong Data_Deidentified','info')}return r}catch(e){status(e.message,true);notify(formatErrorToast(e),'err');return null}}
async function retryBatch(ids){
 const retryable=ids.filter(id=>{const r=batchRows.find(x=>x.id===id);return !r||['FAILED','CANCELLED'].includes(r.state)});
 const targetIds=retryable.length?retryable:ids;
 if(!targetIds.length)return null;
 targetIds.forEach(id=>{retryingIds.add(id);autoOpenedRetries.delete(id);seenFailedJobs.delete(id)});
 const body=targetIds.length===1?{queue_id:targetIds[0]}:{queue_ids:targetIds};
 const r=await batchAction('/batch/retry',body);
 if(r&&r.retried&&r.retried.length){
  notify('Đã xếp hàng thử lại '+r.retried.length+' file và khởi động tiến trình xử lý','info');
 }
 return r;
}
async function testFailedBatchFile(r){
 if(!r)return;
 if(r.can_open||['NEEDS_REVIEW','READY'].includes(r.state)){
  return await openBatch(r.id);
 }
 if(!r.source_path)return;
 try{
  await flush();
  setWorking(true);
  $('busy').textContent='';
  const dest=$('folderDestination').value.trim();
  const payload={path:r.source_path,study_id:'TEST_'+r.id.slice(0,8)};
  if(dest)payload.destination=dest;
  const res=await requestAsync('/open_path',JSON.stringify(payload),{'Content-Type':'application/json'},'Đang mở thử file lỗi để kiểm tra…');
  $('folderResult').replaceChildren();
  acceptState(res);
  notify('Đã mở thử file: '+r.source_name,'info');
 }catch(e){
  status('Lỗi: '+e.message,true);
  notify(formatErrorToast(e,r.source_name),'err');
 }finally{
  setWorking(false);
 }
}
async function openBatch(id){try{await flush();setWorking(true);const r=await request('/batch/open_job',JSON.stringify({queue_id:id}));acceptState(r);$('pageNo').focus();notify('Đã mở hồ sơ trong hàng đợi','info')}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}}
async function loadBatchQc(){if(!queueId||!data)return;const id=queueId,job=data.job_id,revision=data.revision;try{const r=await fetch('/batch/qc?queue_id='+id+'&revision='+revision);const qc=await r.json();if(queueId!==id||!data||data.job_id!==job||data.revision!==revision)return;if(!r.ok)throw Error(qc.error);batchIssues=qc.issues;renderIssues();$('download').classList.remove('hide');$('download').href='/batch/pdf?queue_id='+id+'&revision='+revision;$('download').download=qc.filename||'CASE_'+id.slice(0,16)+'_DRAFT.pdf'}catch(e){if(queueId===id){batchIssues=[];renderIssues();$('qcStatus').textContent=e.message;$('download').classList.add('hide')}}}
function renderIssues(){const box=$('qcIssues');if(!box)return;box.replaceChildren();$('batchReview').classList.toggle('hide',!queueId||workspaceMode!=='batch');$('qcStatus').textContent=batchIssues.filter(f=>!f.resolved).length+' cảnh báo chưa xử lý. Kiểm toàn bộ trang, kể cả trang không có cờ.';batchIssues.forEach(f=>{const row=document.createElement('div');row.className='item';const t=document.createElement('span');t.textContent='Trang '+f.page+' · '+f.kind+' · '+f.text+(f.resolved?' · Đã xác nhận':'');row.append(t,batchButton('Đến trang',()=>navigate(f.page-1)));if(!f.resolved)row.append(batchButton('Xác nhận giữ',async()=>{await flush();const reason=$('qcReason').value,reviewer=$('qcReviewer').value;const r=await batchAction('/batch/resolve_finding',{queue_id:queueId,revision:data.revision,finding_id:f.id,reason,reviewer});if(r)await loadBatchQc()}));box.append(row)})}
async function batchReprocess(){try{await flush();const r=await batchAction('/batch/reprocess',{queue_id:queueId,revision:data.revision});if(r){$('download').classList.add('hide');const msg='Đã xếp hàng xuất lại và kiểm PDF. Có thể mở file khác để duyệt.';status(msg);notify(msg,'info')}}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}}
function showDelivered(){
 $('batchFilter').value='READY';
 renderBatch();
 $('batchPanel').scrollIntoView?.({block:'start'});
}
async function batchRelease(){
 try{
  await flush();
  setWorking(true);
  const result=await batchAction('/batch/release',{queue_id:queueId,revision:data.revision});
  if(result){
   await loadBatchQc();
   $('download').download=result.output.split(/[\\/]/).pop();
   showDelivered();
   const msg='Đã bàn giao PDF: '+result.directory;
   status(msg);
   notify(msg,'success');
  }
 }catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}
}
function showResult(box,message,items,reviewAction){
 box.replaceChildren();
 const summary=document.createElement('p');
 summary.textContent=message;
 box.append(summary);
 for(const item of items){
  const line=document.createElement('div');
  line.className='item';
  const text=document.createElement('span');
  text.textContent=item.source_name+' — '+item.reason;
  line.append(text);
  const action=reviewAction(item);
  if(action)line.append(batchButton('Mở / duyệt',action));
  box.append(line);
 }
}
function batchReviewAction(item){
 const row=batchRows.find(r=>r.id===item.id);
 if(row&&['NEEDS_REVIEW','READY','DUPLICATE'].includes(row.state))return ()=>openBatch(row.duplicate_of||row.id);
}
async function deleteBatch(ids){
 if(!ids.length||!window.confirm('Xóa '+ids.length+' mục khỏi hàng đợi và dọn dữ liệu làm việc? File gốc và PDF đã bàn giao được giữ. Mục đang chạy cần hủy và đợi dừng trước. Không thể khôi phục vùng duyệt đã xóa.'))return;
 try{
  await flush();setWorking(true);const r=await request('/batch/delete',JSON.stringify({queue_ids:ids}));
  if(r.active_deleted){data=null;queueId=null;files=[];batchIssues=[];dirty=false;clearTimeout(timer);$('workflow').classList.add('hide');$('batchReview').classList.add('hide');$('download').classList.add('hide');$('auditModal').classList.add('hide');$('auditModal').textContent='';$('uploadInputs').classList.remove('hide');$('upload').classList.remove('hide')}
  await refreshBatch();const message='Đã xóa '+r.deleted.length+' mục; '+r.skipped.length+' mục chưa xóa.';showResult($('batchResult'),message,r.skipped,batchReviewAction);status(message);
 }catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}
}
function batchPaths(){return $('batchPaths').value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean)}
async function pickFolder(targetId,appendMode=false){
 const el=$(targetId);
 const current=el.value.trim();
 const initial_dir=appendMode?(current.split(/\r?\n/).map(p=>p.trim()).filter(Boolean).at(-1)||''):current;
 try{
  const r=await request('/pick_folder',JSON.stringify({initial_dir}));
  if(r&&r.path){
   if(appendMode){
    el.value=current?current+'\n'+r.path:r.path;
   }else{
    el.value=r.path;
    if(targetId==='folderDestination')folderDestinations[workspaceMode]=r.path;
   }
   pushSessionMeta();
   notify('Đã chọn thư mục: '+r.path,'info');
  }
 }catch(e){status('Lỗi: '+e.message,true);notify(formatErrorToast(e),'err')}
}
$('pickLocalFolder').onclick=()=>pickFolder('localPath',false);
$('pickBatchFolder').onclick=()=>pickFolder('batchPaths',true);
$('pickDestFolder').onclick=()=>pickFolder('folderDestination',false);
async function exportFolder(){
 const batch=workspaceMode==='batch';
 if(!batch&&(!data||queueId)){status('Mở PDF hoặc thư mục của một ca để xuất',true);return}
 try{
  await flush();
  setWorking(true);
  const destination=$('folderDestination').value.trim();
  let result,count;
  if(batch){
   result=await request('/batch/release_folder',JSON.stringify({paths:batchPaths(),destination}));
   count=result.exported.length;
   await refreshBatch();
   const released=result.exported.find(x=>x.id===queueId);
   if(released){
    await loadBatchQc();
    $('download').download=released.output.split(/[\\/]/).pop();
   }
   if(result.comparisons&&result.comparisons.length){
    result.comparisons.forEach(c=>{
     const copyName=(c.target_folder||'').split(/[\\/]/).pop();
     notify('Phát hiện bản xuất trước! Đã tạo bản sao đối chiếu: '+copyName+' (giữ nguyên thư mục gốc)','info',10000);
    });
   }
  }else{
   result=await requestAsync('/export_folder',JSON.stringify({...identity(),destination}),{'Content-Type':'application/json'},'Đang xuất thư mục các PDF đã duyệt…');
   count=result.count;
   if(result.copied_for_comparison){
    const copyName=(result.directory||'').split(/[\\/]/).pop();
    notify('Phát hiện bản xuất trước! Đã tạo bản sao đối chiếu: '+copyName+' (giữ nguyên thư mục gốc)','info',10000);
   }
  }
  const message='Đã xuất '+count+' PDF.'+(result.directory?' Thư mục: '+result.directory:'')+' Còn '+result.pending.length+' file chưa đủ điều kiện.';
  const reviewAction=batch?batchReviewAction:item=>files.some(f=>f.index===item.index)?()=>openCaseFile(item.index):null;
  showResult($('folderResult'),message,result.pending,reviewAction);
  status(message,!!result.pending.length);
  notify(message,result.pending.length?'info':'success');
  if(batch&&count)showDelivered();
 }catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}finally{setWorking(false)}
}
$('exportFolder').onclick=exportFolder;
$('batchAdd').onclick=()=>{const dest=$('folderDestination').value.trim();batchAction('/batch/enqueue',{paths:batchPaths(),...(dest?{destination:dest}:{})})};
$('batchSelectAll').onclick=()=>{filteredBatchRows().forEach(r=>batchSelected.add(r.id));renderBatch()};$('batchClearSelection').onclick=()=>{batchSelected.clear();renderBatch()};
if($('batchRetrySelected'))$('batchRetrySelected').onclick=()=>retryBatch([...batchSelected]);
$('batchDeleteSelected').onclick=()=>deleteBatch([...batchSelected]);
$('batchStart').onclick=()=>batchAction('/batch/resume');$('batchPause').onclick=()=>batchAction('/batch/pause');$('batchFilter').onchange=()=>{if($('batchFilter').value!=='FAILED'){retryingIds.clear();autoOpenedRetries.clear()}renderBatch()};
$('refreshQc').onclick=async()=>{try{await flush();await loadBatchQc()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}};
$('compareOutput').onclick=async()=>{try{await flush();previewOutput=!previewOutput;show()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}};
const BUTTON_CONTAINERS = {
 compareOutput: 'batchReview',
 refreshQc: 'batchReview',
 batchStart: 'batchPanel',
 batchPause: 'batchPanel',
 batchSelectAll: 'batchPanel',
 batchClearSelection: 'batchPanel',
 batchRetrySelected: 'batchPanel',
 batchDeleteSelected: 'batchPanel',
 pickBatchFolder: 'batchPanel',
 batchAdd: 'batchPanel',
 prevFile: 'workflow',
 nextFile: 'workflow',
 prev: 'workflow',
 next: 'workflow',
 mode: 'workflow',
 done: 'workflow',
 approveAll: 'workflow',
 viewAudit: 'workflow',
 save: 'workflow',
 draft: 'workflow',
 export: 'workflow',
 newCase: 'workflow',
 load: 'upload',
 pickLocalFolder: 'upload',
 loadPath: 'upload',
 pickDestFolder: 'folderPanel',
 exportFolder: 'folderPanel'
};

const GLOBAL_SHORTCUTS = [
 { code: 'Digit1', key: '1', id: 'localMode', row: 'global', desc: 'Ca đang mở' },
 { code: 'Digit2', key: '2', id: 'batchMode', row: 'global', desc: 'Hàng đợi' },
 { code: 'Digit3', key: '3', id: 'newCase', row: 'global', desc: 'Mở ca khác' }
];

const CONTEXT_SHORTCUTS = {
 workflow: [
  { code: 'Space', key: 'Space', id: 'done', row: 'space', desc: 'Đã duyệt trang này' },
  { code: 'KeyA', key: 'A', altCode: 'ArrowLeft', id: 'prev', row: 'home', desc: 'Trang trước' },
  { code: 'KeyS', key: 'S', id: 'mode', row: 'home', desc: 'Khoanh thêm vùng xóa' },
  { code: 'KeyD', key: 'D', altCode: 'ArrowRight', id: 'next', row: 'home', desc: 'Trang sau' },
  { code: 'KeyF', key: 'F', id: 'approveAll', row: 'home', desc: 'Duyệt tất cả trang' },
  { code: 'KeyQ', key: 'Q', id: 'prevFile', row: 'top', desc: 'File trước' },
  { code: 'KeyW', key: 'W', id: 'save', row: 'top', desc: 'Lưu' },
  { code: 'KeyE', key: 'E', id: 'nextFile', row: 'top', desc: 'File sau' },
  { code: 'KeyR', key: 'R', id: 'compareOutput', row: 'top', desc: 'Xem ảnh / PDF đã khử' },
  { code: 'KeyZ', key: 'Z', id: 'viewAudit', row: 'bottom', desc: 'Báo cáo Markdown' },
  { code: 'KeyX', key: 'X', id: 'draft', row: 'bottom', desc: 'Xuất PDF thử' },
  { code: 'KeyC', key: 'C', id: 'export', row: 'bottom', desc: 'Xuất PDF chính thức' },
  { code: 'KeyV', key: 'V', id: 'exportFolder', row: 'bottom', desc: 'Xuất cả thư mục' }
 ],
 batch: [
  { code: 'Space', key: 'Space', id: 'batchStart', row: 'space', desc: 'Chạy / tiếp tục' },
  { code: 'KeyA', key: 'A', id: 'batchSelectAll', row: 'home', desc: 'Chọn tất cả' },
  { code: 'KeyS', key: 'S', id: 'batchPause', row: 'home', desc: 'Tạm dừng nhận file' },
  { code: 'KeyD', key: 'D', id: 'batchClearSelection', row: 'home', desc: 'Bỏ chọn' },
  { code: 'KeyF', key: 'F', id: 'batchRetrySelected', row: 'home', desc: 'Thử lại đã chọn' },
  { code: 'KeyQ', key: 'Q', id: 'pickBatchFolder', row: 'top', desc: 'Chọn thư mục' },
  { code: 'KeyE', key: 'E', id: 'batchAdd', row: 'top', desc: 'Thêm vào hàng đợi' },
  { code: 'KeyX', key: 'X', id: 'batchDeleteSelected', row: 'bottom', desc: 'Xóa đã chọn' },
  { code: 'KeyV', key: 'V', id: 'exportFolder', row: 'bottom', desc: 'Xuất các PDF đã duyệt' }
 ],
 upload: [
  { code: 'Space', key: 'Space', id: 'loadPath', fallbackId: 'load', row: 'space', desc: 'Xử lý đường dẫn / Mở PDF' },
  { code: 'KeyQ', key: 'Q', id: 'pickLocalFolder', row: 'top', desc: 'Chọn thư mục' },
  { code: 'KeyW', key: 'W', id: 'load', row: 'top', desc: 'Mở PDF' }
 ]
};

const ROW_PRIORITY = { space: 4, home: 3, top: 2, bottom: 1, global: 0 };

function getShortcutContext() {
 const isReviewing = !!data && (workspaceMode === 'batch' === !!queueId);
 if (isReviewing) return 'workflow';
 if (workspaceMode === 'batch') return 'batch';
 return 'upload';
}

function isButtonActionable(id) {
 if (working) return false;
 const el = $(id);
 if (!el || el.disabled) return false;
 if (el.classList && typeof el.classList.contains === 'function' && el.classList.contains('hide')) return false;
 const containerId = BUTTON_CONTAINERS[id];
 if (containerId) {
  const container = $(containerId);
  if (container && container.classList && typeof container.classList.contains === 'function' && container.classList.contains('hide')) {
   return false;
  }
 }
 return true;
}

function resolveShortcutTarget(item) {
 if (!item) return null;
 if (isButtonActionable(item.id)) return item.id;
 if (item.fallbackId && isButtonActionable(item.fallbackId)) return item.fallbackId;
 return null;
}

function flashShortcutTarget(elOrId) {
 const el = typeof elOrId === 'string' ? $(elOrId) : elOrId;
 if (!el || !el.classList) return;
 el.classList.add('kbd-active');
 setTimeout(() => {
  el.classList.remove('kbd-active');
 }, 140);
}

function triggerShortcutButton(id) {
 if (!isButtonActionable(id)) return false;
 flashShortcutTarget(id);
 const el = $(id);
 if (el) {
  if (typeof el.onclick === 'function') el.onclick();
  else if (typeof el.click === 'function') el.click();
 }
 return true;
}

function isInputElement(el) {
 if (!el) return false;
 const tag = (el.tagName || '').toUpperCase();
 return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || !!el.isContentEditable;
}

function removeChildKbd(btn) {
 if (!btn || !Array.isArray(btn.children)) return;
 for (let i = btn.children.length - 1; i >= 0; i--) {
  const c = btn.children[i];
  if (c && c.classList && typeof c.classList.contains === 'function' && c.classList.contains('kbd-hint')) {
   if (typeof c.remove === 'function') c.remove();
   const idx = btn.children.indexOf(c);
   if (idx >= 0) btn.children.splice(idx, 1);
  }
 }
}

function syncShortcutHints() {
 const currentCtx = getShortcutContext();
 const allShortcuts = [...GLOBAL_SHORTCUTS, ...(CONTEXT_SHORTCUTS[currentCtx] || [])];
 const buttonShortcuts = new Map();
 allShortcuts.forEach(item => {
  const targetId = item.id;
  if (!targetId) return;
  const existing = buttonShortcuts.get(targetId);
  const curPrio = ROW_PRIORITY[item.row] || 0;
  const exPrio = existing ? (ROW_PRIORITY[existing.row] || 0) : -1;
  if (!existing || curPrio > exPrio) {
   buttonShortcuts.set(targetId, item);
  }
 });

 const allKnownIds = new Set();
 GLOBAL_SHORTCUTS.forEach(s => allKnownIds.add(s.id));
 Object.values(CONTEXT_SHORTCUTS).forEach(list => list.forEach(s => {
  allKnownIds.add(s.id);
  if (s.fallbackId) allKnownIds.add(s.fallbackId);
 }));

 allKnownIds.forEach(id => {
  const btn = $(id);
  if (!btn) return;
  const item = buttonShortcuts.get(id);
  removeChildKbd(btn);
  if (item) {
   btn.setAttribute('aria-keyshortcuts', item.key);
   btn.setAttribute('title', (item.desc ? item.desc + ' ' : '') + '(Phím ' + item.key + ')');
   const kbd = document.createElement('kbd');
   kbd.className = 'kbd-hint';
   kbd.textContent = item.key;
   btn.append(kbd);
  } else {
   if (typeof btn.removeAttribute === 'function') btn.removeAttribute('aria-keyshortcuts');
   else if (btn.attributes) delete btn.attributes['aria-keyshortcuts'];
  }
 });

 const grid = $('shortcutGrid');
 if (grid) {
  if (typeof grid.replaceChildren === 'function') grid.replaceChildren();
  const ctxList = CONTEXT_SHORTCUTS[currentCtx] || [];
  ctxList.forEach(item => {
   const keyEl = document.createElement('div');
   keyEl.className = 'ergo-key';
   if (item.row === 'home') keyEl.classList.add('home-row');
   if (item.row === 'space') keyEl.classList.add('space-bar');
   const targetId = resolveShortcutTarget(item);
   if (!targetId) keyEl.classList.add('inactive');
   else {
    keyEl.onclick = () => {
     const tid = resolveShortcutTarget(item);
     if (tid) triggerShortcutButton(tid);
    };
   }
   const kbd = document.createElement('kbd');
   kbd.className = 'kbd-hint';
   kbd.textContent = item.key;
   const descSpan = document.createElement('span');
   descSpan.textContent = item.desc;
   keyEl.append(kbd, descSpan);
   grid.append(keyEl);
  });
 }

 const badge = $('shortcutContextBadge');
 if (badge) {
  const badges = {
   workflow: 'Chế độ: Duyệt ca',
   batch: 'Chế độ: Hàng đợi',
   upload: 'Chế độ: Mở ca'
  };
  badge.textContent = badges[currentCtx] || 'Chế độ: Mở ca';
 }
}

function handleShortcutKeydown(e) {
 if (!e) return;
 if (e.isComposing) return;
 const offlineModal = $('offlineModal');
 if (offlineModal && offlineModal.classList && typeof offlineModal.classList.contains === 'function' && !offlineModal.classList.contains('hide')) return;

 const isSaveCombo = (e.ctrlKey || e.metaKey) && !e.altKey && e.code === 'KeyS';
 if (isSaveCombo) {
  e.preventDefault();
  triggerShortcutButton('save');
  return;
 }

 if (e.code === 'Escape' || e.key === 'Escape') {
  let handled = false;
  const target = isInputElement(e.target) ? e.target : (isInputElement(document.activeElement) ? document.activeElement : null);
  if (target) {
   if (typeof target.blur === 'function') target.blur();
   handled = true;
  }
  if (manual) {
   manual = false;
   const modeBtn = $('mode');
   if (modeBtn) modeBtn.textContent = 'Khoanh thêm vùng xóa';
   syncShortcutHints();
   handled = true;
  }
  const auditModal = $('auditModal');
  if (auditModal && auditModal.classList && typeof auditModal.classList.contains === 'function' && !auditModal.classList.contains('hide')) {
   auditModal.classList.add('hide');
   handled = true;
  }
  const updateModal = $('updateModal');
  if (updateModal && updateModal.classList && typeof updateModal.classList.contains === 'function' && !updateModal.classList.contains('hide')) {
   updateModal.classList.add('hide');
   handled = true;
  }
  if (handled) {
   e.preventDefault();
  }
  return;
 }

 const updateModal = $('updateModal');
 if (updateModal && updateModal.classList && typeof updateModal.classList.contains === 'function' && !updateModal.classList.contains('hide')) {
  return;
 }

 const target = isInputElement(e.target) ? e.target : (isInputElement(document.activeElement) ? document.activeElement : null);
 if (target) return;
 if (e.ctrlKey || e.metaKey || e.altKey) return;
 if (e.repeat) return;
 if (working) return;

 if (e.code === 'Backquote' || e.key === '`') {
  e.preventDefault();
  const pad = $('shortcutPad');
  if (pad && pad.classList) {
   pad.classList.toggle('hide');
   const toggleBtn = $('toggleShortcutPad');
   if (toggleBtn) {
    toggleBtn.setAttribute('aria-expanded', String(!pad.classList.contains('hide')));
   }
  }
  return;
 }

 const globalMatch = GLOBAL_SHORTCUTS.find(s => s.code === e.code || (s.altCode && s.altCode === e.code));
 if (globalMatch) {
  const targetId = resolveShortcutTarget(globalMatch);
  if (targetId) {
   e.preventDefault();
   triggerShortcutButton(targetId);
   return;
  }
 }

 const currentCtx = getShortcutContext();
 const contextList = CONTEXT_SHORTCUTS[currentCtx] || [];
 const ctxMatch = contextList.find(s => s.code === e.code || (s.altCode && s.altCode === e.code));
 if (ctxMatch) {
  const targetId = resolveShortcutTarget(ctxMatch);
  if (targetId) {
   e.preventDefault();
   triggerShortcutButton(targetId);
   return;
  }
 }
}

window.addEventListener('keydown', handleShortcutKeydown);
if ($('batchPaths')) {}
if ($('toggleShortcutPad')) {
 $('toggleShortcutPad').onclick = () => {
  const pad = $('shortcutPad');
  if (pad && pad.classList) {
   pad.classList.toggle('hide');
   $('toggleShortcutPad').setAttribute('aria-expanded', String(!pad.classList.contains('hide')));
  }
 };
}
if ($('saveOfflineSession')) {
 $('saveOfflineSession').onclick = () => saveOfflineSnapshot();
}
if ($('dismissOfflineModal')) {
 $('dismissOfflineModal').onclick = () => dismissOfflinePrompt();
}
addInputListener($('localPath'), () => pushSessionMeta());
addInputListener($('folderDestination'), () => pushSessionMeta());
addInputListener($('sid'), () => pushSessionMeta());
addInputListener($('wholeCase'), () => pushSessionMeta());

let updateStatusCache = null;

function escapeHtml(str) {
 if (!str) return '';
 return String(str).replace(/[&<>"']/g, m => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
 }[m]));
}

function formatVersionBadge(current) {
 if (!current) return '...';
 const tagPart = current.tag ? current.tag + ' · ' : '';
 const commitPart = current.short_commit || 'unknown';
 const branchPart = ' (' + (current.branch || 'detached') + ')';
 const dirtyPart = current.dirty ? ' *' : '';
 return tagPart + commitPart + branchPart + dirtyPart;
}

function renderUpdateCurrentInfo(current) {
 const box = $('updateCurrentInfo');
 if (!box) return;
 if (!current) {
  box.textContent = 'Chưa có thông tin phiên bản';
  return;
 }
 const tagDisplay = current.tag ? `<b>${escapeHtml(current.tag)}</b> · ` : '';
 const dirtyDisplay = current.dirty ? ' · <span style="color:#cf1322;font-weight:600">Có thay đổi cục bộ</span>' : '';

 box.replaceChildren();
 const row1 = document.createElement('div');
 row1.innerHTML = `<strong>Phiên bản hiện tại:</strong> ${tagDisplay}<code>${escapeHtml(current.short_commit || '')}</code> (${escapeHtml(current.branch || 'Detached HEAD')})${dirtyDisplay}`;
 const row2 = document.createElement('div');
 row2.className = 'muted small';
 if (row2.style) row2.style.marginTop = '4px';
 row2.textContent = `Commit: ${current.subject || ''} (${current.committed_at || ''})`;
 box.append(row1, row2);
 if (current.previous_commit) {
  const row3 = document.createElement('div');
  row3.className = 'muted small';
  if (row3.style) row3.style.marginTop = '4px';
  row3.innerHTML = `Bản trước đó (có thể Rollback): <code>${escapeHtml(current.previous_commit.slice(0, 7))}</code>`;
  box.append(row3);
 }
}

function renderComparisonStatus(check) {
 const box = $('updateComparisonStatus');
 if (!box) return;
 box.className = 'update-status-block';
 if (!check) {
  box.textContent = 'Chưa kiểm tra với Git. Bấm "Kiểm tra trên Git" để làm mới.';
  return;
 }
 if (check.offline) {
  box.textContent = '⚠️ Mất kết nối Git remote (ngoại tuyến). Bạn vẫn có thể rollback về các bản có sẵn cục bộ.';
  return;
 }
 if (check.update_available || check.behind > 0) {
  box.classList.add('has-update');
  box.textContent = `⭐ Có ${check.behind} bản cập nhật mới trên Git remote! Bấm "Cập nhật bản mới nhất" để nâng cấp.`;
  return;
 }
 if (check.status === 'up_to_date') {
  box.classList.add('up-to-date');
  box.textContent = '✅ Đã ở bản mới nhất trên Git remote.';
  return;
 }
 if (check.status === 'ahead') {
  box.textContent = `Đang đi trước Git remote ${check.ahead} commit.`;
  return;
 }
 if (check.status === 'detached') {
  box.textContent = '⚠️ Đang ở phiên bản cũ (Detached HEAD). Bấm "Cập nhật bản mới nhất" để quay về nhánh chính.';
  return;
 }
 if (check.status === 'diverged') {
  box.textContent = `⚠️ Nhánh cục bộ và remote bị phân nhánh (ahead ${check.ahead}, behind ${check.behind}).`;
  return;
 }
 box.textContent = `Trạng thái Git: ${check.status || 'OK'}`;
}

function renderVersionSelect(versions, currentCommit) {
 const select = $('versionSelect');
 if (!select) return;
 select.replaceChildren();

 const tags = versions?.tags || [];
 const commits = versions?.commits || [];

 if (!tags.length && !commits.length) {
  const opt = document.createElement('option');
  opt.value = '';
  opt.textContent = '-- Không tìm thấy phiên bản nào --';
  select.append(opt);
  return;
 }

 if (tags.length) {
  const tagGroup = document.createElement('optgroup');
  tagGroup.setAttribute('label', 'Tags phát hành');
  tags.forEach(t => {
   const opt = document.createElement('option');
   opt.value = t.name;
   const cur = t.is_current || (currentCommit && t.commit === currentCommit) ? ' [Hiện tại]' : '';
   opt.textContent = `${t.name} - ${t.subject || ''} (${t.short_commit})${cur}`;
   tagGroup.append(opt);
  });
  select.append(tagGroup);
 }

 if (commits.length) {
  const commitGroup = document.createElement('optgroup');
  commitGroup.setAttribute('label', 'Lịch sử Commit');
  commits.forEach(c => {
   const opt = document.createElement('option');
   opt.value = c.commit;
   const cur = c.is_current || (currentCommit && c.commit === currentCommit) ? ' [Hiện tại]' : (c.is_previous ? ' [Trước đó]' : '');
   const remote = c.is_remote_head ? ' [Remote Head]' : '';
   opt.textContent = `${c.short_commit} - ${c.subject || ''} (${c.date || ''})${cur}${remote}`;
   commitGroup.append(opt);
  });
  select.append(commitGroup);
 }
}

async function loadUpdateStatus() {
 try {
  const res = await fetch('/update/status');
  if (!res.ok) return;
  const data = await res.json();
  if (!data || !data.current) return;
  updateStatusCache = data;
  const current = data.current;
  if ($('versionBadge')) {
   $('versionBadge').textContent = 'Phiên bản: ' + formatVersionBadge(current);
  }
  if ($('btnRollbackPrev')) {
   $('btnRollbackPrev').disabled = !current.can_rollback;
  }
  renderUpdateCurrentInfo(current);
  if (data.versions) {
   renderVersionSelect(data.versions, current.commit);
  }
  if ($('updateComparisonStatus') && !$('updateComparisonStatus').textContent) {
   renderComparisonStatus(null);
  }
 } catch (_) {}
}

async function checkGitUpdates() {
 const btn = $('btnCheckUpdate');
 const oldText = btn ? btn.textContent : '';
 if (btn) { btn.disabled = true; btn.textContent = 'Đang kiểm tra Git…'; }
 try {
  const res = await fetch('/update/check', {
   method: 'POST',
   headers: { 'Content-Type': 'application/json', 'X-HMU-Token': token },
   body: JSON.stringify({ fetch: true })
  });
  if (!res.ok) {
   const err = await res.json().catch(() => ({}));
   throw Error(err.error || 'Lỗi khi kiểm tra Git');
  }
  const data = await res.json();
  const check = data.check;
  const versions = data.versions;
  if (check?.current) {
   if ($('versionBadge')) $('versionBadge').textContent = 'Phiên bản: ' + formatVersionBadge(check.current);
   renderUpdateCurrentInfo(check.current);
   if ($('btnRollbackPrev')) {
    const canRb = check.current.can_rollback !== undefined ? !!check.current.can_rollback : !!check.current.previous_commit;
    $('btnRollbackPrev').disabled = !canRb;
   }
  }
  if ($('updateDot')) {
   $('updateDot').classList.toggle('hide', !check?.update_available);
  }
  renderComparisonStatus(check);
  if (versions) {
   renderVersionSelect(versions, check?.current?.commit);
  }
  if (check?.update_available) {
   notify(`Có ${check.behind} bản cập nhật mới trên Git`, 'info');
  } else if (check?.status === 'up_to_date') {
   notify('Công cụ đang ở phiên bản mới nhất', 'success');
  }
 } catch (e) {
  status(e.message, true);
  notify(formatErrorToast(e), 'err');
  if ($('updateComparisonStatus')) {
   $('updateComparisonStatus').textContent = '⚠️ Lỗi kiểm tra: ' + e.message;
  }
 } finally {
  if (btn) { btn.disabled = false; btn.textContent = oldText; }
 }
}

async function waitForServerRestart(pollInterval = 1000, maxAttempts = 30) {
 const notice = $('updateRestartNotice');
 if (notice) {
  notice.textContent = 'Đang khởi động lại phiên bản mới... Vui lòng đợi trong giây lát.';
  notice.classList.remove('hide');
 }
 const modal = $('updateModal');
 if (modal && typeof modal.querySelectorAll === 'function') {
  modal.querySelectorAll('button, select').forEach(b => { if (b.id !== 'closeUpdateModal') b.disabled = true; });
 }
 for (let i = 0; i < maxAttempts; i++) {
  if (pollInterval > 0) {
   await new Promise(r => setTimeout(r, pollInterval));
  }
  try {
   const res = await fetch('/update/status');
   if (res && res.ok) {
    if (window.location && typeof window.location.reload === 'function') {
     window.location.reload();
    }
    return true;
   }
  } catch (_) {}
 }
 if (notice) {
  notice.textContent = 'Server khởi động lại lâu hơn dự kiến. Hãy kiểm tra màn hình Terminal hoặc tải lại trang.';
 }
 return false;
}

async function applyGitVersion(target) {
 if (!target) {
  notify('Vui lòng chọn một phiên bản để chuyển đổi', 'err');
  return;
 }
 const isLatest = target === 'latest';
 const label = isLatest ? 'bản mới nhất' : `phiên bản "${target}"`;
 if (typeof window.confirm === 'function' && !window.confirm(`Xác nhận chuyển sang ${label}? Công cụ sẽ tự khởi động lại.`)) {
  return;
 }
 const notice = $('updateRestartNotice');
 if (notice) {
  notice.textContent = `Đang chuyển sang ${label}...`;
  notice.classList.remove('hide');
 }
 try {
  const res = await fetch('/update/apply', {
   method: 'POST',
   headers: { 'Content-Type': 'application/json', 'X-HMU-Token': token },
   body: JSON.stringify({ target, restart: true })
  });
  if (!res.ok) {
   const err = await res.json().catch(() => ({}));
   throw Error(err.error || 'Lỗi khi chuyển phiên bản');
  }
  const data = await res.json();
  if (data.restarting) {
   await waitForServerRestart();
  } else {
   notify(`Đã chuyển sang ${label}`, 'success');
   await loadUpdateStatus();
  }
 } catch (e) {
  if (notice) notice.classList.add('hide');
  status(e.message, true);
  notify(formatErrorToast(e), 'err');
 }
}

async function rollbackGitVersion() {
 if (typeof window.confirm === 'function' && !window.confirm('Xác nhận quay lại phiên bản trước đó (Rollback)? Công cụ sẽ tự khởi động lại.')) {
  return;
 }
 const notice = $('updateRestartNotice');
 if (notice) {
  notice.textContent = 'Đang quay lại phiên bản trước đó...';
  notice.classList.remove('hide');
 }
 try {
  const res = await fetch('/update/rollback', {
   method: 'POST',
   headers: { 'Content-Type': 'application/json', 'X-HMU-Token': token },
   body: JSON.stringify({ restart: true })
  });
  if (!res.ok) {
   const err = await res.json().catch(() => ({}));
   throw Error(err.error || 'Lỗi khi quay lại phiên bản trước');
  }
  const data = await res.json();
  if (data.restarting) {
   await waitForServerRestart();
  } else {
   notify('Đã quay lại phiên bản trước đó', 'success');
   await loadUpdateStatus();
  }
 } catch (e) {
  if (notice) notice.classList.add('hide');
  status(e.message, true);
  notify(formatErrorToast(e), 'err');
 }
}

if ($('openUpdateModal')) {
 $('openUpdateModal').onclick = () => {
  const modal = $('updateModal');
  if (modal) modal.classList.remove('hide');
  if (!updateStatusCache) loadUpdateStatus();
 };
}
if ($('closeUpdateModal')) {
 $('closeUpdateModal').onclick = () => {
  const modal = $('updateModal');
  if (modal) modal.classList.add('hide');
 };
}
if ($('btnCheckUpdate')) {
 $('btnCheckUpdate').onclick = () => checkGitUpdates();
}
if ($('btnUpdateLatest')) {
 $('btnUpdateLatest').onclick = () => applyGitVersion('latest');
}
if ($('btnRollbackPrev')) {
 $('btnRollbackPrev').onclick = () => rollbackGitVersion();
}
if ($('btnSwitchSelectedVersion')) {
 $('btnSwitchSelectedVersion').onclick = () => {
  const sel = $('versionSelect')?.value;
  if (!sel) {
   notify('Vui lòng chọn một phiên bản trong danh sách', 'err');
   return;
  }
  return applyGitVersion(sel);
 };
}

syncShortcutHints();
loadUpdateStatus().catch(() => {});
fetch('/state').then(r=>{if(!r.ok)throw Error('Không đọc được phiên HMU');return r.json()}).then(async s=>{token=s.token;if(s.workspace)applyWorkspace(s.workspace);await syncOfflineSnapshotIfNeeded(s);acceptState(s,true);if(s.active_task?.status==='running'&&s.active_task.task_id)resumeTask(s.active_task.task_id);pollBatch()}).catch(e=>{showOfflineModal('Không kết nối được máy chủ HMU. Hãy bật MO_CONG_CU.bat');status(e.message,true);notify(formatErrorToast(e),'err');pollBatch()});
