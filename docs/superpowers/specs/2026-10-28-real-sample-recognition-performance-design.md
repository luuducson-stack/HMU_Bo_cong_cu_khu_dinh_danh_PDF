# Vòng 2: nhận diện trên bệnh án thật và hiệu năng

> **Cập nhật yêu cầu29/10/2026:** Người dùng yêu cầu giữ nguyên dữ liệu Tuổi. Chỉ tự tích vùng định danh đã xác nhận; ảnh chuyên môn và vùng chưa chắc giữ để duyệt (người dùng đã xác nhận). Policyv4 thay thế yêu cầu khử tuổi bên dưới. Checklist/spec gốc giữ làm lịch sử; nghiệm thu theo báo cáo chốt vòng2 và evidence của policyv4, không dùng log cũ làm kết quả hiện tại.

Ngày: 2026-10-28. Trạng thái: thiết kế/checklist theo yêu cầu mới; chưa triển khai thay đổi sản phẩm ở vòng này.

## Mục tiêu

Khử đúng **giá trị** trong biểu mẫu, giữ nhãn và nội dung chuyên môn; khắc phục các lỗi được chỉ ra trong bốn ảnh và kiểm tra trên cặp PDF 71 trang đã cung cấp. Tiếp tục tối ưu native, batch, vector và watermark với cùng các kiểm tra an toàn. Các test xanh của vòng trước không chứng nhận độ chính xác trên mọi bệnh án thật.

## Bằng chứng đã có

- Hai PDF đều có 71 trang, không trang nào trả về text qua PyMuPDF. Bản gốc gồm ảnh scan và chữ dạng đường vẽ vector; không được coi mọi trang textless là một ảnh scan toàn trang.
- Đã xem thumbnail toàn bộ 71 trang và render đối chiếu các vùng của trang 1, 12, 14 và 19. Đây chưa phải duyệt chi tiết mọi trường trên 71 trang.
- Đã tái tạo đề xuất từ source hiện tại trong job chẩn đoán riêng; không tự duyệt bệnh án hoặc xuất PDF chính thức.
- Trang 12: `ADDRESS_VN/v20_strict_field` bao gồm cả nhãn BHYT và số thẻ. Một đề xuất dài có thể làm đề xuất BHYT ngắn bị subsume. Kiểm tra chuỗi sạch riêng cũng tái hiện lỗi này.
- Trang 1: OCR cho tên bị nhiễu; job mới không có đề xuất tên bệnh nhân tại trường đó. Chuỗi tên sạch với nhãn đúng vẫn được nhận diện: cần sửa đường OCR/nhãn, không thêm tên bệnh nhân cố định vào code.
- Tuổi không có finding vì chính sách hiện tại giữ tuổi. Yêu cầu mới muốn khử giá trị tuổi bệnh nhân: đây là thay đổi chính sách, phải cập nhật cả tài liệu, audit và test.
- Trang 14 và 15: `memorized_staff_mid_given` chọn các cụm chuyên môn "Van hai" và "lỗ van". Hộp của cụm "van hai" sau mở rộng mực lấn sang giá trị kết quả bên cạnh. Test chuỗi chuyên môn đơn lẻ không tái hiện lỗi: phải test cả quá trình học tên và lan truyền giữa trang.
- Trang 19–21: không có đề xuất vùng ký điều dưỡng ở cuối bảng. OCR toàn trang không cung cấp được tên dọc trong các ô đó.
- PDF đã khử được cung cấp và ảnh review không hoàn toàn trùng kết quả: ở PDF, tên bìa và vùng điều dưỡng đã bị xóa; vùng chuyên môn trang 14 vừa kiểm còn hiển thị. Không suy ra rằng bản PDF đó được xuất từ đúng snapshot đề xuất vừa tái tạo.
- Source hiện tại có cùng hash ba module engine/recognizer/OCR với evidence vòng trước. Python hiện chạy là 3.12.10; báo cáo đo cũ ghi 3.10.11. Không gộp các protocol/môi trường thành một kết quả trước–sau.

Chẩn đoán riêng tư được lưu trong `HMU_JOBS/sample_review_20261028/` (đã git-ignore). Không đưa ảnh, OCR text, patient identifiers hoặc PDF thật vào fixture công khai/benchmark tổng hợp.

## Phạm vi và chính sách

- Khử tên bệnh nhân/người nhà/nhân viên y tế, địa chỉ, số điện thoại, DOB/YOB, BHYT/CCCD và chữ ký như chính sách hiện có.
- Theo yêu cầu mới, bổ sung khử **giá trị tuổi bệnh nhân** có neo nhãn `Tuổi`, gồm ô số ở bìa và dòng nội dung. Không tìm/xóa số 94 trên toàn tài liệu. Giữ nhãn `Tuổi` và đơn vị.
- Giữ nhãn `Địa chỉ`, `Số BHYT`/`Số thẻ BHYT`, chức danh ký, cấu trúc bảng, biểu đồ và toàn bộ nội dung chuyên môn ngoài vùng PII đã xác định.
- Quy định giữ giới tính, mã hồ sơ/bệnh nhân và bệnh viện của vòng trước tiếp tục áp dụng; không tự mở rộng yêu cầu sang các trường này.
- Số BHYT phải khử đủ mọi nhóm ký tự/ô; ngày hết hạn BHYT không tự coi là ngày sinh.
- Vùng ký điều dưỡng: khử chữ ký và tên trong từng ô, hỗ trợ hướng chữ 90/270 độ. Không xóa trắng toàn bảng hoặc toàn ảnh trang.
- Đề xuất tên gần đúng thiếu ngữ cảnh không tự chọn. Phải phân biệt tên có thật ở vùng ký với thuật ngữ chuyên môn có âm tiết giống tên; không chỉ bổ sung blacklist cho hai cụm đang thấy.
- Không hứa khôi phục phần đã mất từ PDF đã khử. Tái tạo kết quả mới từ PDF gốc.

## Các cách tiếp cận

1. **Mở rộng regex/blacklist và kéo rộng hộp:** ít thay đổi nhất nhưng tiếp tục làm mất nhãn, nhận nhầm thuật ngữ và bỏ sót chữ dọc. Không đáp ứng tiêu chí an toàn của yêu cầu.
2. **Nhãn + bố cục + tọa độ từ, giữ OCR hiện có và chỉ thử lại ở ROI thiếu:** phương án đề xuất. Sửa ở các helper hiện có, giữ pipeline offline và dependency hiện tại; cần test hình học và pixel ngoài test chuỗi.
3. **Thay OCR/mô hình nhận diện toàn bộ:** chi phí phụ thuộc/triển khai/đo lại lớn, chưa có bằng chứng cần thiết. Chưa đưa vào vòng này; chỉ xem xét nếu ROI vẫn không đạt trên corpus đã đánh dấu.

Lựa chọn 2 là đề xuất kỹ thuật của người triển khai dựa trên yêu cầu và quyền chủ động đã được trao trong cuộc trao đổi; không mô tả như một lựa chọn mới đã được người dùng duyệt riêng.

## Thiết kế tối thiểu

- Dùng chung quy tắc kết thúc trường cho recognizer chính và recognizer bổ sung. Thêm các biến thể nhãn BHYT đã tái hiện; không để một finding địa chỉ bao qua nhãn kế tiếp.
- Dựng rectangle theo giá trị và cụm từ trong cùng trường/ô. Giới hạn ink expansion tại nhãn hoặc biên ô kế tiếp; subsume không được che mất ranh giới hai trường khác loại.
- Với OCR thiếu tên/tuổi: tìm ROI từ neo và hình học biểu mẫu, OCR lại ROI theo cách có kiểm chứng; chuyển tọa độ về đúng hệ trang, ghi nguồn/độ tin cậy. Hỗ trợ cả chữ dạng vector không có text và ảnh scan.
- Ràng buộc tên học từ tài liệu theo chất lượng seed và vùng/nhãn hợp lệ. Các trường hợp xung đột chuyên môn chuyển sang duyệt, không tự chọn xóa.
- Tìm hàng/ô điều dưỡng bằng neo chữ và đường bảng hoặc đường mực raster khi trang chỉ có ảnh. Tách phần ký/tên theo ô, OCR cục bộ xoay nếu cần; không đòi OCR nhận ra chữ ký viết tay mới có thể đánh dấu vùng ký.
- Giữ chữ ký hàm và cấu trúc `Finding`, `(text, chars)`, proposal và review hiện có nếu có thể. Nếu cần thêm provenance/chính sách, dùng trường bổ sung tương thích và fingerprint; không tái sử dụng job cũ với chính sách mới một cách âm thầm.
- Preview, audit và export phải dùng cùng lựa chọn và tọa độ tại một revision. Export từ các pixel đã mask, metadata/attachments không chứa nguồn; publish PDF+QC nguyên tử.

## Hiệu năng

Bốn mốc đo: B0 bản gốc, R0 source hiện tại trước vòng 2, R1 sau sửa chính xác, R2 sau tối ưu. R1 giúp tách chi phí việc bắt buộc mới khỏi lợi ích tối ưu; không tái tạo giả một baseline chưa đo. Tất cả chạy cùng Python/dependency/máy/protocol và corpus hash. Giữ số đo lịch sử riêng.

- Native: profile I/O, audit lặp, parse/render lặp; không giảm DPI hoặc bỏ kiểm tra để lấy số đẹp.
- Batch: source đang gọi `generate_audit_markdown` một lần trong loop xuất và lần nữa khi ghép audit. Giảm lặp theo snapshot; giữ kiểm tra mọi file và pointer nguyên tử.
- Vector: kiểm tra chi phí `get_drawings`, `vector_qr_rects`, probe mực và render trên cả fixture vector đặc. Không đổi phân loại QR/ảnh chuyên môn chỉ để nhanh.
- Watermark: `apply_review_to_page` đang gọi proof toàn trang rồi proof theo từng proposal. Tạo kết quả proof trong phạm vi một page/snapshot để dùng lại, vẫn xác minh từng target, q/Q, graphics/opacity, shared stream và partial selection. Cache không sống qua thay đổi trang/revision.
- Corpus chính: native10/native150, case50, vector20, watermark10. Scan50/mixed10/largephoto2 là nhóm canh hồi quy; bệnh án thật là phép đo riêng tư tách biệt.
- Chỉ công nhận tối ưu khi cùng oracle chất lượng đạt và median giảm so R1. Mục tiêu native/batch/vector/watermark không chậm hơn B0 được báo riêng; nhóm chưa đạt phải giữ số thực, không đổi tên thành thành công.

## Nghiệm thu

1. Ground truth theo trường/ROI trên 71 trang; bốn lỗi báo cáo có test tái hiện trước sửa và đạt sau sửa. Các tên/số trong test chia sẻ phải được tổng hợp hoặc thay thế.
2. Không sót PII đã đánh dấu; không mất nhãn/nội dung chuyên môn đã đánh dấu. Báo riêng false negative/false positive và các vùng chưa xác định, không chỉ một điểm accuracy tổng.
3. Kiểm hình ảnh sau render ở cùng DPI/hệ tọa độ: vùng cần xóa hết mực PII; vùng bảo vệ giữ nội dung, đường bảng và ảnh; test xuất không chỉ test proposal.
4. Toàn bộ Python tests (gồm 14 workflow), Node UI regression, HTTP, OCR và pixel safety đạt; fixture riêng tư thiếu phải SKIP tường minh.
5. Benchmark warm-up 1 + ít nhất 3 lần, tăng lên 5 nếu dao động/khác biệt sát ngưỡng; ghi từng lần, median/range, prepare/export/total, sampled RAM, corpus/source hash và môi trường. Profiler chạy riêng; không dùng thời gian instrumented làm số headline.
6. Báo cáo có ba mục riêng: đã đạt, chưa đạt, chưa kiểm chứng. Job/PDF chưa được duyệt không mang trạng thái chính thức.
