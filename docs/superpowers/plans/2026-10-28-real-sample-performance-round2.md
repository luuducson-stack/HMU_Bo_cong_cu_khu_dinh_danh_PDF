# Vòng 2: nhận diện bệnh án thật và hiệu năng — Implementation Plan

## Trạng thái chốt theo yêu cầu giữ tuổi (29/10/2026)

Báo cáo: [kết quả và số đo thực tế](E:/HMU_Bo_cong_cu_khu_dinh_danh_PDF/BAO_CAO_VONG_2_2026-10-29.md). Các bước checklist gốc bên dưới được giữ làm tiêu chí lịch sử; trạng thái nghiệm thu hiện tại là bảng này.

| Task | Trạng thái |
|---|---|
| R01 | Chưa nghiệm thu đủ |
| R02 | Đạt trong phạm vi đã kiểm |
| R03 | Chưa nghiệm thu đủ |
| R04 | Đạt trong phạm vi đã kiểm |
| R05 | Đạt trong phạm vi đã kiểm |
| R06 | Đạt các ca hồi quy đã báo |
| R07 | Đạt mẫu mục tiêu |
| R08 | Chưa nghiệm thu đủ |
| R09 | Đạt trong phạm vi đã kiểm |
| R10 | Chưa nghiệm thu đủ |
| P01 | Đạt với giới hạn ghi rõ |
| P02 | Chưa chứng minh tăng tốc ổn định |
| P03 | Count đúng; nghiệm thu tốc độ còn mở |
| P04 | Chưa nghiệm thu đủ |
| P05 | Proof đúng; nghiệm thu tốc độ còn mở |
| P06 | Đạt phần thực thi; còn tiêu chí mở |


> **Cập nhật yêu cầu29/10/2026:** Người dùng yêu cầu giữ nguyên dữ liệu Tuổi. Chỉ tự tích vùng định danh đã xác nhận; ảnh chuyên môn và vùng chưa chắc giữ để duyệt (người dùng đã xác nhận). Policy geometry_v5 thay thế yêu cầu khử tuổi bên dưới. Checklist/spec gốc giữ làm lịch sử; nghiệm thu theo báo cáo chốt vòng2 và evidence của policy geometry_v5, không dùng log cũ làm kết quả hiện tại.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khắc phục lỗi nhận diện/vùng khử trên cặp PDF 71 trang và tối ưu native, batch, vector, watermark bằng số đo thực, giữ kiểm tra an toàn.

**Architecture:** Dùng pipeline offline hiện có; sửa ranh giới giá trị và hình học ở helper dùng chung, giới hạn OCR bổ sung vào ROI chưa đạt. Hoàn thiện độ chính xác trước, đóng băng mốc R1 rồi giảm công việc lặp; kiểm chất lượng và tốc độ riêng.

**Tech Stack:** Windows, Python 3.12.10 hiện tại, PyMuPDF 1.26.6, pypdf 6.10.0, Windows OCR, JavaScript, unittest. Không thêm dependency ở thời điểm lập kế hoạch.

**Spec:** [Thiết kế và bằng chứng](../specs/2026-10-28-real-sample-recognition-performance-design.md).

## Global Constraints

- Giữ PDF nguồn và kết quả cũ; job mới phải tách biệt, không tự duyệt bệnh án thật.
- Dữ liệu bệnh án/ảnh/OCR thật chỉ ở `HMU_JOBS/` đã git-ignore; fixture chia sẻ dùng dữ liệu tổng hợp.
- Giữ kiểm ICD, validation tọa độ, source SHA, revision/job ID, per-target watermark proof, publish PDF+QC nguyên tử, audit theo mask thực.
- Giữ export DPI 200 mặc định; không tắt OCR bắt buộc trên trang mixed/ảnh nhỏ để tăng tốc.
- Giữ toàn bộ dữ liệu Tuổi theo yêu cầu cập nhật; ngày/năm sinh vẫn được khử. Giữ giới tính, mã hồ sơ và nội dung chuyên môn.
- Không dùng PDF đã mất nội dung làm nguồn khôi phục; mọi kết quả mới xuất từ PDF gốc.
- Không dùng runtime/protocol khác nhau để tuyên bố trước–sau. Không dùng thời gian profiler làm headline benchmark.

## Review Focus

- Địa chỉ/BHYT trên cùng dòng, nhãn thiếu dấu/hai chấm: R02–R03 kiểm cả chuỗi và mask cuối.
- Tên thật giống thuật ngữ chuyên môn và seed OCR sai: R06 phải giữ ca dương tính ở vùng ký, chặn ca âm tính trong bảng lâm sàng.
- Tuổi trong ô, 0/94/100, số chuyên môn giống tuổi: R05 chỉ khử giá trị trong trường tuổi, không quét số toàn trang.
- Chữ ký/tên dọc nằm trong ảnh toàn trang hoặc vector outline, không có image object riêng: R07 kiểm cả hai dạng và giữ đường bảng.
- Job đã mở trước thay đổi chính sách, partial watermark selection/shared xref và xuất batch thất bại giữa chừng: R09, P03, P05 phải chặn trạng thái cũ hoặc giữ generation cũ.

## Trạng thái khi lập kế hoạch

- [x] Đọc bốn ảnh và hai PDF, xác nhận 71 trang/file và 0 trang có lớp text trích xuất.
- [x] Xem contact sheet toàn bộ trang, render đối chiếu vùng trang 1/12/14/19; chưa coi đây là duyệt chi tiết 71 trang.
- [x] Tái tạo proposal source hiện tại; thấy lỗi địa chỉ/BHYT, thiếu tên bìa, nhận nhầm chuyên môn và thiếu vùng điều dưỡng. Job prepare đủ 71 trang hoàn tất trong lượt chẩn đoán 436.802 giây; có chạy công việc khác cùng lúc nên không dùng số này làm benchmark trước–sau.
- [x] Freeze source R0 tại `benchmarks/baseline_source/round2_R0_20261028/` (đã ignore), đối chiếu SHA năm file sản phẩm không đổi so với evidence vòng trước. Reviewer độc lập đọc thiết kế/checklist không còn câu hỏi triển khai quan trọng; chưa phải review code sau sửa.
- [x] Chạy lại Python suite: **91 test, 90 PASS, 1 SKIP**; Node delayed-save PASS; `pip check` đạt. Log: `RECHECK_BEFORE_SAMPLE_UNSANDBOXED_2026-10-28.log` ở root repo. Đây là kết quả trước các sửa đổi mới.
- [ ] Triển khai các task bên dưới. Chưa có số benchmark **sau vòng 2**; không dùng số cũ thay cho số mới.

Thứ tự: R01 + P01 tạo mốc trước sửa → R02–R10 sửa/kiểm độ chính xác → đóng băng R1 → P02–P05 tối ưu → P06 kiểm và báo cáo. Các mã R/P dưới đây là vòng mới, không thay thế danh sách F01–F15 của vòng trước.

## Bản đồ file

| File | Trách nhiệm vòng này |
|---|---|
| `hmu_recognizers.py` | Ranh giới trường, tên/tuổi, chất lượng seed, giới hạn fuzzy propagation |
| `ocr_helper.py` | ROI OCR và tọa độ từ, hướng chữ nếu helper hiện tại chưa đủ |
| `engine.py` | Vùng theo trường/ô, ink expansion/subsume, điều dưỡng, audit/export/proof |
| `review.html`, `app.py` | Hiện nguồn/cảnh báo đề xuất, policy fingerprint/revision, preview/export nhất quán nếu cần |
| `test_hmu_recognizers.py`, `test_engine_safety.py`, `test_workflow.py` | Chuỗi, tọa độ, bảng, clinical và pixel/export regression |
| `test_ocr_safety.py`, `test_app.py`, `test_ui_save.js` | ROI/hướng chữ, job cũ, HTTP và trạng thái duyệt |
| `benchmarks/benchmark_workflow.py`, `benchmark_phases.py`, `compare_measurements.py` | Mốc/source hash, count/profile, so sánh matched corpus |
| `HUONG_DAN_SU_DUNG.md` | Chính sách tuổi mới, trạng thái chưa chắc chắn và nghiệm thu đầu ra |

## R01 — P0: bộ đối chứng và mốc trước sửa

**Files:** tạo manifest riêng trong `HMU_JOBS/sample_review_20261028/`; test chia sẻ bổ sung vào các file test hiện có.
**Interfaces:** giữ `prepare(source, job, study_id, ..., case_xml_index=[])`; đọc `review.json` và `analysis_private/{page}.json`, không tự đặt `reviewed=True`.

- [ ] Ghi SHA của hai PDF, snapshot source/runtime và policy hiện tại; liên kết ảnh 1→trang 12, ảnh 2→trang 1, ảnh 3→trang 15, ảnh 4→trang 19; mở rộng các mẫu lặp 13/14/20/21.
- [ ] Đánh dấu ground truth theo trường: giá trị cần khử, nhãn giữ lại, vùng clinical/ảnh/đường bảng cần giữ; phân loại từng trang còn lại, ghi vùng chưa xác định.
- [ ] Tạo fixture tổng hợp giữ đúng quan hệ hình học/OCR nhiễu của từng lỗi; không nhúng tên/số/bệnh án thật vào test chia sẻ.
- [ ] Kiểm manifest: đủ 71 trang, không thiếu/nhầm thứ tự, tọa độ trong trang; đầu ra PDF được cung cấp chỉ là đối chứng, không phải ground truth mặc định.

**Đạt khi:** mỗi lỗi có ROI và kỳ vọng cụ thể; phân biệt bằng chứng trực tiếp với giả thuyết còn cần kiểm.

## R02 — P0: kết thúc đúng giá trị địa chỉ/BHYT

**Files:** `hmu_recognizers.py:_FIELD_BOUNDARY/_field_findings`, `engine.py:additional_findings`; test recognizer/workflow.
**Interfaces:** giữ `Finding(entity_type,start,end,score,text,rule,...)`; `text[start:end]` đúng bằng giá trị.

- [ ] Viết test RED: địa chỉ + `Số BHYT`, `Số thẻ BHYT`, biến thể `S6 BHYT`, có/không hai chấm, tab/khoảng rộng, BHYT nhiều ô.
- [ ] Chạy test, lưu failure thể hiện địa chỉ nuốt nhãn kế tiếp.
- [ ] Dùng chung ranh giới trường ở hai đường nhận diện; địa chỉ dừng trước nhãn BHYT, BHYT chỉ chứa giá trị thẻ.
- [ ] Test GREEN: hai finding độc lập, không có nhãn trong span; không đụng ngày hạn thẻ/giới tính/chẩn đoán/tuổi ở cột khác.

**Đạt khi:** trên trang 12/13/14/15, nhãn địa chỉ và BHYT còn nguyên, các giá trị được khử đủ.

## R03 — P0: hộp theo giá trị, giới hạn mở rộng mực

**Files:** `engine.py:span_rects/expand_rects_with_pixel_ink/merge_and_subsume_proposals`, bản đồ OCR; test engine/OCR.
**Interfaces:** đầu ra rectangle trong hệ display hiện có; không đổi hợp đồng tuple `(offset,line,bbox,char)` âm thầm.

- [ ] Test RED bằng bbox từ tổng hợp: cùng visual row có hai trường, hai cột tên ký, từ bị rơi ở đuôi, khoảng trắng ngắn; thêm crop/rotation 90/270.
- [ ] Sửa helper dùng chung để giữ cụm từ trong từng giá trị/ô, không bridge qua nhãn hoặc ô kế tiếp; expansion dừng theo biên trường.
- [ ] Không để subsume gộp khác loại trường làm mất đề xuất chính xác; giữ ID và trạng thái chọn/bỏ chọn ổn định.
- [ ] Kiểm cả proposal lẫn PDF render cuối: PII trong ROI bị xóa đủ; pixel nhãn/clinical lân cận và cột kế tiếp giữ nguyên theo mask đối chứng.

**Đạt khi:** không chỉ “hộp nhìn gọn”; output không sót đuôi chữ và không xóa nhãn/giá trị bên cạnh.

## R04 — P0: tên bệnh nhân ở bìa và OCR nhiễu

**Files:** `hmu_recognizers.py:_FIELD_LABEL/_INLINE_PATIENT_LABEL/_is_valid_patient_candidate`, `ocr_helper.py`, `engine.py:prepare`; test recognizer/OCR/workflow.
**Interfaces:** giữ map/provenance hiện có. Nếu helper toàn trang không đủ cho retry, thêm `ocr_pdf_regions(pdf_path, regions, *, dpi=200, progress_cb=None)` trong `ocr_helper.py`, tái dùng backend/manifest hiện có; không tạo backend thứ hai. Mỗi region là `{key: str, page: int, rect: [x0,y0,x1,y1], rotation: int}` với page 1-based, rect hệ PDF native, rotation cục bộ 0/90/270. Hàm trả `{key: (text, chars)}` với bbox đã chuyển về hệ PDF native, sau đó engine dùng transform display hiện có. R07 dùng cùng interface khi cần chữ dọc; không đổi signature/map của `ocr_pdf_pages`.

- [ ] Test RED với nhãn bìa bị đọc thành dạng `1.1--10 ten (in hoa)` và tên có dấu gạch/ký tự OCR nhiễu; thêm ca sạch, tên không xuất hiện trong filename/XML.
- [ ] Cải thiện nhận diện neo + giá trị ở vùng hành chính; OCR lại ROI khi không có/không đạt tên, chỉ dùng seed có kiểm chứng từ cùng bệnh nhân.
- [ ] Kiểm bao đủ họ/tên đệm/tên cuối ở trang 1 và các trang lặp; không nối sang ngày sinh/giới tính hoặc chọn cả tiêu đề bệnh viện.
- [ ] Khi retry vẫn không chắc, tạo cảnh báo/đề xuất cần duyệt với provenance, không ghi nhận “đã xử lý đầy đủ”.

**Đạt khi:** tên bìa trong mẫu mới có vùng đúng; giữ được tên khác/chữ nhiễu hợp lý trong fixture tổng hợp, không hardcode bệnh nhân.

## R05 — P1: cập nhật chính sách tuổi

**Files:** recognizer/engine/audit, `review.html`, hướng dẫn, test recognizer/engine/app theo mức thực sự cần sửa.
**Interfaces:** thêm entity `PATIENT_AGE` nếu không có sẵn; proposal vẫn dùng `kind/text/rects/selected`. Policy fingerprint phân biệt job trước/sau.

- [ ] Test RED: `Tuổi: 94 tuổi`, ô số 9|4, tuổi 0/100 và tuổi xuống dòng; ca âm tính EF 94, glucose/nhịp tim/số lượng 94 ngoài trường tuổi.
- [ ] Nhận diện giá trị theo neo `Tuổi`/biến thể OCR và ô bảng; chỉ mask chữ số tuổi, giữ nhãn/đơn vị/giới tính, không lấy DOB rectangle làm tuổi.
- [ ] Cập nhật audit/hướng dẫn/copy UI đang ghi “giữ Tuổi”, schema/policy và tests vốn cố ý giữ tuổi.
- [ ] Test tuổi ở bìa và các trang 12–21 cùng đi theo chính sách mới; job cũ được cảnh báo/tạo lại, không âm thầm trộn hai chính sách.

**Đạt khi:** tuổi bệnh nhân được khử theo yêu cầu mới; các số chuyên môn không thay đổi.

## R06 — P0: ngăn nhận nhầm kết quả chuyên môn thành tên

**Files:** `hmu_recognizers.py:build_document_identifiers/_compile_memorized_name_patterns/_analyze_normalized_document`, `engine.py:additional_findings`; test recognizer/engine.
**Interfaces:** giữ findings/known hiện có; nguồn và chất lượng seed phải truy vết được khi quyết định auto-select.

- [ ] Test RED **nhiều trang**: trang đầu học tên nhân viên; trang sau có “Van hai lá”, “Diện tích lỗ van”, “Hở/Hẹp van hai lá: Không”; tái hiện `memorized_staff_mid_given` sai.
- [ ] Siết seed và short/fuzzy matches bằng neo/vùng/ngữ cảnh; không coi điểm số hardcode 0.99 là bằng chứng đủ để tự xóa.
- [ ] Chặn nhận nhầm trên bảng clinical nhưng giữ test dương tính tên thật tương tự ở vùng ký/chức danh; kiểm tên OCR vỡ dòng vẫn phát hiện được.
- [ ] Kiểm exported pixels của nhãn, kết quả “Không”, chỉ số và bảng ở trang 14/15; thêm thuật ngữ y khoa ngoài hai cụm báo cáo để tránh fix bằng blacklist riêng lẻ.

**Đạt khi:** không còn auto-selected tên giả trong ROI chuyên môn đã đánh dấu, không làm mất khả năng khử tên thật đã có ground truth.

## R07 — P0: điều dưỡng ký và ghi tên theo ô

**Files:** `engine.py:build_image_and_signature_proposals`, OCR ROI, test engine/OCR/workflow.
**Interfaces:** tái dùng proposal chữ ký/tên hiện có; vùng ảnh toàn trang không được chọn xóa nguyên object.

- [ ] Test RED bảng có neo `Điều dưỡng`/`Ký và ghi tên`, nhiều cột ký, tên dọc 90/270; hai phiên bản ảnh toàn trang và chữ/vector outline, có ô trống.
- [ ] Tìm hàng và cột ký từ neo + cấu trúc bảng; xác định nét ký/tên trong từng ô, OCR ROI xoay khi cần; giữ nhãn và đường bảng.
- [ ] Kiểm tên in + chữ ký viết tay đều được che trong ô đã đánh dấu; không cần nhận dạng nội dung chữ ký viết tay mới che được vùng ký rõ ngữ cảnh.
- [ ] Kiểm trang 19–21; các biểu đồ, dấu mốc sinh hiệu và hàng cân nặng/nhịp thở/BMI phía trên không đổi. Ca thiếu neo/mâu thuẫn chuyển duyệt.

**Đạt khi:** vùng ký/tên điều dưỡng không bị bỏ sót và không phải xóa trắng cả khu vực bảng.

## R08 — P1: rà các lỗi khác trên 71 trang

**Files:** ground truth riêng tư + regression fixtures trong test hiện có; chỉ sửa recognizer/engine liên quan lỗi tái hiện được.

- [ ] Rà theo nhóm: bìa 1–2; xét nghiệm/chẩn đoán hình ảnh 3–18; theo dõi/chăm sóc 19–27; bảng thuốc/truyền dịch 28–37; biểu mẫu 38–42; điều trị 43–66; thanh toán/khám lại 67–71. Xác nhận loại từng trang bằng render thực.
- [ ] Ghi FN/FP theo loại tên, địa chỉ, điện thoại, BHYT, DOB/tuổi, chữ ký/QR; kiểm cả tên nằm trong nội dung nhiều cột, ký lặp, ô trống và trang chỉ có bảng.
- [ ] Mỗi lỗi mới có test RED → sửa root cause → GREEN; gom lỗi cùng nguyên nhân, không thêm rule cho riêng từng bệnh nhân/trang.
- [ ] Báo vùng chưa quyết định được và số trường chưa đánh dấu ground truth; không dùng tổng số hộp tăng/giảm làm thước đo accuracy.

**Đạt khi:** có ledger từng trang/trường và trạng thái giải quyết; các ca chưa đạt được nêu tên rõ.

## R09 — P1: nhất quán review, audit, export và job cũ

**Files:** engine/app/review UI và test tương ứng.

- [ ] Test RED: edit/deselect hộp, đổi policy, response cũ sau chuyển trang, job cũ từ bản trước; fingerprint/revision không khớp phải bị chặn/cảnh báo đúng.
- [ ] Sửa phần cần thiết để cùng snapshot dùng cho preview/audit/export; giữ save queue, job guard và source SHA hiện có.
- [ ] Hiện provenance/đề xuất không chắc ở nơi giúp người duyệt quyết định; không thêm màn hình/cấu hình ngoài nhu cầu này.
- [ ] Chạy HTTP + Node regression; đối chiếu số vùng/loại/phạm vi mask và revision trong audit/QC với ảnh xuất.

**Đạt khi:** không có “review một kết quả, xuất một kết quả khác”; đề xuất chưa chắc không bị biểu diễn như đã nghiệm thu.

## R10 — P0: nghiệm thu độ chính xác và đóng băng R1

**Files:** toàn bộ test, manifest ground truth riêng tư, evidence JSON.

- [ ] Chạy toàn bộ Python suite (gồm 14 workflow), Node regression, `pip check`, `git diff --check`; thêm mọi regression mới, ghi rõ SKIP/lỗi môi trường.
- [ ] Dùng bản **draft** từ PDF gốc, kiểm chi tiết đủ 71 trang theo ROI đã đánh dấu; không tự đặt tất cả `reviewed=True` để tạo bản chính thức.
- [ ] Đo FN/FP theo trường và pixel bảo vệ; kiểm metadata/attachment/source objects, lân cận nhãn, clinical và đường bảng.
- [ ] Chụp bằng chứng trước/sau bốn lỗi cùng DPI, tọa độ và crop; ghi kết quả còn sai. Đóng băng R1 source + SHA sau khi tiêu chí đạt để đo tối ưu.

**Đạt khi:** lỗi đã báo có bằng chứng sửa đúng ở PDF xuất; không chỉ có test chuỗi đạt. Chưa đạt tiêu chí nào phải giữ task đó mở.

## P01 — P1: mốc benchmark cùng môi trường

**Files:** benchmark scripts hiện có; snapshot/results ở thư mục đã ignore.
**Interfaces:** giữ CLI `--source-dir --output --cases --warmup --runs`; `compare_measurements.py` từ chối corpus hash khác nhau.

- [ ] Freeze R0 hiện tại, giữ B0 nguyên trạng; ghi Python/dependency/OCR language, CPU/RAM, source/corpus SHA và protocol. Không ghi đè JSON lịch sử.
- [ ] Đo B0 và R0 cùng runtime mới: `native10,native150,case50,vector20,watermark10`, warm-up 1 + 3 lần; ngừng job/test khác khi lấy thời gian headline.
- [ ] Profile/call count trong lượt riêng: audit, mở PDF, get_text/get_drawings/get_pixmap, OCR, proof, I/O. Chỉ tối ưu điểm có chi phí quan sát được.
- [ ] Đo R1 sau sửa chính xác theo cùng protocol; giữ source/corpus khác biệt và số proposal trong metadata. Real sample đo riêng, không trộn vào corpus tổng hợp.

**Đạt khi:** có mốc thật B0/R0/R1, không so số Python 3.10 cũ với số Python 3.12 mới để kết luận tăng tốc.

## P02 — P2: native — bớt parse/I/O/audit lặp

**Files:** `engine.py:prepare/generate_audit_markdown/_write_export_pair`, tests engine/workflow, benchmark phases.

- [ ] Đọc profile native10/native150, pin test đếm đúng công việc lặp tốn thời gian; không đặt trần call count tùy ý cho helper rẻ.
- [ ] Tái sử dụng dữ liệu trong một snapshot/page; nếu bỏ một pass render/redact thì phải chứng minh output raster và safety invariants bằng nhau, không bỏ kiểm tra đầu vào.
- [ ] Kiểm proposal/audit và vùng pixel bảo vệ giống R1; test source sửa/revision thay đổi phải làm cache vô hiệu.
- [ ] Đo lại native10/native150 unprofiled, 3–5 lần; giữ thay đổi chỉ khi chất lượng đạt và median cải thiện so R1.

**Đạt khi:** ghi được mức cải thiện riêng prepare/export/total và mức còn chênh B0; không tuyên bố đạt nếu chỉ một phase nhanh.

## P03 — P2: batch — audit một lần cho một snapshot

**Files:** `engine.py:export_case/prepare_case`, test engine/app, benchmark case50.

- [ ] Test RED đếm `generate_audit_markdown` trong export_case: hiện gọi lại khi ghép combined audit; mỗi snapshot chỉ cần một audit đã kiểm chứng.
- [ ] Dùng lại kết quả audit vừa tạo khi ghép; giữ preflight mọi file, lỗi QC/pointer không công bố generation thiếu.
- [ ] Kiểm combined audit đủ mọi file/revision, output theo study ID và không lẫn tên nguồn; test thất bại ở file giữa batch vẫn giữ bản công bố trước.
- [ ] Benchmark case50, đo total, I/O và RAM theo cùng corpus; chỉ mở rộng tối ưu shared data khi profile chỉ ra chi phí còn lại.

**Đạt khi:** audit không bị dựng hai lần cho cùng snapshot, kết quả và cơ chế publish không thay đổi.

## P04 — P2: vector — giảm quét lặp, giữ phân loại

**Files:** `engine.py:vector_qr_rects/barcode_rects/expand_rects_with_pixel_ink`, test engine/workflow, benchmark fixtures.

- [ ] Profile vector20 và một fixture tổng hợp mật độ tương đương chữ outline trong mẫu; không coi vector20 ít nét là đại diện đầy đủ.
- [ ] Pin regression cho QR thật, ô bảng/đồ thị, cụm vuông rời và ảnh chuyên môn; so sánh rectangle/selection với R1.
- [ ] Giảm vòng quét/dữ liệu lặp ở điểm profile xác nhận; kiểm thứ tự/độ chính xác cụm và ink-probe boundaries không đổi.
- [ ] Đo total/RAM trên vector20 và vector đặc; chạy canh hồi quy scan/mixed để không đổi nhanh vector bằng cách tăng công việc nơi khác.

**Đạt khi:** không sinh thêm QR/chữ ký giả hoặc làm mất nét chuyên môn; số đo giảm thực so R1.

## P05 — P2: watermark — dùng lại proof trong page snapshot

**Files:** `engine.py:watermark_streams/apply_review_to_page`, test engine safety/workflow.

- [ ] Test RED cho proof lặp; pin mỗi proposal phải ánh xạ đúng phần watermark bị bỏ, kể cả một safe và một unsafe proposal cùng trang.
- [ ] Tính proof/mapping một lần trong page snapshot hiện tại, dùng lại khi kiểm target; không tin xref cũ từ review.json thay cho revalidation.
- [ ] Chạy q/Q isolation, opacity/graphics/images, mixed-content refusal, watermark chéo clinical, shared xref qua trang, partial selection và pixel reference tests.
- [ ] Đo watermark10 với 400 nét vector/trang, warm-up 1 + 3–5 lần; báo so R1 và B0 tách biệt, giữ mọi refusal an toàn.

**Đạt khi:** giảm proof trùng với cùng khả năng từ chối ca không an toàn; còn chậm B0 thì báo chưa đạt mục tiêu đó.

## P06 — P0: kiểm toàn bộ, đo sau và báo cáo thực tế

**Files:** test/evidence/results, báo cáo vòng 2 và hướng dẫn nếu cần.

- [ ] Chạy lại full suite + Node + pip check + diff check trên source R2 cuối; không dùng log trước thay đổi làm bằng chứng sau.
- [ ] Đo R2 matched với B0/R0/R1; nhóm chính native10/native150/case50/vector20/watermark10, canh hồi quy scan50/mixed10/largephoto2. Tăng số lần khi dao động lớn, giữ từng lần thay vì chọn số nhanh nhất.
- [ ] Báo prepare/export/total, median/range, sampled task RAM và output size; pipeline trên bệnh án thật ghi riêng, không thay thế fixture benchmark tổng hợp.
- [ ] So lại ground truth 71 trang và bốn cặp ảnh trước/sau, test vùng bảo vệ; không công nhận nhanh hơn nếu FN/FP xấu đi hoặc guard bị bỏ.
- [ ] Báo rõ **đã đạt / chưa đạt / chưa kiểm chứng**. Mục tiêu tối thiểu tối ưu là tốt hơn R1 với cùng kiểm an toàn; mục tiêu hết chậm hơn B0 chỉ đánh dấu đạt bằng số thực. Chưa đo browser p95 thì không lấy HTTP p95 thay thế.

## Lệnh kiểm và đo

Chạy test từ `HMU_KhuDinhDanh`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -p 'test_*.py' -v
node test_ui_save.js
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Ví dụ đo từ root repo, dùng tên snapshot và output mới cho từng mốc:

```powershell
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\benchmark_workflow.py --source-dir HMU_KhuDinhDanh\benchmarks\baseline_source --cases native10,native150,case50,vector20,watermark10 --warmup 1 --runs 3 --output HMU_KhuDinhDanh\benchmarks\results\ROUND2_B0.json
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\benchmark_workflow.py --cases native10,native150,case50,vector20,watermark10 --warmup 1 --runs 3 --output HMU_KhuDinhDanh\benchmarks\results\ROUND2_R2.json
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\compare_measurements.py HMU_KhuDinhDanh\benchmarks\results\ROUND2_B0.json HMU_KhuDinhDanh\benchmarks\results\ROUND2_R2.json HMU_KhuDinhDanh\benchmarks\results\ROUND2_B0_vs_R2.json
```

Khi sandbox chặn thao tác tệp tạm, chạy lại đúng kiểm thử với quyền thực thi phù hợp; không sửa code để né guard. Chỉ đánh dấu checkbox khi đã có bằng chứng tương ứng. Không đưa job chẩn đoán hoặc PDF bệnh án thật vào commit.
