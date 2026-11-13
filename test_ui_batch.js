const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
function element(){const classes=new Set();return {children:[],classList:{add(x){classes.add(x)},remove(x){classes.delete(x)},toggle(x,on){if(on===undefined?!classes.has(x):on)classes.add(x);else classes.delete(x)},contains(x){return classes.has(x)}},getContext(){return {}},replaceChildren(){this.children=[]},append(...children){this.children.push(...children)},setAttribute(k,v){this[k]=v},value:'',disabled:false,focus(){}}}
const ctx=vm.createContext({console,structuredClone,Image:class {},window:{addEventListener(){}},
 document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},querySelectorAll(){return []},createElement:element,createTextNode:t=>t},
 setTimeout(){return 1},clearTimeout(){},requestAnimationFrame(){},fetch:async()=>{throw Error('unexpected request')}});
let script=fs.readFileSync(__dirname+'/ui/review.js','utf8');
script=script.slice(0,script.lastIndexOf("fetch('/state')"));vm.runInContext(script,ctx);
(async()=>{
 vm.runInContext("data={job_id:'old',revision:1};queueId='old-queue';dirty=true;flush=async()=>{throw Error('save failed')};switchPromise=openBatch('new-queue')",ctx);
 await vm.runInContext('switchPromise',ctx);
 assert.equal(vm.runInContext('data.job_id',ctx),'old');
 assert.equal(vm.runInContext('queueId',ctx),'old-queue');
const sent=[];vm.runInContext('loadBatchQcOriginal=loadBatchQc',ctx);ctx.fetch=async(path,opts)=>{sent.push(path);return {ok:true,json:async()=>({review:{job_id:'new',revision:0},queue_id:'new-queue',files:[]})}};
 vm.runInContext("flush=async()=>{dirty=false};show=()=>{};loadBatchQc=async()=>{};switchPromise=openBatch('new-queue')",ctx);
 await vm.runInContext('switchPromise',ctx);
 assert.equal(sent[0],'/batch/open_job');assert.equal(vm.runInContext('queueId',ctx),'new-queue');
 let finish;ctx.fetch=async()=>{await new Promise(r=>finish=r);return {ok:true,json:async()=>({issues:[{id:'old'}],pages_checked:1,pages_expected:1})}};
 vm.runInContext("qcPromise=loadBatchQcOriginal()",ctx);
 while(!finish)await new Promise(r=>setImmediate(r));
 vm.runInContext("queueId='third-queue';data.job_id='third'",ctx);finish();await vm.runInContext('qcPromise',ctx);
 assert.equal(vm.runInContext('batchIssues.length',ctx),0,'stale QC must not switch current findings');
 let switchDone;ctx.fetch=async()=>{await new Promise(r=>switchDone=r);return {ok:true,json:async()=>({review:{job_id:'last',revision:0},queue_id:'last-queue',files:[]})}};
 vm.runInContext("switchPromise=openBatch('last-queue')",ctx);
 while(!switchDone)await new Promise(r=>setImmediate(r));
 assert.equal(vm.runInContext('working',ctx),true,'edits must stay disabled while the open response is pending');
 switchDone();await vm.runInContext('switchPromise',ctx);
 assert.equal(vm.runInContext('working',ctx),false);
 const alerts=[];ctx.window.alert=t=>alerts.push(t);ctx.window.confirm=()=>false;
 const calls=[];ctx.fetch=async(path,opts)=>{calls.push([path,opts&&JSON.parse(opts.body)]);return {ok:true,json:async()=>path==='/batch/status'?{jobs:[],coordinator:{}}:{deleted:['a'],skipped:[],active_deleted:true}}};
 vm.runInContext("batchRows=[{id:'a',state:'NEEDS_REVIEW',source_name:'a.pdf'},{id:'b',state:'FAILED',source_name:'b.pdf'}];$('batchFilter').value='FAILED';$('batchSelectAll').onclick()",ctx);
 assert.deepEqual([...vm.runInContext('batchSelected',ctx)],['b'],'select all must honor current filter');
 vm.runInContext("deletePromise=deleteBatch(['a'])",ctx);await vm.runInContext('deletePromise',ctx);assert.equal(calls.length,0,'cancelled confirmation must not delete');
 ctx.window.confirm=()=>true;
 vm.runInContext("flush=async()=>{throw Error('save failed')};deletePromise=deleteBatch(['a'])",ctx);await vm.runInContext('deletePromise',ctx);
 assert.equal(calls.length,0,'failed save must block deletion');
 vm.runInContext("flush=async()=>{};queueId='a';data={job_id:'open'};deletePromise=deleteBatch(['a'])",ctx);await vm.runInContext('deletePromise',ctx);
 assert.equal(calls[0][0],'/batch/delete');assert.deepEqual(calls[0][1].queue_ids,['a']);assert.equal(vm.runInContext('queueId',ctx),null);assert.equal(vm.runInContext('data',ctx),null);
 calls.length=0;
 ctx.fetch=async(path,opts)=>{calls.push([path,opts&&JSON.parse(opts.body)]);return {ok:true,json:async()=>path==='/batch/status'?{jobs:[{id:'b',state:'NEEDS_REVIEW',source_name:'patient2.pdf'}],coordinator:{}}:{directory:'E:/delivery/BAN_GIAO_01',exported:[{id:'a'}],pending:[{id:'b',source_name:'patient2.pdf',reason:'Chưa duyệt'}]}}};
 vm.runInContext("$('batchPaths').value='E:/input';$('folderDestination').value='E:/delivery';exportPromise=exportFolder()",ctx);await vm.runInContext('exportPromise',ctx);
 assert.equal(calls[0][0],'/batch/release_folder');assert.deepEqual(calls[0][1],{paths:['E:/input'],destination:'E:/delivery'});
 assert.ok(elements.get('folderResult').children.some(row=>row.children.some(child=>child.textContent?.includes('patient2.pdf'))));
 const report=elements.get('folderResult');assert.ok(report.children.length,'pending report must remain on screen');
 assert.equal(elements.get('batchFilter').value,'READY');
 ctx.fetch=async(path,opts)=>({ok:true,json:async()=>path.startsWith('/batch/qc?')?{issues:[],filename:'Kết quả.pdf'}:path==='/batch/status'?{jobs:[{id:'a',state:'READY',source_name:'Kết quả.pdf'}],coordinator:{}}:path==='/batch/release'?{directory:'E:/delivery',output:'E:/delivery/Kết quả.pdf'}:{directory:'E:/delivery/BAN_GIAO_02',exported:[{id:'a',output:'E:/delivery/BAN_GIAO_02/Kết quả.pdf'}],pending:[]}});
 vm.runInContext("queueId='a';data={job_id:'engine-a',revision:2};loadBatchQc=loadBatchQcOriginal;exportPromise=exportFolder()",ctx);await vm.runInContext('exportPromise',ctx);
 assert.ok(elements.get('download').href?.includes('revision=2'),'group release must refresh download to the saved review revision');
 assert.equal(elements.get('download').download,'Kết quả.pdf');
 vm.runInContext("$('batchFilter').value='NEEDS_REVIEW';singlePromise=batchRelease()",ctx);await vm.runInContext('singlePromise',ctx);
 assert.equal(elements.get('batchFilter').value,'READY');
 assert.equal(elements.get('download').download,'Kết quả.pdf');
 ctx.fetch=async(path)=>({ok:true,json:async()=>path==='/batch/status'?{jobs:[],coordinator:{}}:{directory:null,exported:[],pending:[]}});
 vm.runInContext("$('batchFilter').value='NEEDS_REVIEW';exportPromise=exportFolder()",ctx);await vm.runInContext('exportPromise',ctx);
 assert.equal(elements.get('batchFilter').value,'NEEDS_REVIEW','empty export must leave the review filter');
 calls.length=0;vm.runInContext("flush=async()=>{throw Error('save failed')};exportPromise=exportFolder()",ctx);await vm.runInContext('exportPromise',ctx);
 assert.equal(calls.length,0,'failed save must block group export');

 // Phase 3 tests: batchAction error toast, deleteBatch error toast, and refreshBatch FAILED deduplication
 const toastBox=elements.get('toastContainer');
 const errToasts=()=>toastBox.children.filter(t=>t.classList.contains('err'));
 const errCountBeforeBatch=errToasts().length;

 // 1. batchAction catch(e) -> notify(..., 'err')
 ctx.fetch=async()=>({ok:false,status:500,json:async()=>({error:'Lỗi khởi động worker',error_detail:{category:'CODE_ERROR',message:'Lỗi khởi động worker',code_location:{file:'batch.py',line:50}}})});
 await vm.runInContext("batchAction('/batch/resume')",ctx);
 assert.ok(errToasts().length>errCountBeforeBatch,'batchAction failure must emit .pill-toast.err');
 assert.ok(errToasts().some(t=>t.textContent.includes('batch.py:50')),'batchAction toast must show code location if available');

 // 2. deleteBatch catch(e) -> notify(..., 'err')
 const countBeforeDelete=errToasts().length;
 ctx.fetch=async()=>({ok:false,status:500,json:async()=>({error:'Không thể xóa mục đang bận'})});
 await vm.runInContext("deleteBatch(['locked-id'])",ctx);
 assert.ok(errToasts().length>countBeforeDelete,'deleteBatch failure must emit .pill-toast.err');

 // 3. refreshBatch() FAILED job notification and deduplication by queue_id + updated
 const countBeforeFailedPoll=errToasts().length;
 const failedJob={id:'q_fail_1',state:'FAILED',source_name:'corrupted_file.pdf',error:'PDF hỏng',updated:100};
 ctx.fetch=async()=>({ok:true,json:async()=>({jobs:[failedJob],coordinator:{}})});
 await vm.runInContext("refreshBatch()",ctx);
 assert.equal(errToasts().length,countBeforeFailedPoll+1,'refreshBatch must emit 1 .pill-toast.err for newly failed job');
 const failedToast=errToasts().at(-1);
 assert.ok(failedToast.textContent.includes('corrupted_file.pdf'),'failed toast must include source_name');
 assert.ok(failedToast.textContent.includes('PDF hỏng'),'failed toast must include error');

 // Second poll with same job & updated -> NO duplicate toast
 await vm.runInContext("refreshBatch()",ctx);
 assert.equal(errToasts().length,countBeforeFailedPoll+1,'refreshBatch must not duplicate toast if updated timestamp has not changed');

 // Third poll with updated timestamp -> emits new toast
 failedJob.updated=200;
 failedJob.error='PDF hỏng lần 2';
 await vm.runInContext("refreshBatch()",ctx);
 assert.equal(errToasts().length,countBeforeFailedPoll+2,'refreshBatch must emit new toast when updated timestamp changes');

 // Fourth poll with structured error_detail (from /batch/status payload) -> formats code location in toast
 const failedWithDetail={
  id:'q_fail_detail',
  state:'FAILED',
  source_name:'crash_worker.pdf',
  error:'Worker stopped with exit 1',
  updated:300,
  error_detail:{
   category:'CODE_ERROR',
   stage:'BATCH_WORKER',
   message:'Worker stopped with exit 1',
   source_file:'crash_worker.pdf',
   code_location:{file:'batch.py',line:441,function:'_reap_active_workers'}
  }
 };
 ctx.fetch=async()=>({ok:true,json:async()=>({jobs:[failedJob,failedWithDetail],coordinator:{}})});
 await vm.runInContext("refreshBatch()",ctx);
 assert.equal(errToasts().length,countBeforeFailedPoll+3,'refreshBatch must emit toast for newly failed job with error_detail');
 assert.ok(errToasts().at(-1).textContent.includes('[Lỗi Code: batch.py:441] Worker stopped with exit 1'),'failed toast must format error_detail when present');

 // Phase 4 Task 4.1: Batch pre-clone toasts & release collision comparison toasts & state workspace
 // 1. Batch enqueue returns cloned_folders -> pill toast
 ctx.fetch = async (path, opts) => {
   if (path === '/batch/status') return { ok: true, json: async () => ({ jobs: [], coordinator: {} }) };
   return {
     ok: true,
     json: async () => ({
       added: 3,
       cloned_folders: [
         'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified/BN01',
         'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified/BN02',
         'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified/BN03'
       ]
     })
   };
 };
 await vm.runInContext("batchAction('/batch/enqueue', {paths: ['C:/Users/Test/Desktop/HMU_Dot1/Data_Root']})", ctx);
 assert.ok(toastBox.children.some(t => t.textContent.includes('3 thư mục bệnh án trống')), 'batch enqueue with cloned_folders must emit pill toast');

 // 2. Batch release_folder returns comparisons -> pill toast for comparisons
 ctx.fetch = async (path, opts) => {
   if (path === '/batch/status') return { ok: true, json: async () => ({ jobs: [], coordinator: {} }) };
   return {
     ok: true,
     json: async () => ({
       directory: 'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified',
       exported: [{ id: 'q1', output: 'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified/BN01_Copy1/to_bia.pdf' }],
       pending: [],
       comparisons: [
         {
           source_folder: 'BN01',
           target_folder: 'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified/BN01_Copy1',
           copied_from: 'C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified/BN01'
         }
       ]
     })
   };
 };
 vm.runInContext("flush=async()=>{};dirty=false;workspaceMode='batch';$('batchPaths').value='C:/Users/Test/Desktop/HMU_Dot1/Data_Root';$('folderDestination').value='C:/Users/Test/Desktop/HMU_Dot1/Data_Deidentified'", ctx);
 await vm.runInContext("exportFolder()", ctx);
 assert.ok(toastBox.children.some(t => t.textContent.includes('BN01_Copy1') && t.textContent.includes('đối chiếu')), 'batch release collision comparisons must emit comparison toast');

 // 3. Test applyWorkspace updates UI and folderDestination
 vm.runInContext("applyWorkspace({workspace_name:'HMU_State_Ws',data_root:'C:/Ws/Data_Root',data_deidentified:'C:/Ws/Data_Deidentified'})", ctx);
 assert.equal(elements.get('workspaceName').value, 'HMU_State_Ws');
 assert.equal(elements.get('workspaceDataRoot').textContent, 'C:/Ws/Data_Root');
 assert.equal(elements.get('workspaceDataDeidentified').textContent, 'C:/Ws/Data_Deidentified');
 assert.equal(elements.get('folderDestination').value, 'C:/Ws/Data_Deidentified');

 // Phase 2 Task 3: Offline Toast deduplication and auto token resync on server reconnect
 vm.runInContext("token='OLD_TOKEN_BEFORE_RESTART';serverOffline=false", ctx);
 const toastsBeforeOffline = toastBox.children.length;

 // 1. First disconnect -> sets serverOffline = true and shows 1 warning toast mentioning MO_CONG_CU.bat
 ctx.fetch = async () => { throw new TypeError('Failed to fetch'); };
 await vm.runInContext("refreshBatch()", ctx);
 assert.equal(vm.runInContext('serverOffline', ctx), true, 'serverOffline flag must become true on fetch failure');
 assert.equal(toastBox.children.length, toastsBeforeOffline + 1, 'first disconnect must emit 1 warning toast');
 assert.ok(toastBox.children.at(-1).textContent.includes('MO_CONG_CU.bat'), 'offline toast must instruct user to reopen MO_CONG_CU.bat');

 // 2. Subsequent 2s polls while still offline -> NO duplicate toasts
 await vm.runInContext("refreshBatch()", ctx);
 await vm.runInContext("refreshBatch()", ctx);
 assert.equal(toastBox.children.length, toastsBeforeOffline + 1, 'repeated offline polls must not spam additional toasts');

 // 3. Server comes back online -> serverOffline transitions true -> false, fetches /state to update token, and notifies user
 let stateCalledOnReconnect = false;
 ctx.fetch = async (path) => {
   if (path === '/batch/status') {
     return { ok: true, json: async () => ({ jobs: [], coordinator: {} }) };
   }
   if (path === '/state') {
     stateCalledOnReconnect = true;
     return {
       ok: true,
       json: async () => ({
         token: 'NEW_TOKEN_AFTER_RESTART',
         review: null,
         files: [],
         queue_id: null
       })
     };
   }
   throw Error('Unexpected path: ' + path);
 };
 await vm.runInContext("refreshBatch()", ctx);
 assert.equal(vm.runInContext('serverOffline', ctx), false, 'serverOffline must reset to false when server responds');
 assert.equal(stateCalledOnReconnect, true, 'reconnect must automatically fetch /state');
 assert.equal(vm.runInContext('token', ctx), 'NEW_TOKEN_AFTER_RESTART', 'reconnect must synchronize new security token');
 assert.equal(toastBox.children.length, toastsBeforeOffline + 2, 'reconnect must emit a success/reconnect toast');

 // 4. Subsequent normal online polls -> does not re-fetch /state or spam reconnect toast
 stateCalledOnReconnect = false;
 await vm.runInContext("refreshBatch()", ctx);
 assert.equal(stateCalledOnReconnect, false, 'normal online poll must not fetch /state again');
 assert.equal(toastBox.children.length, toastsBeforeOffline + 2, 'normal online poll must not emit toast');

 // 5. Issue 2: 8 different failed jobs must display 8 distinct root-cause error messages in both toasts and batch rows
 const eightFailedJobs = Array.from({ length: 8 }, (_, idx) => ({
   id: 'fail_8_' + idx,
   state: 'FAILED',
   source_name: `benh_an_${idx + 1}.pdf`,
   source_path: `E:/HoSo/benh_an_${idx + 1}.pdf`,
   pages: idx % 2,
   updated: 500 + idx,
   error: `Worker stopped with exit 1`,
   error_detail: {
     category: idx < 4 ? 'FILE_ERROR' : 'CODE_ERROR',
     stage: idx < 4 ? 'BATCH_ENQUEUE' : 'BATCH_WORKER',
     source_file: `benh_an_${idx + 1}.pdf`,
     error_type: `SpecificErrorType${idx + 1}`,
     message: `Lỗi riêng biệt số ${idx + 1}`,
     root_cause: `RootCause_${idx + 1}: Chi tiết gốc lỗi tại file số ${idx + 1}`,
     code_location: { file: 'engine.py', line: 100 + idx, function: `step_${idx + 1}` }
   }
 }));
 const errBeforeEight = errToasts().length;
 ctx.fetch = async (path) => {
   if (path === '/batch/status') return { ok: true, json: async () => ({ jobs: eightFailedJobs, coordinator: { running: false } }) };
   throw Error('Unexpected path: ' + path);
 };
 vm.runInContext("$('batchFilter').value='FAILED'", ctx);
 await vm.runInContext("refreshBatch()", ctx);
 assert.equal(errToasts().length, errBeforeEight + 8, '8 failed jobs must emit 8 error toasts');
 const lastEightToastTexts = errToasts().slice(-8).map(t => t.textContent);
 assert.equal(new Set(lastEightToastTexts).size, 8, 'All 8 error toasts must be distinct and show their specific root cause');
 for (let i = 0; i < 8; i++) {
   assert.ok(lastEightToastTexts[i].includes(`RootCause_${i + 1}`), `Toast ${i + 1} must include RootCause_${i + 1}, got: ${lastEightToastTexts[i]}`);
 }
 const renderedRowTexts = elements.get('batchList').children.map(row => row.children[1]?.textContent || '');
 assert.equal(renderedRowTexts.length, 8, 'All 8 failed rows must be rendered under FAILED filter');
 assert.equal(new Set(renderedRowTexts).size, 8, 'All 8 batch list rows must display distinct root causes');
 for (let i = 0; i < 8; i++) {
   assert.ok(renderedRowTexts[i].includes(`RootCause_${i + 1}`), `Row ${i + 1} must include RootCause_${i + 1}, got: ${renderedRowTexts[i]}`);
 }

 // 6. Issue 1: Filtering by FAILED, selecting failed files, and clicking "Thử lại đã chọn" (#batchRetrySelected)
 // keeps retried files visible under FAILED filter and auto-opens the file onto the viewer when NEEDS_REVIEW
 vm.runInContext("batchSelected.clear();$('batchFilter').value='FAILED'", ctx);
 const retryJobsState = [
   {
     id: 'retry_f1',
     state: 'FAILED',
     source_name: 'loi_mo_file_1.pdf',
     source_path: 'E:/HoSo/loi_mo_file_1.pdf',
     pages: 0,
     can_open: false,
     updated: 701,
     error: 'PDF hỏng (Gốc lỗi: FileDataError: broken xref)'
   },
   {
     id: 'retry_f2',
     state: 'FAILED',
     source_name: 'loi_qc_2.pdf',
     source_path: 'E:/HoSo/loi_qc_2.pdf',
     pages: 1,
     can_open: true,
     updated: 702,
     error: 'QC thất bại'
   }
 ];
 ctx.fetch = async (path) => ({ ok: true, json: async () => ({ jobs: retryJobsState, coordinator: { running: false } }) });
 await vm.runInContext("refreshBatch()", ctx);
 vm.runInContext("$('batchSelectAll').onclick()", ctx);
 assert.equal(elements.get('batchRetrySelected').disabled, false, 'batchRetrySelected must be enabled when failed rows are selected');

 const retryCalls = [];
 let autoOpenedQueueId = null;
 ctx.fetch = async (path, opts) => {
   const body = opts && opts.body ? JSON.parse(opts.body) : null;
   retryCalls.push([path, body]);
   if (path === '/batch/retry') {
     // Transition retry_f1 -> QUEUED and retry_f2 -> NEEDS_REVIEW
     retryJobsState[0].state = 'QUEUED';
     retryJobsState[0].pages = 1;
     retryJobsState[0].error = '';
     retryJobsState[1].state = 'NEEDS_REVIEW';
     retryJobsState[1].error = '';
     return { ok: true, json: async () => ({ queued: true, retried: ['retry_f1', 'retry_f2'] }) };
   }
   if (path === '/batch/status') {
     return { ok: true, json: async () => ({ jobs: retryJobsState, coordinator: { running: true, active: 1 } }) };
   }
   if (path === '/batch/open_job') {
     autoOpenedQueueId = body.queue_id;
     return {
       ok: true,
       json: async () => ({
         review: { job_id: 'rev_' + body.queue_id, revision: 0, pages: [{ page: 1, width: 100, height: 100, reviewed: false, proposals: [], manual_rects: [] }], watermarks_removed: [] },
         queue_id: body.queue_id,
         files: []
       })
     };
   }
   throw Error('Unexpected path during retry: ' + path);
 };
 vm.runInContext("dirty=false;data=null;queueId=null", ctx);
 await vm.runInContext("$('batchRetrySelected').onclick()", ctx);
 assert.equal(retryCalls[0][0], '/batch/retry', 'batchRetrySelected must POST to /batch/retry');
 assert.deepEqual(retryCalls[0][1].queue_ids, ['retry_f1', 'retry_f2'], 'batchRetrySelected must send selected queue_ids');
 // Both retried rows must stay visible in #batchList even though filter is still FAILED!
 assert.equal(elements.get('batchList').children.length, 2, 'Retried jobs must remain visible under FAILED filter so user can track & open them');
 assert.equal(autoOpenedQueueId, 'retry_f2', 'Retried job reaching NEEDS_REVIEW must automatically open on viewer canvas to test');

 // 7. Direct "Mở thử" button on a FAILED row without review.json opens source_path via /open_path for testing
 let openPathPayload = null;
 retryJobsState[0].state = 'FAILED';
 retryJobsState[0].can_open = false;
 ctx.fetch = async (path, opts) => {
   const body = opts && opts.body ? JSON.parse(opts.body) : null;
   if (path === '/batch/status') return { ok: true, json: async () => ({ jobs: retryJobsState, coordinator: { running: false } }) };
   if (path === '/open_path') {
     openPathPayload = body;
     return {
       ok: true,
       json: async () => ({
         async: false,
         review: { job_id: 'local_test_job', revision: 0, pages: [{ page: 1, width: 100, height: 100, reviewed: false, proposals: [], manual_rects: [] }], watermarks_removed: [] },
         files: []
       })
     };
   }
   throw Error('Unexpected path during testFailedBatchFile: ' + path);
 };
 await vm.runInContext("refreshBatch()", ctx);
 await vm.runInContext("testFailedBatchFile(batchRows[0])", ctx);
 assert.ok(openPathPayload, 'testFailedBatchFile must call /open_path when can_open is false');
 assert.equal(openPathPayload.path, 'E:/HoSo/loi_mo_file_1.pdf');

 console.log('Batch UI save-before-switch and stale-QC guards: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
