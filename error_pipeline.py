"""Error recording and diagnostic pipeline for HMU PDF De-identification.

Captures, classifies (FILE_ERROR vs CODE_ERROR vs CONFLICT_ERROR),
extracts codebase traceback frames, and persists structured errors to error_report.json.
"""
from datetime import datetime
from pathlib import Path
import json
import re
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


def extract_root_cause(exc: BaseException | str) -> str:
    if not isinstance(exc, BaseException):
        return str(exc)
    chain = []
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen and len(chain) < 5:
        seen.add(id(cur))
        text = str(cur).strip()
        name = type(cur).__name__
        entry = f"{name}: {text}" if text and not text.startswith(name + ":") else (text or name)
        if not chain or chain[-1] != entry:
            chain.append(entry)
        cur = getattr(cur, '__cause__', None) or getattr(cur, '__context__', None)
    return " <- ".join(chain)


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
        'workspace',
    )
    if any(kw in msg_str for kw in file_err_keywords):
        return CATEGORY_FILE_ERROR

    if stage in {'OPEN_PATH', 'WORKSPACE', 'WORKSPACE_INIT'} and ('không' in msg_str or 'invalid' in msg_str or 'lỗi' in msg_str or 'tên' in msg_str):
        return CATEGORY_FILE_ERROR

    return CATEGORY_CODE_ERROR


_VIETNAMESE = re.compile(r'[ạảãàáâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', re.I)

# Region kinds as the reviewer knows them, for the "where" details of an error.
_KIND_VI = {
    'MANUAL': 'vùng khoanh tay', 'SIGNATURE_IMAGE': 'vùng ký / ảnh chữ ký', 'IMAGE_REVIEW': 'ảnh trên trang',
    'PATIENT_NAME': 'họ tên bệnh nhân', 'PATIENT_NAME_REVIEW': 'họ tên bệnh nhân', 'RELATIVE_NAME': 'tên người thân',
    'HEALTHCARE_STAFF_NAME': 'tên nhân viên y tế', 'PERSON_NAME': 'họ tên', 'PERSON_NAME_UNCLASSIFIED': 'họ tên (chưa phân loại)',
    'DATE_OF_BIRTH': 'ngày sinh', 'YEAR_OF_BIRTH': 'năm sinh', 'ADDRESS_VN': 'địa chỉ', 'PHONE_NUMBER_VN': 'số điện thoại',
    'NATIONAL_ID': 'CCCD/CMND', 'HEALTH_INSURANCE_ID': 'mã BHYT', 'EMAIL': 'email', 'WATERMARK_TEXT': 'watermark',
    'BARCODE_CANDIDATE': 'mã vạch', 'QR_CANDIDATE': 'mã QR', 'ACCESS_CREDENTIAL': 'mã truy cập',
}

# (full-match English pattern, Vietnamese template). Every user-facing `raise` message of the code base is listed here;
# test_error_messages.Catalogue fails when a new English message is added without a translation.
_CATALOGUE = [
    (r'Preview requires opaque RGB', 'Ảnh xem trước phải là RGB không trong suốt.'),
    (r'Render workers must be 1 or 2', 'Số tiến trình dựng trang phải là 1 hoặc 2.'),
    (r'Incomplete rendered page map', 'Dựng trang chưa đủ: thiếu một số trang.'),
    (r'Text-to-geometry mismatch.*', 'Chữ và vị trí chữ trên trang không khớp; trang cần trích xuất bằng cách khác (OCR).'),
    (r'Audit snapshot changed', 'Bản duyệt đã thay đổi trong lúc lập báo cáo kiểm; hãy thử lại.'),
    (r'Redaction policy changed.*', 'Chính sách khử định danh đã đổi; hãy xử lý lại từ PDF gốc.'),
    (r'Working PDF changed.*', 'PDF làm việc đã bị thay đổi; từ chối xuất để tránh sai lệch.'),
    (r'OCR settings changed.*', 'Cấu hình OCR đã đổi; hãy xử lý lại tệp.'),
    (r'Analysis fingerprint changed.*', 'Dữ liệu phân tích không còn khớp PDF; hãy xử lý lại tệp.'),
    (r'Source hash does not match.*', 'Mã băm nguồn không khớp bản gốc; từ chối khôi phục.'),
    (r'Use a new empty job(?:_root)? directory', 'Cần dùng thư mục công việc mới và còn trống.'),
    (r'Encrypted PDF.*', 'PDF có mật khẩu; hãy mở khóa trong môi trường được phép rồi thử lại.'),
    (r'Empty PDF', 'PDF trống (không có trang nào).'),
    (r'Invalid research ID', 'Mã nghiên cứu không hợp lệ (chỉ dùng chữ, số, gạch dưới, gạch ngang; tối đa 64 ký tự).'),
    (r'Review/PDF page count differs', 'Số trang của bản duyệt và của PDF không khớp.'),
    (r'Page (?:order|count) mismatch', 'Số trang hoặc thứ tự trang không khớp.'),
    (r'Page text changed since preparation', 'Chữ trên trang đã thay đổi so với lúc xử lý ban đầu.'),
    (r'Invalid rectangles?', 'Vùng chọn không hợp lệ.'),
    (r'Rectangle outside page', 'Vùng chọn nằm ngoài trang.'),
    (r'UNSAFE_WATERMARK_REMOVAL on page (\d+)', r'Trang \1: không thể gỡ watermark một cách an toàn; cần kiểm tra lại.'),
    (r'Export DPI must be between 150 and 600', 'DPI xuất phải từ 150 đến 600.'),
    (r'Review all pages, or export a draft for review', 'Chưa duyệt hết các trang. Hãy duyệt tất cả trang hoặc xuất PDF thử (bản nháp) để xem lại.'),
    (r'Review all files before exporting the case', 'Chưa duyệt hết các file trong ca. Hãy duyệt hết hoặc xuất PDF thử (bản nháp).'),
    (r'SOURCE_RECHECK_REQUIRED.*', 'Cần kiểm lại nguồn: hãy xử lý lại từ đúng PDF gốc.'),
    (r'Invalid sub-job(?: path)?', 'Đường dẫn file con trong ca không hợp lệ.'),
    (r'Invalid case file index', 'Số thứ tự file trong ca không hợp lệ.'),
    (r'Invalid file index', 'Số thứ tự file không hợp lệ.'),
    (r'Unknown batch action', 'Thao tác hàng đợi không xác định.'),
    (r'Unknown or expired task', 'Tác vụ không tồn tại hoặc đã hết hạn.'),
    (r'Invalid page', 'Số trang không hợp lệ.'),
    (r'Job changed; reload state', 'Hồ sơ đã đổi; hãy tải lại trang.'),
    (r'Review (?:changed|revision changed)', 'Bản duyệt đã thay đổi; hãy tải lại.'),
    (r'Invalid export', 'Bản xuất không hợp lệ.'),
    (r'Invalid output index', 'Số thứ tự file xuất không hợp lệ.'),
    (r'Invalid output path', 'Đường dẫn file xuất không hợp lệ.'),
    (r'Invalid request size', 'Kích thước yêu cầu không hợp lệ.'),
    (r'Invalid session payload', 'Dữ liệu phiên làm việc không hợp lệ.'),
    (r'Not a case', 'Đây không phải một ca nhiều file.'),
    (r'Finding identity differs', 'Danh sách vùng phát hiện không khớp với bản hiện tại.'),
    (r'Invalid reviewed value', 'Giá trị "đã duyệt" không hợp lệ.'),
    (r'Invalid selection', 'Giá trị chọn vùng không hợp lệ.'),
    (r'Invalid draft value', 'Giá trị "bản nháp" không hợp lệ.'),
    (r'Invalid export scope', 'Phạm vi xuất không hợp lệ.'),
    (r'Queue database must be on a local disk', 'CSDL hàng đợi phải nằm trên ổ đĩa cục bộ.'),
    (r'Select a PDF or directory', 'Hãy chọn một file PDF hoặc một thư mục.'),
    (r'Input must be a PDF file', 'Đầu vào phải là file PDF.'),
    (r'Do not enqueue queue data or output', 'Không thêm dữ liệu hàng đợi hoặc thư mục kết quả vào hàng đợi.'),
    (r'Invalid queue job ID', 'Mã mục hàng đợi không hợp lệ.'),
    (r'Unknown queue job', 'Không tìm thấy mục trong hàng đợi.'),
    (r'Queue state changed', 'Trạng thái hàng đợi đã thay đổi; hãy thử lại.'),
    (r'Worker cannot publish READY or duplicate decisions', 'Tiến trình xử lý không được tự đặt trạng thái "Đã bàn giao" hoặc "Trùng".'),
    (r'Source snapshot changed', 'Bản sao nguồn đã bị thay đổi.'),
    (r'Source changed since enqueue', 'File nguồn đã thay đổi kể từ khi thêm vào hàng đợi.'),
    (r'Source changed during copy', 'File nguồn thay đổi trong lúc sao chép.'),
    (r'Queue already has a running coordinator', 'Hàng đợi đã có bộ điều phối đang chạy.'),
    (r'Worker result identity mismatch', 'Kết quả của tiến trình xử lý không khớp mục hàng đợi.'),
    (r'Batch supports 1 or 2 concurrent files', 'Hàng đợi chỉ chạy song song 1 hoặc 2 file.'),
    (r'Total OCR worker budget is (\d+)', r'Tổng số tiến trình OCR tối đa là \1.'),
    (r'Total render worker budget is (\d+)', r'Tổng số tiến trình dựng trang tối đa là \1.'),
    (r'Unknown finding', 'Không tìm thấy cảnh báo này.'),
    (r'Output (?:copy )?hash mismatch', 'Bản sao kết quả không khớp mã băm; không bàn giao.'),
    (r'Review revision changed before verification', 'Bản duyệt đã đổi trước khi kiểm; hãy xuất và kiểm lại.'),
    (r'PDF or review changed', 'PDF hoặc bản duyệt đã thay đổi; cần kiểm lại.'),
    (r'PDF or review revision changed during verification', 'PDF hoặc bản duyệt đã đổi trong lúc kiểm; hãy kiểm lại.'),
    (r'OCR batch exceeded (\d+(?:\.\d+)?)s', r'OCR quá thời gian cho phép (\1 giây).'),
    (r'OCR workers must be between 1 and 6', 'Số tiến trình OCR phải từ 1 đến 6.'),
    (r'Invalid prerendered PNG', 'Ảnh dựng sẵn để OCR không hợp lệ.'),
    (r'Empty prerendered PNG', 'Ảnh dựng sẵn để OCR bị rỗng.'),
    (r'Unexpected OCR page', 'OCR trả về trang không mong đợi.'),
    (r'OCR PowerShell failed \(exit (-?\d+)\): ?(.*)', r'OCR bằng PowerShell thất bại (mã \1): \2'),
    (r'OCR returned incomplete page tiles', 'OCR trả về thiếu mảnh trang.'),
    (r'OCR DPI must be between 150 and 600', 'DPI của OCR phải từ 150 đến 600.'),
    (r'Invalid OCR region (?:identity|geometry)', 'Vùng OCR không hợp lệ.'),
    (r'OCR region outside page', 'Vùng OCR nằm ngoài trang.'),
    (r'Processing version changed.*', 'Phiên bản xử lý đã đổi; hãy thêm lại file gốc vào hàng đợi.'),
    (r'Processing code changed during this job.*', 'Mã xử lý đã đổi trong lúc chạy; cần chạy lại file này.'),
    (r'Batch OCR requires Windows', 'Xử lý hàng loạt bằng OCR chỉ chạy trên Windows.'),
    (r'Worker ownership handshake missing', 'Tiến trình xử lý chưa nhận được tín hiệu khởi động từ bộ điều phối.'),
    # Library / operating-system messages seen in the field.
    (r'(?i)cannot open broken document|FileDataError.*', 'Không mở được PDF: file bị hỏng.'),
    (r'.*\[WinError 32\].*', 'File đang được chương trình khác sử dụng; hãy đóng rồi thử lại.'),
    (r'.*\[WinError 5\].*|.*Permission denied.*', 'Không có quyền truy cập file hoặc thư mục này.'),
    (r'.*\[WinError 2\].*|.*No such file or directory.*', 'Không tìm thấy file hoặc thư mục.'),
]
_CATALOGUE = [(re.compile(rx, re.S), template) for rx, template in _CATALOGUE]


def vi_message(text, where=None):
    """Vietnamese text for an error message; `where` (page, kind, code, pages, file) says where it went wrong."""
    text, where = str(text).strip(), where or {}
    page = where.get('page') or (int(m.group(1)) if (m := re.search(r'on page (\d+)', text)) else None)
    if text.startswith('Clinical overlap'):
        what, code = _KIND_VI.get(where.get('kind')), where.get('code')
        return ((f'Trang {page}: ' if page else '') + (f'vùng che «{what}» ' if what else 'vùng che ')
                + (f'chạm vào chữ lâm sàng cần giữ ({code})' if code else 'chạm vào chữ lâm sàng cần giữ')
                + '. Hãy bỏ chọn hoặc thu hẹp vùng che rồi xuất lại.')
    pages = where.get('pages')
    if pages and text.startswith(('Review all pages', 'Cần duyệt tất cả trang')):
        return (f'Chưa duyệt hết các trang (còn trang {", ".join(str(n) for n in pages)}). '
                'Hãy duyệt tất cả trang hoặc xuất PDF thử (bản nháp) để xem lại.')
    if text.startswith('Review all files before exporting the case'):
        name = where.get('file')
        return 'Chưa duyệt hết các file trong ca' + (f' (còn file «{name}»)' if name else '') + '. Hãy duyệt hết hoặc xuất PDF thử (bản nháp).'
    if _VIETNAMESE.search(text):
        return text
    for rx, template in _CATALOGUE:
        if rx.fullmatch(text):
            return rx.sub(template, text)
    return 'Lỗi hệ thống: ' + text


def _vi_chain(chain, where):
    """'ValueError: Empty PDF <- OSError: ...' -> the same chain with every message in Vietnamese."""
    parts = []
    for part in chain.split(' <- '):
        m = re.match(r'^(\w+): (.*)$', part, re.S)
        parts.append(f'{m.group(1)}: {vi_message(m.group(2), where)}' if m else vi_message(part, where))
    return ' <- '.join(parts)


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
    root_cause: str | None = None,
) -> dict:
    now_ts = time.time()
    iso = iso_now()
    msg = str(exc)
    where = getattr(exc, 'where', None) or None
    err_type = type(exc).__name__ if isinstance(exc, BaseException) else "Error"
    code_loc = extract_code_location(exc) if isinstance(exc, BaseException) else None
    cat = category or (CATEGORY_FILE_ERROR if where else classify_error(exc, stage=stage, message=msg))  # located = a problem of that file
    source_file = source_file or (where or {}).get('file')
    rc = _vi_chain(root_cause or extract_root_cause(exc), where)

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
        'message': vi_message(msg, where),
        'root_cause': rc,
        'code_location': code_loc,
    }
    if record['message'] != msg:
        record['message_original'] = msg  # kept for developers; the UI shows the Vietnamese text
    if where:
        record['where'] = where
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
