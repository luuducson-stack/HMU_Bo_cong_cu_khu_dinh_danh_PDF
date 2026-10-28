"""Single-user localhost review application v2.0; no cloud services."""
import argparse, json, re, secrets, threading, time, unicodedata, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--root', default='HMU_JOBS')
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    active = Path(args.job).resolve() if args.job else None
    if active and not (active / 'review.json').exists():
        raise SystemExit('Job review.json not found')
    token = secrets.token_hex(24)
    frontend = Path(__file__).with_name('review.html')
    progress_state = {
        'message': '',
        'status': 'idle',
        'started_at': 0.0,
        'result': None,
        'error': None,
    }
    state_lock = threading.Lock()

    def set_progress(msg: str):
        with state_lock:
            progress_state['message'] = msg
        if msg:
            try:
                print(f'[HMU] {msg}', flush=True)
            except Exception:
                pass

    def run_task(is_async: bool, work_fn, send_fn):
        if not is_async:
            res = work_fn()
            send_fn(200, json.dumps(res, ensure_ascii=False).encode())
            return

        with state_lock:
            if progress_state['status'] == 'running':
                raise ValueError('Hệ thống đang xử lý tác vụ trước đó, vui lòng đợi hoàn tất.')
            progress_state['status'] = 'running'
            progress_state['started_at'] = time.time()
            progress_state['result'] = None
            progress_state['error'] = None
            progress_state['message'] = 'Đang khởi tạo tác vụ bất đồng bộ...'

        def _bg():
            try:
                res = work_fn()
                with state_lock:
                    progress_state['result'] = res
                    progress_state['status'] = 'done'
                    progress_state['message'] = ''
            except Exception as exc:
                try:
                    print(f'[HMU ASYNC ERROR] {exc}', flush=True)
                except Exception:
                    pass
                with state_lock:
                    progress_state['error'] = str(exc)
                    progress_state['status'] = 'error'
                    progress_state['message'] = ''

        threading.Thread(target=_bg, daemon=True).start()
        send_fn(202, json.dumps({'async': True, 'status': 'running'}, ensure_ascii=False).encode())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status, body, ctype='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get('Host') not in {f'127.0.0.1:{args.port}', f'localhost:{args.port}'}:
                self.send(403, b'Forbidden')
                return
            if self.path == '/':
                self.send(200, frontend.read_bytes(), 'text/html; charset=utf-8')
            elif self.path == '/progress':
                with state_lock:
                    elapsed = round(time.time() - progress_state['started_at'], 1) if progress_state['started_at'] else 0.0
                    payload = {
                        'progress': progress_state['message'],
                        'status': progress_state['status'],
                        'elapsed': elapsed,
                        'error': progress_state['error'],
                        'result': progress_state['result'],
                    }
                    if progress_state['status'] in {'done', 'error'}:
                        progress_state['status'] = 'idle'
                        progress_state['result'] = None
                        progress_state['error'] = None
                self.send(200, json.dumps(payload, ensure_ascii=False).encode())
            elif self.path == '/state':
                d = json.loads((active / 'review.json').read_text(encoding='utf-8')) if active and (active / 'review.json').exists() else None
                self.send(200, json.dumps({'token': token, 'review': d, 'progress': progress_state['message']}, ensure_ascii=False).encode())
            elif self.path == '/audit' and active:
                audit_file = active / 'AUDIT_SUMMARY.md'
                if not audit_file.exists() and (active / 'review.json').exists():
                    d = json.loads((active / 'review.json').read_text(encoding='utf-8'))
                    generate_audit_markdown(active, d)
                md = audit_file.read_text(encoding='utf-8') if audit_file.exists() else ''
                self.send(200, json.dumps({'markdown': md}, ensure_ascii=False).encode())
            elif self.path.startswith('/page/') and active:
                number = self.path[6:]
                if number.isdigit() and (active / 'pages' / f'{number}.png').is_file():
                    self.send(200, (active / 'pages' / f'{number}.png').read_bytes(), 'image/png')
                else:
                    self.send(404, b'Not found')
            elif self.path == '/download' and active:
                p = active / 'last_output.txt'
                if p.exists():
                    filename = p.read_text(encoding='utf-8').strip()
                    out = active / filename
                    if out.is_file() and out.parent == active:
                        self.send(200, out.read_bytes(), 'application/pdf')
                    else:
                        self.send(404, b'Not found')
                else:
                    self.send(404, b'No output')
            else:
                self.send(404, b'Not found')

        def do_POST(self):
            nonlocal active
            if self.headers.get('X-HMU-Token') != token:
                self.send(403, b'Forbidden')
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 200 * 1024 * 1024:
                    raise ValueError('Invalid request size')
                body = self.rfile.read(size)
                is_async = self.headers.get('X-HMU-Async') == '1'
                if self.path == '/upload':
                    sid = self.headers.get('X-Study-ID', 'HMU_CASE_0001').strip()
                    orig_name = urllib.parse.unquote(self.headers.get('X-Original-Filename', ''))
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sid):
                        raise ValueError('Invalid research ID')
                    folder = root / (sid + '_' + str(time.time_ns()))
                    folder.mkdir(mode=0o700)
                    source = folder / (orig_name if orig_name.endswith('.pdf') else 'source_private.pdf')
                    source.write_bytes(body)

                    def _do_upload():
                        nonlocal active
                        set_progress(f'Đang tìm hạt giống XML cho {orig_name or source.name}...')
                        ext_seeds = None
                        real_src = _find_original_in_workspace(orig_name)
                        if real_src:
                            ext_seeds = extract_case_seeds(real_src)
                        new_job = folder / 'review'
                        d = prepare(source, new_job, sid, external_seeds=ext_seeds, progress_cb=set_progress)
                        active = new_job
                        set_progress('')
                        return {'review': d}

                    run_task(is_async, _do_upload, self.send)
                elif self.path == '/open_path':
                    req = json.loads(body)
                    sid = str(req.get('study_id', 'HMU_CASE_0001')).strip()
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sid):
                        raise ValueError('Invalid research ID')
                    target = _resolve_local_path(str(req.get('path', '')))
                    if target.is_dir():
                        subdirs = sorted([d for d in target.iterdir() if d.is_dir()])
                        pdfs = sorted(target.glob('*.pdf'))
                        if len(subdirs) >= 5:
                            example_dir = subdirs[0]
                            raise ValueError(
                                f'Thư mục "{target}" là thư mục gốc chứa {len(subdirs)} ca bệnh khác nhau. '
                                f'Vui lòng nhập đường dẫn của 1 ca bệnh cụ thể (ví dụ: {example_dir})'
                            )
                        if not pdfs:
                            raise ValueError(f'Không tìm thấy file PDF trong thư mục: {target}')

                        def _do_open_dir():
                            nonlocal active
                            folder = root / (sid + '_' + str(time.time_ns()))
                            folder.mkdir(mode=0o700)
                            if len(pdfs) == 1:
                                set_progress(f'Đang trích xuất hạt giống XML từ thư mục {target.name}...')
                                ext_seeds = extract_case_seeds(target)
                                new_job = folder / 'review'
                                d = prepare(pdfs[0], new_job, sid, external_seeds=ext_seeds, progress_cb=set_progress)
                                active = new_job
                                set_progress('')
                                return {
                                    'review': d,
                                    'resolved_path': str(target),
                                }
                            else:
                                manifest = prepare_case(target, folder, study_id=sid, progress_cb=set_progress)
                                out_res = export_case(folder, draft=False, approve_all=True, progress_cb=set_progress)
                                first_sub = folder / manifest['files'][0]['sub_job']
                                active = first_sub
                                d = json.loads((active / 'review.json').read_text(encoding='utf-8'))
                                set_progress('')
                                return {
                                    'review': d,
                                    'batch_case': True,
                                    'files_count': len(manifest['files']),
                                    'output_dir': out_res['output_dir'],
                                    'audit_path': str(folder / 'AUDIT_SUMMARY.md'),
                                    'resolved_path': str(target),
                                }

                        run_task(is_async, _do_open_dir, self.send)
                    else:
                        def _do_open_file():
                            nonlocal active
                            folder = root / (sid + '_' + str(time.time_ns()))
                            folder.mkdir(mode=0o700)
                            new_job = folder / 'review'
                            d = prepare(target, new_job, sid, progress_cb=set_progress)
                            active = new_job
                            set_progress('')
                            return {
                                'review': d,
                                'resolved_path': str(target),
                            }

                        run_task(is_async, _do_open_file, self.send)
                elif self.path == '/approve_all' and active:
                    current = approve_all_pages(active)
                    self.send(200, json.dumps({'review': current}, ensure_ascii=False).encode())
                elif self.path == '/save' and active:
                    incoming = json.loads(body)
                    current = json.loads((active / 'review.json').read_text(encoding='utf-8'))
                    if len(incoming['pages']) != len(current['pages']):
                        raise ValueError('Page count mismatch')
                    for src, dst in zip(incoming['pages'], current['pages']):
                        if src['page'] != dst['page'] or len(src['proposals']) != len(dst['proposals']):
                            raise ValueError('Review structure differs')
                        dst['reviewed'] = bool(src['reviewed'])
                        dst['manual_rects'] = src['manual_rects']
                        dst['note'] = str(src.get('note', ''))
                        for q, r in zip(src['proposals'], dst['proposals']):
                            if q['id'] != r['id']:
                                raise ValueError('Finding identity differs')
                            r['selected'] = bool(q['selected'])
                    with fitz.open(active / 'working_private.pdf') as doc:
                        validate_review(current, doc)
                    save_json(active / 'review.json', current)
                    generate_audit_markdown(active, current)
                    self.send(200, b'{"saved":true}')
                elif self.path == '/export' and active:
                    req = json.loads(body)
                    is_draft = bool(req.get('draft'))
                    is_app_all = bool(req.get('approve_all'))

                    def _do_export():
                        out, qc = export(active, is_draft, approve_all=is_app_all, progress_cb=set_progress)
                        set_progress('')
                        (active / 'last_output.txt').write_text(out.name, encoding='utf-8')
                        return {'file': out.name, 'qc': qc, 'directory': str(active)}

                    run_task(is_async, _do_export, self.send)
                else:
                    self.send(404, b'Not found')
            except Exception as e:
                set_progress('')
                try:
                    print(f'[HMU ERROR] {self.path}: {e}', flush=True)
                except Exception:
                    pass
                self.send(400, json.dumps({'error': str(e)}, ensure_ascii=False).encode())

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}'
    print('HMU PDF review v2.0: ' + url + ' (Ctrl+C to stop)')
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()

if __name__ == '__main__':
    main()
