# HMU - Bộ khử định danh PDF và kịch bản vận hành

**Một công cụ, một vòng duyệt trên trang, một lần xuất.** Không cần chuyển qua lại giữa PDF và CSV. Bộ này nhận PDF có text hoặc PDF scan; phần scan/chữ viết tay được xử lý bằng khoanh vùng trực tiếp. Chạy trên máy HMU, không gửi bệnh án tới dịch vụ bên ngoài.

## Cài một lần

1. Giải nén thư mục `HMU_KhuDinhDanh` vào máy xử lý được HMU cho phép. Máy cần Python 3.10 trở lên.
2. Chạy `CAI_DAT_WINDOWS.bat`. Cài đặt hoàn tất khi các kiểm thử báo OK. Cài phụ thuộc cần kết nối nguồn phần mềm; việc xử lý bệnh án sau đó hoạt động offline.
3. Máy hoàn toàn offline: cán bộ CNTT chuẩn bị wheel của PyMuPDF 1.26.6 và pypdf 6.10.0 đúng Python/Windows, rồi cài bằng `pip install --no-index --find-links <thu_muc_wheel> -r requirements.txt` trong môi trường `.venv`.

## Kịch bản mỗi bệnh án — ba thao tác

**1. Mở:** chạy `MO_CONG_CU.bat`, nhập mã nghiên cứu (ví dụ HMU_CASE_0001), chọn PDF gốc và bấm “Mở và đánh dấu PDF”. Công cụ tự đề xuất các vùng tên, mã, ngày sinh, địa chỉ, số điện thoại, email, mật khẩu truy cập kết quả, mã nguồn liên kết, barcode và QR dạng vector. Watermark tên nằm trong stream riêng được bỏ riêng nếu kiểm tra chắc chắn không làm mất phần text khác.

**2. Duyệt trực tiếp:** vùng đỏ sẽ xóa; ảnh, ghi chú và trường biểu mẫu màu cam cần kiểm tra; trường chữ ký số được chọn sẵn. Bỏ chọn vùng không phải định danh hoặc thông tin chuyên môn. Chọn ảnh chữ ký, QR và ảnh có tên; giữ logo, ảnh chuyên môn và checkbox. Với ảnh chuyên môn có chữ định danh, giữ ảnh và dùng “Khoanh thêm vùng xóa” chỉ khoanh chữ. Kiểm tra cả phần chưa được đánh dấu. Bấm “Đã duyệt trang này” để chuyển sang trang tiếp. Việc duyệt chỉ thực hiện một vòng, trạng thái tự lưu và có thể mở lại.

**3. Xuất:** bấm “Xuất sau khi duyệt đủ trang”. Công cụ xóa trên text/pixel/đồ họa rồi dựng lại PDF từ các trang đã xử lý; không đưa đối tượng PDF gốc, metadata, file đính kèm, annotation hay lớp text cũ vào bản bàn giao. Nhận PDF và JSON QC trong cùng thư mục công việc. Nút “Xuất PDF thử để kiểm tra” cho phép tạo bản thử trước khi hoàn tất duyệt và luôn gắn trạng thái DRAFT.

**Kiểm tra đầu ra trước bàn giao:** người duyệt mở PDF, xác nhận các vùng xóa đã đúng, ảnh chẩn đoán và thông tin chuyên môn vẫn đọc được. Nếu cần sửa, quay lại vùng tương ứng trong cùng công việc và xuất lại; không sửa recognizer hoặc chạy lại từ đầu.

## Đầu ra và bảo mật

- PDF mang mã nghiên cứu, giữ kích thước và số trang. Bản giao là PDF ảnh PNG ở 200 dpi, không có lớp text để copy/tìm kiếm; có thể tăng dpi trong cấu hình công việc khi cần chất lượng cao hơn. Nội dung y khoa hiển thị trên trang được giữ ngoài vùng xóa. OCR ở một công đoạn sau sẽ nhận các pixel đã khử, không có lớp text gốc để phục hồi.
- Báo cáo QC: mã nghiên cứu, số trang, số vùng xử lý, hash sản phẩm và trạng thái. Báo cáo bàn giao không chứa các giá trị PII đã xóa.
- `HMU_JOBS/` chứa dữ liệu nguồn, bản làm việc, ảnh xem trước và `review.json` có PII phục vụ duyệt nội bộ. Chỉ bản PDF đầu ra và báo cáo QC mới là sản phẩm bàn giao; không gửi nguyên thư mục công việc. Giới hạn quyền truy cập và xóa bản tạm theo quy trình nội bộ sau nghiệm thu.
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

Kiểm thử phát hiện và offset; kiểm thử xuất/xóa bằng PDF giả lập; kiểm thử vùng trắng sau xóa và vùng chuyên môn còn hiển thị; từ chối vùng ngoài trang và tệp làm việc thay đổi; không mang metadata/file đính kèm gốc vào bản xuất; kiểm thử HTTP localhost cho mở giao diện, xem trang, lưu, xuất, tải và kiểm tra token. Bộ này đã xuất bệnh án mẫu 150 trang được bàn giao riêng.
