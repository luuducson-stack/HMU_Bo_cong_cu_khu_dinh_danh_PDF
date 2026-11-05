# Thiết kế khử chính xác và xử lý 2.000 hồ sơ

## Cập nhật theo yêu cầu triển khai mới nhất

Ưu tiên **nhiều hồ sơ đồng thời**, mặc định yêu cầu hai job với giới hạn tài nguyên và hiệu chuẩn thực; không dùng thời gian treo qua đêm làm căn cứ duy nhất để kết luận đủ công suất. Máy chạy không cần người canh. Mỗi job tự nhận file → phân tích → xuất DRAFT → kiểm PDF → vào hàng chờ duyệt; hoàn tất file nào thì bản xuất riêng của file đó truy cập được ngay, không đợi cả lô và không chờ người duyệt mới chạy file sau. Hàng chờ duyệt lưu bền vững, tách khỏi worker slots. Có cảnh báo QA thì vẫn cho mở DRAFT để sửa, không gắn READY/phát hành chính thức. Duyệt một hồ sơ không khóa xử lý các hồ sơ khác.

Checklist bổ sung bắt buộc: hai job đang chạy; một job xong trước được tải/mở ngay; job chưa duyệt không chặn job thứ ba; đóng UI không dừng queue; restart giữ cả queue máy và queue duyệt; edit/re-export một job không làm sai QC/tiến độ job khác. Năng suất báo theo cấu hình 1 và 2 jobs, có verifier hậu xuất; mốc 30 file/giờ là mục tiêu nếu chỉ tính 6 giờ máy/ngày, không coi đạt khi chưa đo. Các lịch 12–16 giờ bên dưới là phương án năng lực bổ sung, không giả định thời gian máy đã được bảo đảm.


Ngày: 30/10/2026. Trạng thái: đề xuất để triển khai; chưa phải kết quả nghiệm thu.

## Nhu cầu và quyết định làm cơ sở

Người dùng cần xử lý khoảng 2.000 PDF, mỗi file 45–99 trang, trong hai tuần; dành 6 giờ/ngày để làm việc và đã xác nhận máy có thể chạy buổi tối/qua đêm. Cần giảm bỏ sót tên, thông tin của bệnh nhân và nhân viên y tế, giữ nội dung chuyên môn. Mẫu mới được cung cấp là A050, **50 trang**, khác mẫu 71 trang đã đo. Không đưa tên bệnh nhân hoặc đường dẫn mang tên bệnh nhân vào báo cáo công khai.

Đề xuất của người lập kế hoạch: hàng đợi chạy tại máy, trước hết một hồ sơ/lần, tự chuyển hồ sơ; hiệu chuẩn hai hồ sơ/lần để lựa chọn theo năng suất thực. Máy chạy 12–16 giờ/ngày; người duyệt làm ban ngày. Không giả định người dùng đã chấp thuận thay đổi quy tắc giữ/xóa trường dữ liệu hoặc phát hành tự động.

## Bằng chứng hiện tại và giới hạn

- `HMU_JOBS/speed_implementation_20261029/safe_acceptance_20.json`: đủ 20/20 lượt đạt trần 170,4 giây, cùng mã nguồn; trung vị 134,968 giây, chậm nhất 154,655 giây/71 trang; peak RAM cây tiến trình lấy mẫu 847,82 MiB.
- Benchmark chép các lựa chọn từ reference vào job mới ngoài khoảng đo. Nó đo đầy đủ công việc máy của bộ vùng đã chọn, **không đo tỷ lệ nhận diện tự động đầy đủ**. Bộ kiểm PDF cuối của chuỗi 20 vẫn chưa có đủ các artifact nghiệm thu; việc người dùng báo còn sót mở lại mục chất lượng.
- Mẫu A050 có SHA256 `1a315bdb645227a2165614771d5fd5f80de391422b5aac4a24fa9d35a2fc3d7f`; mẫu B071 có SHA256 `bdc0133c91b8d40367c28c54b620c4ffa0dd3477ccfe29b3036d3af72b34cf4f`. A050 chưa được benchmark hoặc kiểm khử trong lượt lập kế hoạch này.
- `app.py:create_server` chỉ có một active job/progress và khóa tác vụ. `engine.py:prepare_case/export_case` xử lý tuần tự, dùng chung seeds cho **cùng ca bệnh**. Đây không phải hàng đợi các bệnh nhân độc lập.
- Một job lớn hiện đã dùng 2 process render, 4 OCR worker ở hai pha; mở nhiều job không bảo đảm tăng tốc tuyến tính.
- `CONTEXT_REQUIRED`, lỗi hình học, vùng xung đột có thể có đề xuất nhưng không tự chọn. Đây là lớp cần phân loại khi điều tra bỏ sót; chưa kết luận là nguyên nhân cụ thể trên A050.
- `PATIENT_ID`, `MEDICAL_RECORD_ID`, tuổi, giới tính và dữ liệu chuyên môn có quy tắc bảo toàn hiện hành. Phải lập bảng chính sách rõ ràng trước khi thay đổi; không coi tất cả những trường được giữ có chủ đích là lỗi nhận diện.
- Máy hiện báo 8 logical CPU, RAM khả dụng toàn phần 11,77 GiB, còn trống khoảng 3,11 GiB tại lúc kiểm. Ổ E còn 44,69 GiB. PDF mẫu xuất lớn nhất 28,44 MiB; 2.000 file cùng kích thước khoảng 55,55 GiB chỉ đầu ra. Một thư mục run mẫu gồm dữ liệu làm việc khoảng 92,26 MiB; ngoại suy gần 180 GiB cho 2.000 run là cảnh báo dung lượng, không phải dự báo corpus thực.

## Trả lời bài toán công suất

Giả định hai tuần là 14 ngày hoạt động. Các chỉ tiêu dưới đây tính cả OCR, khử, audit và kiểm tra PDF đầu ra mới; không lấy tốc độ cũ làm tốc độ đã đạt của luồng mới.

| Giờ máy/ngày | Tổng giờ máy | Tối thiểu để đủ 2.000 file | Mục tiêu có dự phòng khoảng 20% |
|---|---:|---:|---:|
| 6 | 84 | 23,81 file/giờ | 30 file/giờ |
| 12, đề xuất chính | 168 | 11,90 file/giờ | 15 file/giờ |
| 16, khi cần | 224 | 8,93 file/giờ | 12 file/giờ |

Ở 15 file/giờ, công việc máy tốn 133,33 giờ, còn 34,67 giờ trong lịch 12 giờ/ngày. Một job trung bình có thể mất 4 phút và vẫn đạt chỉ tiêu này khi chạy tuần tự liên tục. Nếu chỉ 10 ngày hoạt động, 12 giờ/ngày cần tối thiểu 16,67 file/giờ; mục tiêu có 20% dự phòng là 20,84 file/giờ. Thống kê phải dùng phân bố số trang thực, không mặc định 2.000 file đều giống B071 hoặc dùng trung bình đều của 45 và 99.

Giờ người là ràng buộc độc lập: 84 giờ/2.000 file = 151,2 giây/file, gồm mở, duyệt, sửa, xử lý lỗi và bàn giao. Mục tiêu trung bình 120 giây/file cho các thao tác này dành khoảng 17,33 giờ dự phòng. Đây là **mục tiêu cần đo**, không hứa người duyệt kiểm 45–99 trang trong hai phút. Nếu thực tế là 3 phút/file thì cần 100 giờ người; phải bổ sung người duyệt hoặc điều chỉnh lịch. Chạy đêm không giải quyết thiếu giờ người.

Nếu phát triển/cấu hình chiếm D ngày trong chính hai tuần: giờ máy còn lại = `(14-D)*giờ_máy_mỗi_ngày`; giờ người còn lại = `(14-D)*6`. Ví dụ mất 4 ngày, 12 giờ máy/ngày chỉ còn 120 giờ; cần 16,67 file/giờ tối thiểu, chưa có dự phòng. Phải cập nhật lịch ngay khi biết ngày bắt đầu, không tính thời gian xây dựng là thời gian đã xử lý hồ sơ.

## Các phương án

1. **Hàng đợi cục bộ + chạy đêm + duyệt tập trung (đề xuất).** Ít thay đổi nhất từ engine hiện có, không cần dịch vụ ngoài. Tự chạy từng hồ sơ và tiếp tục sau lỗi; thêm song song nhỏ nếu hiệu chuẩn chứng minh lợi ích.
2. **Hai hồ sơ đồng thời trên máy này.** Có thể tăng năng suất nhưng dễ tranh CPU/RAM/đĩa. Chỉ bật sau đo tổng file/giờ và QA; giới hạn số worker con của từng job.
3. **Hai máy chia danh sách hồ sơ riêng.** Phương án dự phòng nếu 12–16 giờ/ngày trên một máy không đủ sau khi tính QA. Dùng hai hàng đợi độc lập và hợp nhất manifest, chưa cần hệ thống phân tán hoặc máy chủ cloud. Công suất hai máy vẫn phải đo riêng; không cam kết gấp đôi.

Không cần cài Celery, Redis, GPU, mô hình ngôn ngữ hoặc gửi bệnh án ra dịch vụ bên ngoài để giải quyết hàng đợi. Chỉ thử backend OCR/mô hình nhận diện khác khi A050 và bộ kiểm độc lập chứng minh backend hiện tại là nút thắt chất lượng; đánh giá đó là nhánh có điều kiện, không mặc định thêm phụ thuộc.

## Luồng và trách nhiệm

`Kiểm danh sách → nhận job → OCR/phân tích → khử DRAFT → kiểm PDF đầu ra → cần duyệt → duyệt/sửa → xuất lại nếu cần → kiểm lại → sẵn sàng bàn giao`.

### Nhận diện và đối chứng

- Tái hiện A050 từ nguồn bằng job mới, giữ nguyên lựa chọn tự động. Đối chiếu trang nguồn với PDF DRAFT; ghi lỗi theo: OCR không đọc, recognizer không bắt, có đề xuất nhưng không chọn, bbox thiếu, khử/xuất sai, hoặc dùng job/output cũ.
- Gắn nhãn độc lập `must_redact`, `must_preserve`, `uncertain`; gồm tên bệnh nhân, người thân, bác sĩ/điều dưỡng/người ký, địa chỉ, liên hệ, ngày sinh, mã định danh theo chính sách. Không lấy output của recognizer làm ground truth.
- Bổ sung nhận diện và lan truyền tên đã xác nhận **trong đúng hồ sơ**; OCR cục bộ vùng nghi ngờ để sửa lỗi thực đã tái hiện. Không đưa tên/mask mẫu vào rule, không xóa mọi từ giống tên hoặc mọi ngày tháng.
- Đo tách proposal recall, auto-selection recall, độ phủ hình học/khử vật lý và chất lượng PDF cuối. Tên bị xóa một phần vẫn là bỏ sót. Báo số vùng gốc và số lỗi, precision/recall theo từng nhóm, không dùng số đề xuất thay mẫu số.
- Bộ thí điểm đề xuất 30 hồ sơ khác nhau được phép dùng, có 45–60/61–80/81–99 trang, native/scan/mixed, nhiều biểu mẫu; chia 15 phát triển và 15 giữ kín theo hồ sơ. A050/B071 thuộc tập phát triển. Nếu chưa có corpus, dùng hai mẫu để hồi quy nhưng ghi chưa đủ nghiệm thu quy mô.

### Hàng đợi độc lập và bền vững

- Một PDF là một hồ sơ mặc định. Nhóm nhiều PDF cùng ca chỉ qua ánh xạ case được khai báo; không suy ra cùng bệnh nhân từ thư mục chung hoặc tên gần giống.
- `batch.py`: SQLite cục bộ qua thư viện chuẩn, trạng thái bền vững; mỗi hồ sơ có ID ngẫu nhiên, source hash, policy/OCR/engine fingerprint, revision, đường dẫn job riêng. Coordinator là bên ghi trạng thái; worker báo kết quả về coordinator.
- `batch_worker.py`: tiến trình riêng gọi engine hiện có. Mỗi process tự mở PDF; không truyền `fitz.Document/Page` hoặc dùng các thread để xử lý MuPDF đồng thời. [Tài liệu PyMuPDF](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html).
- SQLite dùng transaction cho claim/update và khóa một coordinator trên mỗi queue; không chia sẻ connection xuyên thread. Không đặt DB trên thư mục mạng. [Tài liệu Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html).
- Trạng thái: `QUEUED`, `PREPARING`, `EXPORTING`, `VERIFYING`, `NEEDS_REVIEW`, `READY`, `FAILED`, `CANCELLED`; queue có pause/resume riêng. `READY` nghĩa là đã duyệt và QA đúng revision, không chỉ máy chạy xong.
- Checkpoint sau prepare hoàn chỉnh và sau export/QC đúng hash. Job đang làm dở khi mất điện được chạy lại từ checkpoint hoàn chỉnh gần nhất; không hứa tiếp tục từng trang nếu chưa có định dạng checkpoint trang an toàn. Tối đa một retry tự động với lỗi tạm thời; lỗi nội dung/policy/PII đưa về cần xử lý.
- Khóa riêng mỗi job khi lưu/xuất/kiểm. Duyệt job A vẫn được khi job B đang chạy. Mọi thao tác ghi dùng job ID + revision; không dựa vào biến active chung để chọn file của worker.

### Tài nguyên, chạy đêm, dung lượng

- Default yêu cầu hai job, admission theo tài nguyên; hiệu chuẩn `1 job × OCR4/render2` so với `2 job × OCR1/render1` và `2 job × OCR2/render1` trên cùng tập. OCR đầu ra cũng phải dùng ngân sách này; không có pool phụ không giới hạn.
- Không nhận job mới khi RAM trống dưới `max(1 GiB, 10% RAM vật lý)`; giới hạn tổng cây tiến trình batch ban đầu 50% RAM vật lý. Chỉ tăng concurrency khi dự báo job thêm vẫn chừa ngưỡng này; đo và báo lấy mẫu 100 ms, có thể bỏ lỡ đỉnh ngắn.
- Kiểm đĩa trước nhập lô và mỗi job: dự toán đầu ra còn lại + không gian đỉnh của các job đang hoạt động + dự phòng tối thiểu 2 GiB. Không tự xóa nguồn, review, bằng chứng cũ. Có thể chọn ổ đầu ra khác và chia đợt 100–200 file; xác minh bản bàn giao trước khi giải phóng cache tái tạo của đợt đã hoàn thành.
- Chỉ xóa cache do batch sở hữu, có allowlist loại file và kiểm đường dẫn tuyệt đối nằm trong job. Giữ dữ liệu cần duyệt của mọi job chưa READY. Lưu chính sách giữ dữ liệu và quyền thư mục riêng; manifests tổng hợp không chứa tên/PII.
- Khi chạy đêm, chống sleep khi có job bằng API Windows trong thời gian chạy và khôi phục khi dừng; cảnh báo mất nguồn/pin, tạm dừng nhận job mới khi nguồn không phù hợp. Ghi heartbeat/tiến độ/ETA dựa trên dữ liệu đã đo. Mất điện thật phục hồi qua checkpoint, không dựa vào chống sleep.

### Kiểm PDF cuối và duyệt

- `output_qc.py` đọc chính PDF đã xuất theo SHA/revision: đủ trang, khổ đúng, không còn text/attachment/widget/annotation nguồn; so vùng khử và vùng cần giữ trên bộ nhãn.
- Trong vận hành, OCR lại mọi trang của PDF xuất, so identifiers đã xác nhận trong đúng ca và detector cho tên/ngày sinh/liên hệ. Cảnh báo độ tin cậy thấp, thiếu trang OCR, xung đột hoặc nghi ngờ đều chuyển NEEDS_REVIEW; không lọc hết rồi gọi kết quả sạch. OCR lần hai cùng backend chỉ là lớp kiểm bổ sung, không phải đối chứng độc lập.
- QC hậu xuất được đưa vào đồng hồ throughput; cache kết quả chỉ khi PDF SHA, policy và verifier fingerprint khớp. Không chuyển chi phí này ra ngoài để công bố đạt.
- UI danh sách hồ sơ + vùng nghi ngờ trước/sau + nhảy đúng trang; bộ lọc tên bệnh nhân, nhân viên, OCR lỗi, vùng chưa chọn, xung đột. Vẫn có xem toàn trang và rà trang chưa gắn cờ; không dùng risk score để tự đánh dấu tất cả trang đã duyệt.
- Giữ cơ chế người duyệt hiện hành. Worker chỉ xuất DRAFT. Phát hành đòi hỏi người duyệt, đúng revision và QC không còn vấn đề chưa giải quyết; chỉnh một vùng làm mất hiệu lực QC tương ứng. Tệp lỗi không vào thư mục bàn giao.
- Xuất mã nghiên cứu + PDF + QC đã loại PII + manifest hash. Internal audit/analysis/seeds và tên gốc nằm trong vùng riêng, không đóng gói theo. Mã bệnh nhân/mã hồ sơ vốn được giữ phải được quyết định trong bảng chính sách trước nghiệm thu, không gọi output là vô danh hoàn toàn khi vẫn giữ mã liên kết.

## Nghiệm thu và điểm dừng

1. Tất cả lỗi A050 đã xác nhận được sửa và có hồi quy; không còn PII trọng yếu đã gắn nhãn trên PDF cuối; không mất vùng chuyên môn bắt buộc giữ. Có số lỗi riêng trước/sau tự động và sau người duyệt.
2. Ngưỡng phát triển đề xuất: auto-selection recall ≥99,5% tổng vùng nhãn cần xóa, ≥99% từng nhóm bệnh nhân/nhân viên/liên hệ; precision ≥99%. Đây là mục tiêu trên bộ kiểm được gắn nhãn, không chứng nhận mọi hồ sơ; luôn ghi tử số/mẫu số, vùng thiếu một phần tính fail.
3. Không tự bỏ qua review vì đạt ngưỡng trên. Mọi trang không OCR được, cảnh báo chưa phân xử và không đủ bằng chứng đều chặn READY.
4. Tối thiểu 15 file/giờ ở lịch 12 giờ/ngày, hoặc 12 file/giờ ở lịch 16 giờ/ngày, có đủ QA mới và phân bố mẫu thật; đo 6 giờ liên tục, gồm retry/gián đoạn trong cửa sổ thử. Chỉ tính một lần mỗi hồ sơ có QA máy PASS; hồ sơ còn cảnh báo chưa phân xử/kiểm thiếu được đếm riêng. Trong pilot, tính cả chi phí máy xuất/kiểm lại sau sửa tay; file đã đếm trước đó không được đếm lần hai. Báo latency min/median/p95/max, files/hour, pages/hour, RAM, đĩa, lỗi và backlog review. Không đổi ngưỡng sau khi xem kết quả.
5. Người duyệt đo cả thời gian sửa, chuyển file và bàn giao; nếu vượt quỹ giờ người thì báo cần nguồn lực bổ sung. File máy làm xong, NEEDS_REVIEW và READY được đếm riêng.
6. Khôi phục sau kill/restart không thất lạc hồ sơ, không publish bản dở, không có OCR process mồ côi; chạy nhiều hồ sơ không trộn seeds/output hoặc làm hỏng bản đã duyệt.
7. Thí điểm 100 hồ sơ, rồi 500, rồi phần còn lại; nếu phát hiện bỏ sót quan trọng/mất nội dung, giữ đợt liên quan để sửa và QA lại theo phiên bản, không bỏ qua nhằm đạt số lượng.

## Thông tin còn thiếu nhưng không ngăn lập kế hoạch

- Người dùng chưa chỉ trang cụ thể hoặc PDF đã khử còn sót của A050; kiểm từ nguồn trước, phân biệt lỗi bản đang dùng và bản hiện tại khi có output.
- Chưa có quyền/đường dẫn corpus 2.000 file và 30 file đại diện; không tự quét Downloads để gom bệnh án khác.
- Lịch 14 hay 10 ngày làm việc, thời gian xây dựng có nằm trong hai tuần, ổ đầu ra đủ dung lượng và chính sách mã định danh phải được chốt khi bắt đầu vận hành. Phương án hiện tại nêu giả định để vẫn lập được kế hoạch đầy đủ.

## Công cụ áp dụng

Plugin Superpowers: brainstorming, systematic-debugging, writing-plans, kiểm tra thiết kế độc lập; PDF skill cho đối chiếu ảnh và cấu trúc; Ponytail để tái dùng engine và giới hạn thay đổi. Công cụ Codex mở kế hoạch trong workspace. Không cần kết nối cloud chứa bệnh án; không cài plugin chỉ vì có sẵn.

Kiểm tra thiết kế độc lập đã hoàn tất: không có câu hỏi quan trọng cản lập kế hoạch; công suất, giờ người, thời gian xây dựng và điều kiện READY nhất quán. Reviewer chỉ đọc thiết kế, chưa đo/kiểm phần mềm mới.
