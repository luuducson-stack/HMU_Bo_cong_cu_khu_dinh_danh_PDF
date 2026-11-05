# HMU - Bộ khử định danh PDF và kịch bản vận hành

Kết quả triển khai, checklist 15 vấn đề, kiểm thử và benchmark thực tế: [Báo cáo 28/10/2026](../BAO_CAO_TRIEN_KHAI_2026-10-28.md). Windows OCR trong môi trường kiểm thử chọn en-US; cần nghiệm thu riêng ảnh chữ Việt có dấu/chữ viết tay trên dữ liệu được phép xử lý.

**Một công cụ, một vòng duyệt trên trang, một lần xuất.** Không cần chuyển qua lại giữa PDF và CSV. Bộ này nhận PDF có text hoặc PDF scan; trang scan và ảnh scan trong trang hỗn hợp được OCR offline; chữ viết tay và nội dung chưa nhận diện cần khoanh vùng trực tiếp. Chạy trên máy HMU, không gửi bệnh án tới dịch vụ bên ngoài.

## Cài một lần

1. Giải nén thư mục `HMU_KhuDinhDanh` vào máy xử lý được HMU cho phép. Máy cần Python 3.10 trở lên.
2. Chạy `CAI_DAT_WINDOWS.bat`. Cài đặt hoàn tất khi các kiểm thử báo OK. Cài phụ thuộc cần kết nối nguồn phần mềm; việc xử lý bệnh án sau đó hoạt động offline.
3. Máy hoàn toàn offline: cán bộ CNTT chuẩn bị wheel của PyMuPDF 1.26.6 và pypdf 6.10.0 đúng Python/Windows, rồi cài bằng `pip install --no-index --find-links <thu_muc_wheel> -r requirements.txt` trong môi trường `.venv`.

## Kịch bản mỗi bệnh án — ba thao tác

**1. Mở:** chạy `MO_CONG_CU.bat`, nhập mã nghiên cứu (ví dụ HMU_CASE_0001), chọn PDF gốc và bấm “Mở và đánh dấu PDF”. Công cụ đề xuất vùng tên, ngày sinh, địa chỉ đầy đủ (kể cả tỉnh/thành), số điện thoại, CCCD/BHYT, email, thông tin truy cập kết quả, chữ ký và QR. Mã hồ sơ/mã bệnh nhân/mã nguồn liên kết và barcode được giữ theo chính sách hậu kiểm; người duyệt phải kiểm tra nội dung liên kết còn lại. Watermark không bị bóc trước duyệt; chỉ xóa đối tượng đã xác nhận an toàn khi xuất. Không phủ trắng hộp lớn của watermark chéo vì có thể xóa chữ chuyên môn nằm dưới. Khi không tách an toàn được, công cụ từ chối cách xóa đó để xử lý lại nguồn.

**2. Duyệt trực tiếp:** vùng đỏ sẽ xóa; ảnh, ghi chú và trường biểu mẫu màu cam cần kiểm tra; trường chữ ký số được chọn sẵn. Bỏ chọn vùng không phải định danh hoặc thông tin chuyên môn. Chọn ảnh chữ ký, QR và ảnh có tên; giữ logo, ảnh chuyên môn và checkbox. Với ảnh chuyên môn có chữ định danh, giữ ảnh và dùng “Khoanh thêm vùng xóa” chỉ khoanh chữ. Kiểm tra cả phần chưa được đánh dấu. Bấm “Đã duyệt trang này” để chuyển sang trang tiếp. Việc duyệt chỉ thực hiện một vòng, trạng thái tự lưu và có thể mở lại.

**3. Xuất:** bấm “Xuất sau khi duyệt đủ trang”. Công cụ xóa trên text/pixel/đồ họa rồi dựng lại PDF từ các trang đã xử lý; không đưa đối tượng PDF gốc, metadata, file đính kèm, annotation hay lớp text cũ vào bản bàn giao. PDF và JSON QC được lưu theo thế hệ xuất bất biến trong `exports/<export_id>/`. Chỉ thế hệ được `last_export.json` trỏ tới mới là kết quả đã công bố; lỗi xuất không thay thế bản hợp lệ trước đó. Nút “Xuất PDF thử để kiểm tra” cho phép tạo bản thử trước khi hoàn tất duyệt và luôn gắn trạng thái DRAFT.

**Kiểm tra đầu ra trước bàn giao:** người duyệt mở PDF, xác nhận các vùng xóa đã đúng, ảnh chẩn đoán và thông tin chuyên môn vẫn đọc được. Nếu cần sửa, quay lại vùng tương ứng trong cùng công việc và xuất lại; không sửa recognizer hoặc chạy lại từ đầu.

## Đầu ra và bảo mật

- PDF mang mã nghiên cứu, giữ kích thước và số trang. Bản giao là PDF ảnh PNG ở 200 dpi, không có lớp text để copy/tìm kiếm; có thể tăng dpi trong cấu hình công việc khi cần chất lượng cao hơn. Nội dung y khoa hiển thị trên trang được giữ ngoài vùng xóa. OCR ở một công đoạn sau sẽ nhận các pixel đã khử, không có lớp text gốc để phục hồi.
- Báo cáo QC: mã nghiên cứu, số trang, số vùng xử lý, hash sản phẩm và trạng thái. Báo cáo bàn giao không chứa các giá trị PII đã xóa.
- `HMU_JOBS/` chứa dữ liệu nguồn, bản làm việc, ảnh xem trước và `review.json`, `analysis_private/`, `AUDIT_SUMMARY.md` và manifest có PII phục vụ duyệt nội bộ. Chỉ bản PDF đầu ra và báo cáo QC mới là sản phẩm bàn giao; không gửi nguyên thư mục công việc. Giới hạn quyền truy cập và xóa bản tạm theo quy trình nội bộ sau nghiệm thu.
- Đóng cửa sổ lệnh sẽ dừng công cụ. Để mở lại công việc cũ: `.venv\Scripts\python.exe app.py --job "<duong_dan_thu_muc_review>"`.

## Phạm vi đã chốt

Bộ này hoàn thành **khử định danh PDF**, gồm lớp text và vùng hình ảnh/scan được chọn. Không phải công cụ hoàn toàn tự động bảo đảm phát hiện mọi PII; một vòng duyệt là phần của kịch bản, giúp tránh xóa nhầm dữ liệu y khoa. Không có vòng riêng duyệt CSV hoặc bổ sung từng bản recognizer.

DICOM/JPEG độc lập cần quy trình riêng về header/metadata và pixel; không đưa vào thư mục PDF rồi coi chúng đã được xử lý. Chưa có DICOM/JPEG mẫu trong dữ liệu đính kèm lần này nên không chứng nhận phần đó. Metadata lâm sàng theo Data Dictionary cũng là công đoạn riêng; báo cáo QC của công cụ không thay thế metadata nghiên cứu.

## Dòng lệnh cho CNTT (tùy chọn)

```bat
python engine.py prepare "benh_an.pdf" --job "HMU_JOBS\CASE_001"
python app.py --job "HMU_JOBS\CASE_001"
python engine.py export --job "HMU_JOBS\CASE_001"
```

Lệnh export từ chối bản chính thức nếu chưa duyệt đủ trang, PDF làm việc bị thay đổi, vùng ngoài trang hoặc vùng được đánh dấu chồng lên mã ICD. Tất cả thao tác giữ PDF gốc nguyên vẹn.

## Kiểm thử đã thực hiện

Kiểm thử phát hiện và offset; kiểm thử xuất/xóa bằng PDF giả lập; kiểm thử vùng trắng sau xóa và vùng chuyên môn còn hiển thị; từ chối vùng ngoài trang và tệp làm việc thay đổi; không mang metadata/file đính kèm gốc vào bản xuất; kiểm thử HTTP localhost cho mở giao diện, xem trang, lưu, xuất, tải và kiểm tra token. Bằng chứng mẫu 150 trang v1.0 được giữ riêng ở mục lịch sử, không thay thế nghiệm thu bản hiện tại. Test thiếu fixture riêng tư phải ghi SKIP có lý do, không báo đạt giả.


## Ca nhiều PDF, nhiều tab và công việc cũ

- Mở một thư mục ca chỉ chuẩn bị dữ liệu; không tự duyệt hoặc xuất bản chính thức. Dùng danh sách file để duyệt đủ từng PDF, lưu trước khi chuyển file, rồi xuất cả ca. Tên sản phẩm theo mã nghiên cứu và thứ tự file, không lấy tên nguồn.
- Lưu theo trang dùng job ID và revision. Nếu báo 409/xung đột, giữ thay đổi chưa lưu và nạp lại trạng thái đúng ca để đối chiếu; không retry ghi đè mù. Một server xử lý một tác vụ nặng tại một thời điểm.
- Không đóng cửa sổ khi còn thay đổi chưa lưu. Đang OCR/xuất thì đợi tác vụ xong trước khi mở ca khác.
- Nếu job cũ từng bị bóc stream watermark, cần PDF nguồn khớp SHA-256 để chuẩn bị lại. Không có nguồn đúng hash thì chỉ xem nội bộ, chưa được xuất chính thức với trạng thái SOURCE_RECHECK_REQUIRED.
- Cổng 8765 đang bận: launcher không dừng chương trình khác. Đóng đúng phiên HMU nếu không còn dùng hoặc chạy `.venv\Scripts\python.exe app.py --port 8766`.
- OCR, PNG và xuất vẫn 200 dpi mặc định; tối ưu không hạ chất lượng, không bỏ bước hash hoặc kiểm QC. Không cam kết tự động phát hiện 100% định danh hoặc đã loại mọi khả năng liên kết vì mã hồ sơ được giữ có chủ ý.


## Phục hồi job cũ từ nguồn đã xác minh

Job có `SOURCE_RECHECK_REQUIRED` không được dùng working PDF để chứng minh dữ liệu đã được bảo toàn. Dùng PDF nguồn có SHA-256 khớp bản ghi cũ, tạo job mới riêng:

```bat
.venv\Scripts\python.exe engine.py recover --job "HMU_JOBS\job_cu" --source "PDF_nguon.pdf" --new-job "HMU_JOBS\job_phuc_hoi"
```

Nguồn sai hash bị từ chối. Job cũ không bị ghi đè; job mới cần duyệt lại. Audit là tài liệu nội bộ có PII, còn số stream watermark thực xóa được ghi trong QC của sản phẩm. OCR mặc định dùng 4 worker khi có ít nhất 64 trang cần OCR, và 1 worker với tải nhỏ hơn; cấu hình này được đo trên PDF mẫu 71 trang. Dựng ảnh trước OCR dùng tối đa 2 tiến trình ở tải từ 64 trang; hai pha chạy lần lượt. Không hạ DPI hoặc bỏ kiểm tra để tăng tốc.

Bản tối ưu ngày 30/10 giữ 200 dpi và nén lossless: ảnh giải mã giữ nguyên RGB, dung lượng có thể tăng so với nén chậm. Audit sau xuất tái dùng kết quả khử của đúng snapshot, không chạy khử lại. Khi đang xử lý, giao diện vẫn nhận tiến độ OCR thực nhưng không nhận chỉnh sửa hoặc tạo audit đồng thời. Tên tệp gốc hợp lệ được dùng làm dữ kiện nhận diện cho cả upload và mở đường dẫn; vẫn cần kiểm tra ngữ cảnh và hình học tên.

Nếu job cũ báo cấu hình OCR đã thay đổi, chuẩn bị job mới từ PDF gốc và đối chiếu lại lựa chọn khử. Không sửa fingerprint trong JSON để bỏ qua kiểm tra. Các mốc tốc độ chỉ áp dụng trong phạm vi phép đo ở báo cáo nghiệm thu ngày 30/10; thời gian người rà soát không nằm trong mốc thời gian máy.

Bản ngày 30/10 dùng policy `geometry_v6`: nhận diện thêm ngày sinh nằm cùng dòng với họ tên, nhãn “Ngày, tháng, năm sinh” và địa chỉ có lỗi OCR ở chữ “hiện tại”. Job `geometry_v5` bị từ chối xuất để tránh dùng lại các vùng khử thiếu; file và lựa chọn cũ vẫn được giữ để đối chiếu khi chuẩn bị job mới. Không tự sửa chuỗi policy trong JSON để mở khóa. Ca mẫu đã được rà soát lại có job mới trong báo cáo nghiệm thu; dùng job đó để giữ các lựa chọn đã xác minh.

Tên đứng riêng và tên được suy diễn từ trang khác nhưng thiếu ngữ cảnh trường họ tên/người ký được hiển thị dưới dạng đề xuất chưa chọn (`CONTEXT_REQUIRED`), kể cả tên đầy đủ. Cần kiểm tra rồi chọn vùng cần khử; các đề xuất này không tự trở thành tên đã biết để suy diễn tiếp. Cách này tránh khử nhầm thuật ngữ chuyên môn trùng với họ/tên, nhưng cần người duyệt bổ sung các tên thật chưa chắc chắn trước khi xuất chính thức.

Chính sách cập nhật: giữ nguyên toàn bộ trường Tuổi, kể cả số tuổi, đơn vị và đường ô; tiếp tục giữ giới tính và số chuyên môn. Vùng định danh đã xác nhận được tự tích đỏ khi quét; ảnh chuyên môn, mã vạch hậu kiểm và vùng chưa chắc vẫn để chưa chọn. Công việc tạo theo chính sách cũ phải chuẩn bị lại từ PDF gốc; không dùng lại các lựa chọn cũ để xuất theo chính sách mới. Vùng ký điều dưỡng được tách theo ô bảng, cần kiểm tra cả chữ ký và tên dọc; ô thiếu đường bảng/neo có thể phải khoanh thủ công. Nguồn nhận diện được hiển thị cạnh mỗi đề xuất; trạng thái chọn không thay thế nghiệm thu bằng mắt.


## Hai chế độ làm việc

- **Ca đang mở** dùng cho PDF đơn hoặc thư mục gồm nhiều PDF cùng một ca. Bấm **Mở PDF** hoặc **Xử lý đường dẫn**, rồi chọn file để duyệt. Khi có ca đã mở, khối **Xuất thư mục** xuất các file đủ trang đã duyệt và giữ tên gốc. Gói này có thể chứa thông tin định danh trong tên PDF, QC và manifest. Kiểm PDF và tên file trước bàn giao.
- **Hàng đợi** xử lý mỗi PDF thành một hồ sơ độc lập. Nhập mỗi đường dẫn trên một dòng, bấm **Thêm vào hàng đợi**, rồi **Chạy / tiếp tục**. Khối **Xuất thư mục** lấy phạm vi từ các đường dẫn này và yêu cầu đủ điều kiện QC.

Danh sách file chưa đủ điều kiện hiện ngay dưới nút xuất. Có thể mở file để duyệt tiếp rồi xuất lại. Mỗi chế độ giữ riêng ô đích trong phiên trình duyệt. Nếu phiên cũ báo lỗi tải giao diện hoặc `Not found`, lưu công việc và mở lại bằng tiến trình HMU mới. Dùng `--job` với thư mục công việc đã lưu để tiếp tục ca đang duyệt.

Máy yêu cầu tối đa hai file đồng thời, tự chờ nếu thiếu RAM/đĩa. File nào xong thì có bản DRAFT riêng và vào **Chờ duyệt**, không đợi hết lô. Các file chưa duyệt không ngăn xử lý file tiếp theo. Đóng tab không dừng coordinator; nếu máy/tiến trình dừng, mở lại công cụ và bấm **Chạy / tiếp tục**. **Tạm dừng** chỉ dừng nhận file mới, đợi file đang làm xong; **Hủy xử lý** dừng cây tiến trình của đúng file đó. **Thử lại** giữ chỉnh sửa khi checkpoint còn tương thích; phiên bản xử lý thay đổi sẽ chuẩn bị thế hệ mới và giữ bản cũ trong dữ liệu nội bộ.

Bấm **Mở / duyệt** để kiểm từng trang. **Xem PDF đã khử** hiển thị ảnh từ chính PDF đầu ra. Cảnh báo có nút **Đến trang**; nếu còn định danh, khoanh thêm/chọn vùng trên ảnh nguồn. Sau sửa, **Xuất PDF thử** xếp lại file để xuất và OCR kiểm PDF mới. Nếu cảnh báo là nội dung cần giữ, duyệt trang rồi nhập người duyệt và lý do trước **Xác nhận giữ**. Không dùng xác nhận này để bỏ qua tên còn sót.

**Xuất PDF chính thức** trong hàng đợi chỉ bàn giao khi đủ trang đã duyệt, QC khớp nội dung/PDF/phiên bản và mọi cảnh báo được xử lý. Gói `HMU_JOBS/batch/delivered/` chứa PDF mang tên file gốc, `qc.json` và `manifest.json`. `HMU_JOBS/batch/jobs/` chứa nguồn, tên, OCR và audit riêng tư: không gửi cả thư mục này cho bên nhận. Máy không tự duyệt; machine PASS không chứng nhận hết mọi định danh.

Có thể duyệt file A khi máy xử lý file B. Các thao tác OCR/xuất theo luồng một file cũ bị chặn khi queue đang chạy để tránh vượt budget; thêm file mới qua hàng đợi. Lưu sửa trước khi chuyển hồ sơ; giao diện chặn chuyển nếu lưu lỗi.

**Xóa và xóa hàng loạt (03/11/2026):** mỗi dòng có nút **Xóa**. Hoặc tích các ô chọn, dùng **Chọn tất cả đang hiển thị** (theo bộ lọc hiện tại), rồi **Xóa đã chọn**. Lựa chọn từ các bộ lọc trước vẫn được giữ; kiểm số “đã chọn”, dùng **Bỏ chọn** khi muốn chọn nhóm khác. Hộp xác nhận nêu số mục. Xóa dọn nguồn sao chép nội bộ, các thế hệ làm việc, ảnh xem, OCR, vùng duyệt và PDF thử của đúng mục đó; **giữ file nguồn ban đầu và các PDF đã bàn giao**. Không khôi phục được vùng duyệt sau xóa; thêm nguồn lại sẽ tạo công việc mới. File đang chạy/đang dừng được bỏ qua: bấm **Hủy xử lý**, đợi **Đã hủy**, rồi xóa. Nếu ổ đĩa/khóa file ngăn dọn, mục hiển thị **Xóa chưa xong**; đóng chương trình đang giữ file và bấm **Xóa** lại. Không chạy lại một mục đã dọn một phần. Khi xóa bản chính có bản trùng, bản trùng còn lại được xếp hàng xử lý độc lập.

**Xuất thư mục ở chế độ Hàng đợi.** giữ/nhập lại đường dẫn PDF hoặc thư mục của đợt ở ô đầu hàng đợi; phạm vi bao gồm thư mục con, không phụ thuộc bộ lọc trạng thái. Điền **Thư mục nhận kết quả** nằm ngoài thư mục nguồn/cache nội bộ rồi bấm **Xuất các PDF đã duyệt**. Hệ thống tạo thư mục `BAN_GIAO_<thời điểm>_<mã>` chứa các PDF mang tên gốc cùng `manifest.json` và `qc.json`. PDF trùng tên nằm trong các thư mục con riêng. Gói không chứa đường dẫn nguồn, OCR hay dữ liệu duyệt riêng tư. Tên PDF và manifest có thể chứa thông tin định danh. File đủ trang đã duyệt và mọi điều kiện QC hợp lệ được xuất ngay, kể cả chưa bấm xuất riêng từng file. File còn lại có thông báo tên và lý do, danh sách ở dưới cùng kèm **Mở / duyệt**. Duyệt nốt/xử lý cảnh báo hoặc xuất lại PDF thử nếu sửa vùng, rồi bấm xuất thư mục lần nữa. Mỗi lần xuất tạo thư mục mới gồm toàn bộ file hiện đủ điều kiện, giữ các lần trước; kiểm số lượng và thư mục mới trước bàn giao. Không tự duyệt hoặc bỏ qua cảnh báo QC. Bản trùng nội dung được liệt kê, chỉ bản chính có PDF riêng. Sau khi bàn giao từng hồ sơ hoặc xuất nhóm thành công ít nhất một PDF, giao diện cuộn về danh sách **Đã bàn giao**. File chưa đủ điều kiện vẫn có thể mở từ thông báo kết quả.

Vận hành: cắm nguồn; không đặt lịch sleep/shutdown trong khi chạy. Công cụ giữ máy thức khi có worker nhưng không ngăn tắt nguồn thủ công. Chạy từng đợt 100–200 file nếu ổ không đủ cho toàn bộ backlog; dự trù cả nguồn sao chép, ảnh xem và đầu ra. Công cụ không tự xóa cache/bệnh án; chỉ dọn khi người dùng xác nhận Xóa. Sau bàn giao, kiểm SHA/số lượng trước khi xóa công việc. Chưa nghiệm thu sleep/reboot thực hay 6 giờ chạy bền; không coi các kiểm thử ngắn là bằng chứng các bước này.

CLI (chạy từ thư mục công cụ):

```powershell
.venv\Scripts\python.exe -X utf8 batch.py enqueue --queue HMU_JOBS/batch/queue.sqlite3 --input-dir "E:\HoSo\Dot01"
.venv\Scripts\python.exe -X utf8 batch.py run --queue HMU_JOBS/batch/queue.sqlite3 --jobs 2 --ocr-workers 1 --render-workers 1
.venv\Scripts\python.exe -X utf8 batch.py status --queue HMU_JOBS/batch/queue.sqlite3
```

## Cấu trúc mã và kiểm thử

- `app.py` phục vụ giao diện, quản lý phiên duyệt và nhận yêu cầu HTTP.
- `ui/review.html`, `ui/review.css` và `ui/review.js` là nguồn giao diện. Sau khi sửa, chạy `.venv\Scripts\python.exe ui/build_review.py` để tạo lại `review.html` tự chứa mà HMU phục vụ ở trang chính. Kiểm thử API kiểm tra trang đã được tạo từ đúng mã nguồn hiện tại.
- `delivery.py` xuất ca đã duyệt và cung cấp cơ chế công bố thư mục dùng chung. `batch.py` quản lý hàng đợi và kiểm điều kiện QC của từng hồ sơ trước bàn giao.
- `engine.py`, `ocr_helper.py`, `hmu_recognizers.py` và `output_qc.py` xử lý PDF, nhận diện và kiểm đầu ra.

Chạy `.venv\Scripts\python.exe -X utf8 -m unittest discover -q` từ thư mục công cụ. Các kiểm thử giao diện chạy bằng Node với `test_ui_local_folder.js`, `test_ui_batch.js` và `test_ui_save.js`.
