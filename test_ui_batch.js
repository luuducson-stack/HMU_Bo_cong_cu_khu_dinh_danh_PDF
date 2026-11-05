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

 console.log('Batch UI save-before-switch and stale-QC guards: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
