// Run with Node's standard library: node test_ui_save.js
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
const element = (initHide = false) => {
  const classes = new Set(initHide ? ['hide'] : []);
  return {
    children: [],
    className: '',
    textContent: '',
    classList: {
      add(x) { classes.add(x); },
      remove(x) { classes.delete(x); },
      toggle(x, on) { if (on === undefined ? !classes.has(x) : on) classes.add(x); else classes.delete(x); },
      contains(x) { return classes.has(x); }
    },
    getContext() { return {}; },
    setAttribute() {},
    replaceChildren() { this.children = []; },
    append(...x) { this.children.push(...x); },
    remove() {},
    value: '',
    disabled: false
  };
};
let release, first = true;
const sent = [];
const context = vm.createContext({console, structuredClone, Image:class {},
  window:{addEventListener(){}}, document:{getElementById(id){if(!elements.has(id))elements.set(id,element(id==='auditModal'));return elements.get(id)},querySelectorAll(){return [...elements.values()]},createElement(){return element(false)},createTextNode:t=>t},
  setTimeout(){return 1},clearTimeout(){},requestAnimationFrame(){},
  fetch:async(path,opts)=>{const body=JSON.parse(opts.body);sent.push(body);if(first){first=false;await new Promise(r=>release=r)}return {ok:true,json:async()=>({saved:true,revision:sent.length})}}
});
let source = fs.readFileSync(__dirname+'/ui/review.js','utf8');
source=source.slice(0,source.lastIndexOf("fetch('/state')"));
vm.runInContext(source, context);
vm.runInContext("data={job_id:'job',revision:0,pages:[{page:1,reviewed:false,manual_rects:[],note:'first',proposals:[]},{page:2,reviewed:false,manual_rects:[],note:'',proposals:[]}]};show=()=>{};dirty=true;editVersion=1;navigation=navigate(1)",context);
(async()=>{
  while(!release)await new Promise(r=>setImmediate(r));
  // An edit was already queued when the navigation flush started.
  vm.runInContext("data.pages[0].note='last edit';editVersion++;dirty=true",context);
  release();
  await vm.runInContext('navigation',context);
  assert.equal(sent.length,2,'navigation must flush the edit that arrived during the first save');
  assert.equal(sent[1].page,1);
  assert.equal(sent[1].note,'last edit');
  assert.equal(vm.runInContext('pn',context),1);
  assert.equal(vm.runInContext('dirty',context),false);
  console.log('UI late-edit navigation regression: PASS');
  let releaseAudit;
  context.fetch=async()=>{await new Promise(r=>releaseAudit=r);return {ok:true,json:async()=>({markdown:'stale audit'})}};
  vm.runInContext("auditRequest=$('viewAudit').onclick()",context);
  while(!releaseAudit)await new Promise(r=>setImmediate(r));
  vm.runInContext("data.job_id='another job'",context);
  releaseAudit();await vm.runInContext('auditRequest',context);
  assert.notEqual(elements.get('auditModal').textContent,'stale audit','late audit response must not populate a different job');
  console.log('UI stale-audit response regression: PASS');
  const manualCalls = [];
  context.fetch = async (path, opts) => {
    manualCalls.push({ path, body: JSON.parse(opts.body) });
    return { ok: true, json: async () => ({ saved: true, revision: 99 }) };
  };
  vm.runInContext("data.job_id='job';data.revision=2;dirty=false;$('status').textContent='old status';manualSave=$('save').onclick()", context);
  await vm.runInContext('manualSave', context);
  assert.equal(manualCalls.length, 1, 'manual save button must send /save_page even when dirty is false');
  assert.equal(manualCalls[0].path, '/save_page');
  assert.equal(vm.runInContext('data.revision', context), 99);
  assert.match(elements.get('status').textContent, /^Đã lưu · Đã duyệt /);
  const toastBox = elements.get('toastContainer');
  assert.ok(toastBox && toastBox.children.length >= 1, 'manual save must create a pill toast in #toastContainer');
  assert.equal(toastBox.children.at(-1).classList.contains('pill-toast'), true);
  assert.equal(toastBox.children.at(-1).classList.contains('success'), true);
  console.log('UI manual-save force when clean: PASS');

  // Test notify(msg, type) directly
  vm.runInContext("notify('Kiểm tra toast', 'info')", context);
  assert.equal(toastBox.children.at(-1).classList.contains('pill-toast'), true);
  assert.equal(toastBox.children.at(-1).classList.contains('info'), true);
  assert.match(toastBox.children.at(-1).textContent, /Kiểm tra toast/);

  // Test #done (Duyệt trang) creates pill toast while keeping standard #status.textContent
  const beforeDoneToasts = toastBox.children.length;
  vm.runInContext("show=()=>{status('Đã duyệt '+data.pages.filter(p=>p.reviewed).length+'/'+data.pages.length+' trang')};pn=0;data.pages[0].reviewed=false;donePromise=$('done').onclick()", context);
  await vm.runInContext('donePromise', context);
  assert.equal(toastBox.children.length, beforeDoneToasts + 1, '#done must append a pill toast');
  assert.equal(toastBox.children.at(-1).classList.contains('pill-toast'), true);
  assert.equal(toastBox.children.at(-1).classList.contains('success'), true);
  assert.match(toastBox.children.at(-1).textContent, /Đã duyệt trang 1/);
  assert.match(elements.get('status').textContent, /^Đã duyệt 1\/2 trang/);

  // Test #approveAll (Duyệt tất cả) creates pill toast while keeping standard #status.textContent
  context.fetch = async (path, opts) => {
    if (path === '/approve_all') {
      return { ok: true, json: async () => ({ review: { job_id: 'job', revision: 100, pages: [{ page: 1, reviewed: true, manual_rects: [], proposals: [] }, { page: 2, reviewed: true, manual_rects: [], proposals: [] }], watermarks_removed: [] } }) };
    }
    return { ok: true, json: async () => ({ saved: true, revision: 100 }) };
  };
  const beforeApproveAllToasts = toastBox.children.length;
  vm.runInContext("approvePromise=$('approveAll').onclick()", context);
  await vm.runInContext('approvePromise', context);
  assert.equal(toastBox.children.length, beforeApproveAllToasts + 1, '#approveAll must append a pill toast');
  assert.equal(toastBox.children.at(-1).classList.contains('pill-toast'), true);
  assert.equal(toastBox.children.at(-1).classList.contains('success'), true);
  assert.match(toastBox.children.at(-1).textContent, /Đã duyệt toàn bộ 2\/2 trang/);
  assert.equal(elements.get('status').textContent, 'Đã duyệt toàn bộ 2/2 trang! Bạn có thể bấm Xuất PDF chính thức.');

  // Test #export (Xuất PDF) creates pill toast while keeping standard #status.textContent
  context.fetch = async (path, opts) => {
    return { ok: true, json: async () => ({ file: 'out.pdf', count: 1, directory: 'E:/out' }) };
  };
  const beforeExportToasts = toastBox.children.length;
  vm.runInContext("exportPromise=$('export').onclick()", context);
  await vm.runInContext('exportPromise', context);
  assert.equal(toastBox.children.length, beforeExportToasts + 1, '#export must append a pill toast');
  assert.equal(toastBox.children.at(-1).classList.contains('pill-toast'), true);
  assert.equal(toastBox.children.at(-1).classList.contains('success'), true);
  assert.match(toastBox.children.at(-1).textContent, /Đã xuất 1 PDF/);
  assert.equal(elements.get('status').textContent, 'Đã xuất 1 PDF · Cần QC bản đầu ra');
  console.log('UI Pill Toast notifications on save/done/approveAll/export: PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
