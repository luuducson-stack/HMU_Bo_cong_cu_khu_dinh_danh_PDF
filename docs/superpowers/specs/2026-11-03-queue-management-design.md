# Quản lý và xuất hàng đợi — 03/11/2026

Người dùng yêu cầu xóa từng mục/hàng loạt và xuất các PDF đã duyệt của đường dẫn nhập vào một thư mục. Đã chọn rõ: xóa cả dữ liệu làm việc, giữ nguồn và PDF bàn giao. Các lựa chọn kỹ thuật bên dưới do người triển khai quyết định theo ủy quyền làm tốt nhất, không phải các lựa chọn người dùng đã nêu.

## Phương án

- Chỉ ẩn hàng đợi: đơn giản nhưng không giải phóng dữ liệu, không đáp ứng lựa chọn vừa xác nhận.
- Dọn công việc khi xóa và tái sử dụng kiểm duyệt hiện có để xuất nhóm: được chọn; không thêm dependency hoặc thay engine nhận diện.
- Thêm hệ thống quản lý đợt và lưu trữ mới: chưa cần cho hai chức năng này.

## Xóa

Checkbox từng dòng, chọn tất cả trong bộ lọc, bỏ chọn, xóa đã chọn; mỗi dòng có nút Xóa. Hiện xác nhận nêu số mục, dữ liệu sẽ dọn và dữ liệu được giữ. Không tự hủy file đang chạy: báo tên mục bị bỏ qua, yêu cầu hủy và đợi dừng rồi xóa.

Đồng bộ với claim/retry/review/release bằng khóa và trạng thái DELETING trong SQLite. Đánh dấu cả nhóm trước khi dọn, để coordinator không nhận mục bị xóa. Xóa chỉ thư mục jobs/<id> hoặc jobs/<id>_<generation> hợp lệ của database hiện tại; từ chối junction/symlink, nguồn hay bản bàn giao nằm trong cây cần dọn. Lỗi ổ đĩa/khóa file giữ trạng thái DELETING để thử xóa lại, không cho chạy lại dữ liệu đã dọn một phần. Bản trùng còn lại được nối lại hoặc xếp hàng độc lập nếu bản chính bị xóa. Dọn không sửa nguồn, vùng chuẩn, job khác hay thư mục bàn giao. Mục đang mở được đóng sau xóa; lưu chỉnh sửa trước thao tác.

## Xuất nhóm

Phạm vi là các job trong hàng đợi thuộc PDF/thư mục đang nhập (bao gồm thư mục con), không dùng bộ lọc trạng thái để tự thu hẹp. Người dùng nhập thư mục nhận, hệ thống tạo một thư mục con mới chứa các CASE_<id>_REDACTED.pdf và manifest/QC không mang tên/đường dẫn bệnh nhân. Không ghi đè sản phẩm cũ; không xuất vào thư mục nguồn hay cache nội bộ. Không sao chép nguồn, OCR, ảnh xem trước, audit riêng tư.

Mỗi PDF phải qua đúng các điều kiện release_job hiện tại: reviewed mọi trang, QC đủ trang/structural, hash PDF/content/policy/verifier khớp, mọi cảnh báo đã xác nhận. Dùng revision thực trên review.json, kể cả đã duyệt nhưng chưa bấm xuất từng file. Không chạy lại OCR khi QC hiện tại còn hợp lệ. Chỉ xuất mục đủ điều kiện, liệt kê tên và lý do các mục còn lại, giữ chúng trong hàng đợi; sau duyệt có thể xuất lại. Giữ khóa review khi kiểm/copy/công bố, kiểm SHA bản copy và công bố thư mục nguyên khối. Ghi READY sau khi có sản phẩm công bố. Không có file hợp lệ thì không tạo thư mục bàn giao rỗng.

## Kiểm chứng

Kiểm thử trạng thái/xóa/quan hệ bản trùng, bảo vệ đường dẫn và nguồn/bàn giao, khóa worker/review, phục hồi xóa dở; kiểm export trộn đã/chưa duyệt/cảnh báo/QC cũ/phạm vi/trùng tên/đích cũ/lỗi copy; API có token và trạng thái mở, UI xác nhận/chọn theo lọc/lưu trước xóa/thông báo còn thiếu. Chạy bộ unittest, hai bộ Node UI và smoke trình duyệt nếu có. Không sửa engine, OCR, DPI, vùng chuẩn hoặc dữ liệu thật để thử xóa. Không suy diễn tốc độ thực 50/71 trang từ kiểm thử chức năng mới.
