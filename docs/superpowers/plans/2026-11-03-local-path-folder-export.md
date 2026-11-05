# Bổ sung xuất thư mục cho Chạy Tự động Đường dẫn / Cả Thư mục

Yêu cầu sửa thiếu phạm vi: chức năng phải có ngay tại khối nhập đường dẫn/ca bệnh người dùng khoanh đỏ, dùng công việc đã mở bằng `/open_path`, không cần thêm vào queue hoặc chuẩn bị lại. Người dùng yêu cầu bổ sung ngay; giữ nguyên lựa chọn triển khai trong phiên hiện tại.

Phạm vi: app.py orchestration/API, review.html khối đường dẫn và kết quả duyệt, test_app.py + test_ui_local_folder.js, hướng dẫn. Không sửa engine/OCR/bộ vùng chuẩn, không đổi tính năng hàng đợi vừa làm, không thêm dependency.

Thiết kế nhỏ: bọc các ô mở PDF trong uploadInputs, đặt ô đích và nút xuất thư mục trong upload; khi duyệt file thường/ca bệnh, chỉ ẩn uploadInputs để nút xuất còn hiện. Khi mở queue, ẩn cả upload như trước. Thư mục xuất mới chứa các PDF/QC của file đã duyệt đủ trang; báo tên/lý do file còn lại và nút mở duyệt qua select_file. Chỉ xuất từ active/case_root đã được server chuẩn bị, không đọc lại đường dẫn mới gõ để quyết định phạm vi. Dùng exporter hiện tại với draft=False, không tự duyệt. Gói giữ trạng thái QC hiện hành HUMAN_REVIEWED_NEEDS_FINAL_QC; không gắn chứng nhận QC mới. Công bố staging nguyên thư mục, kiểm SHA, không ghi đè, không đưa source/OCR/audit riêng tư vào đích. Giữ nguyên last_export cũ.

Các cách cân nhắc: chỉ thêm nút gọi xuất cả ca cũ không đạt vì chặn cả nhóm khi còn file chưa duyệt; chuyển công việc sang queue buộc xử lý lại và sai luồng. Chọn bổ sung orchestration nhỏ dùng export hiện tại, hỗ trợ file PDF đơn và thư mục ca bệnh đang mở.

- [x] Tái hiện RED: bốn ca API thiếu /export_folder trả 404; sau triển khai PASS. Mở ca hai PDF qua /open_path, duyệt một, xuất thư mục chỉ có một và báo đúng tên còn lại; duyệt nốt rồi xuất hai, giữ sản phẩm cũ. Thử scope/revision/token, đích trong cache, lỗi xuất/hash, nguồn và metadata.
- [x] GREEN: helper xuất file đã duyệt và POST /export_folder trong cùng guard tác vụ/identity/giới hạn worker hiện có. Bổ sung kiểm hash sai giữ last_export cũ; manifest traversal; async không cho chuyển ca khi đang xuất.
- [x] RED→GREEN UI: trước sửa upload bị ẩn sau chuẩn bị; sau sửa chỉ ẩn uploadInputs, nút xuất còn hiện. Đúng API/identity sau flush, alert tên thiếu, mở file cần duyệt, chặn khi lưu lỗi hoặc đang ở queue. Ba bộ Node UI PASS.
- [x] Kiểm đầy đủ unittest: 381 chạy, 380 PASS, 1 SKIP (fixture riêng tư không có), 0 lỗi, 198,028 giây. pip check/diff PASS. Smoke trình duyệt đúng luồng open_path trên hai PDF tổng hợp: chuẩn bị → duyệt một → xuất một/alert tên còn thiếu → Mở/duyệt → duyệt nốt → xuất hai/không còn pending. PDF/QC hash và render PASS, nguồn SHA không đổi. Reviewer độc lập không có finding Critical/Important/Minor.

Ledger: phiên trước chỉ hoàn thiện xuất nhóm cho queue, thiếu khối localPath. Không hỏi lại phạm vi vì ảnh và yêu cầu đã xác định rõ. Làm trên checkout đang có thay đổi v20, không commit/push hoặc khởi động lại server thật khi chưa lưu việc người dùng.

Hoàn tất: không sửa engine.py, hmu_recognizers.py, ocr_helper.py, output_qc.py hoặc bộ vùng chuẩn; SHA đối chiếu v20 không đổi. Thư mục nghiệm chứng `HMU_JOBS/local_folder_20261103` giữ log, ảnh, verification.json; fixture tổng hợp được dọn sau kiểm. Không kiểm hồ sơ thật/đo lại hiệu năng lô thật ở task sửa thiếu này. Đã giữ nguyên yêu cầu QC cuối của luồng local; reviewer không chứng nhận lại độ chính xác OCR hay chất lượng lâm sàng.
