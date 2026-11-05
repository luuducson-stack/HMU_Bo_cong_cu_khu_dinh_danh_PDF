# Sửa 15 vấn đề khử định danh PDF — Implementation Plan

> Cập nhật triển khai 28/10/2026: source đã sửa và kiểm chứng; trạng thái nghiệm thu, giới hạn và mục tiêu hiệu năng chưa đạt xem [báo cáo thực tế](../../../../BAO_CAO_TRIEN_KHAI_2026-10-28.md). Các bước chi tiết bên dưới được giữ làm kế hoạch gốc để đối chiếu, không thay thế log kiểm thử.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Chỉ dùng subagent triển khai nếu người dùng chọn cách đó; lượt hiện tại chỉ tạo tài liệu.

**Goal:** Khắc phục đủ 9 vấn đề ưu tiên và 6 vấn đề tiếp theo của báo cáo review, có kiểm thử hồi quy và nghiệm thu rõ ràng cho từng việc.

**Architecture:** Sửa trong `app.py`, `engine.py`, `ocr_helper.py`, `hmu_recognizers.py` và UI hiện có; không viết lại hệ thống. Danh tính job/revision bảo vệ vòng duyệt, analysis nội bộ làm nguồn tọa độ chung cho kiểm tra vùng xóa và audit; xuất vẫn dựng PDF ảnh mới.

**Tech Stack:** Python >=3.10, PyMuPDF 1.26.6, pypdf 6.10.0, Windows.Media.Ocr/PowerShell, vanilla JavaScript, unittest và stdlib.

**Spec:** [Thiết kế sửa lỗi và hiệu năng](../specs/2026-10-28-remediation-performance-design.md).

## Global Constraints

- Chỉ lập kế hoạch trong lượt này; tất cả ô sửa lỗi bên dưới bắt đầu chưa hoàn tất.
- Xử lý offline; không gửi bệnh án tới cloud; fixture được tạo từ dữ liệu giả.
- Giữ Python >=3.10, PyMuPDF 1.26.6, pypdf 6.10.0; không thêm framework/dependency.
- Giữ DPI OCR 200, xuất 200 mặc định và PNG không mất dữ liệu.
- Không sửa/xóa bệnh án nguồn; giữ token và bind loopback.
- study ID `[A-Za-z0-9_-]{1,64}`; tên batch theo `<study_id>_F001_REDACTED.pdf` hoặc `_DRAFT.pdf`.
- Mọi sửa đổi có nhánh logic phải có test thất bại trước sửa và đạt sau sửa; không hạ chất lượng test để làm xanh.
- Hỗ trợ mở job cũ theo cơ chế migration trong spec; không tự ghi nhận đã duyệt khi dữ liệu nhận diện thay đổi.
- Dùng một tác vụ nặng/server, không chia sẻ `fitz.Document` giữa các thread.

## Review Focus

1. Hai tab dùng hai ca cùng số trang/proposal, request cũ đến sau khi chuyển ca: F09 phải trả 409, không thay đổi job đích.
2. Trang xoay/cropbox, vừa có text vừa có scan, OCR/native không đồng ý: F05/F10 phải giữ đúng hình học và không bỏ mất PII.
3. Xuất batch lỗi ở file giữa, tên nguồn Unicode/trùng sau chuẩn hóa và mã nghiên cứu 64 ký tự: F06/F07 phải không mất output hợp lệ trước đó hoặc báo thành công thiếu file.
4. Thay đổi lựa chọn trong khi export và đọc progress từ hai tab: F09/F11 phải dùng một snapshot, kết quả không bị một tab lấy mất.
5. Job cũ thiếu analysis, OCR không có engine/ngôn ngữ hoặc nhận diện rỗng: F05/F11/F13 phải báo rõ trạng thái, không chuyển âm thầm sang đã duyệt.

## Checklist tổng và thứ tự triển khai

ID F01–F15 trùng số phát hiện trong báo cáo để đối chiếu. Phụ thuộc có thể khiến phần nền kiểm thử của F13 và bảo vệ hình học F10 được làm trước vài mục P1; không có nghĩa hạ ưu tiên các P1 đó.

| ID | Mức | Checklist kết quả | Phụ thuộc |
|---|---|---|---|
| F01 | P1 | [x] Batch không tự xuất/duyệt; UI duyệt được mọi PDF | F09, F06–F07, F13a |
| F02 | P1 | [x] Watermark đúng mẫu; chữ/đồ họa chuyên môn xoay còn nguyên | F13a |
| F03 | P1 | [x] Hộp mực dừng ở khoảng trắng và ranh giới trường | F13a; nghiệm thu với F10 |
| F04 | P1 | [x] Ảnh chuyên môn nhỏ không tự bị xóa theo vị trí | F13a |
| F05 | P1 | [x] OCR trang mixed, giữ text native và tọa độ đúng | F02–F04 |
| F06 | P1 | [x] Tên PDF/QC bàn giao không dùng tên nguồn | F13a |
| F07 | P1 | [x] Đường dẫn xuất duy nhất, lỗi batch không làm mất bản hợp lệ | F06 |
| F08 | P1 | [x] Upload chỉ ghi vào tên cố định trong job | F13a |
| F09 | P1 | [x] Job/revision/task chống lưu nhầm ca và xuất sai snapshot | F13a |
| F10 | P2 | [x] Kiểm giao vùng xóa cuối cùng và mã chuyên môn | F03, F05 |
| F11 | P2 | [x] Audit phản ánh đúng snapshot duyệt/xuất hiện tại | F05, F09–F10, F12 |
| F12 | P2 | [x] Hợp span che kín mọi đoạn giao nhau | F13a |
| F13 | P2 | [x] Không test xanh giả; đủ HTTP/pixel/hồi quy cho 15 vấn đề | Nền F13a đầu tiên; nghiệm thu F13b cuối |
| F14 | P2 | [x] Launcher không kill chương trình dùng cổng 8765 | Độc lập |
| F15 | P2 | [x] Chính sách, hướng dẫn và bằng chứng v1/v2 thống nhất | F01–F14 |

**Trình tự đề xuất:** P00 của kế hoạch hiệu năng → F13a → F08 → F09 → F06 → F07 → F01 → F02 → F03 → F04 → F05 → F10 → F12 → F11 → F14 → F15 → F13b → baseline B1 và các tối ưu hiệu năng.

**Quy trình chung mỗi task:** Viết đúng test được chỉ định → chạy để thấy thất bại vì lỗi mục tiêu → sửa nhỏ nhất → chạy lại test mục tiêu và nhóm bị ảnh hưởng → kiểm diff → commit riêng khi bước triển khai có quyền ghi Git. Không gom refactor ngoài phạm vi. Chạy toàn bộ suite tại các mốc nhóm để tránh lặp OCR/full suite sau từng chỉnh sửa nhỏ.

## Bản đồ tệp

| Tệp | Thay đổi dự kiến |
|---|---|
| `HMU_KhuDinhDanh/app.py` | Testable server factory; ID/revision/khóa/task; upload cố định; chọn file và export cả ca. |
| `HMU_KhuDinhDanh/engine.py` | Vùng xóa, snapshot analysis/audit, validate, tên output và batch. Giữ hàm public trừ thay đổi mặc định đã ghi. |
| `HMU_KhuDinhDanh/ocr_helper.py` | Kết quả OCR/mapping cho mixed; lỗi/giới hạn OCR; tối ưu ở kế hoạch riêng. |
| `HMU_KhuDinhDanh/hmu_recognizers.py` | Chỉ sửa nếu cần dùng lại chuẩn hóa và protected hits cho map mới; không thêm rule riêng cho từng bệnh nhân. |
| `HMU_KhuDinhDanh/review.html` | Danh sách file; gửi ID/revision/task; giữ revision sau lưu; khóa thao tác xung đột và báo 409. |
| `HMU_KhuDinhDanh/test_workflow.py` | Test PDF tổng hợp và pixel hồi quy; giữ 14 test gốc có giá trị. |
| `HMU_KhuDinhDanh/test_app.py` (mới) | HTTP localhost với cổng tự cấp, tiến trình server do fixture sở hữu. |
| `HMU_KhuDinhDanh/test_hmu_recognizers.py` | Bỏ nhánh no-op, fixture portable hoặc skip có lý do. |
| `HMU_KhuDinhDanh/MO_CONG_CU.bat` | Bỏ taskkill; thông báo cổng bận. |
| Hướng dẫn, kết quả mẫu, báo cáo mới | Cập nhật chính sách và kết quả thực; giữ QC cũ là bằng chứng lịch sử. |

Các lệnh dưới chạy trong `HMU_KhuDinhDanh` bằng `\.venv\Scripts\python.exe` với dấu `.` đầu đường dẫn như ví dụ. Nếu sandbox chặn đổi tên tệp tạm, chạy lại nguyên test với quyền phù hợp; không sửa hàm lưu chỉ để tránh sandbox.

## F13a — Nền kiểm thử dùng ngay từ task đầu

**Files:** `app.py`, `test_app.py` (mới), `test_workflow.py`, `test_hmu_recognizers.py`.
**Interfaces:** Tách phần dựng HTTP ra `create_server(root: Path, active: Path | None, port: int = 0) -> ThreadingHTTPServer`; `main()` vẫn xử lý CLI/mở browser rồi gọi factory. Cổng 0 được dùng trong test; kiểm Host theo `server.server_port` thực tế. Không đổi cơ chế bảo mật vì factory.

- [ ] Viết `test_server_factory_uses_bound_port`: GET `/state` bằng Host của cổng được cấp phải 200; Host sai/token sai phải 403 ở endpoint tương ứng; server shutdown và thread join sau test.
- [ ] Chạy `.\.venv\Scripts\python.exe -m unittest test_app -v`; xác nhận đỏ vì chưa có factory, rồi tách tối thiểu từ `main()` và chạy xanh.
- [ ] Đổi hai test dữ liệu thực thành fixture nhỏ có assert hoặc `skipTest` có lý do khi thiếu dữ liệu; test chuỗi dựng tay không phụ thuộc tệp ổ D.
- [ ] Chạy `.\.venv\Scripts\python.exe -m unittest discover -p 'test_*.py' -v`; lưu số đạt/skipped đúng. Chuẩn tham chiếu hiện có: 14 workflow đạt, không coi hai test no-op là bằng chứng dữ liệu thật.

## F08 — Chặn tên upload thoát thư mục

**Files:** `app.py` nhánh `/upload`; `test_app.py`.
**Interfaces:** Header `X-Original-Filename` chỉ làm nhãn/basename nội bộ; byte upload luôn lưu `folder / 'source_private.pdf'`. Seed lookup không được dùng header như đường dẫn để ghi.

- [ ] Viết `test_upload_filename_cannot_escape_job`: gửi tên `../outside.pdf`, đường dẫn Windows tuyệt đối, UNC và URL-encoded traversal; assert không tạo/đổi sentinel ngoài folder, chỉ có `source_private.pdf` trong job. Dùng toàn bộ tệp sentinel trong temp fixture được phép ghi.
- [ ] Chạy `.\.venv\Scripts\python.exe -m unittest test_app.AppTests.test_upload_filename_cannot_escape_job -v` để thấy đỏ; sửa tên lưu cố định.
- [ ] Chạy test lại; test PDF hỏng phải trả lỗi và không làm hỏng file bên ngoài; nhãn tên Unicode không gây lỗi nhận PDF hợp lệ.

## F09 — Danh tính job, revision, khóa và snapshot

**Files:** `app.py`, `engine.py:prepare/approve_all_pages`, `review.html`, `test_app.py`.
**Interfaces:** Review có `schema_version=2`, `job_id: str`, `revision: int`. POST save/approve/export/select phải kiểm job/revision; thành công trả revision mới; stale/mismatch/busy trả 409 JSON có mã lỗi. Tác vụ async trả `task_id`; progress nhận task ID và đọc nhiều lần cùng kết quả đến tác vụ tiếp theo.

- [ ] Viết `test_stale_tab_cannot_save_other_job` và `test_revision_conflict_preserves_latest_save`: hai ca cùng cấu trúc; request cũ phải 409 và hash review ca B không đổi; hai save cùng revision chỉ một được chấp nhận.
- [ ] Viết `test_export_captures_job_and_blocks_conflicting_edits`, `test_progress_result_is_not_consumed_by_other_tab`, `test_page_and_download_reject_wrong_job`: xuất đang chạy vẫn thuộc job chụp lúc đầu; edit/open xung đột 409; hai poll thấy cùng kết quả.
- [ ] Chạy từng test mới trong `test_app`; sửa bằng một khóa đọc–kiểm–ghi, đường dẫn tác vụ bất biến và metadata job. Không dùng thư viện phân tán hoặc giữ lock suốt OCR.
- [ ] UI chờ save hoàn tất, cập nhật revision trả về, hủy timer save cũ khi chuyển ca; mọi endpoint ảnh/tải gửi job ID. Xử lý 409 hiển thị yêu cầu nạp lại thay vì retry mù ghi đè.
- [ ] Chạy `test_app` và `test_workflow`; thử hai tab trên fixture giả, lưu/đổi ca/xuất theo đúng trường hợp trên.

## F06 — Tên sản phẩm không lấy từ PII

**Files:** `engine.py:prepare_case/export_case`, `test_workflow.py`.
**Interfaces:** Manifest index quyết định tên `<study_id>_F{index:03d}_{REDACTED|DRAFT}.pdf`; `source_name` chỉ ở manifest nội bộ. `output` trong QC đúng basename an toàn; không tạo study ID phụ vượt giới hạn 64 ký tự.

- [ ] Viết `test_batch_output_names_use_only_study_id_and_index`: nguồn tên có dấu, không dấu, dấu `_`, tên không nhận diện được; `assert set(out.name) == expected_names`, và QC không chứa tên gốc. Thêm `test_batch_accepts_64_character_study_id`.
- [ ] Chạy test đỏ; bỏ vòng thay tên bệnh nhân bằng regex, tạo tên theo manifest/index; giữ mapping riêng.
- [ ] Chạy xanh; kiểm bản thử có `_DRAFT`, bản chính thức có `_REDACTED`, số lượng/trật tự file không thay đổi.

## F07 — Không trùng tên hoặc công bố output dở

**Files:** `engine.py:export/export_case`, `test_workflow.py`.
**Interfaces:** `export` giữ giá trị trả `(Path, qc)`; `export_case` trả count theo sản phẩm đã kiểm tồn tại/hash/đường dẫn duy nhất. Tách phần render/ghi/verify hiện có thành `_write_export_pair(job: Path, snapshot: dict, destination: Path, draft: bool, progress_cb=None) -> tuple[Path, dict]` để file và batch dùng cùng logic. Preflight toàn ca; tạo `export_id` ngẫu nhiên, ghi staging cùng filesystem, verify đủ PDF+QC rồi đổi tên sang `exports/<export_id>/`. Chỉ công bố bằng `last_export.json` nguyên tử chứa export_id, job_id/revision và danh sách basename/hash. `/download` chỉ resolve file thuộc generation đã công bố; thay `last_output.txt` bằng pointer này, không tin đường dẫn từ client. Batch lỗi không báo thành công cả ca.

- [ ] Viết `test_batch_outputs_are_unique_and_complete`, `test_failed_reexport_keeps_previous_valid_output`: hai tên nguồn từng cùng thành REDACTED phải có hai PDF/QC; mô phỏng lỗi render/verify tại file 2 bằng `unittest.mock` và assert sản phẩm hợp lệ cũ không đổi. Thêm `test_qc_write_or_pointer_failure_keeps_previous_generation`: lỗi ngay sau ghi PDF/trước QC, sau QC/trước rename và trước replace pointer đều không đổi last_export hoặc cặp sản phẩm cũ.
- [ ] Chạy test đỏ; kiểm toàn bộ đường dẫn đích một lần, ghi staging riêng, dọn staging do tác vụ sở hữu khi lỗi; không xóa generation cũ. Generation đã verify nhưng pointer chưa cập nhật là bản chưa công bố, không được download tự suy là bản mới nhất theo thời gian tệp.
- [ ] Chạy xanh; `assert len(set(outputs)) == expected_count`; từng QC hash đúng PDF và file lỗi không có nhãn thành công. Kiểm disk-full/lỗi quyền qua lỗi IO giả lập, không làm đầy ổ thật.

## F01 — Duyệt cả ca trước khi xuất

**Files:** `app.py:/open_path`, `engine.py:export_case/CLI`, `review.html`, `test_app.py`, `test_workflow.py`.
**Interfaces:** `export_case(..., approve_all=False)` mặc định. `/state` thêm danh sách file của manifest; `POST /select_file` nhận `{job_id, revision, file_index}` và chỉ chọn sub-job thuộc case hiện tại; `/export` nhận `scope: 'file' | 'case'`, mặc định file. Không nhận đường dẫn sub-job tùy ý từ client.

- [ ] Viết `test_open_case_does_not_export_or_approve`, `test_batch_export_requires_every_file_reviewed`, `test_select_file_preserves_review`: mở 2 file không tạo sản phẩm, tất cả reviewed false; chỉ duyệt file 1 vẫn bị chặn xuất cả ca; chọn file 2 rồi quay lại giữ dữ liệu đã lưu.
- [ ] Chạy đỏ; bỏ `export_case(...approve_all=True)` trong open và CLI export-case; thêm file picker nhỏ, số trang đã duyệt và nút xuất cả ca. Kiểm `file_index` ngoài manifest bị từ chối.
- [ ] Chạy xanh; thao tác duyệt tất cả chỉ ghi nhận khi người dùng chủ động bấm; draft không đổi reviewed; export chính thức của ca hợp lệ tạo đủ N PDF và N QC.

## F02 — Watermark không làm mất chữ chuyên môn

**Files:** `engine.py:remove_isolated_watermarks/rotated_watermark_rects/prepare`, `test_workflow.py`.
**Interfaces:** Giữ `remove_isolated_watermarks(doc) -> list` nhưng no-op trả `[]`; chỉ `WATERMARK_RE`/watermark đã xác nhận thành proposal. Proposal watermark có `method='isolated_watermark_stream'`, `stream_xrefs` và `text_spans` khi chứng minh được stream thuần watermark, còn `rects` chỉ để hiển thị. `text_spans` là các khoảng offset trong analysis của chính watermark, không của chữ chuyên môn nằm dưới. `apply_review_to_page` xóa stream đã chọn bằng thao tác đối tượng; không đưa bbox chéo vào danh sách phủ trắng chung. Không chứng minh được stream thuần hoặc tách toán tử chính xác thì báo `UNSAFE_WATERMARK_REMOVAL`, yêu cầu xử lý/duyệt lại; không fallback phủ trắng cả hộp.

- [ ] Viết `test_rotated_clinical_text_and_shared_graphics_survive_prepare`, `test_watermark_can_be_deselected`, `test_selected_repeated_watermarks_are_removed_from_pixels`: watermark chéo thực sự đi qua chữ/đồ thị chuyên môn, không chỉ ở vùng trắng. Thêm `test_shared_stream_watermark_refuses_unsafe_rectangle_fallback`: stream chung chưa tách được phải báo lỗi an toàn, không xóa dữ liệu nằm dưới.
- [ ] Chạy đỏ; dừng bóc stream trước duyệt, siết detector watermark; giữ nguyên chữ xoay không khớp mẫu. Không dùng “xoay + dài >=6” làm điều kiện xóa.
- [ ] Chạy xanh; preview giữ nguyên nguồn; so bản xuất với fixture đối chứng tạo cùng nội dung nhưng không vẽ watermark: chữ/đồ thị dưới watermark vẫn nguyên, watermark không còn mực. Kiểm text/geometry/style/ảnh/drawings của nội dung khác không đổi sau xóa đối tượng; không kiểm “cả bbox phải trắng”. Cập nhật test cũ chỉ nếu assertion phụ thuộc hành vi bóc sớm.

## F03 — Hộp xóa dừng đúng trường

**Files:** `engine.py:expand_rects_with_pixel_ink/prepare`, `test_workflow.py`.
**Interfaces:** Giữ signature hiện có; truyền `max_x1` theo ranh giới trường khi biết. Ngưỡng khoảng trắng 14 điểm phải áp dụng ngay từ đầu, giữ `max_expand_pt` theo caller hiện tại.

- [ ] Viết `test_ink_expansion_stops_at_initial_white_gap` và `test_ink_expansion_does_not_cross_age_or_clinical_column`: mực cột kế cách 30 điểm không làm tăng hộp; đuôi tên thật sát hộp vẫn được bao trùm.
- [ ] Chạy đỏ; sửa điều kiện dừng trước khi có mực đầu tiên, không thay ngưỡng nhận diện tùy tiện.
- [ ] Chạy xanh cùng `test_ink_expansion_and_proposal_subsumption`; thêm fixture đường kẻ bảng để không quét xuyên cột. F10 kiểm lại hình học cuối khi tích hợp.

## F04 — Không xóa ảnh chuyên môn vì nằm cuối trang

**Files:** `engine.py:build_image_and_signature_proposals`, `test_workflow.py`.
**Interfaces:** Ảnh chỉ có bằng chứng vị trí trả `IMAGE_REVIEW, selected=False`; ảnh có signature anchor đủ rõ mới `SIGNATURE_IMAGE, selected=True`.

- [ ] Viết `test_small_bottom_clinical_image_is_not_auto_selected`: ảnh 200×100 điểm ở y=500 trên trang cao 800, không anchor, phải chưa chọn. Fixture thứ hai có anchor thật và logo/ảnh lớn để giữ hành vi cần thiết.
- [ ] Chạy đỏ; bỏ nhánh `near_sig or in_bottom_sig_band` tự chọn chỉ từ vị trí; giữ ảnh mơ hồ là vùng cần duyệt.
- [ ] Chạy xanh và kiểm pixel bản xuất: ảnh chuyên môn còn nguyên, chữ ký đã chọn bị xóa, không làm mất text nằm dưới ảnh trong fixture hiện có.

## F05 — PDF hỗn hợp, hình học OCR và analysis nội bộ

**Files:** `engine.py:prepare/char_map`, `ocr_helper.py`, `test_workflow.py`.
**Interfaces:** Bổ sung helper trong `engine.py`: `combine_page_maps(native_map: tuple, ocr_map: tuple) -> tuple[str, list]`; định dạng `(offset,line,bbox,char)` không đổi. Ghi `analysis_private/<pn>.json` gồm `text`, `chars`, `protected_rects`, `source_fingerprint`; review chỉ giữ tham chiếu và hash để không gửi char map lớn qua HTTP.

- [ ] Viết `test_mixed_page_detects_pii_inside_scan_and_keeps_native_text`, `test_native_ocr_duplicates_do_not_erase_other_text`, `test_rotated_cropped_page_coordinates`: header native + ảnh có tên/CCCD; OCR/native trùng chỉ gộp khi cả text và vị trí trùng, bất đồng vẫn giữ. Kiểm tọa độ và pixel ở 0/90/180/270 độ.
- [ ] Chạy đỏ; quyết định OCR dựa trên vùng ảnh/nội dung chưa có text, không chỉ toàn trang rỗng. OCR full-page cho mixed khi cần; ghép map và dịch offset rõ ràng. Ảnh vượt giới hạn WinRT phải chia tile giữ 200 dpi, overlap ban đầu 64 pixel, dịch tọa độ tile về trang và gộp bản trùng. Thêm `test_ocr_tiles_preserve_pii_across_seams`; nếu 64 pixel không đủ theo fixture, tăng overlap theo chiều cao chữ đo được, không co ảnh/làm mất chi tiết.
- [ ] Dựng `protected_rects` từ `protected_hits(text)` và char map; lưu analysis riêng có PII. Hash working/native vẫn được kiểm độc lập với OCR.
- [ ] Viết/chạy `test_ocr_unavailable_or_empty_requires_review`: lỗi OCR có thông báo; kết quả rỗng trên trang có mực vẫn NEEDS_VISUAL_REVIEW, không auto-approve. Chạy cả OCR Windows thật, không chỉ mock.
- [ ] Chạy toàn bộ workflow; số trang, kích thước, native text còn đủ, PII trong ảnh được đề xuất và che đúng pixel; đo thêm chi phí OCR mixed ở B1.

## F10 — Kiểm giao hình học trước xuất

**Files:** `engine.py:validate_review/apply_review_to_page/export`, `test_workflow.py`.
**Interfaces:** `validate_review(data, doc)` tiếp tục kiểm cấu trúc; bổ sung `validate_redaction_regions(rects: list, protected_rects: list, pn: int) -> None` ở `engine.py`, gọi sau khi chốt cả fallback ảnh và manual. Giao vùng ICD dương tính phải `ValueError` có trang/vùng, không có bypass ngầm. Chỉ kiểm geometry các vùng thật sự phủ trắng/xóa pixel; bbox hiển thị của watermark xóa bằng đối tượng F02 không thành mask, và phải vượt kiểm bảo toàn nội dung riêng của F02.

- [ ] Viết `test_manual_and_expanded_rects_over_icd_are_rejected`: vùng manual, mở rộng mực và fallback ảnh giao ICD đều bị chặn, không chỉ dựa vào `clinical_overlap` ban đầu. Test không giao phải xuất được.
- [ ] Chạy đỏ; dùng geometry từ analysis F05, kiểm cả vùng native/OCR; QC ghi kết quả kiểm thật của snapshot đã xuất.
- [ ] Chạy xanh; pixel tuổi/giới và các dòng kết quả mẫu ngoài mask không đổi ngoài sai số raster đã định; test annotation/ảnh trong 14 test cũ vẫn đạt.

## F12 — Gộp hợp span, không hở đuôi

**Files:** `engine.py:_build_redacted_markdown`, `test_workflow.py`.
**Interfaces:** Giữ `_build_redacted_markdown(text: str, findings: list) -> str`; các khoảng giao được hợp bằng `max(end)`, quy tắc nhãn chọn ổn định theo sort hiện tại.

- [ ] Viết `test_markdown_masks_union_of_overlapping_spans`: `[0,5)` + `[3,10)` trên `ABCDEFGHIJK` không còn `FGHIJ`, chỉ `K` nằm ngoài vùng che. Thêm nested, trùng hệt, kề nhau, Unicode và danh sách rỗng.
- [ ] Chạy đỏ; sửa hợp khoảng bằng stdlib, không thêm parser/dependency.
- [ ] Chạy xanh; mỗi offset ngoài hợp span được giữ, mọi offset trong hợp span bị che.

## F11 — Audit cùng snapshot với PDF

**Files:** `engine.py:generate_audit_markdown/export/export_case`, `app.py:/save,/audit`, `test_workflow.py`, `test_app.py`.
**Interfaces:** Bổ sung `build_review_markdown(text: str, chars: list, review: dict) -> str` dùng vùng phủ trắng cuối cùng để suy offset cần che, còn watermark xóa bằng đối tượng dùng `text_spans` F02, không che text chuyên môn nằm trong bbox hiển thị; gọi bộ hợp span F12. `generate_audit_markdown(job_dir, data)` giữ signature và nạp analysis riêng; audit có job_id/revision/draft/source fingerprint.

- [ ] Viết `test_audit_tracks_deselect_manual_and_expanded_regions`: bỏ chọn tên làm tên xuất hiện lại trong phần nội dung; khoanh tay/đổi vùng che cập nhật tương ứng. Bảng PII luôn được ghi nhãn nội bộ.
- [ ] Viết `test_case_audit_matches_export_snapshot` và `test_legacy_job_analysis_is_migrated_safely`: summary cả ca cập nhật từ đúng sub-job/revision; job cũ được bổ sung analysis, không tự duyệt nếu tọa độ thay đổi. Thêm `test_legacy_removed_stream_requires_matching_source`: job có watermarks_removed phải tạo lại từ nguồn đúng SHA-256; thiếu/sai nguồn phải `SOURCE_RECHECK_REQUIRED`, không xuất chính thức, không ghi đè job cũ.
- [ ] Chạy đỏ; dựng audit theo snapshot, không dùng `redacted_markdown` ban đầu làm nguồn sự thật; vùng ảnh không có text ghi rõ cần kiểm pixel.
- [ ] Chạy xanh; tên nguồn/analysis/audit không bị đưa vào gói bàn giao; export và audit cùng revision. `/audit` kiểm revision, tạo lại nếu bẩn thay vì trả bản cũ.

## F14 — Mở công cụ không dừng chương trình khác

**Files:** `MO_CONG_CU.bat`, `app.py:main`, hướng dẫn.
**Interfaces:** Giữ `--port`; không `taskkill`. Bind thất bại báo cổng bận và cách dùng cổng khác bằng thông báo dễ hiểu.

- [ ] Bỏ vòng `netstat → taskkill /F /T`; giữ kiểm `.venv` và chạy app.
- [ ] Kiểm thủ công bằng một listener giả trên 8765 do phiên kiểm thử sở hữu: chạy launcher, listener vẫn sống, thông báo cổng bận, không treo vô hạn. Dừng đúng listener của fixture sau kiểm tra.
- [ ] Kiểm launcher khi cổng trống mở được app; không cần thêm framework/test BAT chỉ để kiểm một thay đổi xóa lệnh.

## F15 — Chính sách và tài liệu vận hành thống nhất

**Files:** `HUONG_DAN_SU_DUNG.md`, `KET_QUA_BENH_AN_MAU.md`, báo cáo QC/nghiệm thu mới; giữ `HMU_CASE_0001_QC.json` là lịch sử v1.
**Interfaces:** Chính sách v2 theo spec: xóa tên/địa chỉ đầy đủ kể cả tỉnh thành/DOB/SĐT/CCCD/BHYT/chữ ký đã chọn; giữ tuổi/giới/mã hồ sơ/bệnh nhân và barcode theo lựa chọn duyệt. Audit/manifest là dữ liệu nội bộ có PII.

- [ ] Đối chiếu từng mục chính sách với recognizer, default selection, QC và UI; ghi rõ mã liên kết được giữ có chủ ý và không đồng nghĩa mất mọi khả năng liên kết danh tính.
- [ ] Cập nhật thao tác batch duyệt rồi xuất, xử lý 409/cổng bận/job cũ; chỉ PDF+QC hợp lệ được bàn giao, không gửi toàn thư mục.
- [ ] Không đổi version/hash/trạng thái của bằng chứng mẫu v1; tạo báo cáo nghiệm thu mới với code revision và môi trường thực chạy. Không dùng cụm “đã chứng minh 99%” khi chưa có tập nhãn đo tương ứng.
- [ ] Kiểm thủ công một lượt theo đúng hướng dẫn trên ca giả hai PDF: mở, chuyển, lưu, duyệt, xuất draft/chính thức, tải và xác minh tệp.

## F13b — Nghiệm thu cuối cho toàn bộ 15 vấn đề

- [ ] Chạy `.\.venv\Scripts\python.exe -m unittest discover -p 'test_*.py' -v`; ghi đúng tổng test, PASS/FAIL/ERROR/SKIP và lý do skip. 14 workflow gốc và OCR thực không bị bỏ qua.
- [ ] Chạy HTTP fixture đầu cuối: upload → state → page → save → switch → approve → export → progress → download; token/Host sai, stale revision, hai tab và batch chưa đủ duyệt đều bị từ chối đúng.
- [ ] Kiểm pixel trong/ngoài vùng xóa và lớp dữ liệu ẩn; hash nguồn không đổi; tên/QC không PII; output count/uniqueness/hash đúng manifest.
- [ ] Xem ảnh phóng lớn các fixture rủi ro (xoay, watermark, chữ nhỏ sát cột, ảnh nhỏ cuối trang, mixed); không chỉ nhìn checkbox proposal.
- [ ] Chạy mẫu bệnh viện thật chỉ khi có corpus được phép truy cập; nếu thiếu, báo rõ chưa nghiệm thu thực tế thay vì đánh dấu xong phần đó.
- [ ] Cập nhật checklist F01–F15 chỉ sau đủ bằng chứng; ghi liên kết test/log/code revision vào báo cáo hoàn tất.

## Điểm bàn giao

Mỗi task để lại: diff nhỏ, test hồi quy có ý nghĩa, lệnh và kết quả kiểm chứng, hạn chế còn lại. Không triển khai tối ưu P01–P07 nếu nó đổi lại hành vi an toàn vừa khóa bằng test. Kế hoạch hiệu năng có cổng kiểm riêng, dùng baseline sau sửa độ đúng.
