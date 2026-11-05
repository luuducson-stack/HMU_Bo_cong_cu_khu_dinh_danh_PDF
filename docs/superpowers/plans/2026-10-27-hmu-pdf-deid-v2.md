# HMU PDF De-identification v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `HMU_KhuDinhDanh` to extract Coordinate-Linked Markdown (with offline OCR fallback for vector/scanned PDFs like `3.BVQT`), automatically select 99% of patient/doctor PII & signatures while preserving Age, Gender, Medical Record/Patient IDs, and Hospital Names, generate `AUDIT_SUMMARY.md`, and support both single-PDF cases (`2.BV71`, `3.BVQT`) and multi-PDF case folders (`1.DHYHN`) with 1-click fast visual QC.

**Architecture:** We extend `hmu_recognizers.py` for the updated retention policy (keeping `PATIENT_ID`, `MEDICAL_RECORD_ID`, `SOURCE_LINK_ID`, `AGE`, `GENDER`, hospital names) and OCR-tolerant/multi-format PII + doctor name extraction. We add `ocr_helper.py` to batch-OCR textless/vector PDF pages via Windows built-in `Windows.Media.Ocr.OcrEngine` mapped back to PDF point coordinates. We upgrade `engine.py`, `app.py`, and `review.html` to handle multi-watermark removal, 8-box DOB vs 2-box Age separation, automatic signature selection, `AUDIT_SUMMARY.md` generation, batch folder mode for `1.DHYHN`, and 1-click "Approve All Pages" in the UI.

**Tech Stack:** Python 3.12, PyMuPDF (`fitz` 1.26.6), `pypdf` (6.10.0), Windows Runtime `Windows.Media.Ocr` (via PowerShell bridge, 100% offline), Vanilla JS/HTML (`review.html`).

**Spec:** `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\docs\superpowers\specs\2026-10-27-hmu-pdf-deid-optimization-design.md`

## Global Constraints

- Run 100% offline on local machine without sending medical records to external cloud services.
- Keep `PATIENT_ID`, `MEDICAL_RECORD_ID`, `SOURCE_LINK_ID` (`Số lưu trữ`, `Số vào viện`, `Mã BA`, `Mã BN`, `Mã y tế`, `Mã KCB`, `Số phiếu`, `Mã bệnh phẩm`), `Tên Bệnh viện`, `Tuổi` (`AGE`), and `Giới tính` (`GENDER`).
- Redact (`selected = True` by default): `PATIENT_NAME`, `RELATIVE_NAME`, `PHONE_NUMBER_VN`, `ADDRESS_VN` (including province/city in patient/relative address lines), `DATE_OF_BIRTH` (including 8-box split DOB), `YEAR_OF_BIRTH`, `NATIONAL_ID`, `HEALTH_INSURANCE_ID` (including 5/6-box split BHYT), `HEALTHCARE_STAFF_NAME`, `SIGNATURE_REGION` (doctor/staff signature images, widgets, and scan signature zones), and `WATERMARK_TEXT`.
- Preserve 100% original PDF page layout and clinical images by applying white redaction rectangles `[x0, y0, x1, y1]` and rasterizing at 200 DPI (`engine.py`).
- For `1.DHYHN`, preserve individual PDF files (40–90 files per case) rather than merging them into one file.

## Review Focus

1. **8-box DOB adjacent to 2-box Age on Cover Page:** Redacting the 8 DOB boxes (`1|5|1|0|1|9|5|8`) must never redact the 2 Age boxes (`6|8` or `6|1`) located immediately to the right on the same horizontal row.
2. **Multi-instance Diagonal Watermark (`2.BV71`):** Pages with 6 diagonal watermarks (`Hồ Thị Minh Châu_20260803161916`) must have all 6 watermarks removed/redacted and must never seed `Hồ Thị Minh Châu` as `PATIENT_NAME`.
3. **Textless Vector/Scanned PDF (`3.BVQT`):** Pages with `page.get_text() == ""` must fall back to `ocr_helper.py` without raising `ValueError('No geometry for finding')`, and must detect both OCR-degraded PII (`HQ ten: TRAN BAN`, `con: Pham van huy-quang nhan`) and embedded signature bitmaps (`275x137`).
4. **Logo & Clinical Image Preservation:** Auto-selecting doctor signature images (`IMAGE_REVIEW`) must not select top-left hospital logos (`x0 < 220, y0 < 120`) or large clinical diagnostic images (`width > 240, height > 170`).
5. **Post-Inspection ID Preservation:** `Mã hồ sơ: 2603040231`, `Số lưu trữ: BA260608783`, `Mã y tế: 45/010/26/025448`, `Mã KCB: 2600012287` must remain unredacted in both `analyze_hmu_text` and `prepare`.

---

### Task 1: Policy Update, Case Seed Extractor & Enhanced Recognizers (`hmu_recognizers.py`)

**Files:**
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\hmu_recognizers.py`
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\test_hmu_recognizers.py`

**Interfaces:**
- Produces:
  - `analyze_hmu_text(text: str) -> List[Finding]`
  - `analyze_hmu_document(page_texts: List[str], external_seeds: Dict[str, List[str]] = None) -> Tuple[List[List[Finding]], Dict[str, List[str]]]`
  - `extract_case_seeds(source_path: Path) -> Dict[str, List[str]]`
  - `WATERMARK_RE: re.Pattern`

- [ ] **Step 1: Update `test_hmu_recognizers.py` with tests for ID preservation, watermark filtering, expanded doctor titles/headings, relative-address lines, and XML/folder seed extraction**
- [ ] **Step 2: Run `test_hmu_recognizers.py` to verify new tests fail (RED)**
  - Run: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\.venv\Scripts\python.exe -m unittest test_hmu_recognizers.py -v`
- [ ] **Step 3: Implement recognizer upgrades in `hmu_recognizers.py`**
  - Remove `PATIENT_ID` and `MEDICAL_RECORD_ID` from active redaction `RULES` and `PROPAGATE_TYPES` (keep them preserved for post-inspection).
  - Add `WATERMARK_RE = re.compile(r"(?m)^\s*([A-ZÀ-ỸĐa-zà-ỹđ]+(?:\s+[A-ZÀ-ỸĐa-zà-ỹđ]+){1,5})_\d{8,16}\s*$")` and strip/capture watermark lines as `WATERMARK_TEXT` before running `PATIENT_NAME` extraction so watermark names never pollute `PATIENT_NAME`.
  - Expand `_TITLE` to include `BSCKI`, `BSCKII`, `CKI`, `CKII`, `DS`, `C\.N` and signature block headings (`BÁC SĨ LÀM BỆNH ÁN`, `BÁC SĨ ĐIỀU TRỊ`, `BÁC SĨ CHỈ ĐỊNH`, `TRƯỞNG KHOA.*`, `GIÁM ĐỐC BỆNH VIỆN`, `NGƯỜI DUYỆT KẾT QUẢ`, `NGƯỜI GIAO HỒ SƠ`, `NGƯỜI NHẬN HỒ SƠ`, `Người kí`, `Ký số bởi`).
  - Expand `_FIELD_LABEL` and `RULES` for OCR-tolerant labels (`h[oọq]\s*(?:v[aà]\s*)?t[eê]n`, `đ[iị]a\s*ch[iỉ]`, `đ[iịeê]n\s*tho[aạ]i(?:\s*s[oố])?`, `ng[uư][oờ]i\s*(?:nh[aà]|k[iý]|l[aà]m\s*xn|nh[aậ]n\s*m[aẫ]u|duy[eệ]t)`), boxed BHYT (`[A-Z]{2}\s+\d\s+\d{2}\s+\d{2}\s+\d{8,10}(?:\s+\d{5})?`), and relative lines with hyphenated addresses (`con:\s*phạm văn huy-quảng nhân`).
  - Implement `extract_case_seeds(source_path: Path) -> Dict[str, List[str]]` to parse patient name from folder/file name and parse companion XML / XML130 files (supporting both direct XML tags and Base64 `<NOIDUNGFILE>`).
- [ ] **Step 4: Run `test_hmu_recognizers.py` and verify all tests pass (GREEN)**

---

### Task 2: Offline OCR Helper for Textless / Vector PDFs (`ocr_helper.py`)

**Files:**
- Create: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\ocr_helper.py`
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\test_workflow.py`

**Interfaces:**
- Produces:
  - `ocr_pdf_pages(pdf_path: Path, page_numbers: List[int], dpi: int = 200) -> Dict[int, Tuple[str, List[Tuple[int, int, Tuple[float, float, float, float], str]]]]`
    Returns `(text, chars)` in the exact format expected by `engine.char_map(page)` for each 1-based page number.

- [ ] **Step 1: Add unit test in `test_workflow.py` for OCR extraction on a textless (rasterized image) PDF page**
- [ ] **Step 2: Run `test_workflow.py` to verify the new test fails (RED)**
- [ ] **Step 3: Implement `ocr_helper.py` using Windows built-in `Windows.Media.Ocr.OcrEngine` batch script**
  - Renders requested textless pages to temporary PNGs at `dpi=200`, invokes a single PowerShell `Windows.Media.Ocr` batch pass with UTF-8 JSON output containing word text and bounding rectangles, scales pixel coordinates back to PDF point coordinates (`72.0 / dpi`), sorts lines top-to-bottom and words left-to-right, and constructs `(text, chars)` compatible with `span_rects(chars, a, b)`.
- [ ] **Step 4: Run `test_workflow.py` and verify it passes (GREEN)**

---

### Task 3: Engine Upgrades — Multi-Watermark, 8-Box DOB vs Age, Auto-Signatures, Markdown Summary & Case Batching (`engine.py`)

**Files:**
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\engine.py`
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\test_workflow.py`

**Interfaces:**
- Consumes: `extract_case_seeds`, `analyze_hmu_document`, `ocr_pdf_pages`
- Produces:
  - `prepare(source, job, study_id='HMU_CASE_0001', external_seeds=None) -> dict`
  - `export(job, draft=False, approve_all=False) -> Tuple[Path, dict]`
  - `prepare_case(case_path, job_root, study_id='HMU_CASE_0001') -> dict`
  - `export_case(job_root, draft=False, approve_all=True) -> dict`
  - `generate_audit_markdown(job_dir: Path, data: dict) -> Path`

- [ ] **Step 1: Add tests in `test_workflow.py` for:**
  1. 8-box split DOB redaction (`1 | 5 | 1 | 0 | 1 | 9 | 5 | 8`) preserving adjacent 2-box Age (`6 | 8`).
  2. Multi-instance diagonal watermark removal (`Hồ Thị Minh Châu_20260803161916` x6) without polluting `PATIENT_NAME`.
  3. Auto-selection (`selected = True`) of signature images near signature headings while keeping top-left hospital logo and large clinical images (`selected = False`).
  4. `AUDIT_SUMMARY.md` generation and `approve_all=True` export.
  5. Multi-PDF case directory preparation & export (`prepare_case` / `export_case`).
- [ ] **Step 2: Run `test_workflow.py` to verify new tests fail (RED)**
- [ ] **Step 3: Implement engine upgrades in `engine.py`**
  - Update `remove_isolated_watermarks(doc)` to remove all isolated diagonal watermark streams per page, and add rotated watermark text detection in `additional_findings`.
  - Integrate `ocr_pdf_pages` in `prepare()` when pages have empty `page.get_text('text').strip()`, caching OCR results in `review.json` so `validate_review` and `export` work seamlessly on textless PDFs (`3.BVQT`).
  - Add `boxed_dob_findings(p, chars, text)` to detect 8-box DOB digits and scanned DOB box strips (`Sinh ngày:` -> left of `Tuổi` column) while protecting Age boxes.
  - Add `classify_signature_images(p, chars, text, image_blocks)` to automatically set `selected = True` on signature images/widgets and scan signature regions under `"Trưởng khoa"`, `"Giám đốc bệnh viện"`, `"BÁC SĨ..."`, `"NGƯỜI DUYỆT KẾT QUẢ"`, etc.
  - Add OCR-tolerant partial name matching for `PATIENT_NAME` seeds (e.g., if seed is `TRẦN THỊ BẢN` and OCR reads `TRAN BAN` after `HQ ten:`, match it!).
  - Remove `SOURCE_LINK_ID` and `BARCODE_CANDIDATE` from auto-redaction (or keep `selected = False` so medical record/specimen IDs remain visible for post-inspection).
  - Generate `AUDIT_SUMMARY.md` in `prepare()` and implement `prepare_case` / `export_case` for multi-PDF folders (`1.DHYHN`) and single-PDF cases (`2.BV71`, `3.BVQT`).
- [ ] **Step 4: Run `test_workflow.py` and `test_hmu_recognizers.py` to verify all tests pass (GREEN)**

---

### Task 4: Web UI Fast Double-Check ("Approve All" & Markdown Audit View) + Real 3-Hospital Verification (`app.py`, `review.html`)

**Files:**
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\app.py`
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\review.html`
- Modify: `D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\test_workflow.py`

**Interfaces:**
- Endpoints added to `app.py`:
  - `GET /audit`: returns `{ "markdown": "..." }` from `AUDIT_SUMMARY.md`.
  - `POST /approve_all`: marks all pages `reviewed = True` in `review.json` and saves.
  - `POST /open_path`: prepares a local file or case directory path directly without browser upload size limits.

- [ ] **Step 1: Add HTTP test in `test_workflow.py` for `/audit` and `/approve_all`**
- [ ] **Step 2: Run `test_workflow.py` to verify failure (RED)**
- [ ] **Step 3: Implement `/audit`, `/approve_all`, `/open_path` in `app.py` and UI buttons (`Duyệt tất cả trang`, `Xem Báo cáo Markdown`) in `review.html`**
- [ ] **Step 4: Run full unit test suite + End-to-End verification on the 3 sample cases from the 3 hospitals (`1.DHYHN`, `2.BV71`, `3.BVQT`) and inspect the output PDFs and `AUDIT_SUMMARY.md` (GREEN)**
