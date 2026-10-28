# Complete Span, Ink-Boundary Extension, and OCR Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triệt tiêu hoàn toàn tình trạng xóa hụt chữ/sót đuôi (như "Lộc", "Cường", "Nhân D/C...", BHYT, tên điều dưỡng, bác sĩ) trên PDF scan và vector bằng kỹ thuật Hybrid Field-Span Geometry, Pixel Ink-Projection Expansion, nâng cấp độ nhạy OCR 200 DPI và làm sạch danh sách hộp đỏ (Subsumption Merging).

**Architecture:**
1. Cải tiến `ocr_helper.py` và `engine.py`: Nâng DPI mặc định cho OCR lên 200 DPI (giữ đa luồng bất đồng bộ siêu tốc).
2. Nâng cấp `hmu_recognizers.py`: Bổ sung rule neo dòng cho trường địa chỉ có bullet `- `, người nhà rút gọn (`ngu&i nhå: ...`), tên bác sĩ chứa ký tự nhiễu sau chức danh, và BHYT lỗi `BHVT`.
3. Bổ sung `engine.expand_rects_with_pixel_ink(page, proposals)`: Dò vết mực thực tế (ink projection/bounding box) của dòng chữ trên ảnh/page raster để tự động kéo dài hộp đỏ bao trùm toàn bộ chữ cuối bị OCR drop/bỏ sót.
4. Bổ sung `engine.subsume_overlapping_proposals(proposals)`: Hợp nhất các hộp con nằm lọt trong hộp mẹ (ví dụ "VĂN HƯỞNG" nằm trong "TRỊNH VĂN HƯỞNG"), giúp giao diện sạch và danh sách proposal rõ ràng.
5. Cập nhật `test_hmu_recognizers.py` và `test_workflow.py` với các ca test thực tế từ 46 trang của bệnh án mẫu.

**Tech Stack:** Python 3.12, PyMuPDF (fitz), Windows.Media.Ocr (PowerShell async bridge), regex, unittest.

---

### Task 1: Nâng cấp Recognizer và Regex cho các trường bị trượt/cắt ngắn (TDD)
**Files:**
- Modify: `d:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\hmu_recognizers.py`
- Test: `d:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\test_hmu_recognizers.py`

- [ ] **Step 1: Viết test failing cho các trường hợp trượt nhãn và tên nhiễu**
- [ ] **Step 2: Chạy test xác nhận FAIL**
- [ ] **Step 3: Sửa `hmu_recognizers.py` để vượt qua test**
- [ ] **Step 4: Chạy lại test xác nhận PASS**

---

### Task 2: Cài đặt Ink-Bounding-Box Expansion & Box Merging trong `engine.py` (TDD)
**Files:**
- Modify: `d:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\engine.py`
- Test: `d:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\test_workflow.py`

- [ ] **Step 1: Viết test failing cho việc mở rộng theo vết mực (Ink Expansion) và triệt tiêu hộp trùng lặp (Subsumption)**
- [ ] **Step 2: Chạy test xác nhận FAIL**
- [ ] **Step 3: Cài đặt `expand_rects_with_pixel_ink` và `merge_and_subsume_proposals` trong `engine.py`**
- [ ] **Step 4: Chạy lại test xác nhận PASS**

---

### Task 3: Tối ưu DPI OCR và Tích hợp vào Pipeline `prepare()`
**Files:**
- Modify: `d:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\engine.py`
- Modify: `d:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\ocr_helper.py`

- [ ] **Step 1: Cấu hình `prepare()` sử dụng DPI 200 mặc định cho OCR và tự động áp dụng ink expansion cho các trường Tên/Địa chỉ/Bác sĩ**
- [ ] **Step 2: Chạy toàn bộ test suite `test_hmu_recognizers.py` và `test_workflow.py`**

---

### Task 4: Chạy Verification Toàn Diện trên Hồ Sơ 46 Trang (`TRỊNH VĂN HƯỞNG`)
- [ ] **Step 1: Chạy chuẩn bị lại job cho file PDF 46 trang**
- [ ] **Step 2: Quét kiểm tra các trang từng bị sót (P01 Địa chỉ "Lộc", P04 Bác sĩ "Cường", P03 BHYT/Người nhà, P10/11 "Tuấn")**
- [ ] **Step 3: Đảm bảo không còn bất kỳ ký tự PII nào bị sót và không làm lem sang các cột bảo vệ (Tuổi, Giới tính)**
