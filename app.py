"""Single-user localhost review application v2.0; no cloud services."""
import argparse, json, re, secrets, threading, time, unicodedata, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from delivery import (
    export_reviewed_folder, init_desktop_workspace, get_workspace_config,
    open_in_explorer, resolve_desktop_path, preclone_patient_folders
)
from error_pipeline import record_error_event, get_error_report
import fitz
from engine import (
    prepare, export, save_json, validate_review, approve_all_pages,
    generate_audit_markdown, prepare_case, export_case, extract_case_seeds, _strip_accents
)

_WORKSPACE_ROOTS = [
    Path(r"D:\Workspaces\10TB_User3"),
    Path(r"D:\Workspaces\10TB_User2"),
    Path(r"D:\Workspaces\Database (Test-Case1)"),
    Path(r"D:\Workspaces\Database"),
    Path(r"D:\Workspaces\Database (Root)"),
]

def _find_original_in_workspace(filename: str) -> Path | None:
    if not filename:
        return None
    fname_nfc = unicodedata.normalize('NFC', filename.strip())
    stem_nfc = Path(fname_nfc).stem
    fold_name = _strip_accents(fname_nfc.lower())
    m_id = re.match(r'^(\d{8,12}|BA\d{6,12})\b', fname_nfc, re.I)
    lead_id = m_id.group(1).lower() if m_id else None

    # 1. Fast check in common BVQT / DHYHN / BV71 pdf directories
    fast_Parents = []
    for wroot in _WORKSPACE_ROOTS:
        if not wroot.exists():
            continue
        for sub in (
            wroot / "HH" / "pdf",
            wroot / "3.BVQT" / "HH" / "pdf",
            wroot / "1.DHYHN",
            wroot / "2.BV71",
        ):
            if sub.is_dir():
                fast_Parents.append(sub)
        for child in wroot.iterdir():
            if child.is_dir() and (child / "pdf").is_dir():
                fast_Parents.append(child / "pdf")

    for pdir in fast_Parents:
        direct = pdir / stem_nfc / fname_nfc
        if direct.is_file():
            return direct
        direct2 = pdir / fname_nfc
        if direct2.is_file():
            return direct2
        for item in pdir.iterdir():
            item_fold = _strip_accents(item.name.lower())
            if item_fold == fold_name and item.is_file():
                return item
            if lead_id and item_fold.startswith(lead_id):
                if item.is_dir():
                    pdfs = list(item.glob("*.pdf"))
                    if pdfs:
                        return pdfs[0]
                elif item.is_file() and item.suffix.lower() == ".pdf":
                    return item

    # 2. Fallback rglob in Database (Test-Case1)
    db_root = Path(r"D:\Workspaces\Database (Test-Case1)")
    if db_root.exists():
        for match in db_root.rglob(fname_nfc):
            if match.is_file():
                return match
    return None

def _resolve_local_path(raw_path: str) -> Path:
    s = raw_path.strip().strip('"').strip("'").rstrip('\\/')
    if not s:
        raise ValueError('Vui lòng nhập đường dẫn tệp PDF hoặc thư mục ca bệnh')
    for form in ('NFC', 'NFD'):
        cand = Path(unicodedata.normalize(form, s))
        if cand.exists():
            return cand.resolve()

    p = Path(unicodedata.normalize('NFC', s))
    parent = p.parent
    if not parent.exists() and parent != p:
        try:
            parent = _resolve_local_path(str(parent))
        except Exception:
            parent = None

    if parent and parent.is_dir():
        target_name = p.name
        target_fold = _strip_accents(target_name.lower())
        m_id = re.match(r'^(\d{8,12}|BA\d{6,12})\b', target_name, re.I)
        lead_id = m_id.group(1).lower() if m_id else None
        want_pdf = target_name.lower().endswith('.pdf')
        id_matches = []
        for child in parent.iterdir():
            c_fold = _strip_accents(child.name.lower())
            if c_fold == target_fold:
                return child.resolve()
            if not want_pdf and c_fold == target_fold + '.pdf':
                id_matches.insert(0, child.resolve())
            elif lead_id and c_fold.startswith(lead_id):
                if (want_pdf and child.is_file() and child.suffix.lower() == '.pdf') or (not want_pdf and child.is_dir()):
                    id_matches.insert(0, child.resolve())
                else:
                    id_matches.append(child.resolve())
        if id_matches:
            return id_matches[0]

    found = _find_original_in_workspace(p.name)
    if found:
        if not p.name.lower().endswith('.pdf') and found.parent.name != 'pdf':
            return found.parent.resolve()
        return found.resolve()
    raise ValueError(f'Đường dẫn không tồn tại: {raw_path}')


def _pick_folder_dialog(initial_dir: str | None = None) -> str | None:
    import os, shutil, subprocess, sys
    start_dir = None
    if initial_dir and isinstance(initial_dir, str) and initial_dir.strip():
        cand = Path(initial_dir.strip().strip('"').strip("'"))
        if cand.is_file():
            start_dir = str(cand.parent)
        elif cand.is_dir():
            start_dir = str(cand)
        elif cand.parent.is_dir():
            start_dir = str(cand.parent)
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        try:
            root.attributes('-topmost', True)
        except Exception:
            pass
        try:
            chosen = filedialog.askdirectory(title='Chọn thư mục', initialdir=start_dir or None)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        if isinstance(chosen, str) and chosen.strip():
            return str(Path(chosen.strip()))
        return None
    except Exception:
        pass
    if sys.platform == 'win32' or os.name == 'nt':
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = 'Chọn thư mục'; "
        )
        if start_dir:
            escaped = start_dir.replace("'", "''")
            ps_script += f"$d.SelectedPath = '{escaped}'; "
        ps_script += "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-STA', '-Command', ps_script],
            capture_output=True, text=True, timeout=300
        )
        out = (proc.stdout or '').strip()
        return str(Path(out)) if proc.returncode == 0 and out else None
    if shutil.which('zenity'):
        cmd = ['zenity', '--file-selection', '--directory', '--title=Chọn thư mục']
        if start_dir:
            cmd.append(f'--filename={start_dir.rstrip("/")}/')
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = (proc.stdout or '').strip()
        return str(Path(out)) if proc.returncode == 0 and out else None
    if shutil.which('kdialog'):
        cmd = ['kdialog', '--getexistingdirectory', start_dir or str(Path.home())]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = (proc.stdout or '').strip()
        return str(Path(out)) if proc.returncode == 0 and out else None
    raise RuntimeError('Không mở được hộp thoại chọn thư mục trên hệ thống này')


class Conflict(ValueError):
    pass


def create_server(root: Path, active: Path | None = None, port: int = 0):
    """Create a loopback-only server. The caller owns serve/shutdown lifecycle."""
    import copy, math, batch, time
    from contextlib import ExitStack
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    active = Path(active).resolve() if active else None
    case_root = active.parent if active and (active.parent / 'case_manifest.json').exists() else None
    token = secrets.token_hex(24)
    lock = threading.RLock()
    validated_jobs = {}
    progress = {'status': 'idle', 'task_id': None, 'progress': '', 'result': None, 'error': None}
    batch_db=root/'batch'/'queue.sqlite3';active_queue_id=None
    session_path=root/'last_session.json'

    def save_session():
        try:
            save_json(session_path,{'active':str(active) if active else None,'case_root':str(case_root) if case_root else None,'active_queue_id':active_queue_id})
        except OSError:
            pass

    def batch_status():
        rows=batch.list_jobs(batch_db,details=False);items=[]
        for row in rows:
            qc=row['result'].get('verification',{})
            item={k:row[k] for k in ('id','source_name','pages','state','error','duplicate_of','revision')}
            item.update(qc_status=qc.get('status'),warnings=qc.get('finding_count',0)+qc.get('unreadable_count',0),
                        seconds=row['result'].get('machine_seconds'),download=bool(row['result'].get('output')))
            items.append(item)
        status_path=batch_db.parent/'coordinator_status.json'
        status=json.loads(status_path.read_text(encoding='utf8')) if status_path.exists() else {}
        from batch_runtime import process_alive
        status['running']=bool(status.get('pid') and time.time()-status.get('heartbeat',0)<30 and process_alive(status['pid']))
        return dict(jobs=items,coordinator=status)

    def batch_post(path,req):
        nonlocal active,case_root,active_queue_id
        if path=='/batch/enqueue':
            paths=req.get('paths')
            if not isinstance(paths,list) or not 1<=len(paths)<=2000 or any(not isinstance(p,str) for p in paths):raise ValueError('Nhập danh sách đường dẫn PDF hoặc thư mục')
            raw_input_paths = [Path(p.strip().strip('"')) for p in paths]
            sources=[]
            for p in raw_input_paths:sources.extend(batch.discover_sources(p))

            ws_cfg = get_workspace_config(root)
            dest_root = None
            data_root = None
            if req.get('destination'):
                dest_root = Path(str(req['destination']).strip().strip('"'))
            elif ws_cfg and ws_cfg.get('data_deidentified'):
                dest_root = Path(ws_cfg['data_deidentified'])
                if ws_cfg.get('data_root'):
                    data_root = Path(ws_cfg['data_root'])

            cloned_folders = []
            target_folders = {}
            if dest_root:
                preclone_res = preclone_patient_folders(raw_input_paths, dest_root, data_root=data_root)
                cloned_folders = preclone_res.get('cloned_folders', [])
                target_folders = preclone_res.get('mappings', {})

            ids = batch.enqueue(batch_db, sources, target_folders=target_folders)
            return {'ids': ids, 'cloned_folders': cloned_folders}
        if path=='/batch/pause':batch.pause_queue(batch_db);return {'paused':True}
        if path=='/batch/resume':
            batch.resume_queue(batch_db)
            if not batch_status()['coordinator']['running']:batch.start_background(batch_db)
            return {'started':True}
        if path=='/batch/delete':
            result=batch.delete_jobs(batch_db,req.get('queue_ids'))
            affected=set(result['deleted'])|{r['id'] for r in batch.list_jobs(batch_db,details=False) if r['state']=='DELETING'}
            result['active_deleted']=active_queue_id is not None and active_queue_id in affected
            if result['active_deleted']:
                active=None;case_root=None;active_queue_id=None;validated_jobs.clear();save_session()
            return result
        if path=='/batch/release_folder':
            return batch.release_folder(batch_db,req.get('paths'),req.get('destination'))
        ident=req.get('queue_id');row=batch.get_job(batch_db,ident)
        if path=='/batch/open_job':
            with batch.review_lock(batch_db,ident) as row:
                active=Path(row['job_dir'])/'review';case_root=None;active_queue_id=ident
                validated_jobs.clear();save_session();return state()
        if path=='/batch/retry':batch.retry_job(batch_db,ident);return {'queued':True}
        if path=='/batch/cancel':batch.cancel_job(batch_db,ident);return {'cancelled':True}
        if path=='/batch/reprocess':
            batch.reprocess_job(batch_db,ident,expected_revision=req.get('revision'))
            batch.resume_queue(batch_db)
            if not batch_status()['coordinator']['running']:batch.start_background(batch_db)
            return {'queued':True}
        if path=='/batch/resolve_finding':
            batch.resolve_finding(batch_db,ident,expected_revision=req.get('revision'),finding_id=req.get('finding_id'),
                reason=req.get('reason'),reviewer=req.get('reviewer'))
            return {'resolved':True}
        if path=='/batch/release':return batch.release_job(batch_db,ident,expected_revision=req.get('revision'),destination=batch_db.parent/'delivered')
        raise ValueError('Unknown batch action')

    def read_review(job):
        import engine
        work = job / 'working_private.pdf'
        stat = work.stat()
        fingerprint = (stat.st_size, stat.st_mtime_ns)
        if hasattr(engine, 'ensure_job') and validated_jobs.get(job) != fingerprint:
            d = engine.ensure_job(job)
            validated_jobs[job] = fingerprint
            return d
        d = json.loads((job / 'review.json').read_text(encoding='utf-8'))
        if d.get('policy') != engine.POLICY:
            raise ValueError('Redaction policy changed; prepare a new job from the original PDF')
        if 'job_id' not in d:
            d.update(schema_version=2, job_id=secrets.token_hex(16), revision=0)
            save_json(job / 'review.json', d)
        return d

    if active is None and session_path.exists():
        try:
            sess = json.loads(session_path.read_text(encoding='utf-8'))
            cand_active = Path(sess['active']).resolve() if sess.get('active') else None
            cand_case = Path(sess['case_root']).resolve() if sess.get('case_root') else None
            cand_queue = sess.get('active_queue_id')
            if cand_active and cand_active.is_relative_to(root) and (cand_active / 'review.json').exists() and (cand_active / 'working_private.pdf').exists():
                read_review(cand_active)
                if cand_case:
                    if cand_case.is_relative_to(root) and (cand_case / 'case_manifest.json').exists() and cand_active.is_relative_to(cand_case):
                        active = cand_active
                        case_root = cand_case
                elif cand_queue:
                    row = batch.get_job(batch_db, cand_queue)
                    if row['state'] in {'NEEDS_REVIEW', 'READY'} and (Path(row['job_dir']) / 'review').resolve() == cand_active:
                        active = cand_active
                        active_queue_id = cand_queue
                else:
                    active = cand_active
        except Exception:
            active = None; case_root = None; active_queue_id = None
    elif active is not None:
        save_session()

    def find_reusable_open_path(target: Path):
        import engine
        resolved_target = target.resolve()
        if resolved_target.is_dir():
            pdfs = sorted(resolved_target.glob('*.pdf'))
            if not pdfs:
                return None
            candidates = sorted(root.glob('*/case/case_manifest.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
            if case_root and (case_root / 'case_manifest.json') in candidates:
                candidates.remove(case_root / 'case_manifest.json')
                candidates.insert(0, case_root / 'case_manifest.json')
            for mp in candidates:
                try:
                    cand_case = mp.parent.resolve()
                    manifest = json.loads(mp.read_text(encoding='utf-8'))
                    if Path(manifest.get('source_path', '')).resolve() != resolved_target:
                        continue
                    files_list = manifest.get('files', [])
                    if [f.get('source_name') for f in files_list] != [p.name for p in pdfs]:
                        continue
                    valid = True
                    for item, pdf_file in zip(files_list, pdfs):
                        sub_job = (cand_case / item['sub_job']).resolve()
                        if not sub_job.is_relative_to(cand_case):
                            valid = False; break
                        sub_rev = read_review(sub_job)
                        if sub_rev.get('source_sha256') != engine.sha(pdf_file):
                            valid = False; break
                    if not valid:
                        continue
                    if case_root == cand_case and active and active.is_relative_to(cand_case):
                        chosen = active
                    else:
                        active_rel = manifest.get('active_sub_job') or files_list[0]['sub_job']
                        chosen = (cand_case / active_rel).resolve()
                        if not chosen.is_relative_to(cand_case) or not (chosen / 'review.json').exists():
                            chosen = (cand_case / files_list[0]['sub_job']).resolve()
                    return cand_case, chosen
                except Exception:
                    continue
            return None
        candidates = sorted(root.glob('*/review/review.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for rp in candidates:
            try:
                cand_job = rp.parent.resolve()
                d = read_review(cand_job)
                if d.get('source_path') and Path(d['source_path']).resolve() == resolved_target:
                    if d.get('source_sha256') == engine.sha(resolved_target):
                        return None, cand_job
            except Exception:
                continue
        return None

    def state():
        d = read_review(active) if active else None
        files = []
        if case_root:
            manifest = json.loads((case_root / 'case_manifest.json').read_text(encoding='utf-8'))
            for item in manifest['files']:
                job = (case_root / item['sub_job']).resolve()
                if not job.is_relative_to(case_root):
                    raise ValueError('Invalid sub-job path')
                sub = read_review(job)
                files.append({'index': item['index'], 'name': item['source_name'], 'job_id': sub['job_id'],
                              'reviewed': sum(bool(p['reviewed']) for p in sub['pages']), 'pages': len(sub['pages'])})
        return {'review': d, 'files': files, 'batch_case': bool(case_root),'queue_id':active_queue_id, 'workspace': get_workspace_config(root)}

    def check_identity(req):
        if not active:
            raise Conflict('Không có công việc đang mở')
        d = read_review(active)
        if active_queue_id:
            row=batch.get_job(batch_db,active_queue_id)
            if row['state'] not in {'NEEDS_REVIEW','READY'} or Path(row['job_dir'])/'review'!=active:
                raise Conflict('File đang được xử lý lại; hãy mở lại từ hàng đợi khi hoàn tất')
        if type(req.get('revision')) is not int or req.get('job_id') != d['job_id'] or req.get('revision') != d['revision']:
            raise Conflict('Công việc hoặc phiên duyệt đã thay đổi. Hãy tải lại trạng thái trước khi lưu.')
        return d

    def set_progress(msg):
        with lock: progress['progress'] = msg

    def run_task(async_mode, work, send, stage='EXPORT', source_file=None, job_id=None):
        task_id = secrets.token_hex(16)
        progress.update(status='running', task_id=task_id, progress='', result=None, error=None, error_detail=None)
        def execute():
            try:
                result = work()
                with lock: progress.update(status='done', result=result, progress='')
                return result
            except Exception as exc:
                err = record_error_event(root, exc, stage=stage, source_file=source_file, job_id=job_id)
                with lock: progress.update(status='error', error=str(exc), error_detail=err, progress='')
                if not async_mode: raise
        if async_mode:
            threading.Thread(target=execute, daemon=True).start()
            send(202, {'async': True, 'task_id': task_id})
        else:
            # The running-task guard blocks mutations; workers must be able to report progress.
            lock.release()
            try: result=execute()
            finally: lock.acquire()
            send(200,result)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, code, data, ctype='application/json'):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8') if ctype == 'application/json' else data
            self.send_response(code); self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def host_ok(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        def do_GET(self):
            if not self.host_ok(): self.send(403, {'error':'Forbidden'}); return
            u = urllib.parse.urlsplit(self.path); q = urllib.parse.parse_qs(u.query); path = u.path
            try:
                with lock:
                    if path == '/':
                        self.send(200, Path(__file__).with_name('review.html').read_bytes(), 'text/html; charset=utf-8'); return
                    if path in {'/ui/review.js', '/ui/review.css'}:
                        asset = Path(__file__).parent / path.lstrip('/')
                        mime = 'text/javascript' if asset.suffix == '.js' else 'text/css'
                        self.send(200, asset.read_bytes(), mime + '; charset=utf-8'); return
                    if path == '/progress':
                        if q.get('task_id', [''])[0] != progress['task_id']: raise Conflict('Unknown or expired task')
                        self.send(200, dict(progress)); return
                    if path in {'/errors/report', '/errors/report.json'}:
                        self.send(200, get_error_report(root)); return
                    if path == '/state': self.send(200, {'token':token, **state()}); return
                    if path == '/workspace/state': self.send(200, get_workspace_config(root) or {}); return
                    if path == '/workspace/open_explorer':
                        ws_cfg = get_workspace_config(root)
                        if not ws_cfg: raise ValueError('Chưa khởi tạo workspace')
                        target_key = q.get('target', ['workspace'])[0]
                        t_path = Path(ws_cfg['data_root']) if target_key == 'data_root' else (Path(ws_cfg['data_deidentified']) if target_key == 'data_deidentified' else Path(ws_cfg['workspace_dir']))
                        open_in_explorer(t_path)
                        self.send(200, {'status': 'ok', 'opened': str(t_path)}); return
                    if path == '/batch/status':self.send(200,batch_status());return
                    if path in {'/batch/qc','/batch/pdf','/batch/preview'}:
                        row=batch.get_job(batch_db,q.get('queue_id',[''])[0])
                        with batch.review_lock(batch_db,row['id']):
                            review,qc,pdf=batch.current_verification(row,int(q.get('revision',['-1'])[0]))
                            if path=='/batch/qc':
                                issues,_,_=batch.review_issues(row,qc)
                                released=row['result'].get('release',{}) if row['state']=='READY' else {}
                                filename=Path(released['output']).name if released.get('output') else pdf.name
                                self.send(200,dict(issues=issues,status=qc['status'],pages_checked=qc['pages_checked'],pages_expected=qc['pages_expected'],filename=filename));return
                            if path=='/batch/pdf':self.send(200,pdf.read_bytes(),'application/pdf');return
                            import fitz
                            pn=int(q.get('page',['0'])[0])
                            with fitz.open(pdf) as doc:
                                if not 1<=pn<=len(doc):raise ValueError('Invalid page')
                                self.send(200,doc[pn-1].get_pixmap(dpi=120,alpha=False).tobytes('png'),'image/png');return
                    if not active: self.send(404, {'error':'No active job'}); return
                    d = read_review(active)
                    if q.get('job_id', [''])[0] != d['job_id']: raise Conflict('Job changed; reload state')
                    if path == '/audit':
                        if progress['status']=='running': raise Conflict('Đang xử lý tác vụ; đợi hoàn tất trước khi mở audit')
                        if q.get('revision', [''])[0] != str(d['revision']): raise Conflict('Review changed')
                        audit = active / 'AUDIT_SUMMARY.md'
                        stamp = active / 'audit_revision.txt'
                        if not audit.exists() or not stamp.exists() or stamp.read_text() != str(d['revision']):
                            generate_audit_markdown(active, d); stamp.write_text(str(d['revision']))
                        self.send(200, {'markdown':audit.read_text(encoding='utf-8'), 'revision':d['revision']}); return
                    if path.startswith('/page/'):
                        n=path[6:]
                        if not n.isdigit() or not 1<=int(n)<=len(d['pages']): raise ValueError('Invalid page')
                        self.send(200, (active/'pages'/f'{int(n)}.png').read_bytes(), 'image/png'); return
                    if path == '/download':
                        owner = case_root if q.get('scope',['file'])[0]=='case' and case_root else active
                        pointer=json.loads((owner/'last_export.json').read_text(encoding='utf-8'))
                        generation=(owner/'exports'/pointer['export_id']).resolve()
                        if not generation.is_relative_to((owner/'exports').resolve()): raise ValueError('Invalid export')
                        index=int(q.get('file_index',['1'])[0])-1
                        if not 0<=index<len(pointer['files']): raise ValueError('Invalid output index')
                        filename=pointer['files'][index]['pdf']; out=(generation/filename).resolve()
                        if out.parent!=generation: raise ValueError('Invalid output path')
                        self.send(200, out.read_bytes(),'application/pdf'); return
                    self.send(404, {'error':'Not found'})
            except Conflict as exc:
                err = record_error_event(root, exc, stage='CONFLICT', http_path=path)
                self.send(409, {'error':str(exc), 'code':'CONFLICT', 'error_detail': err})
            except Exception as exc:
                err = record_error_event(root, exc, stage='HTTP_API', http_path=path)
                self.send(400, {'error':str(exc), 'error_detail': err})
        def do_POST(self):
            nonlocal active, case_root, active_queue_id
            if not self.host_ok() or self.headers.get('X-HMU-Token') != token:
                # Closing a Windows socket with unread bytes can reset the 403 response.
                try:
                    rejected_size=int(self.headers.get('Content-Length','0'))
                    if 0<rejected_size<=65536:
                        self.connection.settimeout(1);self.rfile.read(rejected_size)
                except (ValueError,OSError):pass
                self.send(403, {'error':'Forbidden'}); return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=200*1024*1024: raise ValueError('Invalid request size')
                body=self.rfile.read(size); path=urllib.parse.urlsplit(self.path).path
                import ntpath
                original_name=ntpath.basename(urllib.parse.unquote(self.headers.get('X-Original-Filename','')))
                with lock, ExitStack() as operations:
                    if path == '/pick_folder':
                        req = json.loads(body) if body else {}
                        initial_dir = req.get('initial_dir') if isinstance(req, dict) else None
                        lock.release()
                        try:
                            chosen = _pick_folder_dialog(initial_dir)
                        finally:
                            lock.acquire()
                        if chosen:
                            self.send(200, {'path': chosen})
                        else:
                            self.send(200, {'path': None, 'cancelled': True})
                        return
                    if path == '/workspace/init':
                        req = json.loads(body) if body else {}
                        ws_name = req.get('workspace_name', '')
                        d_base = req.get('desktop_base')
                        cfg = init_desktop_workspace(ws_name, internal_root=root, desktop_base=d_base)
                        self.send(200, cfg); return
                    if path == '/workspace/open_explorer':
                        req = json.loads(body) if body else {}
                        ws_cfg = get_workspace_config(root)
                        if not ws_cfg: raise ValueError('Chưa khởi tạo workspace')
                        target_key = req.get('target', 'workspace')
                        t_path = Path(ws_cfg['data_root']) if target_key == 'data_root' else (Path(ws_cfg['data_deidentified']) if target_key == 'data_deidentified' else Path(ws_cfg['workspace_dir']))
                        open_in_explorer(t_path)
                        self.send(200, {'status': 'ok', 'opened': str(t_path)}); return
                    if path.startswith('/batch/'):
                        if path=='/batch/open_job' and progress['status']=='running':raise Conflict('Đợi thao tác hiện tại hoàn tất trước khi chuyển file')
                        self.send(200,batch_post(path,json.loads(body)));return
                    if progress['status']=='running': raise Conflict('Đang xử lý tác vụ. Hãy đợi hoàn tất.')
                    if path in {'/upload','/open_path','/export','/export_folder'} and batch_status()['coordinator'].get('active',0):
                        raise Conflict('Máy đang chạy hàng đợi. Thêm file vào hàng đợi hoặc tạm dừng và đợi file đang chạy xong; vẫn có thể duyệt file khác.')
                    async_mode=self.headers.get('X-HMU-Async')=='1'
                    if path in {'/upload','/open_path'}:
                        req={} if path=='/upload' else json.loads(body)
                        sid=self.headers.get('X-Study-ID','HMU_CASE_0001') if path=='/upload' else str(req.get('study_id','HMU_CASE_0001'))
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',sid): raise ValueError('Invalid research ID')
                        target=None if path=='/upload' else _resolve_local_path(str(req.get('path','')))
                        folder=None
                        if path=='/upload':
                            folder=root/(sid+'_'+secrets.token_hex(8));folder.mkdir(mode=0o700)
                            target=folder/'source_private.pdf';target.write_bytes(body)
                        def work_open():
                            nonlocal active,case_root,active_queue_id,folder
                            cloned_folders = []
                            target_mapping = {}
                            if path == '/open_path' and target:
                                ws_cfg = get_workspace_config(root)
                                dest_root = None
                                data_root = None
                                if req.get('destination'):
                                    dest_root = Path(str(req['destination']).strip().strip('"'))
                                elif ws_cfg and ws_cfg.get('data_deidentified'):
                                    dest_root = Path(ws_cfg['data_deidentified'])
                                    if ws_cfg.get('data_root'):
                                        data_root = Path(ws_cfg['data_root'])
                                if dest_root:
                                    pc_res = preclone_patient_folders([target], dest_root, data_root=data_root)
                                    cloned_folders = pc_res.get('cloned_folders', [])
                                    target_mapping = pc_res.get('mappings', {})

                            reused=find_reusable_open_path(target) if path=='/open_path' and not req.get('force_reprepare') else None
                            if reused:
                                new_case,new_active=reused
                            else:
                                if folder is None:
                                    folder=root/(sid+'_'+secrets.token_hex(8));folder.mkdir(mode=0o700)
                                if target.is_dir():
                                    manifest=prepare_case(target,folder/'case',study_id=sid,progress_cb=set_progress)
                                    new_case=folder/'case';new_active=new_case/manifest['files'][0]['sub_job']
                                else:
                                    new_case=None;new_active=folder/'review'
                                    external=None
                                    if path=='/upload' and original_name:
                                        original=_find_original_in_workspace(original_name)
                                        if original:external=extract_case_seeds(original)
                                    prepared=prepare(target,new_active,sid,external_seeds=external,progress_cb=set_progress,source_name=original_name if path=='/upload' else None)
                                    if path=='/open_path':
                                        prepared['source_path']=str(target.resolve())
                                        if target_mapping.get(str(target.resolve())):
                                            prepared['target_folder']=target_mapping[str(target.resolve())]
                                        save_json(new_active/'review.json',prepared)
                                    elif path=='/upload' and original_name.lower().endswith('.pdf'):
                                        prepared['original_name']=original_name
                                        save_json(new_active/'review.json',prepared)
                            if new_case and (new_case / 'case_manifest.json').is_file():
                                mf_path = new_case / 'case_manifest.json'
                                try:
                                    mf_data = json.loads(mf_path.read_text(encoding='utf-8'))
                                    for f in mf_data.get('files', []):
                                        full_f = str((target / f['source_name']).resolve()) if target.is_dir() else str(target.resolve())
                                        if full_f in target_mapping:
                                            f['target_folder'] = target_mapping[full_f]
                                    if cloned_folders:
                                        mf_data['target_folder'] = cloned_folders[0]
                                    elif target_mapping:
                                        mf_data['target_folder'] = next(iter(target_mapping.values()))
                                    save_json(mf_path, mf_data)
                                except Exception:
                                    pass
                            with lock:
                                active=new_active;case_root=new_case;active_queue_id=None;validated_jobs.clear();save_session()
                                cur_state = state()
                                cur_state['cloned_folders'] = cloned_folders
                                return cur_state
                        run_task(async_mode,work_open,self.send,stage='PREPARE',source_file=original_name or (target.name if target else None));return
                    if active_queue_id:operations.enter_context(batch.review_lock(batch_db,active_queue_id))
                    current=check_identity(json.loads(body));req=json.loads(body);job=active;captured_case=case_root
                    if path=='/select_file':
                        if not case_root: raise ValueError('Not a case')
                        manifest=json.loads((case_root/'case_manifest.json').read_text(encoding='utf-8'))
                        items=[x for x in manifest['files'] if x['index']==req.get('file_index')]
                        if len(items)!=1: raise ValueError('Invalid file index')
                        selected=(case_root/items[0]['sub_job']).resolve()
                        if not selected.is_relative_to(case_root): raise ValueError('Invalid sub-job')
                        manifest['active_sub_job']=items[0]['sub_job']
                        save_json(case_root/'case_manifest.json',manifest)
                        active=selected;save_session();self.send(200,state());return
                    if path in {'/save','/save_page'}:
                        updated=copy.deepcopy(current)
                        pages=req.get('pages') if path=='/save' else [req]
                        if path=='/save' and (not isinstance(pages,list) or len(pages)!=len(current['pages'])): raise ValueError('Page count mismatch')
                        if path=='/save' and [x['page'] for x in pages]!=[x['page'] for x in current['pages']]: raise ValueError('Page order mismatch')
                        for src in pages:
                            n=src['page']
                            if type(n)!=int or not 1<=n<=len(updated['pages']): raise ValueError('Invalid page')
                            dst=updated['pages'][n-1]
                            selections=src.get('selections',src.get('proposals',[]))
                            if len(selections)!=len(dst['proposals']) or [x['id'] for x in selections]!=[x['id'] for x in dst['proposals']]: raise ValueError('Finding identity differs')
                            rects=src['manual_rects']
                            if not isinstance(rects,list): raise ValueError('Invalid rectangles')
                            for r in rects:
                                if len(r)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in r):raise ValueError('Invalid rectangle')
                                if not 0<=r[0]<r[2]<=dst['width'] or not 0<=r[1]<r[3]<=dst['height']:raise ValueError('Rectangle outside page')
                            if type(src['reviewed'])!=bool: raise ValueError('Invalid reviewed value')
                            dst.update(reviewed=src['reviewed'],manual_rects=rects,note=str(src.get('note','')))
                            for x,y in zip(selections,dst['proposals']):
                                if type(x['selected'])!=bool:raise ValueError('Invalid selection')
                                y['selected']=x['selected']
                        updated['revision']+=1;save_json(job/'review.json',updated)
                        if active_queue_id:
                            row=batch.get_job(batch_db,active_queue_id)
                            batch.set_stage_result(batch_db,active_queue_id,expected_state=row['state'],result={**row['result'],'state':'NEEDS_REVIEW','revision':updated['revision']})
                        self.send(200,{'saved':True,'revision':updated['revision']});return
                    if path=='/approve_all':
                        updated=approve_all_pages(job)
                        if updated.get('revision',0)<=current['revision']:
                            updated['revision']=current['revision']+1;save_json(job/'review.json',updated)
                        self.send(200,{'review':updated});return
                    if path=='/export_folder':
                        if active_queue_id:raise ValueError('Dùng chức năng xuất thư mục trong hàng đợi cho hồ sơ này')
                        destination=req.get('destination')
                        def work_export_folder():
                            return export_reviewed_folder(captured_case or job,destination,internal_root=root,progress_cb=set_progress)
                        run_task(async_mode,work_export_folder,self.send,stage='EXPORT');return
                    if path=='/export':
                        if active_queue_id:raise ValueError('Dùng Xuất lại và kiểm PDF hoặc Bàn giao trong hàng đợi')
                        draft=req.get('draft',False);scope=req.get('scope','file')
                        if type(draft) is not bool:raise ValueError('Invalid draft value')
                        if scope not in {'file','case'}:raise ValueError('Invalid export scope')
                        if scope=='case' and not captured_case: raise ValueError('Not a case')
                        def work_export():
                            if scope=='case':
                                result=export_case(captured_case,draft=draft,approve_all=False,progress_cb=set_progress)
                                return {**result,'file':Path(result['outputs'][0]).name,'scope':'case','directory':result['output_dir']}
                            out,qc=export(job,draft=draft,progress_cb=set_progress)
                            return {'file':out.name,'qc':qc,'directory':str(out.parent),'scope':'file'}
                        run_task(async_mode,work_export,self.send,stage='EXPORT');return
                    self.send(404,{'error':'Not found'})
            except Conflict as exc:
                err=record_error_event(root,exc,stage='CONFLICT',http_path=path)
                self.send(409,{'error':str(exc),'code':'CONFLICT','error_detail':err})
            except Exception as exc:
                stg='WORKSPACE_INIT' if path=='/workspace/init' else ('OPEN_PATH' if path=='/open_path' else ('UPLOAD' if path=='/upload' else 'HTTP_API'))
                src_f=None
                try:
                    if path=='/open_path':
                        r=json.loads(body)
                        src_f=Path(r.get('path','')).name or None
                    elif path=='/upload':
                        src_f=original_name or None
                except Exception:pass
                err=record_error_event(root,exc,stage=stg,source_file=src_f,http_path=path)
                self.send(400,{'error':str(exc),'error_detail':err})
    class LocalServer(ThreadingHTTPServer):
        allow_reuse_address = False
        def server_bind(self):
            import socket
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()
    server=LocalServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--job');ap.add_argument('--port',type=int,default=8765)
    ap.add_argument('--root',default='HMU_JOBS');ap.add_argument('--no-browser',action='store_true');args=ap.parse_args()
    root_path=Path(args.root)
    try:server=create_server(root_path,Path(args.job) if args.job else None,args.port)
    except OSError as exc:
        record_error_event(root_path,exc,stage='STARTUP')
        report_file=root_path/'error_report.json'
        print(f"\n[HMU LỖI] Không mở được cổng {args.port}: {exc}")
        if report_file.exists():
            print(f"[HMU BÁO LỖI] Chi tiết lỗi đã ghi tại: {report_file.resolve()}")
        raise SystemExit(f'Không mở được cổng {args.port}. Kiểm tra phiên đang chạy hoặc dùng --port khác: {exc}')
    except Exception as exc:
        record_error_event(root_path,exc,stage='STARTUP')
        report_file=root_path/'error_report.json'
        print(f"\n[HMU LỖI] Khởi động thất bại: {exc}")
        if report_file.exists():
            print(f"[HMU BÁO LỖI] Chi tiết lỗi đã ghi tại: {report_file.resolve()}")
        raise
    url=f'http://127.0.0.1:{server.server_port}';print('HMU PDF review: '+url)
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.server_close()
        report=get_error_report(root_path)
        if report.get('total_errors',0)>0:
            report_file=root_path/'error_report.json'
            print(f"\n[HMU BÁO LỖI] Phiên làm việc ghi nhận {report['total_errors']} lỗi.")
            print(f"[HMU BÁO LỖI] Báo cáo chi tiết: {report_file.resolve()}\n")

if __name__=='__main__':main()
