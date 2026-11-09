// Run with Node's standard library: node test_ui_shortcuts.js
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const elements = new Map();
const timeouts = [];
const windowListeners = {};

function createEl(id = '', initHide = false) {
  const classes = new Set(initHide ? ['hide'] : []);
  return {
    id,
    tagName: id === 'note' || id === 'sid' || id === 'localPath' || id === 'pageNo' ? 'INPUT'
      : id === 'batchPaths' ? 'TEXTAREA'
      : id === 'caseFile' || id === 'batchFilter' ? 'SELECT'
      : 'BUTTON',
    type: id === 'wholeCase' ? 'checkbox' : 'text',
    children: [],
    className: '',
    textContent: '',
    value: '',
    disabled: false,
    blurred: false,
    attributes: {},
    parentElement: null,
    classList: {
      add(...items) { items.forEach(x => classes.add(x)); },
      remove(...items) { items.forEach(x => classes.delete(x)); },
      toggle(x, on) {
        if (on === undefined ? !classes.has(x) : on) {
          classes.add(x);
          return true;
        } else {
          classes.delete(x);
          return false;
        }
      },
      contains(x) { return classes.has(x); }
    },
    getContext() { return { drawImage() {}, strokeRect() {}, fillRect() {} }; },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return this.attributes[k]; },
    replaceChildren(...nodes) {
      this.children = [...nodes];
      nodes.forEach(n => { if (n && typeof n === 'object') n.parentElement = this; });
    },
    append(...nodes) {
      this.children.push(...nodes);
      nodes.forEach(n => { if (n && typeof n === 'object') n.parentElement = this; });
    },
    remove() {
      if (this.parentElement) {
        const idx = this.parentElement.children.indexOf(this);
        if (idx >= 0) this.parentElement.children.splice(idx, 1);
        this.parentElement = null;
      }
    },
    focus() {},
    blur() { this.blurred = true; },
    click() {
      if (!this.disabled && !this.classList.contains('hide') && typeof this.onclick === 'function') {
        return this.onclick();
      }
    }
  };
}

// Pre-create containers with their initial visibility state
['batchPanel', 'folderPanel', 'batchReview', 'auditModal', 'offlineModal', 'workflow', 'prevFile', 'nextFile', 'filePos', 'caseFile', 'caseScope', 'download', 'shortcutPad'].forEach(id => {
  elements.set(id, createEl(id, true));
});

const localStorageStore = new Map();
const localStorageMock = {
  getItem: k => localStorageStore.has(k) ? localStorageStore.get(k) : null,
  setItem: (k, v) => { localStorageStore.set(k, String(v)); },
  removeItem: k => { localStorageStore.delete(k); },
  clear: () => { localStorageStore.clear(); }
};

const ctx = vm.createContext({
  console,
  structuredClone,
  Image: class {},
  localStorage: localStorageMock,
  window: {
    addEventListener(evt, fn) { windowListeners[evt] = fn; },
    confirm: () => true,
    localStorage: localStorageMock
  },
  document: {
    activeElement: null,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, createEl(id, false));
      return elements.get(id);
    },
    querySelectorAll() { return [...elements.values()]; },
    createElement(tag) {
      const el = createEl('', false);
      el.tagName = String(tag || 'DIV').toUpperCase();
      return el;
    },
    createTextNode: t => String(t)
  },
  setTimeout(fn, delay) {
    const item = { fn, delay };
    timeouts.push(item);
    return timeouts.length;
  },
  clearTimeout() {},
  requestAnimationFrame(fn) { fn(); },
  fetch: async () => ({
    ok: true,
    json: async () => ({ saved: true, revision: 10, review: { job_id: 'j1', revision: 10, pages: [{ page: 1, reviewed: true, manual_rects: [], proposals: [] }], watermarks_removed: [] } })
  })
});

const targetReviewPath = path.join(__dirname, 'ui', 'review.js');
let source = fs.readFileSync(targetReviewPath, 'utf8');
source = source.slice(0, source.lastIndexOf("fetch('/state')"));
vm.runInContext(source, ctx);

(async () => {
  // Helper to dispatch synthetic keyboard events
  const fireKey = (code, key, extra = {}) => {
    let prevented = false;
    const evt = {
      code,
      key,
      repeat: false,
      isComposing: false,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      shiftKey: false,
      target: extra.target || ctx.document.activeElement || { tagName: 'BODY' },
      preventDefault() { prevented = true; },
      ...extra
    };
    if (typeof windowListeners.keydown === 'function') {
      windowListeners.keydown(evt);
    }
    return { prevented, evt };
  };

  // =========================================================================
  // 1.1 Registry
  // =========================================================================
  assert.equal(typeof windowListeners.keydown, 'function', 'window keydown listener must be registered');

  const activeContext = vm.runInContext('typeof getShortcutContext === "function" ? getShortcutContext() : null', ctx);
  assert.equal(activeContext, 'upload', "getShortcutContext() must return 'upload' when no case is open");

  assert.equal(elements.get('localMode').getAttribute('aria-keyshortcuts'), '1', '#localMode aria-keyshortcuts must be 1');
  assert.equal(elements.get('batchMode').getAttribute('aria-keyshortcuts'), '2', '#batchMode aria-keyshortcuts must be 2');
  assert.equal(elements.get('loadPath').getAttribute('aria-keyshortcuts'), 'Space', '#loadPath aria-keyshortcuts must be Space in upload context');
  assert.equal(elements.get('pickLocalFolder').getAttribute('aria-keyshortcuts'), 'Q', '#pickLocalFolder aria-keyshortcuts must be Q in upload context');

  // =========================================================================
  // 1.2 Context 'workflow' (lưới QWER / ASDF / ZXCV / Space)
  // =========================================================================
  vm.runInContext(`
    data = {
      job_id: 'job_1',
      revision: 1,
      ocr_pages_count: 0,
      watermarks_removed: [],
      pages: [
        { page: 1, width: 100, height: 100, reviewed: false, manual_rects: [], proposals: [] },
        { page: 2, width: 100, height: 100, reviewed: false, manual_rects: [], proposals: [] }
      ]
    };
    files = [
      { index: 1, name: 'f1.pdf', job_id: 'job_1', pages: 2, reviewed: 0 },
      { index: 2, name: 'f2.pdf', job_id: 'job_2', pages: 2, reviewed: 0 }
    ];
    queueId = null;
    setMode('local');
    show();
  `, ctx);

  assert.equal(vm.runInContext('getShortcutContext()', ctx), 'workflow', "getShortcutContext() must return 'workflow' when case is open");

  // Verify aria-keyshortcuts in workflow context
  assert.equal(elements.get('done').getAttribute('aria-keyshortcuts'), 'Space', '#done aria-keyshortcuts must be Space');
  assert.equal(elements.get('prev').getAttribute('aria-keyshortcuts'), 'A', '#prev aria-keyshortcuts must be A');
  assert.equal(elements.get('mode').getAttribute('aria-keyshortcuts'), 'S', '#mode aria-keyshortcuts must be S');
  assert.equal(elements.get('next').getAttribute('aria-keyshortcuts'), 'D', '#next aria-keyshortcuts must be D');
  assert.equal(elements.get('approveAll').getAttribute('aria-keyshortcuts'), 'F', '#approveAll aria-keyshortcuts must be F');
  assert.equal(elements.get('prevFile').getAttribute('aria-keyshortcuts'), 'Q', '#prevFile aria-keyshortcuts must be Q');
  assert.equal(elements.get('save').getAttribute('aria-keyshortcuts'), 'W', '#save aria-keyshortcuts must be W');
  assert.equal(elements.get('nextFile').getAttribute('aria-keyshortcuts'), 'E', '#nextFile aria-keyshortcuts must be E');
  assert.equal(elements.get('viewAudit').getAttribute('aria-keyshortcuts'), 'Z', '#viewAudit aria-keyshortcuts must be Z');
  assert.equal(elements.get('draft').getAttribute('aria-keyshortcuts'), 'X', '#draft aria-keyshortcuts must be X');
  assert.equal(elements.get('export').getAttribute('aria-keyshortcuts'), 'C', '#export aria-keyshortcuts must be C');
  assert.equal(elements.get('exportFolder').getAttribute('aria-keyshortcuts'), 'V', '#exportFolder aria-keyshortcuts must be V');

  // Track button trigger clicks
  const triggeredIds = [];
  ['prev', 'next', 'done', 'approveAll', 'save', 'prevFile', 'nextFile', 'viewAudit', 'draft', 'export', 'exportFolder', 'compareOutput', 'refreshQc'].forEach(id => {
    elements.get(id).onclick = () => triggeredIds.push(id);
  });

  // S toggles manual drawing mode
  assert.equal(vm.runInContext('manual', ctx), false, 'manual must initially be false');
  const resS1 = fireKey('KeyS', 's');
  assert.equal(resS1.prevented, true, 'KeyS must call preventDefault in workflow context');
  assert.equal(vm.runInContext('manual', ctx), true, 'KeyS must toggle manual mode to true');
  const resS2 = fireKey('KeyS', 's');
  assert.equal(resS2.prevented, true);
  assert.equal(vm.runInContext('manual', ctx), false, 'KeyS must toggle manual mode back to false');

  // Space -> #done
  fireKey('Space', ' ');
  assert.equal(triggeredIds.at(-1), 'done', 'Space must trigger #done');

  // A / ArrowLeft -> #prev
  fireKey('KeyA', 'a');
  assert.equal(triggeredIds.at(-1), 'prev', 'KeyA must trigger #prev');
  fireKey('ArrowLeft', 'ArrowLeft');
  assert.equal(triggeredIds.at(-1), 'prev', 'ArrowLeft must trigger #prev');

  // D / ArrowRight -> #next
  fireKey('KeyD', 'd');
  assert.equal(triggeredIds.at(-1), 'next', 'KeyD must trigger #next');
  fireKey('ArrowRight', 'ArrowRight');
  assert.equal(triggeredIds.at(-1), 'next', 'ArrowRight must trigger #next');

  // F -> #approveAll
  fireKey('KeyF', 'f');
  assert.equal(triggeredIds.at(-1), 'approveAll', 'KeyF must trigger #approveAll');

  // W -> #save
  fireKey('KeyW', 'w');
  assert.equal(triggeredIds.at(-1), 'save', 'KeyW must trigger #save');

  // Q/E -> #prevFile / #nextFile
  elements.get('prevFile').disabled = false;
  elements.get('nextFile').disabled = false;
  fireKey('KeyQ', 'q');
  assert.equal(triggeredIds.at(-1), 'prevFile', 'KeyQ must trigger #prevFile when enabled');
  fireKey('KeyE', 'e');
  assert.equal(triggeredIds.at(-1), 'nextFile', 'KeyE must trigger #nextFile when enabled');

  // Z -> #viewAudit, X -> #draft, C -> #export, V -> #exportFolder
  fireKey('KeyZ', 'z');
  assert.equal(triggeredIds.at(-1), 'viewAudit', 'KeyZ must trigger #viewAudit');
  fireKey('KeyX', 'x');
  assert.equal(triggeredIds.at(-1), 'draft', 'KeyX must trigger #draft');
  fireKey('KeyC', 'c');
  assert.equal(triggeredIds.at(-1), 'export', 'KeyC must trigger #export');
  fireKey('KeyV', 'v');
  assert.equal(triggeredIds.at(-1), 'exportFolder', 'KeyV must trigger #exportFolder');

  // R -> #compareOutput when #batchReview is visible; NOT triggered when hidden
  elements.get('batchReview').classList.add('hide');
  const countBeforeHiddenR = triggeredIds.length;
  fireKey('KeyR', 'r');
  assert.equal(triggeredIds.length, countBeforeHiddenR, 'KeyR must NOT trigger #compareOutput when #batchReview has .hide');
  elements.get('batchReview').classList.remove('hide');
  fireKey('KeyR', 'r');
  assert.equal(triggeredIds.at(-1), 'compareOutput', 'KeyR must trigger #compareOutput when #batchReview is visible');

  // Disabled and .hide buttons must NOT trigger
  elements.get('prevFile').disabled = true;
  const countBeforeDisabledQ = triggeredIds.length;
  fireKey('KeyQ', 'q');
  assert.equal(triggeredIds.length, countBeforeDisabledQ, 'KeyQ must NOT trigger #prevFile when disabled');

  elements.get('export').classList.add('hide');
  const countBeforeHiddenC = triggeredIds.length;
  fireKey('KeyC', 'c');
  assert.equal(triggeredIds.length, countBeforeHiddenC, 'KeyC must NOT trigger #export when element has .hide');
  elements.get('export').classList.remove('hide');

  // =========================================================================
  // 1.3 Context 'batch'
  // =========================================================================
  vm.runInContext("data = null; queueId = null; setMode('batch')", ctx);
  assert.equal(vm.runInContext('getShortcutContext()', ctx), 'batch', "getShortcutContext() must return 'batch' in batch mode without open review");

  assert.equal(elements.get('batchStart').getAttribute('aria-keyshortcuts'), 'Space', '#batchStart aria-keyshortcuts must be Space');
  assert.equal(elements.get('batchSelectAll').getAttribute('aria-keyshortcuts'), 'A', '#batchSelectAll aria-keyshortcuts must be A');
  assert.equal(elements.get('batchPause').getAttribute('aria-keyshortcuts'), 'S', '#batchPause aria-keyshortcuts must be S');
  assert.equal(elements.get('batchClearSelection').getAttribute('aria-keyshortcuts'), 'D', '#batchClearSelection aria-keyshortcuts must be D');
  assert.equal(elements.get('pickBatchFolder').getAttribute('aria-keyshortcuts'), 'Q', '#pickBatchFolder aria-keyshortcuts must be Q');
  assert.equal(elements.get('batchAdd').getAttribute('aria-keyshortcuts'), 'E', '#batchAdd aria-keyshortcuts must be E');

  const batchTriggered = [];
  ['batchStart', 'batchPause', 'batchSelectAll', 'batchClearSelection', 'pickBatchFolder', 'batchAdd'].forEach(id => {
    elements.get(id).onclick = () => batchTriggered.push(id);
  });

  fireKey('Space', ' ');
  assert.equal(batchTriggered.at(-1), 'batchStart', 'Space in batch context must trigger #batchStart');
  fireKey('KeyA', 'a');
  assert.equal(batchTriggered.at(-1), 'batchSelectAll', 'KeyA in batch context must trigger #batchSelectAll');
  fireKey('KeyS', 's');
  assert.equal(batchTriggered.at(-1), 'batchPause', 'KeyS in batch context must trigger #batchPause');
  fireKey('KeyD', 'd');
  assert.equal(batchTriggered.at(-1), 'batchClearSelection', 'KeyD in batch context must trigger #batchClearSelection');
  fireKey('KeyQ', 'q');
  assert.equal(batchTriggered.at(-1), 'pickBatchFolder', 'KeyQ in batch context must trigger #pickBatchFolder');
  fireKey('KeyE', 'e');
  assert.equal(batchTriggered.at(-1), 'batchAdd', 'KeyE in batch context must trigger #batchAdd');

  // =========================================================================
  // 1.4 Guards
  // =========================================================================
  vm.runInContext("data = { job_id: 'j1', revision: 1, pages: [{ page: 1, reviewed: false, manual_rects: [], proposals: [] }], watermarks_removed: [] }; setMode('local'); show()", ctx);
  const countBeforeGuards = triggeredIds.length;

  // Typing in INPUT must not trigger shortcuts
  const noteInput = elements.get('note');
  ctx.document.activeElement = noteInput;
  const typingResInput = fireKey('KeyA', 'a', { target: noteInput });
  assert.equal(typingResInput.prevented, false, 'typing KeyA in INPUT must not preventDefault');
  assert.equal(triggeredIds.length, countBeforeGuards, 'typing KeyA in INPUT must not trigger shortcut');

  // Typing in TEXTAREA must not trigger shortcuts
  const batchPathsArea = elements.get('batchPaths');
  ctx.document.activeElement = batchPathsArea;
  const typingResTextarea = fireKey('KeyA', 'a', { target: batchPathsArea });
  assert.equal(typingResTextarea.prevented, false, 'typing KeyA in TEXTAREA must not preventDefault');
  assert.equal(triggeredIds.length, countBeforeGuards, 'typing KeyA in TEXTAREA must not trigger shortcut');

  // Selecting in SELECT must not trigger shortcuts
  const filterSelect = elements.get('batchFilter');
  ctx.document.activeElement = filterSelect;
  const typingResSelect = fireKey('KeyA', 'a', { target: filterSelect });
  assert.equal(typingResSelect.prevented, false, 'KeyA in SELECT must not preventDefault');
  assert.equal(triggeredIds.length, countBeforeGuards, 'KeyA in SELECT must not trigger shortcut');

  // Ctrl+S inside input still saves and preventDefault
  const ctrlSRes = fireKey('KeyS', 's', { target: noteInput, ctrlKey: true });
  assert.equal(ctrlSRes.prevented, true, 'Ctrl+S in input must preventDefault');
  assert.equal(triggeredIds.at(-1), 'save', 'Ctrl+S in input must trigger #save');

  // Esc inside input calls blur() and preventDefault
  noteInput.blurred = false;
  const escInputRes = fireKey('Escape', 'Escape', { target: noteInput });
  assert.equal(escInputRes.prevented, true, 'Escape in input must preventDefault');
  assert.equal(noteInput.blurred, true, 'Escape inside input must call blur()');
  ctx.document.activeElement = null;

  // Esc turns off manual mode
  vm.runInContext('manual = true', ctx);
  const escManualRes = fireKey('Escape', 'Escape');
  assert.equal(escManualRes.prevented, true, 'Escape when manual is true must preventDefault');
  assert.equal(vm.runInContext('manual', ctx), false, 'Escape must turn off manual mode');

  // Esc closes #auditModal
  const auditModal = elements.get('auditModal');
  auditModal.classList.remove('hide');
  const escModalRes = fireKey('Escape', 'Escape');
  assert.equal(escModalRes.prevented, true, 'Escape when #auditModal is open must preventDefault');
  assert.equal(auditModal.classList.contains('hide'), true, 'Escape must add .hide to #auditModal');

  // isComposing (Unikey / EVKey) must be blocked
  const countBeforeIme = triggeredIds.length;
  fireKey('KeyW', 'ư', { isComposing: true });
  assert.equal(triggeredIds.length, countBeforeIme, 'isComposing === true must NOT trigger shortcut');

  // e.repeat must be blocked
  fireKey('Space', ' ', { repeat: true });
  assert.equal(triggeredIds.length, countBeforeIme, 'e.repeat === true must NOT trigger shortcut');

  // working === true must be blocked
  vm.runInContext('working = true', ctx);
  fireKey('Space', ' ');
  assert.equal(triggeredIds.length, countBeforeIme, 'shortcuts must NOT trigger when working === true');
  vm.runInContext('working = false', ctx);

  // =========================================================================
  // 1.5 Phản hồi thị giác
  // =========================================================================
  // .kbd-active class added and removed after 140ms timeout
  const modeBtn = elements.get('mode');
  modeBtn.classList.remove('kbd-active');
  const timeoutCountBefore = timeouts.length;
  fireKey('KeyS', 's');
  assert.equal(modeBtn.classList.contains('kbd-active'), true, 'pressed button must receive .kbd-active class');
  assert.ok(timeouts.length > timeoutCountBefore, 'visual flash must register a setTimeout');
  const flashTimeout = timeouts.at(-1);
  assert.equal(flashTimeout.delay, 140, '.kbd-active timeout must be 140ms');
  flashTimeout.fn();
  assert.equal(modeBtn.classList.contains('kbd-active'), false, '.kbd-active must be removed after 140ms timeout');

  // Backquote (`) toggles .hide of #shortcutPad
  const pad = elements.get('shortcutPad');
  pad.classList.add('hide');
  const bqRes1 = fireKey('Backquote', '`');
  assert.equal(bqRes1.prevented, true, 'Backquote must preventDefault');
  assert.equal(pad.classList.contains('hide'), false, 'Backquote must toggle .hide off on #shortcutPad');
  const bqRes2 = fireKey('Backquote', '`');
  assert.equal(bqRes2.prevented, true);
  assert.equal(pad.classList.contains('hide'), true, 'Backquote must toggle .hide on on #shortcutPad');

  // =========================================================================
  // 1.6 Offline Blocking Modal, LocalStorage Snapshot & Auto-Restore Sync
  // =========================================================================
  vm.runInContext(`
    $('localPath').value = 'E:\\\\CaBenh\\\\Folder_01';
    $('folderDestination').value = 'E:\\\\KetQua\\\\Folder_01';
    $('sid').value = 'HMU_TEST_99';
    data = {
      job_id: 'job_2',
      revision: 3,
      ocr_pages_count: 1,
      watermarks_removed: [],
      pages: [
        { page: 1, width: 100, height: 100, reviewed: true, manual_rects: [], proposals: [] },
        { page: 2, width: 100, height: 100, reviewed: false, manual_rects: [[5, 5, 50, 50]], note: 'Ghi chu trang 2', proposals: [{ id: 'p1', selected: true, rects: [[1,1,10,10]] }] }
      ]
    };
    files = [
      { index: 1, name: 'f1.pdf', job_id: 'job_1', pages: 2, reviewed: 2 },
      { index: 2, name: 'f2.pdf', job_id: 'job_2', pages: 2, reviewed: 1 }
    ];
    queueId = null;
    pn = 1;
    dirty = true;
  `, ctx);

  // Simulate terminal disconnect during pollBatch / refreshBatch
  const origFetch = ctx.fetch;
  ctx.fetch = async () => { throw new Error('Failed to fetch'); };
  await vm.runInContext('refreshBatch()', ctx);
  assert.equal(elements.get('offlineModal').classList.contains('hide'), false, '#offlineModal must be visible when terminal disconnects');

  // Click [Lưu phiên làm việc] (#saveOfflineSession)
  await elements.get('saveOfflineSession').click();
  const rawBackup = vm.runInContext('localStorage.getItem("hmu_session_backup_v1")', ctx);
  assert.ok(rawBackup, 'Clicking #saveOfflineSession must write hmu_session_backup_v1 to localStorage');
  const parsedBackup = JSON.parse(rawBackup);
  assert.equal(parsedBackup.selected_path, 'E:\\CaBenh\\Folder_01');
  assert.equal(parsedBackup.active_page, 2);
  assert.equal(parsedBackup.job_id, 'job_2');
  assert.deepEqual(parsedBackup.page_patch.manual_rects, [[5, 5, 50, 50]]);

  // Simulate server restart & reconnect with a new token
  const syncedRequests = [];
  ctx.fetch = async (url, opts = {}) => {
    syncedRequests.push({ url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null });
    if (url === '/batch/status') return { ok: true, json: async () => ({ jobs: [], coordinator: {} }) };
    if (url === '/state') return {
      ok: true,
      json: async () => ({
        token: 'new_token_after_restart',
        review: {
          job_id: 'job_2',
          revision: 3,
          ocr_pages_count: 1,
          watermarks_removed: [],
          pages: [
            { page: 1, width: 100, height: 100, reviewed: true, manual_rects: [], proposals: [] },
            { page: 2, width: 100, height: 100, reviewed: false, manual_rects: [], note: '', proposals: [{ id: 'p1', selected: false, rects: [[1,1,10,10]] }] }
          ]
        },
        files: [
          { index: 1, name: 'f1.pdf', job_id: 'job_1', pages: 2, reviewed: 2 },
          { index: 2, name: 'f2.pdf', job_id: 'job_2', pages: 2, reviewed: 1 }
        ],
        session: { selected_path: 'E:\\CaBenh\\Folder_01', destination: 'E:\\KetQua\\Folder_01', study_id: 'HMU_TEST_99', active_file_index: 2, active_page: 2 }
      })
    };
    if (url === '/save_page') return { ok: true, json: async () => ({ saved: true, revision: 4 }) };
    if (url === '/session/save') return { ok: true, json: async () => ({ saved: true, session: {} }) };
    return origFetch(url, opts);
  };
  await vm.runInContext('refreshBatch()', ctx);
  assert.equal(elements.get('offlineModal').classList.contains('hide'), true, '#offlineModal must hide after server reconnects');
  assert.ok(syncedRequests.some(r => r.url === '/save_page' && r.body.page === 2), 'Reconnecting must auto-sync saved page_patch to /save_page');
  assert.equal(vm.runInContext('pn', ctx), 1, 'Restored session must stay on page 2 (pn === 1)');
  assert.equal(vm.runInContext('localStorage.getItem("hmu_session_backup_v1")', ctx), null, 'Backup must be cleared after successful sync');

  console.log('UI Left-Hand Shortcuts Test: ALL CHECKS PASSED');
})().catch(e => {
  console.error(e);
  process.exitCode = 1;
});
