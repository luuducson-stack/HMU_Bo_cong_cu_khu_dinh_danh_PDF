# Đo và tối ưu hiệu năng xử lý PDF — Implementation Plan

> Cập nhật triển khai 28/10/2026: source đã sửa và kiểm chứng; trạng thái nghiệm thu, giới hạn và mục tiêu hiệu năng chưa đạt xem [báo cáo thực tế](../../../../BAO_CAO_TRIEN_KHAI_2026-10-28.md). Các bước chi tiết bên dưới được giữ làm kế hoạch gốc để đối chiếu, không thay thế log kiểm thử.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Kế hoạch này chưa được thực thi; không coi mục tiêu tốc độ là kết quả đo được.

**Goal:** Tăng tốc mở/duyệt, OCR và xử lý ca nhiều PDF, giảm RAM/IO, giữ nguyên chất lượng đầu ra và các ràng buộc an toàn F01–F15.

**Architecture:** Đo theo công đoạn trước; loại đọc/render/quét XML lặp và toàn bộ review gửi lại; chỉ tăng song song OCR khi số đo chứng minh có lợi. Giữ cache ở phạm vi job/trang, có fingerprint; xử lý tuần tự hoặc process có giới hạn, không dùng chung đối tượng PDF giữa thread.

**Tech Stack:** Python stdlib (`time.perf_counter`, `cProfile`, `pstats`, `hashlib`, `bisect`, `ctypes`, `unittest`), PyMuPDF 1.26.6, pypdf 6.10.0, Windows.Media.Ocr.

**Spec:** [Thiết kế sửa lỗi và hiệu năng](../specs/2026-10-28-remediation-performance-design.md).

## Global Constraints

- Một tác vụ nặng/server; không chia sẻ `fitz.Document` giữa thread.
- Xử lý offline, không gửi bệnh án lên dịch vụ ngoài; không cache chéo ca bệnh.
- Giữ DPI OCR 200, xuất 200 mặc định và PNG không mất dữ liệu.
- Không bỏ kiểm hash/schema/revision/vùng xóa/QC để tăng tốc.
- Không thêm framework/dependency; không đổi OCR engine/GPU hoặc viết lại ứng dụng.
- B0 là số đo bản gốc; B1 là số đo sau F01–F15. Tất cả so sánh tối ưu với B1 hoặc bản trước task trên cùng corpus, cùng máy.
- Nếu một tối ưu không đem lại >=5% ở công đoạn nó nhắm tới qua nhiều lần đo, bỏ phần mã tăng độ phức tạp đó; không cố đạt chỉ tiêu bằng đổi corpus.
- Dữ liệu tạm/analysis chứa PII, lưu trong job, không commit hoặc xuất cùng PDF/QC.

## Review Focus

1. Cache hết hạn khi working PDF, OCR settings, phiên bản engine hoặc schema đổi: P01/P04 phải tính lại, không dùng nhầm ca/trang.
2. Pixel crop/full-page có thể khác ở biên chữ và trang xoay: P02 phải tương đương tọa độ trong sai số <=0,5 điểm và không mất glyph.
3. CPU ít/RAM thấp và nhiều trang lớn: P04/P06 không được nhân số worker vô hạn hoặc giữ đồng thời toàn bộ ảnh/OCR maps trong RAM.
4. Save đến sai thứ tự, user chuyển trang/đóng cửa sổ khi còn thay đổi: P05 phải tuần tự hóa lưu, chặn xuất/chuyển ca đến khi flush xong và cảnh báo dữ liệu chưa lưu.
5. Export/cancel/lỗi giữa chừng hoặc ổ gần đầy: P06 giữ bản hợp lệ trước, dọn staging do task sở hữu; không công bố bộ sản phẩm thiếu và không cần xóa dữ liệu bệnh án của người dùng.

## Checklist

| ID | Kết quả | Điều kiện bắt đầu |
|---|---|---|
| P00 | [ ] Corpus/benchmark B0 và cách đo lặp lại được | Có thể làm trước sửa lỗi; chỉ dữ liệu giả |
| P01 | [ ] Giảm đọc/hash/text/drawings lặp trong prepare | F02, F05; lấy B1 trước tối ưu |
| P02 | [ ] Tăng tốc map span và quét pixel theo kết quả profiler | F03, F10 |
| P03 | [ ] XML/seeds chỉ quét theo ca, không lặp từng file | F01, F05 |
| P04 | [ ] OCR worker/batch/cache được đo và giới hạn | F05, P00 |
| P05 | [ ] Lưu theo trang, render UI và audit theo revision | F09, F11 |
| P06 | [ ] Export hạn chế RAM/IO và không publish output dở | F07, F10 |
| P07 | [ ] So sánh tổng hợp, kiểm hồi quy và chốt cấu hình | Các tối ưu được chấp nhận |

## Điểm nghi ngờ từ source, chưa phải kết luận benchmark

| Công đoạn | Bằng chứng trong source | Thay đổi cần đo |
|---|---|---|
| Hash | `sha` dùng `Path.read_bytes()` cả PDF | Hash streaming để hạ peak RAM, giữ SHA-256 y hệt. |
| Extract | `prepare`, `char_map`, watermark, image detection, validate đều gọi get_text theo dạng khác nhau | Tái sử dụng trong một trang/bản PDF bất biến; không bỏ đối chiếu hash. |
| Vector | Barcode và QR đều đọc `get_drawings()` | Đọc một lần/trang, truyền cùng dữ liệu cho cả hai detector. |
| Span | `span_rects` quét toàn bộ char map mỗi finding | Tra khoảng offset bằng bisect nếu profiler xác nhận đáng kể. |
| Pixel | Mỗi vùng có thể gọi get_pixmap và lặp pixel bằng Python | Dùng chung render/scan row bands khi nhiều vùng; không render full page nếu chỉ một vùng nhỏ. |
| XML | `prepare_case` lấy shared seeds, từng `prepare` lại gọi `extract_case_seeds` | Dùng một chỉ mục/quét theo ca và ánh xạ tệp liên quan; giữ mọi seed nguồn cần thiết. |
| OCR | Đã pre-render trang textless và tối đa 6 worker | Không tuyên bố render trùng đã sửa; đo startup PowerShell, cân tải và nhu cầu cache khi mở lại. |
| Lưu/UI | Save gửi cả review, validate lại mọi trang và viết lại toàn bộ audit | Save patch một trang, audit sinh khi cần theo revision. |
| Export | Giữ `final` đến cuối và mã hóa PNG từng trang | Đo RSS/PNG/nén; chỉ chia shard khi RAM thật sự là giới hạn. |

## P00 — Thiết lập baseline và corpus

**Files:** Tạo `HMU_KhuDinhDanh/benchmarks/benchmark_workflow.py`, `benchmarks/README.md`; kết quả vào `benchmarks/results/` và `.gitignore` cho dữ liệu sinh tự động. Không thêm telemetry trong luồng sản phẩm khi chỉ cần profiler.
**Interfaces:** `benchmark_workflow.py --stage all --output <json>` tạo fixture giả và chạy các stage prepare/export/save theo trạng thái hợp lệ. Output có versions, machine, corpus hash, run index, phase seconds, counts, sampled memory, temp/output bytes. Dữ liệu benchmark không chứa đường dẫn/tên bệnh nhân thật.

- [ ] Tạo corpus native 10/150 trang; scan 10/50 trang; mixed 10 trang; case 50×2 trang; vector/watermark và ảnh lớn. Có manifest ground truth mask/clinical riêng, Unicode, xoay/crop và ca 64 ký tự study ID.
- [ ] Đo B0 bản hiện tại, giữ kết quả không sửa lại sau các lỗi được fix. Trạng thái test 14/14 và thời gian 3,749 giây chỉ là tham chiếu test, không dùng làm số đo prepare/OCR hồ sơ.
- [ ] Sau F13b đo B1 trên đúng corpus đó. Ghi Windows/CPU/RAM/storage/Python/gói/ngôn ngữ OCR, số worker thực tế và trạng thái cache job. Không cố flush cache hệ điều hành hoặc dừng tiến trình người dùng.
- [ ] Mỗi corpus đo một lượt khởi động và 3 lượt đo trên job mới, báo median/range; 30 thao tác chuyển trang/lưu để tính p95. OCR cold-process và mở lại dùng cache báo riêng. Không cộng thời gian cumulative lồng nhau thành tổng.
- [ ] Dùng `cProfile`/`pstats` xác định top chi phí; lấy mẫu RAM Python + tiến trình PowerShell/OCR đang thuộc task mỗi 100ms. Báo đây là peak lấy mẫu, không phải peak tuyệt đối; `tracemalloc` đơn lẻ không đo đủ bộ nhớ native PyMuPDF.
- [ ] Tạo self-check của harness: corpus/hash lặp lại ổn định, output JSON đúng schema và số trang/file đúng; lệnh dự kiến `.\.venv\Scripts\python.exe benchmarks\benchmark_workflow.py --stage all --output benchmarks\results\B1.json`.

**Nghiệm thu:** Có B0/B1 tái lập, thời gian từng pha và RAM tổng task; chưa cần đạt phần trăm tăng tốc ở P00.

## P01 — Đọc, hash và extract một lần khi có thể

**Files:** `engine.py:sha/char_map/prepare/barcode_rects/vector_qr_rects`, `test_workflow.py`.
**Interfaces:** `sha(path)` giữ nguyên kết quả/return; đọc từng khối 1 MiB. `barcode_rects(page, drawings=None)` và `vector_qr_rects(page, drawings=None)` nhận dữ liệu preloaded khi caller có; caller cũ vẫn hoạt động. Context tạm của trang giải phóng ngay khi xong, không global cache PII.

- [ ] Viết `test_streaming_sha_matches_full_file_hash` cho rỗng/1 byte/>2 MiB và `test_cached_extraction_matches_original_geometry`: hash y hệt; text/offset/rects/protected hits y hệt, bao gồm Unicode.
- [ ] Dùng TextPage/analysis trong lượt prepare để tránh trích lại cùng nội dung bất biến; tách lấy thông tin ảnh khỏi lấy byte ảnh khi chỉ cần bbox. Chỉ tái dùng khi trang chưa bị thay đổi; export sau redaction phải dùng dữ liệu tương ứng snapshot.
- [ ] Lấy drawings một lần/trang; hai detector dùng cùng danh sách. Kiểm `get_drawings` call count giảm nhưng barcode/QR list không đổi.
- [ ] Chạy test P01 và workflow, rồi đo prepare native/vector so với B1. Giữ tối ưu hash vì hạ peak memory được đo, không hứa hashing streaming luôn nhanh hơn read_bytes.

**Nghiệm thu:** Hash không đổi, cùng đầu vào cho kết quả nhận diện/hình học tương đương; số lần extract/drawings giảm và không giữ ảnh cả tài liệu trong RAM.

## P02 — Span lookup và quét mực

**Files:** `engine.py:span_rects/expand_rects_with_pixel_ink/prepare`, `test_workflow.py`.
**Interfaces:** Giữ caller cũ `span_rects(chars,a,b)`; nếu profiler chứng minh chi phí lớn, thêm `offsets=None` để caller prepare dùng mảng offset tăng dần đã tạo một lần. `expand_rects_with_pixel_ink` chỉ nhận thêm dữ liệu pixel có sẵn qua tham số keyword tùy chọn nếu đo cho thấy có lợi, không thêm lớp cache tổng quát.

- [ ] Viết `test_indexed_span_rects_equal_linear_scan` với offset thưa/newline/combining/first/last/empty và nhiều findings; kết quả phải bằng danh sách rect baseline.
- [ ] Nếu cần, dùng `bisect_left` vào mảng offset thay vì cắt danh sách toàn bộ rồi quét; vẫn gộp theo line như hiện tại.
- [ ] Viết `test_shared_ink_raster_matches_individual_probes`: ảnh crop/full-page, xoay và mép glyph; chênh hình học <=0,5 điểm, không xóa thêm tuổi/ICD. Áp dụng điều kiện dừng khoảng trắng đã sửa F03.
- [ ] Trước hết dừng vòng row ngay khi đã có đủ dark pixel cho cột, vì tiêu chí hiện tại là >=1. Sau đó mới thử render row-band dùng chung cho nhiều vùng trên cùng dòng; lựa chọn theo số vùng/chi phí đã đo, không render full page mặc định cho một vùng nhỏ.
- [ ] Chạy F03/F10 và so pixel ngoài mask; benchmark trên trang nhiều findings. Chỉ thêm index/cache nếu đạt ngưỡng lợi ích và không tăng RAM quá mức.

**Nghiệm thu:** Tương đương vùng cần xóa/bảo vệ; số lần probe/render hoặc thời gian span giảm rõ, không chỉ tối ưu một vòng lặp không ảnh hưởng tổng.

## P03 — Quét XML và seeds theo ca

**Files:** `engine.py:prepare/prepare_case`, `hmu_recognizers.py:extract_case_seeds`, `test_hmu_recognizers.py`, `test_workflow.py`.
**Interfaces:** Caller `prepare_case` sở hữu việc quét/parse XML: `build_case_xml_index(case_path: Path) -> list[tuple[Path, dict]]` trong `hmu_recognizers.py` trả từng đường dẫn XML với seeds đã parse. `extract_case_seeds(source_path, *, xml_index=None)` vẫn tự tìm/parse khi index là None, còn index được truyền thì chỉ khớp đường dẫn/tên ca và hợp seeds đã có, không parse lại. `prepare(..., external_seeds=None, progress_cb=None, *, case_xml_index=None)` chuyển index của tác vụ xuống extractor. Tệp đơn vẫn lấy seeds từ basename/thư mục và XML liên quan, không bỏ bước vì external_seeds khác rỗng. Index chỉ sống trong prepare_case, không global cache PII.

- [ ] Viết `test_case_xml_index_preserves_all_per_file_seeds`: hai PDF tên khác chứa thông tin bổ sung và XML chỉ khớp tên của file thứ hai; tập seeds hợp mới không được ít hơn bản trước. Thêm `test_case_xml_is_parsed_once_per_task`: spy ở bước đọc/parse trong helper, 50 PDF dùng cùng XML vẫn chỉ đọc/parse mỗi XML một lần, không chỉ đếm rglob.
- [ ] Tìm XML trong phạm vi hiện có một lần theo ca, chuẩn hóa filename/parent một lần; parse mỗi XML liên quan một lần trong ca. Không mở rộng quét toàn ổ đĩa hoặc lấy XML của ca khác vì muốn cache hit.
- [ ] Loại cover_candidates trùng đường dẫn trước đọc mẫu; giữ thứ tự ưu tiên hiện tại. Không giới hạn số PDF/text mẫu thấp hơn để tăng tốc.
- [ ] Chạy test nhận diện và batch; đo số lượt duyệt directory, parse XML và thời gian ca 50 file. Cache trong tác vụ, bỏ khi đổi ca để không dùng seed cũ hoặc giữ PII vô hạn.

**Nghiệm thu:** Không mất seeds/không lẫn ca, directory/XML IO giảm trên batch; tên PDF thứ hai vẫn phát hiện đúng ở file khác theo quy tắc lan truyền.

## P04 — OCR có giới hạn và tái sử dụng an toàn

**Files:** `ocr_helper.py:ocr_pdf_pages`, `engine.py:prepare`, analysis riêng và `test_workflow.py`.
**Interfaces:** Giữ `ocr_pdf_pages` caller hiện có; chỉ thêm keyword `max_workers=None` cho harness chọn 1/2/4/6. Default được chọn sau số đo, vẫn không quá số trang, 6 và giới hạn CPU/RAM được ghi trong benchmark; giới hạn RAM ban đầu chỉ là giả thuyết phải hiệu chỉnh bằng dữ liệu.

- [ ] Đo 1/2/4/6 worker trên cùng corpus/máy, gồm startup PowerShell, thời gian render, RecognizeAsync và tổng; worker vượt CPU/RAM hoặc làm tổng chậm bị loại.
- [ ] Viết `test_ocr_worker_counts_return_same_page_maps`, `test_ocr_cache_invalidates_on_fingerprint_change`: cùng đầu vào ra đủ trang/offset; thay working hash/dpi/engine settings/schema phải miss cache. Cache key ít nhất có working SHA-256, page index, render size, OCR language/engine info, OCR algorithm version và analysis schema.
- [ ] Giữ tái sử dụng pre-render hiện có; không render lại chỉ để tạo preview khi đã có ảnh hợp lệ. Gom OCR theo batch có số pixel ước tính cân bằng nếu round-robin đang tạo đuôi chậm, không tạo một PowerShell/trang.
- [ ] Lưu analysis/OCR theo trang sau khi xong; khi mở lại job có review hợp lệ/migration F11, chỉ dựng lại analysis thiếu hoặc fingerprint không khớp. Không bỏ kiểm “prepare cần thư mục rỗng”; resume job prepare bị ngắt trước khi có review hợp lệ nằm ngoài đợt này. Không tái sử dụng `reviewed=True` khi vùng xóa thay đổi.
- [ ] Bổ sung timeout/cancel có giới hạn cho tiến trình do task tạo, báo trang lỗi; đọc stdout/stderr không để buffer nghẽn. Đo giới hạn từ worst-case fixture rồi ghi rõ giá trị; không kill tiến trình PowerShell không thuộc task.
- [ ] Chạy OCR Windows thật với worker thấp/cấu hình chọn; mô phỏng engine không tồn tại, kết quả rỗng, hỏng một batch; không trả thành công thiếu trang.

**Nghiệm thu:** Mở lại analysis hợp lệ không OCR lại; thay fingerprint OCR lại đúng trang; throughput tăng hoặc peak RAM giảm, không nhân xử lý PDF/OCR chồng nhau ngoài giới hạn.

## P05 — Lưu và duyệt không gửi/viết lại cả hồ sơ

**Files:** `app.py`, `review.html`, `engine.py:generate_audit_markdown`, `test_app.py`.
**Interfaces:** Thêm `POST /save_page` nhận `{job_id,revision,page,reviewed,manual_rects,note,selections:[{id,selected}]}`, trả `{saved:true,revision}`. `/save` cũ vẫn kiểm ID/revision cho tương thích; UI chuyển sang save_page. Không gửi text/char map đã có ở server cho mỗi lần chọn checkbox.

- [ ] Viết `test_save_page_changes_only_target_page` và `test_page_patch_requires_revision_and_valid_geometry`: trang khác không đổi, ID proposal lạ bị từ chối, manual ngoài trang bị từ chối; không tin text/rect proposal từ client.
- [ ] Giữ một hàng đợi save Promise trong UI, gộp thay đổi nhanh trên cùng trang nhưng không làm mất phiên bản mới nhất. Chuyển trang/ca, duyệt và export phải await flush; bật cảnh báo beforeunload khi còn dirty. Không dựa vào sendBeacon vì cần token/revision và phản hồi xác nhận.
- [ ] Chỉ dựng lại audit khi `/audit` hoặc export yêu cầu revision mới; save đánh dấu audit dirty. Cập nhật review.json nguyên tử như hiện tại, không tách database hay nhiều file trạng thái khi chưa cần.
- [ ] Chỉ validate page thay đổi trong save; export vẫn validate toàn bộ và hash working. Phân biệt validator cấu trúc với kiểm giao chuyên môn F10; không làm yếu trust boundary.
- [ ] UI tránh reset canvas/kích thước/drawImage ảnh nền nhiều lần trong cùng frame: dùng `requestAnimationFrame` cho kéo vùng và chỉ dựng lại list khi dữ liệu thay đổi. Cache tối đa ảnh trang trước/hiện tại/sau nếu đo có lợi; xóa khi đổi job, key theo job_id/page/working hash.
- [ ] Chạy test HTTP và thử 30 tương tác trên 150 trang; ghi request bytes, số lần ghi audit, p95 save/navigation. Lỗi mạng/409 phải giữ dirty và hiển thị cần xử lý, không tự ghi đè.

**Nghiệm thu:** Giảm payload/IO và độ trễ; không mất edit khi bấm nhanh, chuyển ca hoặc export; audit vẫn đúng snapshot khi mở.

## P06 — Export với RAM/IO được kiểm soát

**Files:** `engine.py:export/export_case`, `test_workflow.py`, benchmark.
**Interfaces:** Giữ `export`/`export_case` và schema sản phẩm an toàn; staging và generation/pointer F07 công bố cả cặp PDF+QC, chỉ chứa trang ảnh đã redacted, không copy đối tượng nguồn. Không song song nhiều PDF trong ca ở vòng tối ưu đầu.

- [ ] Đo riêng render, mask, PNG encoding, insert_image, final.save và verify; không kết luận nén là nút thắt nếu profiler không cho thấy.
- [ ] Giải phóng pixmap/PNG bytes ngay sau insert, không giữ danh sách ảnh toàn tài liệu. Hash đọc streaming P01 dùng cho source/working/output.
- [ ] Nếu RSS vẫn tăng vượt ngân sách trên corpus lớn, thử shard 10/25/50 trang, lưu tạm chỉ chứa các trang PDF ảnh mới, rồi ráp tuần tự; chọn phương án có peak RAM/thời gian tốt hơn. Không thêm shard nếu chi phí IO lớn hơn lợi ích hoặc không có áp lực RAM.
- [ ] Viết `test_export_shards_match_unsharded_pixels_and_qc` nếu nhánh shard được giữ: số trang/kích thước/pixel sau render/QC vùng bằng baseline; không metadata/file/text/attachment nguồn. Không đòi SHA-256 PDF byte giống vì serialization có thể khác.
- [ ] Chạy `test_failed_reexport_keeps_previous_valid_output`, kiểm lỗi save/verify/cancel giữa file; cleanup chỉ đúng staging thuộc task, không recursive delete theo đường dẫn chưa kiểm.
- [ ] Đo dung lượng và thời gian nén trên cùng PNG lossless; không dùng JPEG/lower dpi để giảm file. Giữ mẫu đầu ra phóng lớn chữ nhỏ, dấu tiếng Việt và ảnh chuyên môn.

**Nghiệm thu:** Peak RAM và tổng thời gian được báo; sản phẩm tương đương hình ảnh/QC, không công bố file dở hoặc bỏ kiểm an toàn.

## P07 — Đánh giá tổng hợp và chốt tối ưu được giữ

**Files:** `benchmarks/README.md`, báo cáo mới trong `docs/`, hướng dẫn cấu hình đang thực sự dùng.

- [ ] Chạy toàn bộ unit/HTTP/workflow/OCR thực; không chạy lặp vô hạn sau khi đã xanh nếu không có thay đổi mới.
- [ ] Chạy benchmark P00 cùng phiên bản Windows/OCR/máy và corpus, ghi B1, sau từng tối ưu và cuối; phân biệt lần mở mới với mở lại cache.
- [ ] Báo bảng trước/sau: native prepare, scan/mixed, ca 50 file, p95 lưu/chuyển trang, export, tổng RSS, đĩa tạm và số lần OCR/render/extract. Đính kèm profiler cho nút thắt còn lại.
- [ ] Mục tiêu tham khảo so B1: native prepare -25%, scan tổng -20%, p95 lưu/chuyển trang -50% nếu full-save là nút thắt, RAM ca lớn -25%; nhóm khác không chậm >10% khi không có xử lý bắt buộc mới. Ghi đạt/chưa đạt theo từng mục, không gọi tất cả đã tối ưu chỉ vì một nhóm nhanh hơn.
- [ ] Bỏ các tối ưu phức tạp không cải thiện >=5% công đoạn mục tiêu hoặc làm tăng rủi ro. Chốt số worker/cache/shard theo bằng chứng; ghi `shortcut: <giới hạn>, <khi nâng cấp>` nếu giữ giới hạn đã biết trong code.
- [ ] Cập nhật hướng dẫn với cấu hình thật, cách xử lý OCR lỗi/cache invalid và quy trình xóa dữ liệu tạm nội bộ sau nghiệm thu. Không có tác vụ tự xóa dữ liệu bệnh án chưa được người dùng yêu cầu.

## Điểm chưa đo và cách quyết định

Chưa có profiler/RAM/IO của corpus lớn hoặc máy đích bệnh viện; những điểm nghi ngờ và mục tiêu phần trăm trên là đề xuất, không phải kết luận hệ thống hiện đang chậm ở đâu. Quyết định giữ cache worker/shard dựa trên P00/P07; ưu tiên loại công việc lặp, sau đó mới tăng song song. Không cần mua phần cứng hoặc cài OCR mới trong kế hoạch hiện tại.
