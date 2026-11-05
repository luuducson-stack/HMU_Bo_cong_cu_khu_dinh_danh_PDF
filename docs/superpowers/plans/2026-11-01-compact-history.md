# Compact historical test data Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. No product code changes, no new dependencies, no commit/push/merge. Keep existing dirty checkout.

**Goal:** Giảm dung lượng bằng lưu trữ lossless các job thử cũ, giữ engine/nguồn/v20/oracle và chức năng.
**Architecture:** stdlib ZIP_DEFLATED+SHA256 dedup cho lịch sử lạnh; nguồn/hồ sơ hiện dùng và v20 giữ trực tiếp. Hash từng tệp trước/đọc lại archive trước khi bỏ bản rời.
**Tech Stack:** Python3.12 stdlib, native PowerShell; PyMuPDF/QC sẵn có để kiểm đầu ra.
**Spec:** ../specs/2026-11-01-compact-history-design.md

- [x] T1 Lập danh sách old-test allowlist, giữ SHA của tệp nguồn và tất cả tệp ngoài phạm vi; kiểm không có worker đang dùng.
- [x] T2 Tạo archive lossless, kiểm member/size/SHA100%; chỉ sau đó bỏ bản rời bằng PowerShell đã kiểm path. Không xóa source bên ngoài, mã/v20/oracle/live queue. Lưu manifest và cách phục hồi.
- [x] T3 Kiểm mọi tệp giữ trực tiếp không đổi, archive không đổi; suite349/NodeUI/pip/diff và4QC trên PDFv20 vào thư mục riêng; rà độc lập manifest một lượt.
- [x] T4 Đo dung lượng, ghi phần chưa kiểm chứng, cập nhật tài liệu vận hành để tránh nén/dọn job chưa duyệt. Báo số đo thực, không tạo cam kết dung lượng archive hay tốc độ mới trước khi đo.

## Review focus

Path traversal/symlinks; sai SHA hoặc tệp đổi lúc nén; thiếu archive member; nhầm job đang chạy/nguồn chuẩn; giữ đường dẫn cần cho4QC và v19/RGB/reference. Archive phải phục hồi bằng script restore_history.py dùng stdlib ZIP có kiểm SHA, không tạo công cụ runtime mới.

## Kết quả

Dữ liệu lịch sử4,42GB->2,07GB; dự án phần đọc được3,78GB, ngoàiHMU_JOBS91,43MB. Tất cả3893tệpgiữtrực tiếp khớpSHA trước/sau, corev20/oraclekhôngđổi. Suite349/348PASS/1SKIP;Node/pip/diffđạt;4QCkếtquảgiữnguyên408/409(298/298preserve,rawp69nhưtrước). Phục hồi giảlập và5payloadthựcđạt, hỗtrợWindowslongpath. Khôngchạybenchmarktốcđộmới;7ACLdeniedđểnguyên. Xem BAO_CAO_TINH_GON_2026-11-01.md ởroot.
