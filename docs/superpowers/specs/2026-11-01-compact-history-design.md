# Tinh gọn dự án, giữ engine v20

Người dùng giao quyền chọn cách tốt nhất để giảm dung lượng, giữ chất lượng/logic/tốc độ hiện tại; không yêu cầu thêm tính năng. Lựa chọn của người triển khai: lưu trữ lossless lịch sử kiểm thử cũ bằng ZIP+SHA256 objects/stdlib, giữ khả năng khôi phục từng tệp, không sửa mã nguồn hoặc tự xóa dữ liệu hồ sơ đang dùng.

## Approaches

1. Tiếp tục xóa bản thử: nhẹ hơn nhưng mất thêm lịch sử, không chọn.
2. Chỉ loại bản PDF trùng SHA: tiết kiệm tối đa khoảng1,43GB, vẫn còn nhiều bản làm việc khác metadata; không chọn làm cơ chế chính.
3. Nén lịch sử cũ theo luồng và xác minh từng tệp: chọn vì giữ đủ nội dung cũ, không nằm trên đường xử lý thực tế. Dữ liệu lịch sử cần giải nén trước khi mở lại ở đường dẫn cũ.

Giữ trực tiếp toàn bộ v20, v19 dùng so RGB, v18 ca hồi quy, safe_acceptance run20 bản chuẩn cũ, reference_clean/final/fixed, tất cả bộ nhãn/vùng chuẩn ngoài các thư mục thử được chọn, bản giao cũ/finalround2v6, mọi hồ sơ mặc định đang xử lý/chờ duyệt. Giữ nguyên nguồn gốc bên ngoài và7thư mục bị khóa quyền. Không nén môi trường chạy hoặc mã nguồn. Không thêm chính sách tự dọn sau bàn giao vì phải giữ khả năng sửa lại hồ sơ.

Trước khi bỏ bản rời: tệp nguồn khớp SHA/size manifest; archive có đủ đúng các regular member và hash giải nén khớp100%; archive đóng hoàn chỉnh/đổi tên nguyên tử; đường dẫn xóa có allowlist, không symlink, không vượt workspace. Nếu kiểm thất bại không bỏ bản rời. Mọi mã/source/v20/oracle giữ trực tiếp phải khớp SHA sau cùng. Chạy suite, NodeUI/pip/diff và4QC độc lập ghi vào thư mục riêng. Không có thay đổi mô hình để nghiệm thu lại precision trên corpus; kết quả v20 giữ byte và QC giữ nguyên. Chưa đo4h/holdout rộng.
