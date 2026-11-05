# Windows 11 Desktop Workspace & Pre-Cloned Folder Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tối ưu hóa quy trình khử định danh trên Windows 11 bằng cách khởi tạo Workspace động ngoài Desktop (`<Tên_Tự_Đặt>\Data_Root` và `Data_Deidentified`), tự động clone các folder bệnh án trống ngay khi nạp đường dẫn, định tuyến xuất PDF hàng loạt về đúng folder từng bệnh án (không trộn lẫn, bỏ tên `BAN_GIAO_<hex>`), tạo bản sao đối chiếu khi trùng, và trích xuất báo cáo 100% từ quá trình chạy test case thật.

**Architecture:**
1. **Desktop Workspace Manager (`app.py`, `delivery.py`):** Tự động xác định đường dẫn Desktop trên Windows 11 (hỗ trợ cả `OneDrive\Desktop` qua `SHGetKnownFolderPath` và `%USERPROFILE%\Desktop`), khởi tạo `<Desktop>\<Workspace_Name>\Data_Root` (đầu vào) và `Data_Deidentified` (đầu ra), lưu cấu hình tại `HMU_JOBS/workspace_config.json`.
2. **Pre-Clone Empty Folder Engine (`delivery.py`, `batch.py`, `app.py`):** Ngay khi người dùng nạp đường dẫn từ `Data_Root` qua `/open_path` hoặc `/batch/enqueue`, hệ thống quét danh sách các folder bệnh án nguồn, tạo sẵn các folder trống có tên giống hệt bên trong `Data_Deidentified`, đồng thời lưu khóa ánh xạ `target_folder` cho từng file PDF trong `case_manifest.json` và bảng `jobs` (`queue.sqlite3`).
3. **1:1 Patient Folder Export & Collision Copy (`delivery.py`, `batch.py`):** Khi bấm xuất đơn lẻ hoặc hàng loạt (`/export_folder`, `/batch/release_folder`, `/batch/release`), mỗi file PDF đã duyệt sẽ được đổ thẳng về đúng `target_folder` đã clone của bệnh án đó; nếu đã tồn tại bản xuất trước thì giữ nguyên bản cũ, xuất ra bản sao đổi tên (`_Copy1`, `_Copy2`...) kèm thông báo đối chiếu. Mọi file báo cáo (`manifest.json`, `qc.json`, `AUDIT_SUMMARY.md`) đều do pipeline thật sinh ra trong quá trình xử lý PDF thật.

**Tech Stack:** Python 3 stdlib (`pathlib`, `sqlite3`, `shutil`, `ctypes`, `hashlib`, `json`), PyMuPDF (`fitz`), Vanilla HTML/CSS/JS, `unittest`, Node.js `vm` test runner.

**Spec:** Thiết kế thống nhất trong phiên làm việc ngày 2026-11-05.

## Global Constraints

- **Tuyệt đối không tự tạo (fake/mock/hardcode import) dữ liệu báo cáo:** Mọi báo cáo nghiệm thu (`manifest.json`, `qc.json`, `error_report.json`, `AUDIT_SUMMARY.md`) phải được sinh ra tự động từ việc chạy engine (`prepare` / `export` / `verify_output` / `batch_worker.py`) trên các file PDF test case thật trên đĩa.
- **Không nhầm lẫn giữa các bệnh án:** Khi quét và xuất hàng loạt nhiều folder bệnh án, file PDF thuộc folder gốc nào trong `Data_Root` chỉ được phép đổ vào đúng folder mang tên đó trong `Data_Deidentified`.
- **Không hardcode tên folder tổng ngoài Desktop:** Người dùng được tự nhập tên folder Workspace (ví dụ: `HMU_Dot1_TimMach`), bên trong luôn gồm 2 thư mục chuẩn `Data_Root` và `Data_Deidentified`.
- **Không ghi đè làm mất kết quả cũ:** Khi folder/file đích đã có kết quả từ lần xuất trước, tự động tạo bản sao đổi tên (`_Copy1`, `_Copy2`) và trả thông báo để người dùng đối chiếu.
- Đồng bộ đầy đủ code và test giữa `HMU_KhuDinhDanh.V3` và `HMU_KhuDinhDanh.V3 (NixOS)`.

## Review Focus

- Máy Windows 11 bật đồng bộ OneDrive làm đổi đường dẫn Desktop sang `C:\Users\<User>\OneDrive\Desktop`: hàm `resolve_desktop_path()` phải lấy đúng đường dẫn Desktop thực tế từ Windows Shell hoặc fallback an toàn.
- Khi nạp nhiều folder bệnh án có các file PDF trùng tên nhau (ví dụ `BN_01/Tờ_bìa.pdf` và `BN_02/Tờ_bìa.pdf`): lúc xuất hàng loạt phải đổ về 2 folder riêng `Data_Deidentified/BN_01/Tờ_bìa.pdf` và `Data_Deidentified/BN_02/Tờ_bìa.pdf`, không bị đè hoặc gom chung.
- Khi người dùng mới chỉ nạp folder vào công cụ mà chưa xuất: các folder bệnh án tương ứng trong `Data_Deidentified` đã phải được tạo sẵn ở trạng thái trống (0 file PDF) để người dùng kiểm tra cấu trúc ngay lập tức.
- Khi xuất lại lần 2 cho cùng 1 bệnh án đã xuất trước đó: giữ nguyên folder/file cũ và tạo bản sao `_Copy1` kèm cảnh báo Toast 10s trên giao diện.
- Báo cáo kiểm thử cuối mỗi phase phải đọc trực tiếp từ file JSON/PDF thật do hệ thống xuất ra kèm kiểm tra mã băm `SHA-256`.

---

## Phase 1: Khởi Tạo Workspace Động Ngoài Desktop Windows 11 (`Data_Root` & `Data_Deidentified`)

### Task 1.1: Xây dựng Desktop Workspace Manager & API (`/workspace/init`, `/workspace/state`, `/workspace/open_explorer`)

**Files:**
- Modify: `HMU_KhuDinhDanh.V3/delivery.py`
- Modify: `HMU_KhuDinhDanh.V3/app.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/delivery.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/app.py`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_app.py`

**Interfaces:**
- Produces:
  - `delivery.resolve_desktop_path(override_base: Path | None = None) -> Path`
  - `delivery.init_desktop_workspace(workspace_name: str, *, internal_root: Path, desktop_base: Path | None = None) -> dict`
    Trả về:
    ```json
    {
      "workspace_name": "HMU_Dot1_TimMach",
      "workspace_dir": "C:\\Users\\...\\Desktop\\HMU_Dot1_TimMach",
      "data_root": "C:\\Users\\...\\Desktop\\HMU_Dot1_TimMach\\Data_Root",
      "data_deidentified": "C:\\Users\\...\\Desktop\\HMU_Dot1_TimMach\\Data_Deidentified"
    }
    ```
  - `POST /workspace/init` (body: `{"workspace_name": "..."}`) và `GET /state` trả kèm trường `"workspace"`.

- [x] **Step 1: Viết failing test trong `test_app.py` kiểm tra khởi tạo Desktop Workspace động**
  Kiểm tra:
  1. Gọi `POST /workspace/init` với `workspace_name="BenhAn_Dot01"` tạo đúng 2 thư mục `Data_Root` và `Data_Deidentified` trên đĩa và lưu vào `HMU_JOBS/workspace_config.json`.
  2. Tên chứa ký tự không hợp lệ trên Windows (`<>:"/\|?*` hoặc `..`) bị chặn với mã lỗi 400 (`FILE_ERROR`).
  3. `GET /state` trả về đúng cấu hình `workspace` đã lưu khi mở lại phiên làm việc.
- [x] **Step 2: Chạy test để xác nhận RED (Fail)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -k "workspace" -v`
  Expected: FAIL (404 Not Found cho `/workspace/init`).
- [x] **Step 3: Triển khai `resolve_desktop_path`, `init_desktop_workspace` trong `delivery.py` và endpoint `/workspace/init` trong `app.py`**
- [x] **Step 4: Chạy lại test để xác nhận GREEN (Pass)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -k "workspace" -v`
  Expected: PASS (exit code 0).

---

## Phase 2: Cơ Chế Tự Động Clone Folder Trống Ngay Khi Nhập Đường Dẫn (`Pre-Clone on Ingest`)

### Task 2.1: Tự động clone vỏ thư mục bệnh án trống sang `Data_Deidentified` và khóa ánh xạ `target_folder` khi gọi `/open_path` & `/batch/enqueue`

**Files:**
- Modify: `HMU_KhuDinhDanh.V3/delivery.py`
- Modify: `HMU_KhuDinhDanh.V3/batch.py`
- Modify: `HMU_KhuDinhDanh.V3/app.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/delivery.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/batch.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/app.py`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_batch.py`, `HMU_KhuDinhDanh.V3 (NixOS)/test_app.py`

**Interfaces:**
- Consumes: `workspace_config.json` (`data_root`, `data_deidentified`) hoặc `destination` được truyền vào.
- Produces:
  - `delivery.preclone_patient_folders(input_paths: list[Path], destination_root: Path, *, data_root: Path | None = None) -> dict`
    Tạo sẵn các folder bệnh án trống bên trong `destination_root` khớp 100% tên folder gốc và trả về bảng ánh xạ `{str(source_pdf): str(target_patient_folder)}` cùng danh sách `cloned_folders`.
  - Cập nhật `batch.enqueue(db_path, sources, *, target_folders=None)` lưu đường dẫn `target_folder` của từng file PDF trong bảng `jobs` (cột `target_folder TEXT NOT NULL DEFAULT ''`, tự động migrate schema bằng `ALTER TABLE` nếu DB cũ chưa có cột này).
  - Cập nhật `/open_path` và `/batch/enqueue` trả thêm `cloned_folders: [...]` trong JSON response.

- [x] **Step 1: Viết failing test trong `test_batch.py` và `test_app.py` kiểm tra clone folder trống lúc nạp**
  Kiểm tra:
  1. Tạo 2 folder bệnh án thật trong `Data_Root`: `Data_Root/BA001_NguyenVanA/to_bia.pdf` và `Data_Root/BA002_TranThiB/xet_nghiem.pdf`.
  2. Gọi `POST /batch/enqueue` với đường dẫn `Data_Root` (hoặc từng folder): ngay lập tức trong `Data_Deidentified` xuất hiện 2 folder trống `Data_Deidentified/BA001_NguyenVanA` và `Data_Deidentified/BA002_TranThiB` (chưa có file PDF nào bên trong).
  3. Kiểm tra trong SQLite `jobs`: bản ghi của `to_bia.pdf` có `target_folder` trỏ đúng vào `Data_Deidentified/BA001_NguyenVanA`, và bản ghi của `xet_nghiem.pdf` trỏ đúng vào `Data_Deidentified/BA002_TranThiB`.
- [x] **Step 2: Chạy test để xác nhận RED (Fail)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_batch.py" -k "preclone" -v`
  Expected: FAIL.
- [x] **Step 3: Triển khai `preclone_patient_folders` trong `delivery.py`, cập nhật schema/enqueue trong `batch.py` và nối vào `/open_path`, `/batch/enqueue` trong `app.py`**
- [x] **Step 4: Chạy lại test để xác nhận GREEN (Pass)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_batch.py" -k "preclone" -v && python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -k "preclone" -v`
  Expected: PASS (exit code 0).

---

## Phase 3: Định Tuyến Xuất PDF 1:1 Về Đúng Folder Đã Clone & Cơ Chế Bản Sao Đối Chiếu

### Task 3.1: Cập nhật `export_reviewed_folder` (`delivery.py`) xuất thẳng vào folder gốc đã clone & tạo bản sao `_CopyN` khi trùng

**Files:**
- Modify: `HMU_KhuDinhDanh.V3/delivery.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/delivery.py`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_app.py`

**Interfaces:**
- Consumes: `case_manifest.json` (`source_path`) hoặc `review.json` (`source_path`, `original_name`).
- Produces:
  - `delivery.resolve_target_folder_with_copy(base_dest: Path, folder_name: str, expected_pdfs: list[str]) -> tuple[Path, bool, str | None]`
    - Nếu `<base_dest>/<folder_name>` đang trống (vừa được pre-clone) hoặc chưa tồn tại: dùng trực tiếp `<base_dest>/<folder_name>`, `copied=False`.
    - Nếu `<base_dest>/<folder_name>` đã chứa file PDF hoặc `manifest.json` từ lần xuất trước: giữ nguyên folder cũ, tạo `<base_dest>/<folder_name>_Copy1` (tăng dần `_Copy2`...), trả về `copied=True, copied_from=str(base_dest / folder_name)`.
  - `export_reviewed_folder` trả về:
    `{"directory": str(folder), "outputs": [...], "count": len(records), "pending": pending, "copied_for_comparison": bool, "original_directory": str | None}`

- [x] **Step 1: Viết failing test trong `test_app.py` cho xuất folder giữ đúng tên gốc và xuất lần 2 tạo bản sao `_Copy1`**
- [x] **Step 2: Chạy test để xác nhận RED (Fail)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -k "export_folder" -v`
  Expected: FAIL (hiện tại vẫn sinh `BAN_GIAO_...`).
- [x] **Step 3: Cập nhật `delivery.py` bỏ `BAN_GIAO_...`, đổ thẳng vào folder đã clone theo tên gốc và tạo `_Copy1` khi xuất trùng**
- [x] **Step 4: Chạy lại test để xác nhận GREEN (Pass)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_app.py" -k "export_folder" -v`
  Expected: PASS.

### Task 3.2: Cập nhật `release_folder` và `release_job` (`batch.py`) đổ từng PDF về đúng folder bệnh án đã clone (Không trộn lẫn bệnh án)

**Files:**
- Modify: `HMU_KhuDinhDanh.V3/batch.py`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/batch.py`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_batch.py`, `HMU_KhuDinhDanh.V3 (NixOS)/test_batch_manage.py`

**Interfaces:**
- Consumes: `row['target_folder']`, `row['source_path']`, `destination` trong `release_folder` và `release_job`.
- Produces:
  - Khi gọi `release_folder(db_path, paths, destination)`:
    - Nhóm các job đã đạt QC theo đúng folder bệnh án gốc của từng job (`target_folder` trong `destination`).
    - Đổ file PDF của bệnh án nào về đúng folder đã clone của bệnh án đó (`Data_Deidentified/<Tên_Folder_Bệnh_Án>/<Tên_PDF>.pdf`).
    - Ghi `manifest.json` và `qc.json` riêng cho từng folder bệnh án từ dữ liệu thật của các PDF trong folder đó.
    - Nếu folder bệnh án đó đã có sẵn file từ lần bàn giao trước (với nội dung/revision mới): tạo bản sao `<Tên_Folder_Bệnh_Án>_Copy1` (hoặc `<Tên_File>_Copy1.pdf`) và trả danh sách `comparisons: [{"source_folder": ..., "target_folder": ..., "copied_from": ...}]`.

- [x] **Step 1: Viết failing test trong `test_batch.py` kiểm tra xuất hàng loạt nhiều folder bệnh án có file trùng tên (`to_bia.pdf`) đổ về đúng từng folder đã clone mà không trộn lẫn**
- [x] **Step 2: Chạy test để xác nhận RED (Fail)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_batch.py" -k "release" -v`
  Expected: FAIL.
- [x] **Step 3: Cập nhật `release_folder` và `release_job` trong `batch.py`**
- [x] **Step 4: Chạy lại toàn bộ test `test_batch.py` và `test_batch_manage.py` để xác nhận GREEN (Pass)**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3 (NixOS)" -p "test_batch*.py" -v`
  Expected: PASS.

---

## Phase 4: Giao Diện Windows 11 Desktop Workspace & Báo Cáo Nghiệm Thu Từ Test Case Thật

### Task 4.1: Tích hợp UI Desktop Workspace (`review.html`, `ui/review.js`) & Cảnh báo Bản sao đối chiếu

**Files:**
- Modify: `HMU_KhuDinhDanh.V3/review.html`
- Modify: `HMU_KhuDinhDanh.V3/ui/review.js`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/review.html`
- Modify: `HMU_KhuDinhDanh.V3 (NixOS)/ui/review.js`
- Test: `HMU_KhuDinhDanh.V3 (NixOS)/test_ui_local_folder.js`, `HMU_KhuDinhDanh.V3 (NixOS)/test_ui_batch.js`

**Interfaces:**
- Produces:
  - Khối `#workspacePanel` trên `review.html`: ô nhập tên folder ngoài Desktop (`#workspaceName`), nút `#initWorkspace` ("Tạo / Kết nối Workspace trên Desktop"), nút `#scanWorkspaceRoot` ("Quét toàn bộ Data_Root"), hiển thị đường dẫn `Data_Root` và `Data_Deidentified`.
  - Tự động điền `#folderDestination` bằng `workspace.data_deidentified`.
  - Khi `/open_path` hoặc `/batch/enqueue` trả về `cloned_folders`, bắn Toast thông báo số lượng folder bệnh án trống đã clone sẵn trong `Data_Deidentified`.
  - Khi `/export_folder` hoặc `/batch/release_folder` trả về `copied_for_comparison` / `comparisons`, bắn Toast thông báo rõ tên bản sao để người dùng đối chiếu.

- [x] **Step 1: Viết failing UI tests trong `test_ui_local_folder.js` và `test_ui_batch.js`**
- [x] **Step 2: Chạy Node UI tests để xác nhận RED (Fail)**
  Run: `node "HMU_KhuDinhDanh.V3/test_ui_local_folder.js" && node "HMU_KhuDinhDanh.V3/test_ui_batch.js"`
  Expected: FAIL.
- [x] **Step 3: Cập nhật `review.html` và `ui/review.js`**
- [x] **Step 4: Chạy lại toàn bộ Node UI tests để xác nhận GREEN (Pass)**
  Run: `node "HMU_KhuDinhDanh.V3/test_ui_local_folder.js" && node "HMU_KhuDinhDanh.V3/test_ui_batch.js" && node "HMU_KhuDinhDanh.V3/test_ui_save.js"`
  Expected: PASS.

### Task 4.2: Kiểm thử End-to-End trên Test Case Thật & Trích xuất Báo Cáo Thật (Không Tự Import)

**Files:**
- Create: `HMU_KhuDinhDanh.V3/test_real_workspace_e2e.py`

**Interfaces:**
- Chạy thực tế qua HTTP Server (`app.create_server`) + Worker thật (`batch.run_queue` / `batch_worker.py`) + Engine thật (`engine.prepare`, `engine.export`, `output_qc.verify_output`) trên các folder bệnh án test case thật.
- Xuất báo cáo tổng hợp được đọc trực tiếp từ các tệp `manifest.json`, `qc.json`, `AUDIT_SUMMARY.md` và `error_report.json` sinh ra trên ổ đĩa.

- [x] **Step 1: Viết kịch bản E2E `test_real_workspace_e2e.py` chạy trên dữ liệu PDF thật và kiểm chứng toàn bộ chuỗi SHA-256 + báo cáo sinh ra từ engine**
- [x] **Step 2: Chạy `test_real_workspace_e2e.py` và toàn bộ unittest suite để lấy báo cáo thật**
  Run: `python3 -m unittest discover -s "HMU_KhuDinhDanh.V3" -p "test_*.py" -v`
  Expected: 100% PASS, in báo cáo trích xuất trực tiếp từ `Data_Deidentified/<Folder_Bệnh_Án>/manifest.json` và `qc.json`.
