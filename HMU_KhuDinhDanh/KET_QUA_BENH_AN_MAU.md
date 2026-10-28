# Kết quả hồ sơ mẫu và điều kiện bàn giao

- Hồ sơ mẫu: 150 trang. Bản xuất giữ 150 trang, 200 dpi.
- Loại 150 watermark tên; xử lý 185 vùng ảnh định danh/chữ ký/QR và 44 trường dấu ký số; xử lý 7 QR dạng vector.
- 17 kiểm thử tự động đạt; kiểm thử thực tế giao diện localhost, xem trang, lưu, xuất, tải và từ chối token sai đạt.
- Sau xử lý lớp nội dung, không còn ứng viên định danh theo bộ nhận diện hiện có; không mất các token ICD, tên xét nghiệm và chỉ số nằm trong bộ kiểm tra. Đây không phải chứng nhận phát hiện 100% định danh.
- Đã xem tổng quan 150 trang, rà ảnh nguồn và kiểm tra phóng lớn các trang có rủi ro. Không thay thế nghiệm thu bởi người phụ trách chuyên môn.
- Trang 109 là ảnh giấy ủy quyền hành chính có chữ viết tay và định danh: loại toàn bộ ảnh; không có chẩn đoán/xét nghiệm trên trang đó. Hồ sơ gốc giữ nguyên.
- Giữ tuổi, giới, ngày điều trị, nội dung y khoa và tỉnh/thành theo cấu hình hiện tại. Ngày sinh, địa chỉ chi tiết và mã liên kết nguồn được xóa. Nếu bộ dữ liệu nghiên cứu yêu cầu dịch ngày hoặc bỏ thêm biến, người phụ trách cần quyết định chính sách trước bàn giao.
- PDF được dựng lại từ pixel; không mang lớp text nguồn, metadata nguồn, file đính kèm hay đối tượng PDF gốc. Không tìm/copy text trong bản xuất.
- Bản mẫu có trạng thái DRAFT_NEEDS_QC: đã xử lý để kiểm tra cuối, chưa đánh dấu giả rằng cán bộ HMU đã duyệt từng trang. Chỉ bàn giao ngoài đơn vị sau nghiệm thu bản PDF.

## Chốt vận hành

Cán bộ CNTT cài bộ công cụ một lần. Người duyệt mở hồ sơ, duyệt trực tiếp vùng xóa trên từng trang, xuất PDF và kiểm tra đầu ra. Không cần chạy lại V1.3 để tạo CSV. Nếu một vùng cần sửa, sửa trong cùng công việc đã lưu rồi xuất lại.

Bộ công cụ này áp dụng cho PDF, kể cả vùng scan/ảnh được khoanh. Không chứng nhận DICOM/JPEG độc lập.
