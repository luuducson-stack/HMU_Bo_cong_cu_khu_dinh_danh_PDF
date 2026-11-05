let workspaceMode='local';
const folderDestinations={local:'',batch:''};
let queueId=null,batchRows=[],batchIssues=[],previewOutput=false;
const batchSelected=new Set();
const batchLabels={QUEUED:'Chờ xử lý',PREPARING:'Đang phân tích',EXPORTING:'Đang khử / xuất',VERIFYING:'Đang kiểm PDF',NEEDS_REVIEW:'Chờ duyệt',READY:'Đã bàn giao',FAILED:'Lỗi',CANCELLING:'Đang dừng tiến trình',CANCELLED:'Đã hủy',DUPLICATE:'Trùng nội dung',DELETING:'Xóa chưa xong — thử Xóa lại'};
let token='',data=null,pn=0,img=new Image(),manual=false,start=null,preview=null,files=[],dirty=false,editVersion=0,working=false;
let saveQueue=Promise.resolve();
function identity(){return {job_id:data.job_id,revision:data.revision}}
function acceptState(r){data=r.review;queueId=r.queue_id||null;batchIssues=[];previewOutput=false;if(r.files)files=r.files;setMode(queueId?'batch':'local');pn=0;dirty=false;clearTimeout(timer);$('download').classList.add('hide');$('auditModal').classList.add('hide');$('auditModal').textContent='';show();if(queueId)loadBatchQc()}
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
}
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
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
async function request(path,body,headers={}){const r=await fetch(path,{method:'POST',headers:{'X-HMU-Token':token,...headers},body});const d=await r.json();if(!r.ok){const err=Error(d.error||'Không thực hiện được');err.detail=d.error_detail;throw err}return d}
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
 if(detail&&detail.category==='CODE_ERROR'&&loc&&loc.file){
  return '[Lỗi Code: '+loc.file+':'+loc.line+'] '+msg;
 }
 if(src||(detail&&detail.category==='FILE_ERROR')){
  return '[Lỗi File: '+(src||'Tệp')+'] '+msg;
 }
 if(detail&&detail.category==='CONFLICT_ERROR'){
  return '[Lỗi Xung đột] '+msg;
 }
 return msg;
}
const seenFailedJobs=new Map();
async function requestAsync(path,body,headers={},fallback='Đang xử lý bất đồng bộ…'){
 status('⏳ '+fallback);
 const r=await fetch(path,{method:'POST',headers:{'X-HMU-Token':token,'X-HMU-Async':'1',...headers},body});
 const init=await r.json();
 if(r.status===404&&path==='/export_folder')throw Error('Phiên HMU đang chạy chưa hỗ trợ xuất thư mục. Lưu công việc rồi mở lại đúng công việc bằng bản mới.');
 if(!r.ok){const err=Error(init.error||'Không thực hiện được');err.detail=init.error_detail;throw err}
 if(!init.async)return init;
 while(true){
  await new Promise(res=>setTimeout(res,350));
  const pr=await fetch('/progress?task_id='+encodeURIComponent(init.task_id));
  const pd=await pr.json();
  if(!pr.ok){const err=Error(pd.error||'Không lấy được trạng thái tác vụ');err.detail=pd.error_detail;throw err}
  if(pd.status==='error'){const err=Error(pd.error||'Lỗi xử lý bất đồng bộ');err.detail=pd.error_detail;throw err}
  if(pd.status==='done')return pd.result;
  if(pd.progress)status('⏳ '+pd.progress+(pd.elapsed?' ('+pd.elapsed+'s)':''));
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
async function navigate(n){try{await flush();pn=Math.max(0,Math.min(data.pages.length-1,n));show()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}}
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
$('mode').onclick=()=>{manual=!manual;$('mode').textContent=manual?'Đang khoanh — nhấp để dừng':'Khoanh thêm vùng xóa'};
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
function filteredBatchRows(){const filter=$('batchFilter').value;return batchRows.filter(r=>!filter||r.state===filter||(filter==='RUNNING'&&['PREPARING','EXPORTING','VERIFYING'].includes(r.state)))}
function renderBatch(){
 const box=$('batchList');box.replaceChildren();
 filteredBatchRows().forEach(r=>{
  const row=document.createElement('div');row.className='item';
  const check=document.createElement('input');check.type='checkbox';check.checked=batchSelected.has(r.id);check.disabled=working;check.setAttribute('aria-label','Chọn '+r.source_name);
  check.onchange=()=>{if(check.checked)batchSelected.add(r.id);else batchSelected.delete(r.id);renderBatch()};
  const t=document.createElement('span');t.textContent=r.source_name+' · '+r.pages+' trang · '+batchLabels[r.state]+(r.qc_status?' · QC: '+r.qc_status+' ('+r.warnings+' cảnh báo)':'')+(r.error?' · '+r.error:'');row.append(check,t);
  if(['NEEDS_REVIEW','READY'].includes(r.state))row.append(batchButton('Mở / duyệt',()=>openBatch(r.id)));
  if(['FAILED','CANCELLED'].includes(r.state))row.append(batchButton('Thử lại',()=>batchAction('/batch/retry',{queue_id:r.id})));
  if(['QUEUED','PREPARING','EXPORTING','VERIFYING'].includes(r.state))row.append(batchButton('Hủy xử lý',()=>batchAction('/batch/cancel',{queue_id:r.id})));
  if(r.state==='DUPLICATE')row.append(batchButton('Mở bản gốc',()=>openBatch(r.duplicate_of)));
  row.append(batchButton('Xóa',()=>deleteBatch([r.id])));box.append(row);
 });
 $('batchSelectedCount').textContent=batchSelected.size+' đã chọn';$('batchDeleteSelected').disabled=working||!batchSelected.size;
 updateFileNav();
}
async function refreshBatch(){try{const response=await fetch('/batch/status');const r=await response.json();if(!response.ok)throw Error(r.error);batchRows=r.jobs||[];const ids=new Set(batchRows.map(x=>x.id));for(const id of batchSelected)if(!ids.has(id))batchSelected.delete(id);for(const id of seenFailedJobs.keys())if(!ids.has(id))seenFailedJobs.delete(id);for(const j of batchRows){if(j.state==='FAILED'){const lastUpdated=seenFailedJobs.get(j.id);if(lastUpdated!==j.updated){seenFailedJobs.set(j.id,j.updated);notify(formatErrorToast(j.error_detail||j.error,j.source_name),'err')}}}renderBatch();const pending=batchRows.filter(x=>x.state==='NEEDS_REVIEW').length,ready=batchRows.filter(x=>x.state==='READY').length;$('batchStatus').textContent=batchRows.length+' file · '+(r.coordinator.active||0)+' đang chạy · '+pending+' chờ duyệt · '+ready+' đã bàn giao. '+(r.coordinator.message||'')}catch(e){$('batchStatus').textContent=e.message;notify(formatErrorToast(e),'err')}}
async function pollBatch(){await refreshBatch();setTimeout(pollBatch,2000)}
async function batchAction(path,body={}){try{const r=await request(path,JSON.stringify(body));await refreshBatch();if(r&&r.cloned_folders&&r.cloned_folders.length){notify('Đã tạo sẵn '+r.cloned_folders.length+' thư mục bệnh án trống trong Data_Deidentified','info')}return r}catch(e){status(e.message,true);notify(formatErrorToast(e),'err');return null}}
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
$('batchDeleteSelected').onclick=()=>deleteBatch([...batchSelected]);
$('batchStart').onclick=()=>batchAction('/batch/resume');$('batchPause').onclick=()=>batchAction('/batch/pause');$('batchFilter').onchange=renderBatch;
$('refreshQc').onclick=async()=>{try{await flush();await loadBatchQc()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}};
$('compareOutput').onclick=async()=>{try{await flush();previewOutput=!previewOutput;show()}catch(e){status(e.message,true);notify(formatErrorToast(e),'err')}};
fetch('/state').then(r=>{if(!r.ok)throw Error('Không đọc được phiên HMU');return r.json()}).then(s=>{token=s.token;data=s.review;queueId=s.queue_id;files=s.files||[];if(s.workspace)applyWorkspace(s.workspace);setMode(queueId?'batch':'local');if(data){show();if(queueId)loadBatchQc()}pollBatch()}).catch(e=>{status(e.message,true);notify(formatErrorToast(e),'err')});
