> Cập nhật 01/11, v20: **đã đo đủ hai PDF +4QC**, B071 **120.84 s <170 s**, A05097.57 s; cặp121.71 s+4QC29.73 s=151.44 s. Thêm so121trangRGB5.57 s, tổngcửasổmáy157.01 s. RSS xửlý/QC0.887/1.010 GiB; oracle408/409,298/298vùnggiữđạt; rawp69FAILgiữchúthích,đốichứngảnhđạt. Còn2/3cảnhbáo,0READY; suite349/348PASS/1SKIP. Chưa12/12 nghiệmthu. [Báocáo](../../../../BAO_CAO_HANG_DOI_2026-10-31.md).

# Khử chính xác và xử lý 2.000 hồ sơ — Implementation Plan

## Cập nhật theo yêu cầu triển khai mới nhất

Ưu tiên **nhiều hồ sơ đồng thời**, mặc định yêu cầu hai job với giới hạn tài nguyên và hiệu chuẩn thực; không dùng thời gian treo qua đêm làm căn cứ duy nhất để kết luận đủ công suất. Máy chạy không cần người canh. Mỗi job tự nhận file → phân tích → xuất DRAFT → kiểm PDF → vào hàng chờ duyệt; hoàn tất file nào thì bản xuất riêng của file đó truy cập được ngay, không đợi cả lô và không chờ người duyệt mới chạy file sau. Hàng chờ duyệt lưu bền vững, tách khỏi worker slots. Có cảnh báo QA thì vẫn cho mở DRAFT để sửa, không gắn READY/phát hành chính thức. Duyệt một hồ sơ không khóa xử lý các hồ sơ khác.

Checklist bổ sung bắt buộc: hai job đang chạy; một job xong trước được tải/mở ngay; job chưa duyệt không chặn job thứ ba; đóng UI không dừng queue; restart giữ cả queue máy và queue duyệt; edit/re-export một job không làm sai QC/tiến độ job khác. Năng suất báo theo cấu hình 1 và 2 jobs, có verifier hậu xuất; mốc 30 file/giờ là mục tiêu nếu chỉ tính 6 giờ máy/ngày, không coi đạt khi chưa đo. Các lịch 12–16 giờ bên dưới là phương án năng lực bổ sung, không giả định thời gian máy đã được bảo đảm.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Đây là kế hoạch mới; không đánh dấu hoàn thành chỉ vì có các tối ưu tốc độ trước đó.

**Goal:** Giảm sót định danh trên PDF xuất và vận hành hàng đợi 2.000 hồ sơ độc lập trong ngân sách hai tuần, 6 giờ người/ngày, máy được chạy thêm buổi tối/qua đêm.

**Architecture:** Tái dùng engine OCR/khử hiện có; thêm hàng đợi SQLite tại máy và worker process riêng cho mỗi hồ sơ. Mặc định yêu cầu hai job, admission theo tài nguyên; hiệu chuẩn so một/hai job để báo năng suất thật. DRAFT → kiểm PDF thật → người duyệt → kiểm đúng revision → READY; không cho hàng đợi tự duyệt.

**Tech Stack:** Windows, Python 3.12, sqlite3/stdlib, PyMuPDF 1.26.6, pypdf 6.10.0, backend Windows OCR hiện có, HTTP/HTML/JS hiện có. Chưa thêm dịch vụ hoặc package.

**Spec:** [Thiết kế và tính công suất](../specs/2026-10-30-batch-accuracy-design.md).

## Global Constraints

- Ưu tiên hàng đợi nhiều file, không cần người canh; cơ sở đánh giá chính là 14 ngày × 6 giờ. Chạy ngoài giờ là phần công suất bổ sung, không mặc định dùng để tuyên bố đạt. Trừ ngày phát triển nếu nằm trong cùng hai tuần.
- Mốc tối thiểu cho 2.000 file/84 giờ máy là 23,81 file/giờ; mục tiêu có dự phòng là 30 file/giờ. Tính cả ingest/OCR/khử/audit/QC PDF cuối. Báo riêng tốc độ tạo DRAFT và tốc độ không còn cảnh báo máy. Các lịch 12–16 giờ chỉ là tính toán theo kết quả thực.
- Giữ 200 dpi RGB/lossless, xóa vật lý, bảo toàn nội dung chuyên môn; không giảm QC hoặc hạ chất lượng để đạt chỉ tiêu.
- A050 là mẫu mới 50 trang do người dùng chỉ định; B071 là mẫu cũ. Không chép mask/reference vào benchmark nhận diện tự động.
- Dữ liệu thật, ground truth và audit chứa PII ở `HMU_JOBS/` đã ignore. Test trong repo dùng dữ liệu giả; báo cáo công khai chỉ ID ca, số đo, SHA và số lỗi.
- Không đưa 2.000 bệnh nhân độc lập vào `prepare_case` với shared seeds. Mỗi file/case có job riêng và ánh xạ case tường minh.
- Mọi `READY` cần người duyệt, output SHA + review revision + verifier fingerprint khớp và không còn vấn đề chưa phân xử; worker không gọi `approve_all_pages`.
- RAM trống tối thiểu trước nhận job: `max(1 GiB, 10% RAM vật lý)`; budget cây tiến trình batch ban đầu 50% RAM vật lý. Đĩa cần đủ dự toán đầu ra còn lại, các job đang làm và dự phòng 2 GiB.
- Ngưỡng phát triển đề xuất trên nhãn độc lập: auto-selection recall ≥99,5% tổng, ≥99% từng nhóm bệnh nhân/nhân viên/liên hệ, precision ≥99%. PDF sau duyệt: 0 bỏ sót trọng yếu đã gắn nhãn, 0 mất vùng chuyên môn bắt buộc giữ. Luôn báo tử số/mẫu số và giới hạn corpus.
- Giữ branch/thay đổi sẵn có. Không commit, merge hoặc thay chính sách giữ mã định danh ngoài phạm vi đã thống nhất; các quyết định chính sách phải ghi ở T01.

## Review Focus

1. Hai bệnh nhân trùng tên hoặc XML ở thư mục chung: không lan seeds sang ca khác — T02/T05, `test_patient_seed_scope_never_crosses_jobs`.
2. Mất điện/kill giữa rename PDF và ghi DB: không mất bản đã bàn giao, không READY bản thiếu QC — T07/T09, `test_resume_after_publish_before_queue_commit`.
3. OCR trống, lỗi một trang hoặc tên bị cắt qua cột: không coi “không phát hiện” là sạch — T03/T04, `test_unreadable_page_blocks_ready`, `test_partial_name_counts_as_miss`.
4. Người sửa review khi worker đang kiểm bản cũ: không gắn QC cũ cho revision mới — T08/T09, `test_review_change_invalidates_pending_verification`.
5. Hết RAM/đĩa, sleep và worker OCR mồ côi khi chạy đêm: dừng nhận job có kiểm soát, phục hồi không chạy trùng — T06/T07, `test_resource_pressure_defers_admission`, `test_cancel_reaps_worker_descendants`.

## Bản đồ thay đổi

| File | Trách nhiệm |
|---|---|
| `hmu_recognizers.py`, `engine.py` | Sửa đúng lỗi tái hiện, provenance/geometry, seed trong ca, budget OCR/render và tích hợp QC |
| `ocr_helper.py` | OCR cục bộ, chỉ số trang lỗi/chất lượng và budget worker kể cả hậu xuất |
| `output_qc.py` (mới) | Kiểm actual PDF theo hash/revision, residual PII và coverage |
| `batch.py` (mới) | Queue SQLite, trạng thái, tài nguyên, checkpoint, release và CLI |
| `batch_worker.py` (mới) | Một process chạy một stage trên job riêng, báo kết quả về coordinator |
| `app.py`, `review.html` | API batch, chuyển job an toàn, hàng đợi duyệt và thao tác người dùng |
| `test_*.py`, `test_ui_save.js`, `test_ui_batch.js` (mới) | Hồi quy chất lượng, isolation, recovery và UI |
| `benchmarks/benchmark_batch.py` (mới), `benchmarks/README.md` | Đo nhiều hồ sơ, đủ chi phí QC và backlog người duyệt |
| `HUONG_DAN_SU_DUNG.md` | Chạy đêm, phục hồi, giới hạn, quy trình giao nhận và dung lượng |

Các đường dẫn ở bảng/task tính từ `HMU_KhuDinhDanh/`. Không tách/refactor engine toàn bộ để làm hàng đợi.

## Trạng thái triển khai ngày 01/11/2026 — v20 đã đo

| Task | Đã triển khai và xác minh | Còn thiếu trước nghiệm thu toàn bộ |
|---|---|---|
| T01 Bằng chứng/chính sách | Hai mẫu được phép; snapshot/SHA; oracle 409 bất biến; loader đối chiếu bản cũ | Corpus 30 ca, nhãn độc lập đầy đủ |
| T02 Nhận diện | Sửa tên/bác sĩ/người thân/BHYT và seed đúng ca; v20 lọc alias yếu theo ngữ cảnh hẹp; sửa lỗi tên + chữ “là” bị hiểu là thuật ngữ, 4 ca RED→GREEN | Recall/precision holdout; cảnh báo mơ hồ cần người duyệt |
| T03 OCR/hình học | 298/298 vùng giữ đạt; đường bảng/nhãn giữ nguyên; tăng tốc parser vector; RGB cả 121 trang giống v19 | Scan/bố cục ngoài hai mẫu; chưa có nhãn đủ mọi vùng trong mask |
| T04 QC đầu ra | OCR đủ 121 trang; kiểm pixel 144 ô; cache gắn SHA/revision; rà 48 cảnh báo; còn 5 đã xem trực tiếp | 5 cảnh báo vẫn chờ phân xử người dùng; không tự READY |
| T05 Hàng đợi | SQLite/job tách ca, chống trùng/claim; DRAFT riêng/backlog không giữ slot; sửa lỗi đọc progress bị khóa, 3 ca RED→GREEN | Tải thực 2.000 file và đủ edge case nhập |
| T06 Đồng thời/budget | Hai worker thực; OCR1/render1; RSS xử lý 0.887 GiB; kiểm giới hạn/teardown | So đủ cấu hình/lặp; vừa duyệt UI thật vừa xử lý |
| T07 Phục hồi/tài nguyên | Guard RAM/AC thực sự chờ rồi chạy; checkpoint/retry/atomic publish; lỗi progress không hủy worker hợp lệ | Soak 6 giờ; sleep/reboot/power loss thật; dung lượng corpus |
| T08 UI duyệt | API/Node: lưu trước chuyển job; chống response/QC cũ; PDF/cảnh báo; hàng chờ duyệt riêng | Browser smoke đầy đủ, keyboard/focus, nghiệm thu thao tác |
| T09 Bàn giao | Gate người duyệt + phân xử + QC đúng bản; gói PDF/QC/manifest có test | Hai DRAFT chưa người duyệt; chưa phát hành/đối soát đợt thật |
| T10 Năng suất | B071 120.84 s <170 s; cặp +4QC 151.44 s; thêm đối chiếu RGB, tổng cửa sổ máy 157.01 s | Mới 1 cặp hoàn tất; thiếu 3 lượt×3 cấu hình và soak; chưa có công suất bàn giao |
| T11 Chất lượng/giờ người | Suite 349/348 PASS/1 SKIP; NodeUI/pip/diff đạt; reviewer 1 Important đã sửa; 409 ROI + kiểm bổ sung hoàn tất | Raw p69 còn FAIL; holdout 15 ca, nhãn đủ, giờ người 30 ca, duyệt cuối |
| T12 Vận hành 2.000 file | Queue nhiều file, xuất từng file/chờ duyệt riêng; CLI/UI/runbook; 45.86 DRAFT/giờ trên hai mẫu tính mọi kiểm máy | Pilot 100–500, corpus/đối soát 2.000, giờ người và deadline chưa xác nhận |

Chưa hoàn tất 12/12. Hai mẫu không thay corpus 30 ca; DRAFT chưa READY. Raw FAIL p69 giữ nguyên.

## Phạm vi nghiệm thu v20

- [x] Rà 48 cảnh báo cũ và 5 cảnh báo cuối; 0 PII thấy trong nhóm này, không thay nhãn toàn trang.
- [x] Sửa 1 Important reviewer (4 ca RED→GREEN) và lỗi khóa progress thực tế (3 ca RED→GREEN).
- [x] Suite cuối 349/348 PASS/1 SKIP, 54.058 s; NodeUI/pip/diff đạt.
- [x] Hai job fresh đồng thời: A050 97.57 s, B071 120.84 s; QC ứng dụng đã tính.
- [x] Bốn QC độc lập 29.73 s; cặp +4QC 151.44 s; thêm kiểm RGB 5.57 s, tổng cửa sổ máy 157.01 s.
- [x] Giữ nguyên oracle 409/predicate/SHA; 298/298 preserve,110/111 redact; raw p69 FAIL riêng và đối chứng ảnh đạt.
- [x] 121 trang ngoài mask,3 bìa,2 BHYT,2 tên,144 ô và toàn121RGB so v19 đạt.
- [ ] Người dùng phân xử 2/3 cảnh báo hai file, raw p69 và nghiệm thu toàn trang; 0 READY.
- [ ] Corpus/holdout/đo lặp/soak/UI thật/giờ người/pilot và giao2.000 file.

## Checklist thực hiện

### T01 — Chốt bằng chứng, tái hiện mẫu 50 trang và chính sách

**Phụ thuộc:** Không. **Files:** private `HMU_JOBS/batch_accuracy_20261030/`; báo cáo cũ `../BAO_CAO_TOI_UU_2026-10-30.md`; `benchmarks/README.md`; test hồi quy liên quan.

**Interfaces:** Corpus manifest có `case_id, source_sha256, source_path_private, split, pages`; nhãn có `case_id, page, kind, rects, action, evidence, adjudicated`. Action = `must_redact|must_preserve|uncertain`. Source của A050 dùng đường dẫn người dùng đã cấp, không tìm thêm bệnh án chưa được phép.

- [x] Khóa và ghi SHA/runtime hiện tại; xác nhận đủ 20 log B071, hoàn tất các kiểm PDF đầu/cuối, 409 ROI và toàn bộ output còn thiếu bằng helper sẵn có. Không gọi hoàn thành chất lượng khi chỉ có log tốc độ.
- [ ] Chuẩn bị job mới và xuất DRAFT A050 bằng lựa chọn **tự động nguyên bản**; giữ ảnh nguồn/đích để rà toàn bộ 50 trang, xác định trường/trang sót. Nếu có output người dùng đã thử thì đối chiếu hash, policy, revision để phân biệt phiên bản.
- [ ] Lập danh sách từng lỗi qua 6 lớp: OCR, nhận diện, selection, geometry, export, stale job; mỗi lỗi có ca tái hiện và oracle giữ nội dung cạnh bên. Tạo test thất bại trước khi sửa ở T02/T03/T04.
- [ ] Ghi bảng cần xóa/cần giữ/cần quyết định. Giữ chính sách mã bệnh nhân, mã hồ sơ, tuổi, giới tính hiện tại cho tới khi có quyết định tường minh; không gọi là khử hết định danh nếu chủ đích vẫn giữ mã liên kết.
- [ ] Lập corpus 30 hồ sơ được phép dùng theo các nhóm trong spec, chia 15 phát triển/15 giữ kín theo hồ sơ, lập nhãn độc lập. Nếu mới có A050/B071 thì ghi rõ chỉ đủ hồi quy, không thay corpus bằng bản sao.
- [ ] Kiểm manifest: mỗi nhãn trỏ đúng hash/trang, bbox hợp lệ, nhãn trọng yếu không còn `uncertain` trước khi tính metric; lưu baseline tự động, không dùng reference đã sửa tay làm kết quả tự động.

**Hoàn tất khi:** Có bảng lỗi tái hiện, baseline có mẫu số, chính sách rõ và trạng thái nghiệm thu cũ trung thực. Chưa có nguyên nhân thì tiếp tục điều tra thay vì tăng độ rộng mask hàng loạt.

### T02 — Nhận diện tên và thông tin theo ngữ cảnh đúng hồ sơ

**Phụ thuộc:** T01. **Files:** `hmu_recognizers.py`, `engine.py:additional_findings/prepare`, `test_hmu_recognizers.py`, `test_round2.py`.

**Interfaces:** Giữ `analyze_hmu_document(page_texts, external_seeds=None, *, _finding_validator=None)` và `Finding`; bổ sung provenance trong proposal hiện có nếu cần. Seeds có nguồn/chứng cứ xác nhận và phạm vi case, không lưu bộ tên học tự động toàn hệ thống.

- [x] Viết ca giả tương ứng lỗi thật: bệnh nhân viết hoa/mất dấu/tách dòng, bác sĩ có học hàm/viết tắt/tên ở chân trang, tên lặp không nhãn, người thân/liên hệ; kèm câu chuyên môn gần giống tên và ngày điều trị phải giữ.
- [x] Thêm `test_patient_seed_scope_never_crosses_jobs`: hai ca có tên giống một phần, XML không cùng case; assert không nhận seed của ca còn lại. Kiểm lan truyền trong ca giữ đúng người và không nối qua cột.
- [x] Chạy test mới xác nhận FAIL đúng nguyên nhân; sửa helper dùng chung nhỏ nhất sau khi tìm toàn bộ caller. Không mặc định mọi `CONTEXT_REQUIRED` thành selected.
- [x] Phân biệt “không phát hiện” với “phát hiện chưa chọn”; các candidate nghi ngờ phải tồn tại cho UI và residual QA, không bị deduplicate làm biến mất. Bổ sung test hai lớp này.
- [x] Chạy `.venv\Scripts\python.exe -X utf8 -m unittest test_hmu_recognizers test_round2 -v`; test mới/hiện có PASS, không xuất tên thật vào log công khai.

**Hoàn tất khi:** Các lỗi recognizer đã chứng minh ở T01 có RED→GREEN, negative cases giữ nguyên, không nhúng tên mẫu vào code.

### T03 — OCR vùng nghi ngờ và hình học vùng khử

**Phụ thuộc:** T01/T02. **Files:** `ocr_helper.py:ocr_pdf_pages/ocr_pdf_regions`, `engine.py:prepare/span_rects/name_geometry_valid/expand_rects_with_pixel_ink`; `test_ocr_safety.py`, `test_engine_safety.py`, `test_speed.py`.

**Interfaces:** Giữ API OCR trả map chữ hiện tại; lưu diagnostics riêng theo trang trong analysis. Mỗi trigger retry có `reason, page, rect, attempt, result`; tối đa một lần retry cục bộ mỗi vùng. `ocr_pdf_regions(..., max_workers=None)` nhận budget tương thích caller cũ khi T06 thêm.

- [ ] Tạo test ROI dựa lỗi thật: chữ nghiêng/xoay, scan nhòe, họ tên dính chữ, dấu/đuôi tên ngoài bbox, chữ sát bảng; test âm cho ảnh chuyên môn/logo và ô kế bên.
- [ ] Chạy test mới để thấy FAIL; xác định trang trống thật khác trang có ảnh nhưng OCR không đọc được bằng độ phủ/ink + anchor. Trường hợp không chứng minh được trang trống phải là nghi ngờ.
- [ ] Bổ sung retry có giới hạn bằng `ocr_pdf_regions` sẵn có; thử scale/rotation cho loại lỗi đã tái hiện. Không tăng DPI toàn bộ tài liệu; giữ export 200 dpi. Nếu cùng backend vẫn không đọc được thì NEEDS_REVIEW, ghi nhánh đánh giá backend khác với corpus trước khi thêm dependency.
- [x] Sửa ánh xạ bbox/ink đúng nguồn lỗi; `test_partial_name_counts_as_miss` phải bắt sót nét cuối, đồng thời oracle dòng/ô chuyên môn cạnh bên khớp.
- [x] Chạy `.venv\Scripts\python.exe -X utf8 -m unittest test_ocr_safety test_engine_safety test_speed -v`; kiểm OCR thật cho ROI mới và so nguồn/đích A050. Bump fingerprint/policy khi thay đổi hành vi làm cache cũ không còn đúng.

**Hoàn tất khi:** Retry giúp đúng các ca xác định, vùng mơ hồ được báo chứ không coi sạch, không mất nội dung sát mask.

### T04 — Kiểm định danh còn sót trên chính PDF đã xuất

**Phụ thuộc:** T02/T03. **Files:** mới `output_qc.py`, `test_output_qc.py`; tích hợp `engine.py` ở ranh giới export; tái dùng ý tưởng từ helper private `post_export_ocr.py`, không mang hardcode 71 trang/reference vào sản phẩm.

**Interfaces:** `verify_output(job: Path, pdf: Path, *, expected_revision: int, ocr_workers: int, progress_cb=None) -> dict`. Kết quả gồm `pdf_sha256, job_id, revision, policy, verifier_fingerprint, pages_expected, pages_checked, findings, unreadable_pages, structural_ok, status`; status = `PASS|NEEDS_REVIEW|FAIL`. PASS là kiểm máy, chưa phải READY.

- [x] Test PDF giả còn tên dưới dạng ảnh, text ẩn, widget, attachment, thiếu một trang, tên chỉ sót một phần và cảnh báo score thấp. `test_unreadable_page_blocks_ready` assert không PASS nếu thiếu map hoặc OCR không đọc được trang có nội dung.
- [x] Test `test_verification_is_bound_to_pdf_and_review`: đổi PDF/revision/fingerprint thì kết quả cũ không được tái dùng. Chạy tests để xác nhận RED.
- [x] Đọc/reopen PDF thật, kiểm cấu trúc và OCR mọi trang; so seeds đúng ca + detector ngữ cảnh, giữ cảnh báo cần phân xử. Không dùng điều kiện chỉ score ≥0,95 rồi bỏ các cảnh báo khác để gọi sạch.
- [x] Kết quả chỉ ghi PASS khi đã kiểm đủ trang và không còn vấn đề chưa phân xử; chính sách phân xử false positive phải gắn page/bbox/reason/reviewer/revision. Sửa vùng xóa yêu cầu xuất và kiểm lại, không tự sửa mask trong vòng lặp vô hạn.
- [x] Chạy `.venv\Scripts\python.exe -X utf8 -m unittest test_output_qc test_engine_safety -v`; trên A050/B071 đo riêng chi phí verifier và đưa vào total. Kiểm nét/bảng/nhãn bằng oracle độc lập, không chỉ lặp cùng detector.

**Hoàn tất khi:** Tên còn thấy trong PDF và trang kiểm bị thiếu không lọt PASS; QA gắn đúng output, mọi cảnh báo hiện được cho người duyệt.

### T05 — Hàng đợi bền vững cho các hồ sơ độc lập

**Phụ thuộc:** T01; có thể làm trước T02–T04 nếu chỉ dùng fixture. **Files:** mới `batch.py`, `test_batch.py`.

**Interfaces:** `enqueue(db_path: Path, sources: list[Path]) -> list[str]`; `claim_next(db_path: Path) -> dict | None`; `get_job(db_path: Path, job_id: str) -> dict`; `set_stage_result(db_path: Path, job_id: str, *, expected_state: str, result: dict) -> None`. DB private giữ source path, SHA, case ID, policy/runtime/OCR fingerprints, stage, revision, attempts, timings, output hash và review/QA status. Giá trị trạng thái đúng spec.

- [ ] Test 2.000 mục nhập, file cùng tên ở hai thư mục, trùng byte, tên Unicode, PDF hỏng/mã hóa, path ngoài root khai báo/symlink vòng. Trùng hash phải báo alias/duplicate có thể truy vết, không âm thầm mất một mục đầu vào.
- [x] Test claim hai lần không chạy cùng job; sau reopen DB đủ mục và tiến độ. Kiểm case-ID riêng, không gọi `prepare_case` với thư mục nhiều bệnh nhân.
- [ ] Chạy `.venv\Scripts\python.exe -X utf8 -m unittest test_batch -v` xác nhận RED; thêm SQLite/transaction và một coordinator; dữ liệu lớn nằm ở job, không nạp tất cả PDF vào RAM.
- [x] Thêm CLI trong `batch.py`: `enqueue --queue PATH --input-dir PATH`, `run --queue PATH --jobs 1`, `status --queue PATH`, `pause --queue PATH`, `resume --queue PATH`. Quét nguồn tường minh và loại job/output dirs; mặc định không đi ra ngoài input root.
- [ ] Chạy lại test, kill/reopen fake queue và xác nhận số mục nguồn = queued + running + needs_review + ready + failed + cancelled + duplicates được ghi riêng, không biến mất.

**Hoàn tất khi:** Danh sách 2.000 hồ sơ có tiến độ độc lập, không trộn dữ liệu, không chạy lại việc đã hoàn tất một cách mù quáng.

### T06 — Worker process và giới hạn tài nguyên toàn batch

**Phụ thuộc:** T04/T05. **Files:** mới `batch_worker.py`; `batch.py`, `engine.py:_render_scan_pages/prepare`, `ocr_helper.py`, `test_batch.py`, `test_ocr_safety.py`.

**Interfaces:** `run_stage(job_dir: Path, stage: str, *, ocr_workers: int, render_workers: int) -> dict` ở worker; stage = `prepare|export|verify`. `prepare(..., ocr_workers=None, render_workers=None)` thêm keyword-only; `_render_scan_pages(..., max_workers=None)` tương thích mặc định cũ. Worker nhận đường dẫn và số nguyên, không nhận Document/Page. `can_admit(available_ram, batch_rss, next_peak, free_disk, reserved_disk) -> bool` dùng ngưỡng spec.

- [ ] Test giới hạn thực tổng child workers của hai job, kể cả verifier; kết quả OCR/ảnh giữa cấu hình phải khớp. Test `test_resource_pressure_defers_admission`, hoàn tất một job phải giải phóng slot.
- [x] Test một worker lỗi không làm mất trạng thái job còn lại; progress đúng ID, cancellation chỉ tác động cây process của job đích. Chạy test xác nhận RED.
- [x] Coordinator chạy stage ở process riêng, đóng handle/Document đúng vòng đời. Khóa engine operations UI cũng dùng budget, không để UI export tạo pool ngoài kiểm soát. Mặc định yêu cầu jobs=2; admission có thể giữ một job khi thiếu tài nguyên; cấu hình thực được hiệu chuẩn T10.
- [x] Truyền budget đến mọi caller OCR/render, kể cả ROI và QA hậu xuất; dùng kiểm kê process/RAM hiện có trong benchmark, không thêm dependency chỉ để đọc RAM.
- [ ] Chạy tests batch/OCR/engine liên quan; so pixel và map trên fixture mixed/rotated/crop. Báo tổng RSS cây process, không cộng đơn giản peak từng job ở thời điểm khác nhau.

**Hoàn tất khi:** Có thể xử lý hai job mà không share MuPDF/thread unsafe, không nhân worker vô hạn, không lẫn kết quả.

### T07 — Tiếp tục sau lỗi, dung lượng và chạy qua đêm

**Phụ thuộc:** T05/T06. **Files:** `batch.py`, `batch_worker.py`, `test_batch.py`, `HUONG_DAN_SU_DUNG.md`.

**Interfaces:** `recover_queue(db_path: Path) -> dict`; `pause_queue(db_path: Path) -> None`; `resume_queue(db_path: Path) -> None`. Checkpoint chỉ hoàn chỉnh sau khi manifest/hash đóng; cache key gồm source SHA, policy, engine/OCR fingerprint, DPI, review revision và output SHA theo stage.

- [ ] Test kill ở giữa prepare, export, verify, sau publish trước DB commit; test đổi source/policy hoặc cache thiếu file. Assert resume chỉ tái dùng checkpoint hợp lệ, bản dở không READY, không chép reviewed từ snapshot không tương thích.
- [x] Test `test_cancel_reaps_worker_descendants` trên Windows cho worker + OCR/render con; timeout/đóng queue không để process mồ côi. Retry tối đa một lần chỉ cho lỗi tạm thời, lỗi nội dung chuyển FAILED/NEEDS_REVIEW với lý do.
- [ ] Test đĩa dưới ngưỡng không khởi chạy tiếp, giữ nguồn và bản tốt; cleanup chỉ cache đã được phân loại của job READY, resolve path trong root, không chạm review/nguồn/log nghiệm thu cũ. Chạy tests để xác nhận RED.
- [x] Hoàn thiện pause ngừng nhận việc mới và lưu tiến độ; hard-cancel cần teardown cây process. Phục hồi khi khởi động đọc DB/manifests, idempotent khi gọi hai lần.
- [ ] Thêm giữ máy thức trong thời gian có công việc bằng Windows API, giải phóng khi dừng; heartbeat + log cuối và hướng dẫn cắm nguồn/không sleep. Kiểm thủ công mất kết nối UI, khóa màn hình, sleep/resume và khởi động lại.
- [ ] Lập dự toán dung lượng từ corpus pilot, chỉ chọn output root đủ chỗ; cho phép đợt 100–200 file. Không triển khai tự xóa bệnh án để giải phóng ổ.

**Hoàn tất khi:** Chạy không giám sát có thể dừng/tiếp tục và phục hồi đúng; không coi hết đĩa là xử lý thành công.

### T08 — Giao diện hàng đợi và duyệt tập trung

**Phụ thuộc:** T04/T05/T06. **Files:** `app.py`, `review.html`, `test_app.py`, mới `test_ui_batch.js`; giữ `test_ui_save.js`.

**Interfaces:** thêm `GET /batch/status`, `POST /batch/enqueue`, `/batch/pause`, `/batch/resume`, `/batch/open_job`, `/batch/resolve_finding`. Giữ token/loopback, validate input; payload ghi có `job_id, revision`. Worker không thay `active`; frontend mở job bằng ID đã ánh xạ an toàn trong queue.

- [x] Test API token/path/identity, job A đang được duyệt khi B chạy; không còn global busy chặn mọi hồ sơ nhưng vẫn chặn mutation job đang export/verify. Test response cũ không ghi đè state job mới.
- [ ] Test `test_review_change_invalidates_pending_verification`: save tăng revision, QC đang chạy bản cũ chỉ ghi cho bản cũ và không READY bản mới. `test_ui_batch.js` kiểm flush-before-switch, lỗi save không mất chỉnh sửa, keyboard/focus khi chuyển vùng.
- [x] Chạy tests RED, thêm danh sách queued/running/needs_review/ready/failed, tổng trang, ETA và nút pause/resume/retry lỗi. Không gọi nút “xong” cho job chỉ xử lý máy xong.
- [x] Thêm danh sách nghi ngờ theo nhóm, ảnh trước/sau, nhảy trang, lý do chưa chọn và vùng chưa OCR đủ; giữ xem toàn trang. Không dùng risk filter làm bằng chứng trang không gắn cờ đã sạch.
- [x] Hành động duyệt vẫn do người dùng; không nối queue tới `/approve_all` tự động. Giữ trang chưa duyệt, khi sửa mask xuất lại và QA lại đúng revision.
- [ ] Chạy `node test_ui_save.js`, `node test_ui_batch.js` và test_app; smoke trên batch nhỏ, vừa xử lý nền vừa duyệt, refresh/reopen không mất trạng thái.

**Hoàn tất khi:** Người dùng có thể tập trung duyệt trong 6 giờ, không phải chờ từng lần máy xử lý hoặc dò lỗi bằng cách mở từng PDF thủ công từ đầu.

### T09 — Bàn giao PDF đã kiểm và manifest không lộ dữ liệu riêng

**Phụ thuộc:** T04/T07/T08. **Files:** `batch.py`, `engine.py:_publish_generation/export`, `test_batch.py`, `test_engine_safety.py`.

**Interfaces:** `release_job(db_path: Path, job_id: str, *, expected_revision: int, destination: Path) -> dict`; output mã nghiên cứu + PDF + sanitized QC + manifest `{case_id, pages, source_hash, output_hash, policy, revision, qc_status}`. Internal source path/name/seeds/audit không ra gói bàn giao.

- [x] Test review chưa đủ, tồn tại finding chưa phân xử, QC SHA/revision sai đều bị chặn; `READY` không đồng nghĩa với chỉ `verify=PASS`.
- [ ] Test file trùng tên, output directory có bản cũ, copy thất bại, đĩa đầy, manifest giả/đường dẫn vượt root; không ghi đè bản tốt. `test_resume_after_publish_before_queue_commit` xác nhận reconcile bằng hash không tạo bản bàn giao trùng.
- [x] Chạy RED; tái dùng publication staging/atomic hiện có, kiểm lại hash ở destination trước commit trạng thái. Bản FAIL/cancel và internal audit không nằm trong package.
- [ ] Test tên file/metadata/CSV/manifest/log bàn giao không chứa tên bệnh nhân hoặc đường dẫn nguồn; kiểm trạng thái chứa mã liên kết đúng bảng chính sách T01, không tuyên bố vô danh tuyệt đối.
- [ ] Chạy tests batch/engine, reopen toàn bộ PDF của đợt fixture và đối chiếu manifest, số lượng, hash và QC.

**Hoàn tất khi:** Đếm được chính xác bao nhiêu file READY và đã bàn giao; không giao nhầm DRAFT hoặc làm lộ audit.

### T10 — Hiệu chuẩn năng suất nhiều hồ sơ và chạy bền

**Phụ thuộc:** T04/T06/T07/T09. **Files:** mới `benchmarks/benchmark_batch.py`, `test_benchmark_batch.py`; `benchmarks/README.md`.

**Interfaces:** `run_batch_benchmark(manifest: Path, destination: Path, *, jobs: int, ocr_workers: int, render_workers: int) -> dict`. Kết quả gồm source/code/policy fingerprints, từng stage, số trang/file, ready_for_review/ready/rejected, latencies, tổng cửa sổ đo, tổng RSS tree và đĩa. Định nghĩa files/hour = số hồ sơ duy nhất **QA máy PASS, đủ điều kiện chờ người duyệt** / tổng giờ cửa sổ; hồ sơ còn cảnh báo chưa phân xử/kiểm thiếu không tính vào công suất đạt. Báo READY/hour riêng. Pilot tính cả thời gian máy xuất/kiểm lại sau sửa tay nhưng không đếm lại file đó lần hai.

- [x] Test đồng hồ gồm nhập/hash, OCR mới, nhận diện, khử, audit, verifier, retry; thời gian queue wait báo riêng cho latency nhưng nằm trong cửa sổ throughput. Không dùng tổng số “attempt” thay số file hoàn tất; job lỗi không tính thành công.
- [ ] Đo ít nhất ba lần mỗi cấu hình `1×OCR4/render2`, `2×OCR1/render1`, `2×OCR2/render1` trên cùng tập đa dạng; xen thứ tự để giảm thiên lệch nhiệt/tải nền. Không chạy profiler/QA benchmark khác đồng thời.
- [ ] Chọn cấu hình nhanh nhất thỏa chất lượng và tài nguyên; nếu hai job không tốt hơn hoặc làm máy không duyệt được thì giữ một job. Đo cả khi UI/người duyệt hoạt động bình thường và phân biệt cache lạnh/mới với OS cache.
- [ ] Chạy liên tục 6 giờ, báo worst/p95/median và RAM lấy mẫu 100 ms; kiểm leak theo thời gian, retry, disk usage, backlog. Không lặp một file rồi gọi là nhiều bệnh án độc lập; nếu phải lặp để soak thì ghi riêng phạm vi reliability.
- [ ] PASS nếu ≥15 file/giờ lịch 12h hoặc ≥12 file/giờ lịch 16h **đã gồm verifier mới**, cùng quality gate; nếu fail, tính lịch theo số thực và đánh giá chia hai máy độc lập. Không bỏ QC/hạ DPI.
- [x] Giữ hồi quy B071 với protocol cũ để biết chi phí thay đổi; báo total protocol mới riêng. Tổng cũ ≤170,4 giây không thay mục tiêu throughput mới có QA bổ sung.

**Hoàn tất khi:** Có lựa chọn concurrency dựa số đo và dự báo ngày hoàn thành theo workload thật, không có lời hứa tăng tốc tuyến tính.

### T11 — Nghiệm thu độ chính xác độc lập và giờ người

**Phụ thuộc:** T02/T03/T04/T08/T10. **Files:** nhãn/private evidence của T01; mới `benchmarks/benchmark_accuracy.py`, `test_benchmark_accuracy.py`; báo cáo chất lượng mới.

**Interfaces:** `evaluate_labels(labels: Path, predictions: Path, final_pdf_dir: Path) -> dict`; mỗi nhãn cần xóa chỉ tính TP khi toàn vùng nhận diện cần xóa được phủ, đúng lớp đã thống nhất; phần bị bỏ sót vẫn FN. Báo TP/FP/FN theo proposal, selection và actual output, cùng FP vùng giữ. Đối sánh 1–1 hoặc union tách/gộp theo entity_id, không đếm trùng để nâng recall.

- [x] Test metric với tên bị chia hai proposal, bbox thiếu đuôi, proposal đúng nhưng không selected, mask quá rộng ăn nội dung chuyên môn. Nhãn/đối sánh không phụ thuộc output recognizer cần đánh giá.
- [ ] Chạy automatic fresh jobs tập giữ kín 15 hồ sơ; không tinh chỉnh bằng test set rồi giữ nguyên tên “holdout”. Ghi riêng kết quả A050/B071 là hồi quy đã biết.
- [ ] Rà PDF xuất cuối theo nhãn trọng yếu, so toàn bộ pixel ngoài vùng khử với đối chứng thích hợp; kiểm bảng/nhãn/ngày điều trị/ICD/hình chuyên môn trong và sát vùng ảnh bị xóa. Mọi sai khác phải giải thích, không nới oracle để PASS.
- [ ] Đo trên ít nhất 30 hồ sơ tổng thời gian người mở/duyệt/sửa/xuất/xử lý lỗi/bàn giao, số trang cần can thiệp và số file quay lại. Phân bố các nhóm độ dài/chất lượng được báo riêng; cần cả review toàn trang không gắn cờ trong kiểm độc lập.
- [ ] Nghiệm thu ngưỡng spec, 0 bỏ sót trọng yếu đã gắn nhãn/0 mất nội dung bắt buộc trên PDF sau duyệt. Ghi mức trung bình phút người/file và tổng giờ cho 2.000; nếu >151,2 giây/file ở 84 giờ khả dụng thì không kết luận một người đủ sức hoàn tất.
- [x] Chạy `.venv\Scripts\python.exe -X utf8 -m unittest discover -p 'test_*.py' -v`, hai bộ UI, `python -m pip check`, `git diff --check`; mọi SKIP có lý do. Bản v19:341 tests/340 PASS/1 SKIP thiếu fixture riêng; mã đo khớp snapshot source freeze. Test xanh không thay phép đo và kiểm dữ liệu thật.

**Hoàn tất khi:** Báo rõ tự động còn bao nhiêu lỗi, người phải sửa bao nhiêu, PDF sau duyệt còn lỗi nào và giới hạn suy rộng; không dùng “OCR không báo lỗi” làm chứng nhận 100%.

### T12 — Thí điểm và lịch vận hành 2.000 file

**Phụ thuộc:** T09/T10/T11 đạt. **Files:** `HUONG_DAN_SU_DUNG.md`; runbook + manifest/log private; báo cáo tổng hợp không PII.

- [ ] Ghi ngày khởi chạy, số ngày thực, giờ máy/người, deadline, số file/trang thực, ổ lưu đủ chỗ. Trừ ngày phát triển/cài đặt/label khỏi hai tuần nếu dùng chung quỹ lịch.
- [ ] Thí điểm 100 hồ sơ: sáng duyệt kết quả đêm trước, giải quyết cảnh báo; chiều xác nhận dung lượng/nguồn/queue cho đêm tiếp. Mỗi ngày đếm file đưa vào, chờ duyệt, READY, lỗi và đã bàn giao; không chỉ đếm file máy đã xuất.
- [ ] Nếu phát hiện rò định danh hoặc mất nội dung quan trọng: giữ đợt bị ảnh hưởng, xác định version/rule, sửa và QA lại. Lưu mẫu lỗi để hồi quy, không tiếp tục phát hành đợt đó cho đủ tiến độ.
- [ ] Qua pilot thì chạy đợt 500 và phần còn lại; dùng 100–200 file/đợt giao nhận nếu dung lượng yêu cầu. Đối chiếu SHA/số lượng trước chuyển/giải phóng cache cho phép.
- [ ] Nếu máy không đủ công suất: tăng lịch 12→16h hoặc chia manifest không trùng sang máy thứ hai rồi đo. Nếu thiếu giờ người: bổ sung người duyệt có phân công hồ sơ hoặc điều chỉnh deadline; tăng worker không sửa được nút thắt này.
- [ ] Bàn giao PDF/QC/manifest + danh sách ngoại lệ chưa xử lý + báo cáo worst time/RAM/dung lượng/năng suất thực/giờ người/lỗi còn mở. Chỉ đánh dấu hoàn thành khi 2.000 mục đầu vào đã được đối soát, bản cần giao đều READY và ngoại lệ được giải quyết theo phạm vi đã thống nhất.

**Hoàn tất khi:** Số lượng và chất lượng bàn giao khớp sổ queue, có bằng chứng đo đủ cả phần máy lẫn người.

## Thứ tự và lịch đề xuất

T01 trước; T02→T03→T04 là nhánh chất lượng. T05→T06→T07 là nhánh vận hành, dùng fixture trong khi chờ nhãn. T08/T09 nối hai nhánh; T10/T11 nghiệm thu, T12 mở rộng. Đây là phụ thuộc công việc, không yêu cầu tạo thêm agent hoặc đồng thời chạy benchmark trên cùng máy.

Không ấn định “viết xong trong N ngày” khi chưa tái hiện A050 và chưa có corpus. Ưu tiên hàng đợi hai job, xuất và chờ duyệt độc lập, cùng quality gate; dùng số đo để chốt cấu hình. Nếu hai tuần tính từ hôm nay, chốt lại công suất cần đạt ngay sau T01 theo số ngày còn lại. Giờ người và giờ máy có thể chồng lên nhau; không cộng hai con số một cách máy móc, nhưng cả hai đều phải đủ.

## Tự rà kế hoạch

- [x] Đã trả lời công suất trước khi lập kế hoạch; cập nhật việc máy được chạy đêm.
- [x] Đã kiểm nguồn mẫu mới: 50 trang, không có native text; khác B071.
- [x] Đã đối chiếu log đủ 20 lượt và phân biệt speed benchmark có reference với độ chính xác tự động.
- [x] Kế hoạch bao phủ code, CLI/API/UI, cache, tests, dữ liệu mẫu, xuất file, tài nguyên, vận hành và các giới hạn.
- [x] Năm rủi ro trọng yếu đều có test và task sở hữu; API/signature mới được ghi ở task cung cấp.
- [x] Thiết kế đã được một reviewer độc lập rà: không có câu hỏi quan trọng cản lập kế hoạch; vẫn cần phép đo và QA thực trước nghiệm thu.
- [x] Kế hoạch đã chuyển sang triển khai ngày 31/10; checklist bên dưới chỉ đánh dấu các bước có bằng chứng. Không coi test xanh là nghiệm thu corpus thật.
