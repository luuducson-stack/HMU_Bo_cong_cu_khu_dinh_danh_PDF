"""Local durable queue; each PDF is an independent case, never a shared seed pool."""
from contextlib import contextmanager, ExitStack, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import time


RUNNING = {'PREPARING', 'EXPORTING', 'VERIFYING'}
STATES = RUNNING | {'QUEUED', 'NEEDS_REVIEW', 'READY', 'FAILED', 'CANCELLING', 'CANCELLED', 'DUPLICATE', 'DELETING'}
GIB = 1024**3


class QueueLimits:
    MAX_JOBS = 2
    OCR_BUDGET = 4
    RENDER_BUDGET = 2
    WORKER_PEAK_BYTES = int(0.5 * GIB)
    PAGE_DISK_ESTIMATE_BYTES = 2 * 1024**2
    MIN_FREE_DISK_BYTES = 2 * GIB
    MAX_ATTEMPTS = 2
    BASE_TIMEOUT_SECONDS = 900
    SECONDS_PER_PAGE = 15
    POLL_INTERVAL_SECONDS = 0.1
    RESOURCE_POLL_SECONDS = 1.0
    DISK_POLL_SECONDS = 2.0
    HEARTBEAT_WRITE_SECONDS = 5.0
    HEARTBEAT_STALE_SECONDS = 30.0
    MAX_BULK_ITEMS = 2000


_INITIALIZED_SCHEMAS = {}


def _ensure_schema(path: Path) -> None:
    try:
        stat = path.stat()
        stamp = (stat.st_dev, stat.st_ino)
        if _INITIALIZED_SCHEMAS.get(path) == stamp:
            return
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=NORMAL')
        con.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, source_path TEXT NOT NULL, source_name TEXT NOT NULL,
            source_sha256 TEXT NOT NULL, pages INTEGER NOT NULL, state TEXT NOT NULL,
            job_dir TEXT NOT NULL, duplicate_of TEXT, revision INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL, updated REAL NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(source_path, source_sha256))''')
        con.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.commit()
    finally:
        con.close()
    stat = path.stat()
    _INITIALIZED_SCHEMAS[path] = (stat.st_dev, stat.st_ino)


@contextmanager
def _db(path, *, write=True):
    path = Path(path).resolve()
    if str(path).startswith('\\\\'):
        raise ValueError('Queue database must be on a local disk')
    _ensure_schema(path)
    con = sqlite3.connect(path, timeout=10, isolation_level=None if write else 'DEFERRED')
    con.row_factory = sqlite3.Row
    try:
        if write:
            con.execute('BEGIN IMMEDIATE')
        yield con
        if write:
            con.commit()
    except BaseException:
        if write and con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def _record(row):
    result = dict(row)
    result['result'] = json.loads(result.pop('result_json'))
    return result


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def worker_timeout(pages: int, override: float | None = None) -> float:
    if override is not None:
        return override
    return max(QueueLimits.BASE_TIMEOUT_SECONDS, max(1, int(pages or 1)) * QueueLimits.SECONDS_PER_PAGE)


def discover_sources(root):
    root = Path(root).resolve(strict=True)
    if root.is_file():
        if root.suffix.lower() != '.pdf':
            raise ValueError('Select a PDF or directory')
        return [root]
    excluded = {'hmu_jobs', '.git', '.venv', 'exports', '.export_staging'}
    result = []
    for directory, children, files in os.walk(root, followlinks=False):
        children[:] = [n for n in sorted(children) if n.lower() not in excluded and not Path(directory, n).is_symlink()]
        for name in sorted(files):
            p = Path(directory, name)
            if p.suffix.lower() == '.pdf' and not p.is_symlink() and p.resolve().is_relative_to(root):
                result.append(p.resolve())
    return result


def enqueue(db_path: Path, sources: list[Path]) -> list[str]:
    import fitz
    root = Path(db_path).resolve().parent
    ids = []
    for value in sources:
        source = Path(value).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != '.pdf':
            raise ValueError('Input must be a PDF file')
        if source.is_relative_to(root):
            raise ValueError('Do not enqueue queue data or output')
        digest = _sha(source)
        pages = 0
        error = ''
        try:
            with fitz.open(source) as doc:
                if doc.is_encrypted:
                    raise ValueError('Encrypted PDF')
                pages = len(doc)
                if not pages:
                    raise ValueError('Empty PDF')
        except Exception:
            error = 'PDF hỏng, trống hoặc có mật khẩu; cần kiểm tra nguồn.'
        with _db(db_path) as con:
            old = con.execute('SELECT id,state FROM jobs WHERE source_path=? AND source_sha256=?', (str(source), digest)).fetchone()
            if old:
                if old['state'] == 'DELETING':
                    raise ValueError('Mục đang xóa; hoàn tất xóa trước khi thêm lại nguồn')
                ids.append(old['id'])
                continue
            duplicate = con.execute(
                "SELECT id FROM jobs WHERE source_sha256=? AND duplicate_of IS NULL AND state NOT IN ('FAILED','DELETING') ORDER BY created LIMIT 1",
                (digest,),
            ).fetchone()
            ident = secrets.token_hex(16)
            now = time.time()
            state = 'FAILED' if error else ('DUPLICATE' if duplicate else 'QUEUED')
            con.execute(
                '''INSERT INTO jobs
                (id,source_path,source_name,source_sha256,pages,state,job_dir,duplicate_of,error,created,updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (ident, str(source), source.name, digest, pages, state, str(root / 'jobs' / ident),
                 duplicate['id'] if duplicate else None, error, now, now),
            )
            ids.append(ident)
    return ids


def get_job(db_path: Path, job_id: str) -> dict:
    if not isinstance(job_id, str) or not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('Invalid queue job ID')
    with _db(db_path, write=False) as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown queue job')
        return _record(row)


_SUMMARY_FIELDS = '''id,source_path,source_name,source_sha256,pages,state,job_dir,duplicate_of,
    revision,attempts,error,created,updated,
    json_object('output',json_extract(result_json,'$.output'),
      'machine_seconds',json_extract(result_json,'$.machine_seconds'),
      'verification',json_object('status',json_extract(result_json,'$.verification.status'),
        'finding_count',coalesce(json_array_length(result_json,'$.verification.findings'),0),
        'unreadable_count',coalesce(json_array_length(result_json,'$.verification.unreadable_pages'),0))) AS result_json'''


def list_jobs(db_path: Path, *, details=True) -> list[dict]:
    with _db(db_path, write=False) as con:
        fields = '*' if details else _SUMMARY_FIELDS
        return [_record(r) for r in con.execute(f'SELECT {fields} FROM jobs ORDER BY created,id')]


def _queue_snapshot(db_path: Path) -> tuple[list[dict], bool]:
    with _db(db_path, write=False) as con:
        rows = [_record(r) for r in con.execute(f'SELECT {_SUMMARY_FIELDS} FROM jobs ORDER BY created,id')]
        paused = con.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        return rows, bool(paused and paused['value'] == '1')


def claim_next(db_path: Path) -> dict | None:
    with _db(db_path) as con:
        paused = con.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        if paused and paused['value'] == '1':
            return None
        row = con.execute("SELECT * FROM jobs WHERE state='QUEUED' ORDER BY created,id LIMIT 1").fetchone()
        if row is None:
            return None
        con.execute("UPDATE jobs SET state='PREPARING', attempts=attempts+1, updated=? WHERE id=?", (time.time(), row['id']))
        return _record(con.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())


def set_stage_result(db_path: Path, job_id: str, *, expected_state: str, result: dict) -> None:
    with _db(db_path) as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None or row['state'] != expected_state:
            raise ValueError('Queue state changed')
        _write_stage_result(con, row, result)


def _write_stage_result(con, row, result):
    state = result.get('state')
    if state not in STATES or state in {'READY', 'DUPLICATE', 'DELETING'}:
        raise ValueError('Worker cannot publish READY or duplicate decisions')
    revision = result.get('revision', row['revision'])
    if type(revision) is not int or revision < row['revision']:
        raise ValueError('Review revision changed')
    con.execute(
        'UPDATE jobs SET state=?,revision=?,result_json=?,error=?,updated=? WHERE id=?',
        (state, revision, json.dumps(result, ensure_ascii=False), str(result.get('error', '')), time.time(), row['id']),
    )


def finish_worker(db_path, job_id, result):
    # Call only after owned process teardown; cancellation and completion commit atomically.
    with _db(db_path) as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None or row['state'] not in RUNNING | {'CANCELLING'}:
            raise ValueError('Queue state changed')
        _write_stage_result(con, row, {'state': 'CANCELLED'} if row['state'] == 'CANCELLING' else result)


def pause_queue(db_path: Path) -> None:
    with _db(db_path) as con:
        con.execute("INSERT OR REPLACE INTO settings VALUES ('paused','1')")


def resume_queue(db_path: Path) -> None:
    with _db(db_path) as con:
        con.execute("INSERT OR REPLACE INTO settings VALUES ('paused','0')")


def recover_queue(db_path: Path) -> dict:
    # Caller owns the coordinator lock: no live worker may still publish here.
    import engine
    from output_qc import content_digest, verifier_fingerprint
    counts = {'requeued': 0, 'reconciled': 0}
    for row in list_jobs(db_path, details=False):
        if row['state'] == 'CANCELLING':
            set_stage_result(db_path, row['id'], expected_state='CANCELLING', result={'state': 'CANCELLED'})
            continue
        if row['state'] not in RUNNING:
            continue
        result = None
        root = Path(row['job_dir'])
        for request_path in root.glob('request_*.json'):
            try:
                request = json.loads(request_path.read_text(encoding='utf8'))['job']
                if request['attempts'] != row['attempts'] or request['id'] != row['id']:
                    continue
                candidate = json.loads((root / f"result_{request['attempt_id']}.json").read_text(encoding='utf8'))
                pdf = Path(candidate['output']).resolve()
                qc = candidate['verification']
                review = engine.ensure_job(root / 'review')
                if (candidate['source_sha256'] == row['source_sha256']
                        and candidate['attempt_id'] == request['attempt_id']
                        and candidate['state'] == 'NEEDS_REVIEW'
                        and candidate['revision'] == review['revision']
                        and candidate['engine_job_id'] == review['job_id']
                        and pdf.is_relative_to((root / 'review' / 'exports').resolve())
                        and _sha(pdf) == qc['pdf_sha256']
                        and qc['content_sha256'] == content_digest(review)
                        and qc['verifier_fingerprint'] == verifier_fingerprint()):
                    result = candidate
                    break
            except (OSError, ValueError, KeyError):
                continue
        set_stage_result(db_path, row['id'], expected_state=row['state'], result=result or {'state': 'QUEUED'})
        counts['reconciled' if result else 'requeued'] += 1
    return counts


def snapshot_source(row: dict) -> Path:
    root = Path(row['job_dir']).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'source_private.pdf'
    if target.exists():
        if _sha(target) != row['source_sha256']:
            raise ValueError('Source snapshot changed')
        return target
    source = Path(row['source_path'])
    if _sha(source) != row['source_sha256']:
        raise ValueError('Source changed since enqueue')
    pending = root / 'source_private.pending'
    shutil.copyfile(source, pending)
    if _sha(pending) != row['source_sha256']:
        raise ValueError('Source changed during copy')
    os.replace(pending, target)
    return target


def can_admit(*, available_ram, batch_rss, next_peak, free_disk, reserved_disk, total_ram, power_ok=True):
    return (power_ok and available_ram - next_peak >= max(GIB, 0.1 * total_ram)
            and batch_rss + next_peak <= 0.5 * total_ram
            and free_disk - reserved_disk >= QueueLimits.MIN_FREE_DISK_BYTES)


def disk_reservation(rows):
    remaining = 0
    for row in rows:
        if row['state'] not in RUNNING | {'QUEUED', 'CANCELLING'}:
            continue
        source = Path(row['source_path'])
        root = Path(row['job_dir'])
        estimate = row['pages'] * QueueLimits.PAGE_DISK_ESTIMATE_BYTES + (source.stat().st_size if source.exists() else 0)
        used = 0
        if root.exists():
            for p in root.rglob('*'):
                try:
                    if p.is_file():
                        used += p.stat().st_size
                except FileNotFoundError:
                    pass  # Publication may rename a complete staging directory.
        remaining += max(0, estimate - used)
    return remaining


@contextmanager
def queue_lock(db_path):
    path = Path(db_path).resolve().with_suffix('.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Queue already has a running coordinator') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _sync_worker_progress(db_path: Path, row: dict, attempt_id: str) -> None:
    progress_path = Path(row['job_dir']) / 'progress.json'
    if not progress_path.exists():
        return
    try:
        progress = json.loads(progress_path.read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError):
        return  # Progress is advisory; the final worker result remains mandatory.
    stage = progress.get('stage')
    if progress.get('attempt_id') == attempt_id and stage in RUNNING and stage != row['state']:
        try:
            set_stage_result(db_path, row['id'], expected_state=row['state'], result={'state': stage, 'revision': row['revision']})
        except ValueError:
            if get_job(db_path, row['id'])['state'] == row['state']:
                raise


def _reap_active_workers(db_path: Path, active: dict, by_id: dict, timeout_seconds: float | None) -> bool:
    mutated = False
    for ident, work in list(active.items()):
        row = by_id.get(ident) or get_job(db_path, ident)
        code = work['process'].process.poll()
        if row['state'] in {'CANCELLING', 'CANCELLED'}:
            work['process'].close()
            del active[ident]
            if row['state'] == 'CANCELLING':
                finish_worker(db_path, ident, {'state': 'CANCELLED'})
            mutated = True
            continue
        deadline = worker_timeout(row.get('pages', 1), timeout_seconds)
        if time.monotonic() - work['started'] > deadline:
            work['process'].close()
            code = work['process'].process.poll()
        if code is None:
            _sync_worker_progress(db_path, row, work['attempt_id'])
            continue
        work['process'].close()
        del active[ident]
        mutated = True
        result_path = Path(row['job_dir']) / f"result_{work['attempt_id']}.json"
        if code == 0 and result_path.exists():
            result = json.loads(result_path.read_text(encoding='utf8'))
            if result.get('attempt_id') != work['attempt_id'] or result.get('source_sha256') != row['source_sha256']:
                raise ValueError('Worker result identity mismatch')
            finish_worker(db_path, ident, result)
        else:
            error_path = Path(row['job_dir']) / f"error_{work['attempt_id']}.json"
            error = (json.loads(error_path.read_text(encoding='utf8'))
                     if error_path.exists()
                     else {'message': f'Worker stopped with exit {code}', 'retryable': True})
            retry = bool(error.get('retryable')) and row['attempts'] < QueueLimits.MAX_ATTEMPTS
            finish_worker(db_path, ident, {'state': 'QUEUED' if retry else 'FAILED', 'error': error['message']})
    return mutated


def _admit_pending_workers(
    db_path: Path, active: dict, pending: list[dict], *, jobs: int, ocr_workers: int,
    render_workers: int, stats: dict, disk_reserve: int, stop_event,
) -> tuple[str, int]:
    import sys
    import engine
    from batch_runtime import ManagedProcess
    last_message = ''
    admitted = 0
    while pending and len(active) < jobs and not stop_event.is_set():
        if not can_admit(**stats, next_peak=QueueLimits.WORKER_PEAK_BYTES, reserved_disk=disk_reserve):
            last_message = (
                'Chờ cắm nguồn điện để chạy không giám sát.'
                if not stats.get('power_ok', True)
                else 'Chờ đủ RAM hoặc dung lượng; các file đã xong vẫn có thể duyệt.'
            )
            break
        row = claim_next(db_path)
        if row is None:
            break
        attempt = secrets.token_hex(12)
        row['attempt_id'] = attempt
        work_root = Path(row['job_dir'])
        work_root.mkdir(parents=True, exist_ok=True)
        request = work_root / f'request_{attempt}.json'
        engine.save_json(request, dict(job=row, ocr_workers=ocr_workers, render_workers=render_workers))
        try:
            managed = ManagedProcess(
                [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('batch_worker.py')), '--request', str(request)],
                work_root / f'worker_{attempt}.log',
            )
        except Exception as exc:
            set_stage_result(db_path, row['id'], expected_state='PREPARING', result={'state': 'FAILED', 'error': str(exc)})
            raise
        active[row['id']] = dict(process=managed, attempt_id=attempt, started=time.monotonic())
        pending = [r for r in pending if r['id'] != row['id']]
        stats['available_ram'] -= QueueLimits.WORKER_PEAK_BYTES
        stats['batch_rss'] += QueueLimits.WORKER_PEAK_BYTES
        admitted += 1
    return last_message, admitted


def run_queue(
    db_path: Path, *, jobs=2, ocr_workers=1, render_workers=1, stop_event=None, timeout_seconds=None,
) -> dict:
    import threading
    import engine
    from batch_runtime import keep_awake, resources
    if type(jobs) is not int or not 1 <= jobs <= QueueLimits.MAX_JOBS:
        raise ValueError('Batch supports 1 or 2 concurrent files')
    if type(ocr_workers) is not int or not 1 <= ocr_workers <= QueueLimits.OCR_BUDGET or jobs * ocr_workers > QueueLimits.OCR_BUDGET:
        raise ValueError('Total OCR worker budget is 4')
    if type(render_workers) is not int or not 1 <= render_workers <= QueueLimits.RENDER_BUDGET or jobs * render_workers > QueueLimits.RENDER_BUDGET:
        raise ValueError('Total render worker budget is 2')
    stop_event = stop_event or threading.Event()
    db_path = Path(db_path).resolve()
    root = db_path.parent
    active = {}
    started = time.perf_counter()
    maximum = 0
    peak = 0
    last_message = ''
    stats = None
    stats_checked = 0.0
    disk_checked = 0.0
    disk_reserve = 0
    disk_scope = None
    status_snapshot = None
    status_written = 0.0

    def publish_status(pid, *, force=False):
        nonlocal status_snapshot, status_written
        now_mono = time.monotonic()
        snapshot = (pid, len(active), jobs, maximum, last_message)
        if not force and snapshot == status_snapshot and now_mono - status_written < QueueLimits.HEARTBEAT_WRITE_SECONDS:
            return
        engine.save_json(
            root / 'coordinator_status.json',
            dict(pid=pid, heartbeat=time.time(), active=len(active), requested_jobs=jobs,
                 max_active_jobs=maximum, peak_sampled_rss_bytes=peak, message=last_message),
        )
        status_snapshot = snapshot
        status_written = now_mono

    with queue_lock(db_path):
        recover_queue(db_path)
        with ExitStack() as stack:
            awake_active = False
            try:
                while not stop_event.is_set():
                    rows, paused = _queue_snapshot(db_path)
                    if active:
                        by_id = {r['id']: r for r in rows}
                        if _reap_active_workers(db_path, active, by_id, timeout_seconds):
                            rows, paused = _queue_snapshot(db_path)
                    pending = [r for r in rows if r['state'] == 'QUEUED']
                    now_mono = time.monotonic()
                    need_admit = bool(pending and not paused and len(active) < jobs)
                    if stats is None or need_admit or (active and now_mono - stats_checked >= QueueLimits.RESOURCE_POLL_SECONDS):
                        stats = resources(root)
                        stats_checked = now_mono
                        peak = max(peak, stats['batch_rss'])
                    # Reserve unfinished outputs and retained review previews, not just the next PDF.
                    scope = tuple((r['id'], r['state']) for r in rows if r['state'] in RUNNING | {'QUEUED', 'CANCELLING'})
                    if need_admit and (scope != disk_scope or now_mono - disk_checked >= QueueLimits.DISK_POLL_SECONDS):
                        disk_reserve = disk_reservation(rows)
                        disk_checked = now_mono
                        disk_scope = scope
                        stats['free_disk'] = shutil.disk_usage(root).free
                    last_message = ''
                    if need_admit:
                        last_message, _ = _admit_pending_workers(
                            db_path, active, pending, jobs=jobs, ocr_workers=ocr_workers,
                            render_workers=render_workers, stats=stats, disk_reserve=disk_reserve, stop_event=stop_event,
                        )
                        maximum = max(maximum, len(active))
                    if active and not awake_active:
                        stack.enter_context(keep_awake())
                        awake_active = True
                    publish_status(os.getpid())
                    if not active and (not pending or paused):
                        break
                    stop_event.wait(QueueLimits.POLL_INTERVAL_SECONDS)
            finally:
                for work in active.values():
                    work['process'].close()
                active.clear()
                publish_status(None, force=True)
    states = {s: 0 for s in STATES}
    for row in list_jobs(db_path, details=False):
        states[row['state']] += 1
    return dict(seconds=time.perf_counter() - started, max_active_jobs=maximum, peak_sampled_rss_bytes=peak, states=states)


def start_background(db_path: Path, *, jobs=2, ocr_workers=1, render_workers=1):
    import subprocess
    import sys
    root = Path(db_path).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'coordinator.log').open('ab') as log:
        process = subprocess.Popen(
            [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), 'run', '--queue', str(Path(db_path).resolve()),
             '--jobs', str(jobs), '--ocr-workers', str(ocr_workers), '--render-workers', str(render_workers)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    return process.pid


@contextmanager
def review_lock(db_path, job_id):
    row = get_job(db_path, job_id)
    with queue_lock(Path(row['job_dir']) / 'review_operation'):
        row = get_job(db_path, job_id)
        if row['state'] not in {'NEEDS_REVIEW', 'READY'}:
            raise ValueError('File đang xử lý; chờ PDF để duyệt')
        yield row


def current_verification(row, expected_revision):
    import engine
    from output_qc import content_digest, verifier_fingerprint
    job = Path(row['job_dir']) / 'review'
    review = engine.ensure_job(job)
    if type(expected_revision) is not int or review['revision'] != expected_revision:
        raise ValueError('Review revision changed')
    qc = json.loads((job / 'output_verification_private.json').read_text(encoding='utf8'))
    pdf = Path(row['result']['output']).resolve()
    if (not pdf.is_relative_to((job / 'exports').resolve()) or not pdf.is_file()
            or qc.get('pdf_sha256') != _sha(pdf) or qc.get('job_id') != review['job_id']
            or qc.get('content_sha256') != content_digest(review) or qc.get('policy') != review['policy']
            or qc.get('verifier_fingerprint') != verifier_fingerprint()):
        raise ValueError('Vùng khử hoặc phiên bản QC thay đổi; cần xuất và kiểm lại')
    return review, qc, pdf


def review_issues(row, qc):
    binding = {k: qc[k] for k in ('pdf_sha256', 'content_sha256', 'verifier_fingerprint')}
    path = Path(row['job_dir']) / 'decisions_private.json'
    decisions = json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    resolved = decisions.get('findings', {}) if decisions.get('binding') == binding else {}
    issues = list(qc['findings']) + [
        dict(id=f'unreadable:{pn}', page=pn, kind='OCR_UNREADABLE',
             text='OCR chưa đọc được nội dung; phải kiểm tra toàn trang PDF', rects=[])
        for pn in qc['unreadable_pages']
    ]
    return [{**f, 'resolved': f['id'] in resolved} for f in issues], binding, resolved


def resolve_finding(db_path, job_id, *, expected_revision, finding_id, reason, reviewer):
    import engine
    if not isinstance(reason, str) or len(reason.strip()) < 5 or not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError('Ghi người duyệt và lý do xác nhận cảnh báo')
    with review_lock(db_path, job_id) as row:
        review, qc, pdf = current_verification(row, expected_revision)
        issues, binding, decisions = review_issues(row, qc)
        matches = [f for f in issues if f['id'] == finding_id]
        if len(matches) != 1:
            raise ValueError('Unknown finding')
        if not review['pages'][matches[0]['page'] - 1]['reviewed']:
            raise ValueError('Cần duyệt trang trước khi xác nhận cảnh báo')
        decisions[finding_id] = dict(reason=reason.strip(), reviewer=reviewer.strip(), revision=expected_revision, at=time.time())
        engine.save_json(Path(row['job_dir']) / 'decisions_private.json', dict(binding=binding, findings=decisions))


def reprocess_job(db_path, job_id, *, expected_revision):
    import engine
    with review_lock(db_path, job_id) as row:
        review = engine.ensure_job(Path(row['job_dir']) / 'review')
        if review['revision'] != expected_revision:
            raise ValueError('Review revision changed')
        set_stage_result(db_path, job_id, expected_state=row['state'], result={'state': 'QUEUED', 'revision': expected_revision})


def cancel_job(db_path, job_id):
    row = get_job(db_path, job_id)
    if row['state'] == 'DELETING':
        raise ValueError('Mục đang xóa; chỉ được thử Xóa lại để hoàn tất dọn dữ liệu')
    if row['state'] in {'READY', 'DUPLICATE', 'NEEDS_REVIEW'}:
        raise ValueError('Không hủy bản đã xuất; giữ lại để duyệt')
    set_stage_result(
        db_path, job_id, expected_state=row['state'],
        result={'state': 'CANCELLING' if row['state'] in RUNNING | {'CANCELLING'} else 'CANCELLED'},
    )


def retry_job(db_path, job_id):
    from batch_worker import processing_fingerprint
    row = get_job(db_path, job_id)
    if row['state'] not in {'FAILED', 'CANCELLED'}:
        raise ValueError('Chỉ thử lại file lỗi hoặc đã hủy')
    if _sha(row['source_path']) != row['source_sha256']:
        raise ValueError('Nguồn đã đổi; thêm lại file mới')
    # Preserve all old generations; a changed engine must never bless an old fingerprint.
    checkpoint = Path(row['job_dir']) / 'prepare_checkpoint.json'
    compatible = not checkpoint.exists() or json.loads(checkpoint.read_text(encoding='utf8')) == processing_fingerprint(row)
    new_dir = Path(row['job_dir']) if compatible else Path(db_path).resolve().parent / 'jobs' / f"{job_id}_{secrets.token_hex(8)}"
    with _db(db_path) as con:
        updated = con.execute(
            "UPDATE jobs SET state='QUEUED',job_dir=?,revision=?,attempts=0,error='',result_json='{}',updated=? WHERE id=? AND state=?",
            (str(new_dir), row['revision'] if compatible else 0, time.time(), job_id, row['state']),
        ).rowcount
        if updated != 1:
            raise ValueError('Queue state changed')


def _deletable_work_dir(db_path, row):
    root = Path(os.path.abspath(row['job_dir']))
    jobs = Path(os.path.abspath(db_path)).parent / 'jobs'
    if root.parent != jobs or not re.fullmatch(re.escape(row['id']) + r'(?:_[0-9a-f]{16})?', root.name):
        raise ValueError('Thư mục công việc không thuộc hàng đợi; không xóa')
    for p in (root, *root.parents):
        if p.is_symlink() or p.is_junction():
            raise ValueError('Không xóa qua liên kết/junction')
    release = row['result'].get('release', {})
    protected = [row['source_path']] + [release[k] for k in ('directory', 'output') if release.get(k)]
    if any(Path(p).resolve().is_relative_to(root) for p in protected):
        raise ValueError('Nguồn hoặc PDF bàn giao nằm trong dữ liệu làm việc; không xóa')
    if not root.exists():
        return root

    def scan_error(exc):
        raise exc

    for directory, children, files in os.walk(root, followlinks=False, onerror=scan_error):
        for name in children + files:
            p = Path(directory, name)
            if p.is_symlink() or p.is_junction():
                raise ValueError('Dữ liệu làm việc chứa liên kết/junction; không xóa')
    return root


def delete_jobs(db_path, job_ids):
    if (not isinstance(job_ids, list) or not 1 <= len(job_ids) <= QueueLimits.MAX_BULK_ITEMS
            or any(not isinstance(i, str) or not re.fullmatch(r'[0-9a-f]{32}', i) for i in job_ids)):
        raise ValueError('Chọn từ 1 đến 2000 mục hợp lệ để xóa')
    with queue_lock(Path(db_path).parent / 'delete_operation'):
        return _delete_jobs(db_path, job_ids)


def _deletable_work_dirs(db_path, row):
    current = _deletable_work_dir(db_path, row)
    roots = {current}
    for p in current.parent.glob(row['id'] + '*'):
        if re.fullmatch(re.escape(row['id']) + r'(?:_[0-9a-f]{16})?', p.name):
            roots.add(_deletable_work_dir(db_path, {**row, 'job_dir': str(p)}))
    return sorted(roots)


def _delete_jobs(db_path, job_ids):
    selected = list(dict.fromkeys(job_ids))
    candidates = []
    skipped = []
    deleted = []
    with ExitStack() as locks:
        for ident in selected:
            row = None
            try:
                row = get_job(db_path, ident)
                if row['state'] in RUNNING | {'CANCELLING'}:
                    raise ValueError('Hủy xử lý và đợi dừng xong trước khi xóa')
                _deletable_work_dirs(db_path, row)
                root = Path(row['job_dir'])
                locks.enter_context(queue_lock(root / 'review_operation'))
                candidates.append(row)
            except (OSError, ValueError, RuntimeError) as exc:
                skipped.append(dict(id=ident, source_name=row['source_name'] if row else ident, reason=str(exc)))
        # Mark the whole selection before releasing locks, so a duplicate cannot be claimed mid-delete.
        with _db(db_path) as con:
            marked = []
            for previous in candidates:
                row = _record(con.execute('SELECT * FROM jobs WHERE id=?', (previous['id'],)).fetchone())
                if row['state'] in RUNNING | {'CANCELLING'} or row['job_dir'] != previous['job_dir']:
                    skipped.append(dict(id=row['id'], source_name=row['source_name'], reason='Trạng thái đã đổi; đợi dừng rồi thử xóa lại'))
                    continue
                _deletable_work_dirs(db_path, row)
                con.execute("UPDATE jobs SET state='DELETING',updated=? WHERE id=?", (time.time(), row['id']))
                marked.append(row)
            for row in marked:
                copies = con.execute("SELECT id FROM jobs WHERE duplicate_of=? AND state!='DELETING' ORDER BY created,id", (row['id'],)).fetchall()
                if copies:
                    primary = copies[0]['id']
                    con.execute("UPDATE jobs SET state='QUEUED',duplicate_of=NULL,updated=? WHERE id=?", (time.time(), primary))
                    con.execute(
                        "UPDATE jobs SET duplicate_of=?,updated=? WHERE duplicate_of=? AND id!=? AND state!='DELETING'",
                        (primary, time.time(), row['id'], primary),
                    )
    for row in marked:
        try:
            for root in _deletable_work_dirs(db_path, row):
                if root.exists():
                    shutil.rmtree(root)
            with _db(db_path) as con:
                con.execute("DELETE FROM jobs WHERE id=? AND state='DELETING'", (row['id'],))
            deleted.append(row['id'])
        except (OSError, ValueError) as exc:
            with _db(db_path) as con:
                con.execute("UPDATE jobs SET error=?,updated=? WHERE id=? AND state='DELETING'", (str(exc), time.time(), row['id']))
            skipped.append(dict(id=row['id'], source_name=row['source_name'], reason='Chưa dọn xong; thử Xóa lại: ' + str(exc)))
    return dict(deleted=deleted, skipped=skipped)


def _approved_output(row, expected_revision):
    review, qc, pdf = current_verification(row, expected_revision)
    if not all(p['reviewed'] for p in review['pages']):
        raise ValueError('Cần duyệt tất cả trang trước khi bàn giao')
    issues, _, _ = review_issues(row, qc)
    if not qc['structural_ok'] or qc['pages_checked'] != qc['pages_expected'] or any(not f['resolved'] for f in issues):
        raise ValueError('QC còn cảnh báo chưa xử lý hoặc kiểm tra thiếu trang')
    manifest = dict(
        case_id='CASE_' + row['id'][:16], pages=len(review['pages']), source_hash=row['source_sha256'],
        output_hash=qc['pdf_sha256'], policy=review['policy'], revision=expected_revision, qc_status='HUMAN_REVIEWED',
    )
    report = dict(
        pages_checked=qc['pages_checked'], structural_ok=qc['structural_ok'],
        verifier_fingerprint=qc['verifier_fingerprint'], output_hash=qc['pdf_sha256'], revision=expected_revision,
        human_reviewed_pages=len(review['pages']), adjudicated_findings=len(issues), status='HUMAN_REVIEWED',
    )
    return pdf, manifest, report


def _mark_released(con, row, released):
    con.execute(
        "UPDATE jobs SET state='READY',revision=?,result_json=?,updated=? WHERE id=?",
        (released['revision'], json.dumps({**row['result'], 'release': released}, ensure_ascii=False), time.time(), row['id']),
    )


def release_job(db_path: Path, job_id: str, *, expected_revision: int, destination: Path) -> dict:
    import engine
    from delivery import source_pdf_name
    with review_lock(db_path, job_id) as row:
        pdf, manifest, report = _approved_output(row, expected_revision)
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        if destination.is_relative_to((Path(row['job_dir']) / 'review').resolve()):
            raise ValueError('Không bàn giao vào cache nội bộ')
        folder = destination / f"{job_id}_r{expected_revision}_{manifest['output_hash'][:12]}_named"
        filename = source_pdf_name(row['source_name'])
        if folder.exists():
            if json.loads((folder / 'manifest.json').read_text(encoding='utf8')) != manifest or _sha(folder / filename) != manifest['output_hash']:
                raise ValueError('Bản bàn giao hiện có không khớp; không ghi đè')
        else:
            staging = destination / f'.pending_{job_id}_{secrets.token_hex(8)}'
            staging.mkdir()
            shutil.copyfile(pdf, staging / filename)
            if _sha(staging / filename) != manifest['output_hash']:
                raise ValueError('Output copy hash mismatch')
            engine.save_json(staging / 'manifest.json', manifest)
            engine.save_json(staging / 'qc.json', report)
            staging.rename(folder)
        released = dict(directory=str(folder), output=str(folder / filename), revision=expected_revision)
        with _db(db_path) as con:
            _mark_released(con, row, released)
        return released


def release_folder(db_path, paths, destination):
    import engine
    from collections import Counter
    from delivery import publish_folder, source_pdf_name
    if (not isinstance(paths, list) or not 1 <= len(paths) <= QueueLimits.MAX_BULK_ITEMS
            or any(not isinstance(p, str) or not p.strip().strip('"') for p in paths)):
        raise ValueError('Nhập đường dẫn PDF/thư mục cần xuất')
    if not isinstance(destination, (str, Path)) or not str(destination).strip().strip('"'):
        raise ValueError('Nhập thư mục nhận PDF đã duyệt')
    roots = [Path(p.strip().strip('"')).resolve(strict=True) for p in paths]
    dest = Path(str(destination).strip().strip('"')).resolve()
    queue = Path(db_path).resolve().parent
    if dest.is_relative_to(queue) and not dest.is_relative_to(queue / 'delivered'):
        raise ValueError('Không xuất nhóm vào dữ liệu làm việc nội bộ')
    scopes = [(p, p.is_dir()) for p in roots]
    if any(dest.is_relative_to(p if directory else p.parent) for p, directory in scopes):
        raise ValueError('Chọn thư mục nhận nằm ngoài thư mục nguồn để tránh xử lý lại đầu ra')
    rows = [
        r for r in list_jobs(db_path, details=False)
        if any(Path(r['source_path']) == p or (directory and Path(r['source_path']).is_relative_to(p)) for p, directory in scopes)
    ]
    if not rows:
        raise ValueError('Không có mục trong hàng đợi thuộc đường dẫn đã nhập')
    pending = []
    approved = []
    exported = []
    folder = None
    with ExitStack() as locks:
        for candidate in rows:
            try:
                if candidate['state'] not in {'NEEDS_REVIEW', 'READY'}:
                    reason = {
                        'QUEUED': 'Chưa xử lý xong',
                        'FAILED': 'Xử lý lỗi; cần thử lại',
                        'CANCELLED': 'Đã hủy xử lý',
                        'DUPLICATE': 'Trùng nội dung; duyệt và xuất bản gốc',
                        'DELETING': 'Đang xóa dữ liệu làm việc',
                    }.get(candidate['state'], 'Đang xử lý; chờ PDF và QC hoàn tất')
                    raise ValueError(reason)
                row = locks.enter_context(review_lock(db_path, candidate['id']))
                review = engine.ensure_job(Path(row['job_dir']) / 'review')
                pdf, manifest, report = _approved_output(row, review['revision'])
                name = source_pdf_name(row['source_name'])
                approved.append((row, pdf, manifest, report, name))
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                pending.append(dict(id=candidate['id'], source_name=candidate['source_name'], reason=str(exc)))
        if approved:
            names = Counter(name.casefold() for _, _, _, _, name in approved)
            with publish_folder(dest) as (staging, folder):
                manifests = []
                reports = []
                for row, pdf, manifest, report, name in approved:
                    relative = Path(row['id'], name) if names[name.casefold()] > 1 else Path(name)
                    target = staging / relative
                    target.parent.mkdir(exist_ok=True)
                    shutil.copyfile(pdf, target)
                    if _sha(target) != manifest['output_hash']:
                        raise ValueError('Output copy hash mismatch')
                    manifests.append({**manifest, 'file': relative.as_posix()})
                    reports.append({**report, 'case_id': manifest['case_id']})
                    exported.append(dict(id=row['id'], output=str(folder / relative)))
                engine.save_json(staging / 'manifest.json', dict(files=manifests))
                engine.save_json(staging / 'qc.json', dict(files=reports))
            with _db(db_path) as con:
                for (row, _, manifest, _, _), item in zip(approved, exported):
                    _mark_released(con, row, dict(directory=str(folder), output=item['output'], revision=manifest['revision']))
    return dict(directory=str(folder) if folder else None, exported=exported, pending=pending)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('enqueue', 'run', 'status', 'pause', 'resume'):
        command = commands.add_parser(name)
        command.add_argument('--queue', required=True)
        if name == 'enqueue':
            command.add_argument('--input-dir', required=True)
        if name == 'run':
            command.add_argument('--jobs', type=int, default=2)
            command.add_argument('--ocr-workers', type=int, default=1)
            command.add_argument('--render-workers', type=int, default=1)
    args = parser.parse_args()
    path = Path(args.queue)
    if args.command == 'enqueue':
        result = {'ids': enqueue(path, discover_sources(args.input_dir))}
    elif args.command == 'run':
        result = run_queue(path, jobs=args.jobs, ocr_workers=args.ocr_workers, render_workers=args.render_workers)
    elif args.command == 'pause':
        pause_queue(path)
        result = {'paused': True}
    elif args.command == 'resume':
        resume_queue(path)
        result = {'pid': start_background(path)}
    else:
        result = {'jobs': [{k: r[k] for k in ('id', 'pages', 'state', 'revision', 'duplicate_of')} for r in list_jobs(path, details=False)]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
