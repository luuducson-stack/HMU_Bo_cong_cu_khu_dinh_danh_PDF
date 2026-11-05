# Error Notification & JSON Diagnostic Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng pipeline phát hiện, phân loại (File lỗi vs Code lỗi), hiển thị thông báo Toast (góc trên bên phải `top: 100px`, trượt từ phải qua trái, hiển thị `10s`) và xuất báo cáo JSON có cấu trúc xuyên suốt vòng đời từ lúc chạy `MO_CONG_CU.bat` đến khi tắt terminal.

**Architecture:** Thiết kế theo nguyên tắc **Boundary Capture → Structured JSON Ledger → Top-Right Slide Toast**:
1. Tầng Backend (`error_pipeline.py` tích hợp vào `app.py`, `batch.py`, `batch_worker.py`) bắt mọi ngoại lệ tại ranh giới xử lý, tự động phân loại `FILE_ERROR` (PDF hỏng, mật khẩu, đường dẫn sai, OCR lỗi) và `CODE_ERROR` (trích xuất `code_file`, `line`, `function` từ `traceback`), ghi bền vững vào `HMU_JOBS/error_report.json` và trả kèm trong JSON response / `/progress` / `/batch/status` / `GET /errors/report.json`.
2. Tầng Frontend (`ui/review.css`, `ui/review.js`) nâng cấp `.toast-container` lên góc trên phải (`top: 100px; right: 20px`), animation trượt từ phải sang trái (`translateX(100%)` → `translateX(0)`), giữ `10000ms` (10s), đồng thời nối toàn bộ điểm bắt lỗi đồng bộ, bất đồng bộ (`/progress`) và hàng đợi ngầm (`/batch/status` khi phát hiện job mới chuyển sang `FAILED`) vào `notify(..., 'err')`.
3. Tầng Lifecycle (`MO_CONG_CU.bat` + `app.py:main()`) đảm bảo cả lỗi khởi tạo server/port/venv lẫn lỗi phát sinh trong phiên đều được chốt vào `HMU_JOBS/error_report.json` trước khi đóng terminal.

**Tech Stack:** Python 3 stdlib (`traceback`, `json`, `pathlib`, `time`, `threading`), PyMuPDF (`fitz`), Vanilla HTML/CSS/JS, Node.js `vm` test runner, `unittest`. Không thêm bất kỳ dependency ngoài nào.

**Spec:** Graphify Architecture Report (`graphify-out/GRAPH_REPORT.md` — Communities 0, 1, 3, 5, 8, 14, 20, 39, 44).

## Global Constraints

- Không thay đổi thuật toán nhận diện PII, OCR DPI, hoặc bộ vùng chuẩn (`engine.py`, `hmu_recognizers.py`, `ocr_helper.py`, `output_qc.py` giữ nguyên logic nghiệp vụ).
- Không ghi dữ liệu PII thô (nội dung văn bản bệnh án) vào `error_report.json`; chỉ ghi tên file nguồn (`source_name`), mã công việc (`job_id`/`queue_id`), giai đoạn (`stage`), vị trí code (`code_file`, `line`, `function`), loại lỗi (`category`, `error_type`) và thông điệp lỗi an toàn (`message`).
- Giữ tương thích ngược 100% với trường `{"error": "..."}` trong các HTTP response hiện tại để không làm gãy bất kỳ test cũ nào trong bộ 380+ unittest và Node UI tests.
- Đồng bộ thay đổi giữa `HMU_KhuDinhDanh.V3 (NixOS)` (nơi chứa bộ test) và `HMU_KhuDinhDanh.V3` (bản chạy Windows với `MO_CONG_CU.bat`).

## Review Focus

- Lỗi ngầm trong Batch Worker (`batch_worker.py` dừng với exit code != 0 hoặc exception): UI đang ở tab khác vẫn phải nhận được Toast báo tên file lỗi + lý do đúng 1 lần (deduplicated theo `queue_id` + `updated`), không spam lặp lại mỗi 2 giây khi `pollBatch()` chạy.
- Lỗi bất đồng bộ qua `requestAsync` (`/upload`, `/open_path`, `/export`, `/export_folder`): khi `/progress` trả `status: "error"`, cả `status(..., true)` lẫn `notify(..., 'err')` đều phải hiển thị chi tiết file lỗi / bước lỗi và ghi vào `HMU_JOBS/error_report.json`.
- Phân biệt rõ `FILE_ERROR` (do tệp đầu vào/đường dẫn của người dùng) và `CODE_ERROR` (do lỗi logic/hệ thống có kèm `code_file:line` trong `traceback`).
- Hiệu ứng CSS Toast: `top: 100px; right: 20px`, trượt mượt từ phải qua trái (`translateX`), tự đóng sau đúng `10000ms` (10s).
- Khi tắt terminal (`Ctrl+C` hoặc đóng phiên `MO_CONG_CU.bat`), `app.py` và `MO_CONG_CU.bat` thông báo rõ nếu trong phiên có lỗi và chỉ đường dẫn tới `HMU_JOBS\error_report.json`.

---

### Phase 1 (Task 1): UI Notification — Vị trí Top-Right (`top: 100px`), Trượt Phải qua Trái & Hiển thị 10s

**Files:**
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/ui/review.css:59-77`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/ui/review.js:57-67`
- Modify: `HMU_KhuDinhDanh.V3/ui/review.css:59-77`
- Modify: `HMU_KhuDinhDanh.V3/ui/review.js:57-67`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_ui_local_folder.js`

**Interfaces:**
- Consumes: `#toastContainer` trong `ui/review.html`
- Produces: `notify(msg, type = 'info', duration = 10000)` trong `ui/review.js` và bộ CSS `.toast-container` (`top: 100px; right: 20px`), `@keyframes pillToastIn` (`translateX(110%)` → `translateX(0)`), `.pill-toast.out` (`translateX(110%)`).

- [x] **Step 1: Viết test kiểm tra thời gian hiển thị 10s (10000ms) và CSS top-right slide-in**
  Trong `test_ui_local_folder.js`, bắt tham số `delay` truyền vào `setTimeout` khi gọi `notify()` để xác nhận `delay === 10000`, và kiểm tra nội dung `ui/review.css` chứa `top: 100px`, `right: 20px`, `translateX`.
- [x] **Step 2: Chạy test để xác nhận RED (Fail)**
  Run: `node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_local_folder.js"`
  Expected: FAIL vì hiện tại `setTimeout` đang dùng `2800` và `review.css` đang dùng `bottom: 20px` + `translateY`.
- [x] **Step 3: Cập nhật `ui/review.css` và `ui/review.js`**
  - Trong `ui/review.css`:
    - Đặt `.toast-container` ở `position: fixed; top: 100px; right: 20px; z-index: 99; overflow-x: hidden;`
    - Cập nhật `@keyframes pillToastIn` từ `transform: translateX(110%)` sang `transform: translateX(0)`.
    - Cập nhật `.pill-toast.out` thành `opacity: 0; transform: translateX(110%);`.
  - Trong `ui/review.js`:
    - Cập nhật `notify(msg, type='info', duration=10000)` sử dụng `duration` mặc định `10000` (10s).
- [x] **Step 4: Chạy lại bộ Node UI tests để xác nhận GREEN (Pass)**
  Run: `node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_local_folder.js" && node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_batch.js" && node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_save.js"`
  Expected: PASS.

---

### Phase 2 (Task 2): Backend Error Collector & Chuẩn hóa File JSON Báo Lỗi (`error_report.json`)

**Files:**
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/app.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/batch.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/batch_worker.py`
- Modify: `HMU_KhuDinhDanh.V3/app.py`
- Modify: `HMU_KhuDinhDanh.V3/batch.py`
- Modify: `HMU_KhuDinhDanh.V3/batch_worker.py`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_app.py`, `HMU_KhuDinhDanh.V3 (NixOS)/test_batch_worker.py`

**Interfaces:**
- Produces:
  - Hàm `record_error_event(root_dir, exc, *, stage, source_file=None, job_id=None, queue_id=None, http_path=None) -> dict`
  - Cấu trúc mỗi bản ghi lỗi JSON:
    ```json
    {
      "id": "err_...",
      "timestamp": 1762326672.5,
      "iso_time": "2026-11-05T14:11:12+07:00",
      "category": "FILE_ERROR | CODE_ERROR | CONFLICT_ERROR",
      "stage": "STARTUP | UPLOAD | OPEN_PATH | PREPARE | EXPORT | BATCH_ENQUEUE | BATCH_WORKER | QC | HTTP_API",
      "source_file": "benh_an_01.pdf",
      "job_id": "...",
      "queue_id": "...",
      "error_type": "ValueError",
      "message": "PDF hỏng, trống hoặc có mật khẩu; cần kiểm tra nguồn.",
      "code_location": {
        "file": "batch.py",
        "line": 145,
        "function": "enqueue"
      }
    }
    ```
  - Lưu trữ tại: `<root>/error_report.json` (gồm `session_started_at`, `total_errors`, `errors: [...]`) và `error_<attempt>.json` trong từng worker.
  - Endpoint mới: `GET /errors/report` trả về toàn bộ JSON báo cáo lỗi của phiên/hệ thống (có thể tải về dưới dạng file `.json`).

- [x] **Step 1: Viết unit test trong `test_app.py` và `test_batch_worker.py` cho `error_report.json` và `GET /errors/report`**
  Kiểm tra:
  1. Khi gọi `/open_path` với đường dẫn không tồn tại → trả về 400 kèm `error` và `error_detail` (`category: "FILE_ERROR"`, `stage: "OPEN_PATH"`), đồng thời ghi vào `root / "error_report.json"`.
  2. Khi tác vụ ngầm (`run_task` hoặc `batch_worker.py`) gặp lỗi code (`RuntimeError`/`ValueError`) → `error_detail` chứa đúng `code_location.file`, `code_location.line`, `code_location.function` và `category: "CODE_ERROR"`.
  3. `GET /errors/report` trả về đúng nội dung JSON hợp lệ.
- [x] **Step 2: Chạy test để xác nhận RED (Fail)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -v`
  Expected: FAIL vì chưa có `/errors/report` và `error_report.json`.
- [x] **Step 3: Cài đặt helper ghi nhận lỗi và tích hợp vào `app.py`, `batch.py`, `batch_worker.py`**
  - Trích xuất frame cuối cùng thuộc codebase dự án từ `traceback.extract_tb(exc.__traceback__)` để lấy `file`, `line`, `function`.
  - Phân loại tự động: nếu lỗi thuộc nhóm file đầu vào (PDF hỏng/trống/mật khẩu, đường dẫn không tồn tại, file không phải PDF) → `FILE_ERROR`; nếu là `Conflict` → `CONFLICT_ERROR`; các exception bất ngờ trong quá trình chạy engine/worker → `CODE_ERROR`.
  - Ghi atomic vào `root / 'error_report.json'` qua `save_json`.
  - Bổ sung nhánh `if path == '/errors/report':` trong `do_GET` của `app.py`.
- [x] **Step 4: Chạy lại unittest để xác nhận GREEN (Pass)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -v && python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_batch_worker.py" -v`
  Expected: PASS.

---

### Phase 3 (Task 3): Kết nối Pipeline Báo Lỗi Toàn Diện lên UI Toast (`ui/review.js`) & Vòng đời `MO_CONG_CU.bat`

**Files:**
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/ui/review.js`
- Modify: `HMU_KhuDinhDanh.V3/ui/review.js`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/MO_CONG_CU.bat`
- Modify: `HMU_KhuDinhDanh.V3/MO_CONG_CU.bat`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_ui_local_folder.js`, `HMU_KhuDinhDanh.V3 (NixOS)/test_ui_batch.js`

**Interfaces:**
- Consumes: `error_detail` từ HTTP responses, `/progress`, và danh sách `jobs` từ `/batch/status`.
- Produces:
  - Hàm `formatErrorToast(errOrDetail, fallbackFile)` trong `ui/review.js`: hiển thị rõ `[Lỗi File: <tên file>] <lý do>` hoặc `[Lỗi Code: <file.py>:<dòng>] <lý do>` qua `notify(..., 'err')` trong 10s.
  - Tự động phát hiện job mới chuyển sang `FAILED` trong `refreshBatch()` (dùng `seenFailedJobs = new Map()`) để bắn `notify(..., 'err')` ngay cả khi lỗi xảy ra ở worker chạy ngầm.
  - Trong `MO_CONG_CU.bat` và `app.py:main()`: khi khởi động lỗi hoặc khi tắt terminal, nếu có lỗi trong `HMU_JOBS\error_report.json` thì in tóm tắt số lỗi + đường dẫn file JSON ra màn hình console.

- [x] **Step 1: Viết test UI trong `test_ui_local_folder.js` và `test_ui_batch.js`**
  Kiểm tra:
  1. Các hành động lỗi ở `load`, `loadPath`, `batchAction`, `deleteBatch`, `saveSoon` đều tạo `.pill-toast.err` trong `#toastContainer`.
  2. Khi `/batch/status` trả về một job chuyển sang `state: 'FAILED'`, `refreshBatch()` tự động bắn 1 `.pill-toast.err` chứa tên file `source_name` và nguyên nhân `error`, và không bắn trùng ở lần poll kế tiếp nếu `updated` không đổi.
- [x] **Step 2: Chạy Node UI tests để xác nhận RED (Fail)**
  Run: `node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_batch.js"`
  Expected: FAIL.
- [x] **Step 3: Cập nhật `ui/review.js`, `app.py:main()` và `MO_CONG_CU.bat`**
  - Nối toàn bộ `catch(e)` còn thiếu trong `ui/review.js` vào `notify(..., 'err')`.
  - Bổ sung theo dõi `seenFailedJobs` trong `refreshBatch()` để thông báo ngay khi file trong hàng đợi bị `FAILED`.
  - Cập nhật `MO_CONG_CU.bat` để ghi JSON nếu thiếu `.venv` hoặc `app.py` thoát với mã lỗi `errorlevel != 0`, và hiển thị đường dẫn `HMU_JOBS\error_report.json`.
- [x] **Step 4: Chạy toàn bộ টেস্ট Suite (Python unittest + Node UI tests) & Cập nhật Graphify**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" && node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_local_folder.js" && node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_batch.js" && node "HMU_KhuDinhDanh.V3 (NixOS)/test_ui_save.js"`
  Expected: 100% PASS, 0 lỗi.
