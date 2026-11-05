# Queue Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Xóa từng mục/hàng loạt cùng dữ liệu làm việc an toàn; xuất các PDF đã duyệt theo đường dẫn nhập vào một thư mục.
**Architecture:** Tái sử dụng SQLite, khóa review và validation release hiện có; trạng thái DELETING cho dọn có thể thử lại; xuất thư mục mới qua staging và kiểm hash. Nối API/HTML/JS hiện tại.
**Tech Stack:** Python stdlib, PyMuPDF đã cài, HTML/JavaScript thuần; không thêm dependency.
**Spec:** ../specs/2026-11-03-queue-management-design.md

## Global Constraints

- Giữ nguồn, PDF bàn giao, engine/OCR/DPI/vùng chuẩn và job không chọn.
- Mục đang chạy/CANCELLING không được xóa; DELETING chỉ được thử xóa lại.
- Xuất nhóm dùng đầy đủ điều kiện human review/QC hiện hành, không bỏ qua cảnh báo.
- Làm tại checkout codex/pdf-safety-performance đang chứa phiên bản chưa commit được người dùng tiếp tục sử dụng; không tạo bản từ HEAD cũ, không commit thay đổi phiên trước.

## Review Focus

- Claim/retry/review đồng thời xóa: kiểm khóa, đọc lại trạng thái trong transaction.
- Junction, path ngoài jobs, nguồn/bàn giao trong cây dọn: kiểm từ chối trước xóa.
- Xóa bản chính cùng vài bản trùng: giữ liên kết bản trùng còn lại, không claim mục sắp dọn.
- Duyệt đủ nhưng QC cũ hoặc cảnh báo mở: không xuất; báo tên/lý do đúng.
- Scope nhiều thư mục/trùng tên và lỗi copy/đích có dữ liệu: không lẫn job, không ghi đè hoặc công bố nửa chừng.

### Task 1: Xóa an toàn

**Files:** batch.py, test_batch_manage.py.
**Interfaces:** delete_jobs(db_path, job_ids) -> {deleted: [id], skipped: [{id, source_name, reason}]}.

- [x] Viết test xóa nhóm, giữ source/delivered, active skip, xóa dở thử lại, duplicate promotion, path/junction/lock protection; chạy thấy FAIL do thiếu chức năng.
- [x] Thêm DELETING, validation cây dọn và delete_jobs, sửa worker publication guard để không tự đặt DELETING.
- [x] Chạy test_batch_manage và test_batch; 41/41 PASS sau bổ sung các ca thế hệ cũ và enqueue trong lúc dọn.

### Task 2: Xuất nhóm

**Files:** batch.py, test_batch_manage.py, test_batch_worker.py.
**Interfaces:** release_folder(db_path, paths, destination) -> {directory: str|null, exported: [{id, output}], pending: [{id, source_name, reason}]}.

- [x] Viết test thực pipeline nhỏ: đã/chưa duyệt, warning, stale QC, unreadable, scope, đích nội bộ/nguồn, copy hash/lỗi, giữ gói cũ; chạy RED.
- [x] Tách validation release dùng chung, thêm xuất theo scope; staged flat CASE PDFs + manifest/QC công khai; tái sử dụng current_verification và review lock.
- [x] Chạy test_batch_manage + hai release tests hiện có; 20/20 PASS trước bổ sung ba ca xóa; test_batch_manage + test_batch sau đó 41/41 PASS.

### Task 3: API, UI và nghiệm thu

**Files:** app.py, review.html, test_app.py, test_ui_batch.js, HUONG_DAN_SU_DUNG.md.
**Interfaces:** POST /batch/delete {queue_ids}; POST /batch/release_folder {paths,destination}; kết quả theo hai hàm trên.

- [x] Viết API/UI test token, active clear, selection/filter, confirm, save-before-delete/export, pending alert; chạy RED.
- [x] Nối nút xóa/chọn nhóm và xuất thư mục, vùng thông báo pending dùng textContent, cập nhật hướng dẫn.
- [x] Chạy toàn bộ unittest discover: 374 chạy, 373 PASS, 1 SKIP, 0 lỗi (125,906 giây). Hai bộ Node UI, pip check và git diff --check PASS. Smoke trình duyệt chọn theo lọc, xuất một PDF, alert hai tên thiếu, mở file chưa duyệt, duyệt và xuất lại hai PDF PASS; kiểm hash/mở/render PDF xuất PASS.
- [x] Một reviewer độc lập chỉ rà các thay đổi hiện tại; lỗi DELETING → cancel → retry được tái hiện hai ca RED→GREEN và kiểm lại toàn bộ suite. Không còn Critical/Important/Minor chưa xử lý trong lượt review này.

## Ledger

- Setup: baseline test_batch 20/20 PASS. Nhận lựa chọn xóa cả dữ liệu làm việc từ người dùng.
- Pre-flight: Task 1/2 cùng dùng review-operation lock; Task 3 tiêu thụ đúng response của hai hàm. Thứ tự khóa: review-operation trước transaction SQLite, không giữ transaction khi chờ file lock.
- Ruling: làm tại checkout hiện tại, không commit hoặc sao chép HEAD cũ — đây là phiên bản v20 đang được tiếp tục; chi phí là diff chứa thay đổi có sẵn, reviewer phải giới hạn phạm vi.
- Task 1: complete — 12 test xóa, RED→GREEN; chặn cây junction/ngoài queue, giữ nguồn/bàn giao, khóa review/worker, dọn mọi generation đúng ID, sửa liên kết bản trùng và enqueue khi DELETING.
- Task 2: complete — 9 test xuất nhóm RED→GREEN, hai release tests hiện có PASS; không chạy lại OCR nếu QC còn khớp.
- Task 3: API hai ca RED→GREEN; Node UI RED→GREEN (chọn theo lọc, xác nhận, chặn nếu lưu lỗi, clear active, alert tên pending). Đang chạy suite và smoke/review.
- Final: fixed cancel_job cho phép thoát DELETING — test_cancel_cannot_revive_partially_deleted_work và test_cancel_during_removal_cannot_leave_a_ghost_row RED→GREEN; suite 374 chạy/373 PASS/1 SKIP.
- Final: smoke phát hiện link tải giữ revision cũ sau lưu và xuất nhóm — bổ sung Node regression RED→GREEN; nạp lại QC/link của mục vừa xuất, filename REDACTED. Hai bộ Node UI cuối PASS. Sửa wrap đường dẫn dài ở báo cáo để không tràn ngang trên cửa sổ hẹp.
- Task 3: complete — API/UI/docs, suite, review và browser smoke đã kiểm. Engine/recognizer/OCR/output_qc và 409 vùng chuẩn có SHA không đổi so với v20.
- Final: declined-to-judge từ reviewer: nhận diện/OCR/DPI/oracle đã đối chiếu SHA, không thay; chương trình ngoài tự sửa filesystem trong lúc dọn không chịu khóa của ứng dụng, không mở rộng sang sandbox filesystem; suite/UI do agent chính chạy đã hoàn tất. Đây là giới hạn kiểm chứng, không phải lỗi đã chứng minh của tính năng.
- Không đo lại tốc độ 50/71 trang hoặc chạy bền/lô 50–2000 PDF thật trong task này; không dùng dữ liệu thật để thử xóa. Không commit/push hoặc đóng hàng đợi thật đang chạy. Cần lưu công việc rồi khởi động lại công cụ để nạp backend mới.
