const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map(),alerts=[];
function element(){const classes=new Set();return {children:[],classList:{add(x){classes.add(x)},remove(x){classes.delete(x)},toggle(x,on){if(on===undefined? !classes.has(x):on)classes.add(x);else classes.delete(x)},contains(x){return classes.has(x)}},getContext(){return {}},replaceChildren(){this.children=[]},append(...x){this.children.push(...x)},setAttribute(){},value:'',disabled:false,focus(){}}}
const calls=[],timeouts=[];
const ctx=vm.createContext({console,structuredClone,Image:class {},window:{addEventListener(){},alert(t){alerts.push(t)}},
 document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},querySelectorAll(){return [...elements.values()]},createElement:element,createTextNode:t=>t},
 setTimeout(fn,delay){timeouts.push({fn,delay});return timeouts.length;},clearTimeout(){},requestAnimationFrame(){},fetch:async(path,opts)=>{
  const body=JSON.parse(opts.body);calls.push({path,body});return {ok:true,json:async()=>path==='/save_page'?{revision:3}:path==='/select_file'?{review:{job_id:'second',revision:0,pages:[{page:1,reviewed:false,manual_rects:[],proposals:[]}],watermarks_removed:[]},files:[{index:1,name:'one.pdf',job_id:'first',pages:1},{index:2,name:'<private>.pdf',job_id:'second',pages:1}]}:{directory:'E:/results/BAN_GIAO_01',count:1,pending:[{index:2,source_name:'<private>.pdf',reason:'Chưa duyệt'}]}};
 }});
let script=fs.readFileSync(__dirname+'/ui/review.js','utf8');script=script.slice(0,script.lastIndexOf("fetch('/state')"));vm.runInContext(script,ctx);
(async()=>{
 vm.runInContext("data={job_id:'first',revision:0,pages:[{page:1,reviewed:true,manual_rects:[],proposals:[]}],watermarks_removed:[]};files=[{index:1,name:'one.pdf',job_id:'first',pages:1},{index:2,name:'<private>.pdf',job_id:'second',pages:1}];show()",ctx);
 assert.equal(elements.get('folderPanel').classList.contains('hide'),false,'local export panel must remain visible after preparing the case');
 assert.equal(elements.get('uploadInputs').classList.contains('hide'),true,'hide only the open inputs while reviewing');
 assert.equal(elements.get('exportFolder').disabled,false);
 vm.runInContext("$('folderDestination').value='E:/results';dirty=true;editVersion=1;localExportPromise=exportFolder()",ctx);await vm.runInContext('localExportPromise',ctx);
 assert.equal(calls[0].path,'/save_page');assert.equal(calls[1].path,'/export_folder');
 assert.deepEqual(calls[1].body,{job_id:'first',revision:3,destination:'E:/results'});
 const report=elements.get('folderResult');assert.ok(report.children.length);
 const pending=report.children.find(x=>x.children?.some(y=>y.textContent?.includes('<private>.pdf')));
 assert.ok(pending,'pending source names must remain visible as text');
 await pending.children.find(x=>x.textContent==='Mở / duyệt').onclick();
 assert.equal(calls.at(-1).path,'/select_file');assert.equal(calls.at(-1).body.file_index,2);
 assert.equal(vm.runInContext('data.job_id',ctx),'second');
 const originalFetch=ctx.fetch;ctx.fetch=async()=>({ok:false,status:404,json:async()=>({error:'Not found'})});
 vm.runInContext('localExportPromise=exportFolder()',ctx);await vm.runInContext('localExportPromise',ctx);
 assert.match(elements.get('status').textContent,/Phiên HMU đang chạy chưa hỗ trợ xuất thư mục/);ctx.fetch=originalFetch;
 const before=calls.length;vm.runInContext("flush=async()=>{throw Error('save failed')};localExportPromise=exportFolder()",ctx);await vm.runInContext('localExportPromise',ctx);
 assert.equal(calls.length,before,'failed save must prevent export');
 vm.runInContext("queueId='queue-id';show();localExportPromise=exportFolder()",ctx);await vm.runInContext('localExportPromise',ctx);
 assert.equal(calls.length,before,'local export must not act on a queue job');
 assert.equal(elements.get('workflow').classList.contains('hide'),true);
 assert.equal(elements.get('folderPanel').classList.contains('hide'),true);
 vm.runInContext("setMode('batch')",ctx);
 assert.equal(elements.get('upload').classList.contains('hide'),true);
 assert.equal(elements.get('workflow').classList.contains('hide'),false);
 assert.equal(elements.get('folderPanel').classList.contains('hide'),false);
 assert.equal(elements.get('folderResult').children.length,0,'old result actions must not carry over to the other mode');
 assert.equal(elements.get('folderDestination').value,'','each mode has a separate destination');
 vm.runInContext("queueId=null;data=null;setMode('local');setWorking(false)",ctx);assert.equal(elements.get('exportFolder').disabled,true);
 assert.equal(elements.get('folderDestination').value,'E:/results');
 const pickCalls=[];
 ctx.fetch=async(path,opts)=>{
  const body=opts&&opts.body?JSON.parse(opts.body):{};
  pickCalls.push({path,body});
  if(path==='/session/save')return {ok:true,json:async()=>({saved:true})};
  const folderCalls=pickCalls.filter(c=>c.path==='/pick_folder');
  return {ok:true,json:async()=>({path:folderCalls.length===1?'E:/Cases/Ca01':folderCalls.length===2?'E:/Batch/Dot01':folderCalls.length===3?'E:/Batch/Dot02':folderCalls.length===4?'E:/Out/KetQua':null,cancelled:folderCalls.length>4})};
 };
 vm.runInContext("$('localPath').value='';pickPromise=$('pickLocalFolder').onclick()",ctx);await vm.runInContext('pickPromise',ctx);
 assert.equal(pickCalls[0].path,'/pick_folder');
 assert.equal(elements.get('localPath').value,'E:/Cases/Ca01');
 vm.runInContext("$('batchPaths').value='';pickPromise=$('pickBatchFolder').onclick()",ctx);await vm.runInContext('pickPromise',ctx);
 assert.equal(elements.get('batchPaths').value,'E:/Batch/Dot01');
 vm.runInContext("pickPromise=$('pickBatchFolder').onclick()",ctx);await vm.runInContext('pickPromise',ctx);
 assert.equal(elements.get('batchPaths').value,'E:/Batch/Dot01\nE:/Batch/Dot02');
 vm.runInContext("pickPromise=$('pickDestFolder').onclick()",ctx);await vm.runInContext('pickPromise',ctx);
 assert.equal(elements.get('folderDestination').value,'E:/Out/KetQua');
 vm.runInContext("pickPromise=$('pickDestFolder').onclick()",ctx);await vm.runInContext('pickPromise',ctx);
 assert.equal(elements.get('folderDestination').value,'E:/Out/KetQua','cancelled dialog must keep existing value');
 const navCalls=[];
 ctx.fetch=async(path,opts)=>{
  const body=opts&&opts.body?JSON.parse(opts.body):{};
  navCalls.push({path,body});
  if(path==='/save_page')return {ok:true,json:async()=>({revision:5})};
  if(path==='/select_file'){
   const target=body.file_index===2?'second':'first';
   return {ok:true,json:async()=>({review:{job_id:target,revision:0,pages:[{page:1,reviewed:false,manual_rects:[],proposals:[]}],watermarks_removed:[]},files:[{index:1,name:'one.pdf',job_id:'first',pages:1},{index:2,name:'two.pdf',job_id:'second',pages:1}]})};
  }
  if(path==='/batch/open_job'){
   return {ok:true,json:async()=>({review:{job_id:'batch-2',revision:0,pages:[{page:1,reviewed:false,manual_rects:[],proposals:[]}],watermarks_removed:[]},queue_id:body.queue_id,files:[]})};
  }
  return {ok:true,json:async()=>({issues:[]})};
 };
 vm.runInContext("flush=async()=>{if(dirty)await save()};queueId=null;data={job_id:'first',revision:4,pages:[{page:1,reviewed:false,manual_rects:[],proposals:[]}],watermarks_removed:[]};files=[{index:1,name:'only.pdf',job_id:'first',pages:1}];show()",ctx);
 assert.equal(elements.get('prevFile').classList.contains('hide'),true,'single file must hide prevFile');
 assert.equal(elements.get('nextFile').classList.contains('hide'),true,'single file must hide nextFile');
 vm.runInContext("files=[{index:1,name:'one.pdf',job_id:'first',pages:1},{index:2,name:'two.pdf',job_id:'second',pages:1}];show()",ctx);
 assert.equal(elements.get('prevFile').classList.contains('hide'),false,'multi-file case must show prevFile');
 assert.equal(elements.get('nextFile').classList.contains('hide'),false,'multi-file case must show nextFile');
 assert.equal(elements.get('prevFile').disabled,true,'prevFile disabled at first file');
 assert.equal(elements.get('nextFile').disabled,false,'nextFile enabled at first file');
 assert.match(elements.get('filePos').textContent||'',/1\s*\/\s*2/);
 vm.runInContext("dirty=true;editVersion++;navPromise=$('nextFile').onclick()",ctx);await vm.runInContext('navPromise',ctx);
 assert.equal(navCalls[0].path,'/save_page','must flush before switching to next file');
 assert.equal(navCalls[1].path,'/select_file');
 assert.equal(navCalls[1].body.file_index,2,'nextFile must select adjacent file_index');
 assert.equal(elements.get('prevFile').disabled,false,'prevFile enabled at second file');
 assert.equal(elements.get('nextFile').disabled,true,'nextFile disabled at last file');
 vm.runInContext("navPromise=$('prevFile').onclick()",ctx);await vm.runInContext('navPromise',ctx);
 assert.equal(navCalls.at(-1).path,'/select_file');
 assert.equal(navCalls.at(-1).body.file_index,1,'prevFile must select previous file_index');
 assert.equal(elements.get('prevFile').disabled,true);
 assert.equal(elements.get('nextFile').disabled,false);
 vm.runInContext("queueId='q1';files=[];batchRows=[{id:'q1',state:'NEEDS_REVIEW',source_name:'a.pdf'},{id:'q2',state:'NEEDS_REVIEW',source_name:'b.pdf'}];setMode('batch');show()",ctx);
 assert.equal(elements.get('prevFile').classList.contains('hide'),false,'multi-file queue must show prevFile');
 assert.equal(elements.get('nextFile').classList.contains('hide'),false,'multi-file queue must show nextFile');
 assert.equal(elements.get('prevFile').disabled,true);
 assert.equal(elements.get('nextFile').disabled,false);
 vm.runInContext("navPromise=$('nextFile').onclick()",ctx);await vm.runInContext('navPromise',ctx);
 assert.ok(navCalls.some(c=>c.path==='/batch/open_job'&&c.body.queue_id==='q2'),'nextFile in batch mode must call openBatch for adjacent queue item');
 assert.equal(elements.get('prevFile').disabled,false);
 assert.equal(elements.get('nextFile').disabled,true);
 const toastBox=elements.get('toastContainer');
 assert.ok(toastBox&&toastBox.children.length>=4,'folder export, folder picker, and file switch must create pill toasts in #toastContainer');
 assert.ok(toastBox.children.every(t=>t.classList.contains('pill-toast')),'all toasts in #toastContainer must have .pill-toast class');
 assert.ok(toastBox.children.some(t=>/Đã xuất 1 PDF/.test(t.textContent)),'exportFolder must emit a pill toast');
 assert.ok(toastBox.children.some(t=>/E:\/Cases\/Ca01/.test(t.textContent)),'pickFolder must emit a pill toast when folder is chosen');
 assert.ok(toastBox.children.some(t=>/two\.pdf|File|hồ sơ/i.test(t.textContent)),'prevFile/nextFile must emit a pill toast on file switch');

 // Verify notify() default duration 10000ms (10s)
 const notifyDelays=timeouts.map(t=>t.delay);
 assert.ok(notifyDelays.includes(10000),'notify() must display for 10000ms (10s), got delays: '+notifyDelays.join(', '));
 const beforeManualNotify=timeouts.length;
 vm.runInContext("notify('Kiểm tra 10s')",ctx);
 assert.equal(timeouts[beforeManualNotify]?.delay,10000,'notify() default duration parameter must be 10000ms');

 // Verify ui/review.css top-right position and translateX slide animation
 const css=fs.readFileSync(__dirname+'/ui/review.css','utf8');
 assert.match(css,/\.toast-container\s*\{[^}]*top:\s*100px;/s,'.toast-container must have top: 100px');
 assert.match(css,/\.toast-container\s*\{[^}]*right:\s*20px;/s,'.toast-container must have right: 20px');
 assert.match(css,/@keyframes\s+pillToastIn\s*\{[\s\S]*?from\s*\{[^}]*translateX\(110%\)[\s\S]*?to\s*\{[^}]*translateX\(0\)/,'keyframes pillToastIn must slide from translateX(110%) to translateX(0)');
 assert.match(css,/\.pill-toast\.out\s*\{[^}]*translateX\(110%\)/s,'.pill-toast.out must slide out to translateX(110%)');

 // Phase 3 tests: error toasts on catch(e) and formatErrorToast
 const errToastsBefore=toastBox.children.filter(t=>t.classList.contains('err')).length;

 // Test formatErrorToast helper
 const formattedCodeErr=vm.runInContext("formatErrorToast({category:'CODE_ERROR',message:'IndexError',code_location:{file:'batch.py',line:145}})",ctx);
 assert.equal(formattedCodeErr,'[Lỗi Code: batch.py:145] IndexError');

 const formattedFileErr=vm.runInContext("formatErrorToast({category:'FILE_ERROR',source_file:'doc.pdf',message:'PDF hỏng'})",ctx);
 assert.equal(formattedFileErr,'[Lỗi File: doc.pdf] PDF hỏng');

 // Test load catch(e) -> notify(..., 'err')
 vm.runInContext("$('file').files=[{name:'broken.pdf'}]",ctx);
 ctx.fetch=async()=>({ok:false,status:400,json:async()=>({error:'PDF không đọc được',error_detail:{category:'FILE_ERROR',source_file:'broken.pdf',message:'PDF không đọc được'}})});
 await vm.runInContext("$('load').onclick()",ctx);
 const errToastsAfterLoad=toastBox.children.filter(t=>t.classList.contains('err'));
 assert.ok(errToastsAfterLoad.length>errToastsBefore,'load failure must emit .pill-toast.err');
 assert.ok(errToastsAfterLoad.some(t=>t.textContent.includes('broken.pdf')&&t.textContent.includes('PDF không đọc được')));

 // Test loadPath catch(e) -> notify(..., 'err')
 elements.get('localPath').value='E:/Invalid/Path';
 ctx.fetch=async()=>({ok:false,status:400,json:async()=>({error:'Đường dẫn không tồn tại',error_detail:{category:'FILE_ERROR',source_file:'Path',message:'Đường dẫn không tồn tại'}})});
 await vm.runInContext("$('loadPath').onclick()",ctx);
 const errToastsAfterLoadPath=toastBox.children.filter(t=>t.classList.contains('err'));
 assert.ok(errToastsAfterLoadPath.length>errToastsAfterLoad.length,'loadPath failure must emit .pill-toast.err');

 // Test saveSoon catch(e) -> notify(..., 'err')
 const errCountBeforeSaveSoon=toastBox.children.filter(t=>t.classList.contains('err')).length;
 vm.runInContext("save=async()=>{throw Error('Lỗi lưu tự động')};saveSoon()",ctx);
 const lastTimeout=timeouts.at(-1);
 await lastTimeout.fn();
 const errToastsAfterSaveSoon=toastBox.children.filter(t=>t.classList.contains('err'));
 assert.ok(errToastsAfterSaveSoon.length>errCountBeforeSaveSoon,'saveSoon failure must emit .pill-toast.err');

 // Phase 4 Task 4.1: Desktop Workspace UI & Pre-clone & Collision alerts
 // 1. Test #initWorkspace initializes desktop workspace and auto-fills destination
 ctx.document.getElementById('workspaceName').value = 'HMU_Dot1_TimMach';
 const wsCalls = [];
 ctx.fetch = async (path, opts) => {
  const body = opts && opts.body ? JSON.parse(opts.body) : {};
  wsCalls.push({ path, body });
  if (path === '/workspace/init') {
   return {
    ok: true,
    json: async () => ({
     workspace_name: 'HMU_Dot1_TimMach',
     workspace_dir: 'C:/Users/Test/Desktop/HMU_Dot1_TimMach',
     data_root: 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Root',
     data_deidentified: 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified'
    })
   };
  }
  return { ok: true, json: async () => ({}) };
 };
 await vm.runInContext("$('initWorkspace').onclick()", ctx);
 assert.equal(wsCalls[0].path, '/workspace/init');
 assert.equal(wsCalls[0].body.workspace_name, 'HMU_Dot1_TimMach');
 assert.equal(elements.get('workspaceDataRoot').textContent, 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Root');
 assert.equal(elements.get('workspaceDataDeidentified').textContent, 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified');
 assert.equal(elements.get('folderDestination').value, 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified');
 assert.ok(toastBox.children.some(t => t.textContent.includes('HMU_Dot1_TimMach')), 'initWorkspace must emit a success toast');

 // 2. Test #scanWorkspaceRoot routes to batch queue with Data_Root
 await vm.runInContext("$('scanWorkspaceRoot').onclick()", ctx);
 assert.equal(elements.get('batchPaths').value, 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Root');
 assert.equal(vm.runInContext('workspaceMode', ctx), 'batch', 'scanWorkspaceRoot must switch to batch mode');

 // 3. Test /open_path returns cloned_folders -> toast notification
 ctx.fetch = async (path, opts) => {
  return {
   ok: true,
   json: async () => ({
    review: { job_id: 'case1', revision: 0, pages: [{ page: 1, reviewed: true, manual_rects: [], proposals: [] }], watermarks_removed: [] },
    files: [{ index: 1, name: 'doc.pdf', job_id: 'case1', pages: 1 }],
    batch_case: true,
    cloned_folders: [
     'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified/BA001',
     'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified/BA002'
    ]
   })
  };
 };
 elements.get('localPath').value = 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Root/BA001';
 vm.runInContext("flush=async()=>{};dirty=false;setMode('local')", ctx);
 await vm.runInContext("$('loadPath').onclick()", ctx);
 assert.ok(toastBox.children.some(t => t.textContent.includes('2 thư mục bệnh án trống')), 'open_path with cloned_folders must emit pill toast');

 // 4. Test /export_folder with copied_for_comparison -> toast notification with comparison alert
 ctx.fetch = async (path, opts) => {
  return {
   ok: true,
   json: async () => ({
    directory: 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified/BA001_Copy1',
    count: 1,
    pending: [],
    copied_for_comparison: true,
    original_directory: 'C:/Users/Test/Desktop/HMU_Dot1_TimMach/Data_Deidentified/BA001'
   })
  };
 };
 vm.runInContext("data={job_id:'case1',revision:0,pages:[{page:1,reviewed:true,manual_rects:[],proposals:[]}],watermarks_removed:[]};exportPromise=exportFolder()", ctx);
 await vm.runInContext('exportPromise', ctx);
 assert.ok(toastBox.children.some(t => t.textContent.includes('BA001_Copy1') && t.textContent.includes('đối chiếu')), 'export_folder collision must emit comparison toast');

 console.log('Local-path folder UI: visible controls, save/revision, pending alert/open and queue guard PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
