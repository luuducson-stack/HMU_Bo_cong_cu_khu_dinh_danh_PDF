"""Error recording and diagnostic pipeline for HMU PDF De-identification.

Captures, classifies (FILE_ERROR vs CODE_ERROR vs CONFLICT_ERROR),
extracts codebase traceback frames, and persists structured errors to error_report.json.
"""
from datetime import datetime
from pathlib import Path
import json
import secrets
import threading
import time
import traceback

CATEGORY_FILE_ERROR = "FILE_ERROR"
CATEGORY_CODE_ERROR = "CODE_ERROR"
CATEGORY_CONFLICT_ERROR = "CONFLICT_ERROR"

_PROJECT_FILES = {
    'app.py', 'batch.py', 'batch_worker.py', 'batch_runtime.py',
    'delivery.py', 'engine.py', 'hmu_recognizers.py', 'ocr_helper.py',
    'output_qc.py', 'error_pipeline.py',
}

_REPORT_LOCK = threading.Lock()


def iso_now() -> str:
    return datetime.now().astimezone().isoformat()


def extract_code_location(exc: BaseException) -> dict | None:
    tb = getattr(exc, '__traceback__', None)
    if not tb:
        return None
    frames = traceback.extract_tb(tb)
    if not frames:
        return None

    # Search in reverse for the most specific project/test codebase frame
    chosen = None
    for frame in reversed(frames):
        fname = Path(frame.filename).name
        # Skip stdlib and 3rd party frameworks
        if 'unittest' in frame.filename or 'http/server' in frame.filename or 'socketserver' in frame.filename:
            continue
        if 'site-packages' in frame.filename:
            continue
        if fname in _PROJECT_FILES or fname.startswith('test_'):
            chosen = frame
            break

    if chosen is None:
        chosen = frames[-1]

    return {
        'file': Path(chosen.filename).name,
        'line': chosen.lineno,
        'function': chosen.name,
    }


def classify_error(exc: BaseException | str, stage: str | None = None, message: str | None = None) -> str:
    msg_str = (str(message) if message else str(exc)).lower()
    exc_type = type(exc).__name__ if isinstance(exc, BaseException) else str(exc)

    if stage == 'CONFLICT' or exc_type in {'Conflict', 'ConflictError'}:
        return CATEGORY_CONFLICT_ERROR

    if 'xung đột' in msg_str or 'đang xử lý tác vụ' in msg_str or 'đang chạy hàng đợi' in msg_str:
        return CATEGORY_CONFLICT_ERROR

    if isinstance(exc, FileNotFoundError) or exc_type in {'FileNotFoundError', 'FileDataError', 'EmptyFileError'}:
        return CATEGORY_FILE_ERROR

    file_err_keywords = (
        'pdf hỏng',
        'có mật khẩu',
        'không phải file pdf',
        'chỉ hỗ trợ file .pdf',
        'đường dẫn không tồn tại',
        'file không tồn tại',
        'không tìm thấy',
        'not found',
        'empty pdf',
        'pdf has no pages',
        'corrupt',
        'password',
        'encrypted',
        'trống hoặc có mật khẩu',
        'không mở được file',
        'file rỗng',
        'file bị hỏng',
        'invalid research id',
    )
    if any(kw in msg_str for kw in file_err_keywords):
        return CATEGORY_FILE_ERROR

    if stage == 'OPEN_PATH' and ('không' in msg_str or 'invalid' in msg_str or 'lỗi' in msg_str):
        return CATEGORY_FILE_ERROR

    return CATEGORY_CODE_ERROR


def record_error_event(
    root_dir: Path | str | None,
    exc: BaseException | str,
    *,
    stage: str,
    source_file: str | None = None,
    job_id: str | None = None,
    queue_id: str | None = None,
    http_path: str | None = None,
    category: str | None = None,
) -> dict:
    now_ts = time.time()
    iso = iso_now()
    msg = str(exc)
    err_type = type(exc).__name__ if isinstance(exc, BaseException) else "Error"
    code_loc = extract_code_location(exc) if isinstance(exc, BaseException) else None
    cat = category or classify_error(exc, stage=stage, message=msg)

    err_id = f"err_{int(now_ts * 1000):x}_{secrets.token_hex(4)}"
    record = {
        'id': err_id,
        'timestamp': now_ts,
        'iso_time': iso,
        'category': cat,
        'stage': stage,
        'source_file': source_file,
        'job_id': job_id,
        'queue_id': queue_id,
        'error_type': err_type,
        'message': msg,
        'code_location': code_loc,
    }
    if http_path:
        record['http_path'] = http_path

    if root_dir is not None:
        try:
            r_path = Path(root_dir)
            report_file = r_path if r_path.name.endswith('.json') else (r_path / 'error_report.json')
            with _REPORT_LOCK:
                if report_file.is_file():
                    try:
                        data = json.loads(report_file.read_text(encoding='utf-8'))
                    except Exception:
                        data = {'session_started_at': iso, 'total_errors': 0, 'errors': []}
                else:
                    data = {'session_started_at': iso, 'total_errors': 0, 'errors': []}

                data.setdefault('errors', []).append(record)
                data['total_errors'] = len(data['errors'])

                report_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = report_file.with_suffix('.tmp.' + secrets.token_hex(4))
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                tmp.replace(report_file)
        except Exception:
            pass

    return record


def get_error_report(root_dir: Path | str | None) -> dict:
    if root_dir is not None:
        r_path = Path(root_dir)
        report_file = r_path if r_path.name.endswith('.json') else (r_path / 'error_report.json')
        if report_file.is_file():
            try:
                return json.loads(report_file.read_text(encoding='utf-8'))
            except Exception:
                pass
    return {
        'session_started_at': iso_now(),
        'total_errors': 0,
        'errors': [],
    }
