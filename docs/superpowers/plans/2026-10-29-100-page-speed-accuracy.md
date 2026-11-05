# Tối ưu 100 trang trong 3–4 phút — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đạt 180–240 giây thời gian máy cho một PDF thực khoảng 100 trang, từ nhận file đến tải PDF đã khử và QC, đồng thời giữ các kiểm tra an toàn và cải thiện nhận diện.

**Architecture:** Tối ưu trong engine/OCR/server hiện có. Giảm phân tích stream và khử lặp; dùng xử lý native có điều kiện, kết quả mask cùng snapshot cho audit, raster/nén lossless và số tiến trình nhỏ được đo trên hồ sơ thật. Không thêm dịch vụ hoặc thay OCR trước khi đo hết các nút thắt này.

**Tech Stack:** Python 3.12.10 trên máy đo hiện tại; PyMuPDF 1.26.6; pypdf 6.10.0; Windows.Media.Ocr; HTTP localhost; unittest; JavaScript hiện có.

**Spec:** [Báo cáo rà soát và phương án đề xuất](../../../../BAO_CAO_RA_SOAT_TOC_DO_2026-10-29.md). Kế hoạch này đã được cho phép triển khai; lịch sử kiểm và các quyết định nằm trong ledger riêng, kết quả bàn giao ở [báo cáo 30/10](../../../../BAO_CAO_TOI_UU_2026-10-30.md).

**Điều chỉnh phạm vi đã được người dùng xác nhận:** nghiệm thu trên PDF thực71 trang, quy đổi tuyến tính127,8–170,4s thành180–240s/100 trang. Không cần chờ PDF100 trang mới để kết luận phạm vi này; không gọi số quy đổi là phép đo100 trang thực. Thay vì sửa protocol synthetic cũ, dùng runner HTTP riêng `benchmarks/benchmark_real_workflow.py`, được kiểm hồi quy và băm mã trước/sau. Không commit gộp workspace đang có; checkpoint dùng bản sao/hash và ledger trong thư mục riêng đã ignore.

**Quyết định Task7 sau đo thực:** dùng4 OCR worker từ64 trang (median21,858s so với31,962s ở2, map khớp và RAM khoảng697MiB), cùng tối đa2 tiến trình dựng ảnh chạy trước OCR (median17,789s so với27,795s serial, PNG khớp byte). Tải nhỏ vẫn serial. Mốc10% được đánh giá cho cả gói điều phối trên total, không suy ra bằng cộng các thời gian profiler lồng nhau.

**Bổ sung nghiệm thu chất lượng:** reference cuối revision9/policy `geometry_v6`; không chừa pixel chữ ký ở dải bảng.409 ROI gồm395 gốc+nhãn p71+4 vùng DOB/địa chỉ còn sót đã xác nhận+9 vùng lân cận cần giữ.15 dải bảng dùng control native chỉ xóa ảnh, giữ các path bảng; raw-source oracle cũ có lẫn nét chữ ký. Nhận diện chung sửa DOB inline/verbose, địa chỉ lỗi OCR và loại nhãn biểu mẫu giả.197 kiểm thử (196PASS,1SKIP fixture riêng). Bỏ resource-Form vì làm mất path vector đang dựng; chỉ xóa đúng byte lệnh ảnh, giữ fallback cho scan/ảnh lồng còn lại, rollback Contents gốc khi text thay đổi. Các chuỗi20 cũ chỉ giữ làm lịch sử; nghiệm thu mã cuối dùng `safe_acceptance_20.json`, không trộn số.

## Global Constraints

- Thời gian máy mục tiêu: 180–240 giây/100 trang; không tính thời gian người duyệt.
- Giữ OCR và xuất PDF ở 200 dpi trong phép nghiệm thu.
- Xử lý offline; dữ liệu bệnh án/ground truth nằm trong `HMU_JOBS/` đã git-ignore.
- Giữ toàn bộ Tuổi, nội dung chuyên môn, ICD, ảnh chẩn đoán và chính sách giữ mã hồ sơ hiện hành.
- Giữ source SHA, policy, revision, hình học, kiểm overlap, PDF mới từ pixel và publication PDF+QC nguyên tử.
- Giữ kết quả duyệt thủ công; không tự duyệt hồ sơ thật để lấy số đo.
- Không sửa hoặc commit gộp các thay đổi có sẵn trong workspace. Lưu snapshot/hash trước khi thực hiện.
- Giữ các API công khai và định dạng QC đang dùng; không thêm dependency trong các task 1–6.

## Review Focus

- Cùng bytes PDF nhưng tên tệp Unicode/đường dẫn khác: upload và mở đường dẫn phải nhận cùng dữ kiện hợp lệ; tên tệp không được vượt cổng ngữ cảnh/hình học (Task 2).
- Ảnh chữ ký chồng ảnh chuyên môn, ảnh lặp/shared XObject, Form/inline image: chỉ đường đã chứng minh an toàn được tăng tốc; trường hợp khác dùng đường hiện tại (Task 5).
- Review đổi trong lúc xuất, source đổi, QC/audit lỗi: không dùng mask cũ hoặc thay thế generation hợp lệ trước (Task 3).
- Crop/rotation 0/90/180/270, seam OCR, tên nhỏ, đường bảng mảnh: không đổi pixel do tái dùng raster hoặc nén (Task 4 và 6).
- 100 trang khác nhau, chữ dày, hết thời gian OCR hoặc worker lỗi: không mất trang, không treo báo tiến độ, không công bố sản phẩm một phần (Task 7–8).

## Bản đồ thay đổi

| Tệp | Trách nhiệm |
|---|---|
| `benchmarks/benchmark_workflow.py`, `benchmarks/ocr_worker_sweep.py` | Tái dùng bộ đo hiện có; thêm đầu vào thật và đo HTTP, giữ riêng profiler |
| `app.py` | Chuyển tên gốc hợp lệ vào nhận diện, giữ token/job/revision/task/khóa |
| `hmu_recognizers.py` | Dùng chung dữ kiện tên tệp, giữ kiểm ngữ cảnh trước học tên |
| `engine.py` | Xóa ảnh có proof, mask/audit cùng snapshot, drawing/raster/nén |
| `ocr_helper.py` | Tránh giải mã PNG thừa, đo worker, tiến độ và timeout |
| Các `test_*.py` hiện có | Thêm hồi quy vào module sở hữu hành vi; không đưa PII thật vào source |
| `HUONG_DAN_SU_DUNG.md`, `benchmarks/README.md` | Sửa hướng dẫn và ghi đúng phạm vi số đo sau nghiệm thu |

## Task 1: Đóng băng mốc và thiết lập phép nghiệm thu đúng tải

**Files:** Modify `benchmarks/benchmark_workflow.py`, `benchmarks/README.md`; Test `test_round2.py`; dữ liệu thật chỉ ở `HMU_JOBS/`.

**Interfaces:** Giữ các tham số benchmark đang có; thêm `--real-pdf PATH` và `--http`. `--real-pdf` chạy một PDF đọc từ ngoài job, job mới mỗi lượt; `--http` đo upload/prepare và export/download của server localhost. Kết quả thêm `input_sha256`, `review_sha256`, `mask_sha256`, `source_hashes`, `machine_seconds`, `human_seconds_excluded`, kích thước đầu ra và phạm vi RAM. `mask_sha256` băm JSON canonical của DPI, thứ tự/kích thước trang, các kind/rect/method/target được chọn và manual rects; không băm job ID/revision ngẫu nhiên vào phép so tương đương mask.

- [ ] Viết `test_real_benchmark_preserves_input_and_uses_new_jobs`: assert hash nguồn không đổi, job mỗi lượt khác nhau, không gọi `approve_all_pages` trên hồ sơ thật. Viết `test_machine_total_sums_intervals_per_run`: assert `machine_seconds == ingest_prepare_seconds + export_download_seconds`, không cộng median của các pha.
- [ ] Chạy hai test mới, xác nhận FAIL trước khi thêm khả năng mới.
- [ ] Thêm chế độ trên bằng các hàm `TaskMemory`, prepare/export và server hiện có. Sau fresh prepare, áp lại mask từ bản sao manifest đã kiểm chỉ khi source SHA, thứ tự/kích thước trang và geometry phù hợp; giữ job ID/working SHA/analysis mới của job đó. Bản chưa duyệt chỉ được xuất DRAFT. Không sửa các job bàn giao hoặc chép nguyên identity của review cũ vào job mới.
- [ ] Chạy test mới và benchmark PDF 71 trang có cùng review revision6. Đo riêng một lượt fresh OCR và các lượt dùng mask cố định; không trộn hai nhóm. Ghi khoảng thời gian, CPU/RAM khả dụng và lỗi môi trường.
- [ ] Lưu checkpoint riêng cho task; không gộp các sửa đã có từ phiên trước.

## Task 2: Sửa khác biệt dữ kiện nhận diện giữa upload và mở đường dẫn

**Files:** Modify `app.py:work_open`, `engine.py:prepare`, `hmu_recognizers.py:extract_case_seeds`; Test `test_app.py`, `test_hmu_recognizers.py`.

**Interfaces:** Thêm keyword tùy chọn `source_name=None` vào `prepare(..., *, case_xml_index=None, source_name=None)` và `extract_case_seeds(source_path, *, xml_index=None, source_name=None)`. Dùng basename đã kiểm để lấy dữ kiện tên; giữ tên lưu nội bộ `source_private.pdf`. Lời gọi cũ tiếp tục hoạt động.

- [ ] Viết `test_upload_preserves_filename_seed_without_workspace_lookup`: cùng PDF giả lập chứa `Ho ten: TRINHVANHU0NG`, tên nguồn `BA87654321_TRINH_VAN_HUONG.pdf`; assert cả upload và mở đường dẫn có đúng một đề xuất `PATIENT_NAME` được chọn. Thêm Unicode NFC/NFD và trường hợp tên tệp không hợp lệ; assert không tạo seed hoặc truy cập path từ header. Thêm tên giống thuật ngữ chuyên môn; assert cổng ngữ cảnh/hình học vẫn chặn tự chọn sai.
- [ ] Chạy test đầu, xác nhận upload hiện trả 0 trong khi đường dẫn trả 1.
- [ ] Chuyển tên gốc qua helper dùng chung; XML vẫn chỉ lấy từ nguồn tìm thấy hợp lệ, không suy ra XML/path truy cập từ chuỗi header.
- [ ] Chạy `python -m unittest test_app test_hmu_recognizers test_round2 -v`; xác nhận case trước và các ca tránh xóa thuốc vẫn đạt. Không đổi mask các job cũ.
- [ ] Lưu checkpoint cho sửa độ chính xác này; ghi rõ đây không phải tăng tốc cùng-mask để so benchmark.

## Task 3: Tái dùng kết quả khử cho audit của cùng lần xuất

**Files:** Modify `engine.py:_write_export_pair`, `generate_audit_markdown`, `export`, `export_case`; Test `test_round2.py`, `test_engine_safety.py`, `test_app.py`.

**Interfaces:** Thêm keyword `applied_pages=None` cho `_write_export_pair(...)` và `generate_audit_markdown(...)`. Dict chỉ sống trong một operation; khóa trang 1-based, giá trị `pixel_rects` theo tọa độ hiển thị. Snapshot nhận diện bằng `(working_sha256, job_id, revision, dpi)`; không lưu cache dùng chung giữa các revision.

- [ ] Viết `test_export_audit_reuses_applied_page_masks`: assert 71 trang chỉ gọi `apply_review_to_page` 71 lần trong export+audit, thay vì 142. Viết ca manual/deselect/rotation/ảnh fallback: assert Markdown bằng đường tính lại độc lập. Viết ca snapshot sai và audit lỗi: assert từ chối hoặc tính lại đúng snapshot, pointer cũ không đổi.
- [ ] Chạy các test mới, xác nhận RED về số lần gọi.
- [ ] Thu kết quả mask khi xuất và truyền vào audit. `/audit` trước lần xuất vẫn tính theo review hiện hành. Không bỏ nội dung audit hoặc chuyển chi phí ra ngoài khoảng đo để báo tốc độ tốt hơn.
- [ ] Chạy HTTP stale/busy, audit, publication/failure tests và batch-count test. Assert QC/audit/PDF cùng job/revision; output_path vẫn giữ hợp đồng hiện tại.
- [ ] Đo lại total, lưu checkpoint. Không cộng thời gian audit và parser lồng nhau thành mức tiết kiệm độc lập.

## Task 4: Đo và tối ưu nén lossless

**Files:** Modify `engine.py:_write_export_pair`; Test `test_round2.py`; tái dùng script benchmark.

**Interfaces:** Giữ PDF một ảnh raster mới/trang, QC và tuple trả về. Không tạo helper hoặc tùy chọn người dùng nếu chỉ một điểm sử dụng.

- [ ] Viết `test_lossless_raster_stream_round_trip`: assert RGB giải mã, kích thước, màu, alpha và thứ tự trang đúng tuyệt đối trên ảnh chữ/bảng/ảnh chuyên môn khác nhau; không mang text/annotation/widget/attachment nguồn sang. Giữ test tránh PNG encode/decode roundtrip và nén từng trang trước save.
- [ ] Đo riêng `update_stream` cho image và content streams. So nén native với `zlib` chuẩn ở level 1/3/6 trên cùng RGB, đo cả bytes và thời gian; assert giải nén bằng nhau.
- [ ] Nếu thấp hơn đáng kể, dùng mức lossless nhanh nhất đáp ứng dung lượng được đo; thiết lập `/Filter /FlateDecode` và stream bytes nhất quán, reopen/kiểm tra. Không đổi sang JPEG lossy hoặc giảm DPI.
- [ ] Chạy pixel/structure tests, so raster 71 trang của cùng mask. Đo thêm thời gian ghi/tải file lớn hơn để so total, không chỉ thời gian compressor.
- [ ] Lưu checkpoint kèm mức nén đã đo; nếu không có lợi, không thêm đường nén mới.

## Task 5: Giảm chi phí phân tích stream để xóa ảnh

**Files:** Modify `engine.py:remove_selected_image_paints`, `engine.py:apply_review_to_page`; Test `test_engine_safety.py`, `test_round2.py`.

**Interfaces:** Giữ `remove_selected_image_paints(page, selected_rects) -> list[int]` và tuple trả về của `apply_review_to_page`. Chỉ mục trả về vẫn theo `selected_rects` đầu vào.

- [ ] Viết `test_disjoint_image_removal_avoids_python_stream_parse`: chữ ký rời, native text nằm dưới, ảnh chuyên môn ngoài vùng; assert không gọi `ContentStream.operations` trên đường đủ điều kiện, text giữ nguyên và raster khớp reference. Viết các ca chồng ảnh, ảnh dùng lại cùng trang/khác trang, transform, Form, inline image và partial selection; assert không xóa thêm ảnh hoặc đổi trang không chọn.
- [ ] Chạy test tránh parse để xác nhận RED; các pixel test hiện có phải giữ nguyên ngưỡng.
- [ ] Thêm kiểm tra nhẹ: không có paint khớp hình học thì trả fallback ngay. Với ảnh khớp và không chồng ảnh cần giữ, đánh giá xóa ảnh bằng MuPDF native với fill tắt, graphics/text giữ nguyên; chỉ bật khi các proof và pixel test trên đạt. Trường hợp chưa chứng minh tương đương đi qua parser hiện tại. Không thay bằng `delete_image(xref)` toàn cục hoặc phủ trắng cả ảnh chuyên môn.
- [ ] Chạy các module an toàn/round2, rồi xuất đúng revision6 và so sánh raster giải mã đủ 71 trang với reference. Mọi khác biệt phải có phân loại; các lỗi chất lượng đã mở không được coi là reference đúng tuyệt đối.
- [ ] Đo lại riêng pha này trên cùng-mask. Nếu không nhanh hơn có ý nghĩa, giữ kiểm tra bỏ parse khi chắc chắn không khớp và loại đường native thử nghiệm; lưu kết quả thật.

## Task 6: Giảm drawing và render/giải mã lặp

**Files:** Modify `engine.py:prepare`, `barcode_rects`, `vector_qr_rects`, `expand_rects_with_pixel_ink`, `boxed_age_proposals`, `nurse_signature_regions`, `build_image_and_signature_proposals`; Modify `ocr_helper.py:ocr_pdf_pages`; Test `test_round2.py`, `test_ocr_safety.py`.

**Interfaces:** Các helper vùng giữ kết quả cũ; thêm keyword nội bộ `_display_list=None` cho các helper cần render ROI và truyền tiếp từ classifier ảnh. Mỗi trang tạo tối đa một DisplayList trước khi khử, `annots=True`; hủy sau trang. Compact drawings chỉ dùng ở barcode/QR, không đổi phép so ngữ nghĩa watermark.

- [ ] Viết `test_compact_drawings_preserves_barcode_qr_and_outline_negatives`; assert cùng rects/selection với reference, gồm >2000 outline/trang. Viết `test_cached_displaylist_preserves_roi_pixels_and_rotation`; assert raster ROI đúng byte ở DPI đang dùng, đủ crop/xoay và nhãn tuổi/điều dưỡng. Viết `test_small_prerendered_png_ocr_does_not_decode_pixmap_again`; assert bỏ lần decode Python thừa nhưng cùng kích thước/text/char map.
- [ ] Chạy test mới, xác nhận RED về số lần dựng/giải mã. Không dùng thời gian ngắn giả lập làm bằng chứng hồ sơ thật.
- [ ] Dùng `get_cdrawings()` để đọc rect/fill gọn; chuyển kiểu tại nơi cần. Render ROI từ DisplayList ở đúng scale/colorspace/clip cũ. Với PNG đã dựng và không cần tile/rotation, lấy kích thước bằng API đọc thông tin ảnh hiện có, không dựng Pixmap chỉ để đọc width/height; trường hợp khác giữ đường tile.
- [ ] Chạy test barcode/QR, nurse/grid, age, clinical, crop/rotation/tile; đối chiếu ROI thật. Không tắt OCR trang mixed chỉ vì trang có native text hoặc ảnh nhỏ.
- [ ] Kiểm hồi quy native distinct/outline/scan/mixed, crop/rotation/clinical bằng toàn bộ unittest; đo phase và total trên hồ sơ thật71 trang được người dùng chọn. Không đo lại toàn bộ corpus synthetic cũ trong lượt này, không công bố tốc độ mới cho các corpus chưa đo.

## Task 7: Chọn song song nhỏ và sửa giới hạn OCR theo tải thật

**Files:** Modify `ocr_helper.py`, `engine.py:prepare` nếu phép đo yêu cầu; Modify `benchmarks/ocr_worker_sweep.py`; Test `test_ocr_safety.py`, `test_app.py`.

**Interfaces:** Giữ `ocr_pdf_pages(..., max_workers=None, timeout=120)` cho caller hiện tại. Sweep thực 1/2/4 worker trong process mới; mặc định chỉ thay khi có bằng chứng. Nếu render vẫn vượt ngân sách, thêm worker module-level `_render_page_batch(pdf_path, page_numbers, dpi, output_dir) -> list[dict]` với record `page,width,height,path`; mỗi process tự mở PDF, không truyền Document/Page giữa process.

- [ ] Viết test worker map/order/rotation/error: assert kết quả bằng một worker, lỗi con không publish output. Test subprocess phát `PAGE_DONE` nhiều lần nhưng chưa kết thúc: callback phải tăng trước khi `communicate` hoàn tất. Test timeout với backend giả: không đợi thật 120 giây, assert kill+drain+cleanup và không công bố kết quả thiếu tile.
- [ ] Chạy các test tiến độ/timeout mới để xác nhận RED. Đo worker trên cả 71 trang thật và corpus 100 trang khác nhau khi có; synthetic scan50 không quyết định thay máy này.
- [ ] Drain stdout/stderr an toàn để nhận tiến độ thực. Đặt deadline cho batch từ ngân sách operation và tải đã đo; giữ tham số timeout tương thích, không gọi một timeout của toàn batch là timeout từng trang. Không giải quyết bằng tăng timeout vô hạn.
- [ ] Giữ cấu hình đã hiệu chuẩn thật:4 OCR worker và tối đa2 process render chạy ở hai pha tuần tự; map/RGB khớp, RAM dưới1.5GiB và total của20 job mới đạt trần được giao. Dùng các phép đo phase lặp để chọn worker và total để nghiệm thu; không gán một phần trăm cải thiện total có kiểm soát từ các snapshot khác mask/tải nền. MuPDF không dùng threads; snapshot/hash/cleanup được kiểm.
- [ ] Nếu sau các task thuật toán vẫn >240 giây/100 trang, ghi FAIL với pha vượt ngân sách. Đo lại trên cấu hình CPU/RAM mục tiêu trước khi đề xuất nâng máy; không hứa đạt bằng cách bỏ kiểm tra hoặc dùng cache của file cũ.

## Task 8: Nghiệm thu đồng thời tốc độ và độ chính xác

**Files:** Private ground truth/ROI trong `HMU_JOBS/`; Modify test modules thích hợp, `benchmarks/README.md`, `HUONG_DAN_SU_DUNG.md`; xuất báo cáo mới.

**Interfaces:** Giữ ground truth tách `required_redact`, `required_preserve`, `uncertain`; đánh dấu kết quả automatic proposal, automatic selection và human correction riêng. Partial redaction vẫn tính là bỏ sót vùng định danh.

- [ ] Bổ sung ca hồi quy trước sửa cho nhãn Họ tên trang71 và 15 dải bảng. Phân biệt sai hình học mask với sai khác do raster/clip; giữ nguyên oracle/ngưỡng hiện có cho tới khi chứng minh được oracle sai bằng reference độc lập.
- [ ] Nghiệm thu reference71 trang đã xác minh:577 lựa chọn,409 ROI, xóa vật lý và đối chứng đường bảng; OCR lại PDF xuất và kiểm riêng các cảnh báo/nhãn. Không đưa mask ca mẫu vào rule sản phẩm. Người dùng không yêu cầu chờ PDF100 trang mới; chưa có ground truth độc lập đầy đủ cho mọi trường chưa chọn, không công bố precision/recall toàn ca hay chứng nhận100%PII.
- [ ] Chạy `python -m unittest discover -p test_*.py -v`, `node test_ui_save.js`, `python -m pip check`, `git diff --check`. Mọi SKIP phải có lý do; test xanh không thay nghiệm thu dữ liệu thật.
- [ ] Đo đủ20 job mới của cùng PDF71 trang với mask/policy/runtime/DPI cuối; không profiler hoặc QA nặng đồng thời. Báo từng total, median/max và RAM; trần170.4s theo tỷ lệ được người dùng cho phép. Empirical p95 của20 lượt cùng ca không phải p95 của20 bệnh án khác nhau; chưa đo browser paint/queue nhiều người dùng.
- [ ] Chỉ nghiệm thu khi không còn PII trọng yếu đã gắn nhãn trong output đã duyệt; toàn bộ vùng giữ trọng yếu đạt oracle; không còn lỗi nhãn/grid chưa giải thích; output sạch đối tượng nguồn và publication đúng snapshot. Báo precision/recall nhận diện và tỷ lệ sửa tay riêng, có mẫu số. Không công bố mức chính xác toàn bộ khi chưa có nhãn.
- [ ] Báo tốc độ/RAM/dung lượng trước-sau, tình trạng mọi lỗi cũ/mới, kết quả 100 trang và giới hạn. Nếu có tiêu chí fail, giữ trạng thái chưa nghiệm thu; không chuyển chi phí audit/QC sang bước sau để chốt đủ 4 phút.

## Ngân sách dùng để ra quyết định

| Pha cho 100 trang | Trần đề xuất |
|---|---:|
| Nhận file, kiểm và tạo working | 15s |
| Dựng ảnh + OCR, có tái dùng/điều phối | 100s |
| Nhận diện và hình học | 25s |
| Xóa đối tượng, raster cuối, nén lossless | 70s |
| Audit, QC, publication và tải | 20s |
| Tổng | 230s |

Đây là ngân sách thiết kế, không phải kết quả đã đạt. Pha vượt trần phải có phép đo và quyết định tiếp theo; không bù bằng giảm độ chính xác.

## Tự rà soát kế hoạch

- Phạm vi đã nối đủ caller CLI, single-file HTTP, batch, audit, export và kiểm thử; không có migration âm thầm cho review cũ.
- Task 2 xử lý khác biệt ngữ nghĩa đầu vào; benchmark cùng-mask của Task 3–7 tách khỏi thay đổi đó.
- Các trường hợp Review Focus đều có test/task sở hữu. So raster khớp bản cũ là kiểm tương đương, không phải chứng minh bản cũ không còn lỗi.
- Các nhánh tăng tốc native/nén/song song có điều kiện đo và đường dừng rõ ràng; không có dependency/dịch vụ mới được mặc định thêm.
- Nghiệm thu tốc độ theo tỷ lệ71 trang được người dùng cho phép. Nghiệm thu100 trang thực và precision/recall của mọi trường vẫn cần corpus/ground truth tương ứng; không nhân bản một trang hoặc gọi các lượt lặp cùng ca là nhiều bệnh án độc lập.
