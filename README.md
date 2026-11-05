# HMU - Bộ Công Cụ Khử Định Danh Bệnh Án PDF (V3)
> **HMU Medical PDF De-identification & PHI Redaction Toolkit**  
> *Giải pháp khử định danh dữ liệu bệnh án điện tử ngoại tuyến (Offline 100%), bảo vệ quyền riêng tư bệnh nhân theo chuẩn y tế.*

---

## 📌 Tổng Quan Dự Án

**HMU_Bo_cong_cu_khu_dinh_danh_PDF** là giải pháp phần mềm chuyên dụng được thiết kế cho việc khử định danh (De-identification / Redaction) dữ liệu hồ sơ bệnh án điện tử dạng PDF tại Bệnh viện Đại học Y Hà Nội (HMU) và các cơ sở y tế. 

Hệ thống hoạt động **hoàn toàn Offline** trên máy trạm cục bộ, tuyệt đối không gửi dữ liệu bệnh án ra môi trường Internet hay bất kỳ dịch vụ đám mây bên thứ ba nào, đáp ứng nghiêm ngặt các quy định về an toàn thông tin và bảo mật dữ liệu y tế (PHI - Protected Health Information).

### 🎯 Nguyên Tắc Vận Hành
- **"Một công cụ — Một vòng duyệt — Một lần xuất"**: Người duyệt thao tác trực tiếp trên giao diện trực quan, không cần xuất/nhập trung gian qua bảng tính CSV hay công cụ thứ ba.
- **Triệt tiêu lớp Text & Metadata gốc**: Bản xuất bàn giao được tái tạo dưới dạng PDF phẳng (Flattened image layer 200+ DPI), loại bỏ hoàn toàn metadata, annotation, bookmark, tệp đính kèm và lớp text ẩn để chống trích xuất ngược (Zero-leakage guarantee).
- **Bảo tồn giá trị nghiên cứu y khoa**: Giữ nguyên vẹn bảng biểu, ảnh chẩn đoán, kết quả xét nghiệm, phân loại bệnh tật (ICD-10) và mã hóa hồ sơ liên kết.

---

## ✨ Tính Năng Nổi Bật

1. **Bộ Nhận Diện PHI Tiếng Việt Chuyên Biệt (`hmu_recognizers.py`)**:
   - Nhận diện chính xác họ tên bệnh nhân, ngày sinh, số tuổi.
   - Định danh địa chỉ hành chính Việt Nam (Tỉnh/Thành phố, Quận/Huyện, Xã/Phường, thôn xóm).
   - Số định danh cá nhân: Số CMND, CCCD (12 số), mã thẻ BHYT (15 ký tự), số điện thoại, email.
   - Vùng chữ ký số, chữ ký bác sĩ điều trị, dấu mộc, mã QR.
   - Tự động phát hiện và xử lý watermark nền an toàn mà không làm mất thông tin bệnh học phía dưới.

2. **Giao Diện Duyệt Tương Tác Hiện Đại (`app.py`, `ui/`)**:
   - Chạy trên nền tảng Web Localhost trực quan (cổng mặc định `8765`).
   - Khung Canvas tương tác mượt mà: Phóng to (Zoom), Thu nhỏ, Kéo thả (Pan).
   - Thao tác khoanh vùng nhanh: Thêm vùng xóa thủ công, điều chỉnh hộp bounding box, đổi nhãn phân loại, xóa nhầm/phục hồi.
   - Hệ thống phím tắt thuận tiện cho việc duyệt số lượng lớn trang.
   - **Pill Toast Notification System**: Thông báo trạng thái thời gian thực (`success`, `info`, `error`) tinh tế với hiệu ứng mượt mà.
   - Tính năng Tự động lưu (Auto-save) và ghi nhớ tiến trình làm việc.

3. **Hệ Thống Xử Lý Hàng Loạt & Điều Phối Hàng Đợi (`batch.py`, `batch_runtime.py`)**:
   - Quản lý hàng đợi xử lý hàng nghìn tệp PDF cùng lúc.
   - Kiến trúc Supervisor đa tiến trình (Process Isolation) với cơ sở dữ liệu SQLite chế độ WAL (Write-Ahead Logging) cho hiệu năng đọc/ghi tối ưu.
   - Tự động phát hiện trùng lặp hồ sơ dựa trên hàm băm (Hashing & deduplication).
   - Cơ chế giám sát Worker, cô lập lỗi và phục hồi tác vụ tự động.

4. **Kiểm Định Chất Lượng & Bàn Giao (`output_qc.py`, `delivery.py`)**:
   - Báo cáo QC tự động cho từng ca bệnh (`QC.json`).
   - Kiểm tra rò rỉ vùng định danh trước khi bàn giao.
   - Quản lý thế hệ xuất bất biến (`exports/<export_id>/`).

---

## 📂 Cấu Trúc Mã Nguồn

```text
HMU_Bo_cong_cu_khu_dinh_danh_PDF/
├── app.py                   # HTTP Localhost Server & API điều khiển Review UI
├── batch.py                 # Bộ giám sát (Supervisor) xử lý hàng loạt & API Hàng đợi
├── batch_runtime.py         # Quản lý tiến trình Worker chạy ngầm và ghi log
├── batch_worker.py          # Worker thực thi xử lý hồ sơ độc lập
├── engine.py                # Core Engine: Bóc tách text, vẽ mask, rasterize PDF
├── hmu_recognizers.py       # Bộ nhận diện thực thể định danh PHI y tế tiếng Việt
├── ocr_helper.py            # Tích hợp OCR nhận diện chữ trên trang quét/scan
├── output_qc.py             # Bộ kiểm tra chất lượng bản xuất & chống rò rỉ thông tin
├── delivery.py              # Đóng gói hồ sơ và xuất thư mục bàn giao
├── requirements.txt         # Danh sách thư viện Python phụ thuộc
│
├── ui/                      # Mã nguồn giao diện người dùng
│   ├── review.html          # Bộ khung giao diện HTML
│   ├── review.css           # Định kiểu CSS & hiệu ứng Pill Toast
│   ├── review.js            # Logic tương tác Canvas, phím tắt & API client
│   └── build_review.py      # Script build đóng gói thành single-file review.html
├── review.html              # Bản giao diện biên dịch độc lập (Single-file HTML)
│
├── CAI_DAT_WINDOWS.bat      # Script tự động tạo virtualenv & cài đặt cho Windows 11
├── MO_CONG_CU.bat           # Script khởi động nhanh công cụ trên Windows
├── HUONG_DAN_SU_DUNG.md     # Tài liệu hướng dẫn sử dụng chi tiết cho người vận hành
└── README.md                # Tài liệu tổng quan dự án (Tài liệu này)
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy

### 1. Dành cho môi trường Windows 11 (Khuyến nghị cho người dùng)

#### Bước 1: Chuẩn bị môi trường
- Máy tính cài đặt sẵn **Python 3.10 trở lên** (Khuyến nghị Python 3.12).
- Tải mã nguồn về thư mục làm việc (ví dụ: `D:\HMU_KhuDinhDanh`).

#### Bước 2: Cài đặt tự động
- Click đúp chuột vào file **`CAI_DAT_WINDOWS.bat`**.
- Script sẽ tự động:
  1. Khởi tạo môi trường ảo Python (`.venv`).
  2. Cài đặt các thư viện phụ thuộc từ `requirements.txt` (`pymupdf==1.26.6`, `pypdf==6.10.0`).
  3. Kiểm tra tính toàn vẹn của các module.

#### Bước 3: Khởi động công cụ
- Click đúp vào file **`MO_CONG_CU.bat`**.
- Trình duyệt web mặc định sẽ tự động mở địa chỉ: `http://127.0.0.1:8765`.

---

### 2. Dành cho môi trường Linux / NixOS / macOS

```bash
# 1. Khởi tạo môi trường ảo Python
python3 -m venv .venv
source .venv/bin/activate

# 2. Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt

# 3. Khởi chạy ứng dụng Web Review
python3 app.py --port 8765

# 4. Truy cập giao diện trên trình duyệt
# Mở: http://127.0.0.1:8765
```

---

## 🛠️ Hướng Dẫn Sử Dụng Dòng Lệnh (CLI cho Kỹ Sư CNTT / Pipeline Tự Động)

Hệ thống hỗ trợ thực thi dòng lệnh không cần giao diện người dùng để tích hợp vào các pipeline xử lý dữ liệu lớn:

```bash
# 1. Chuẩn bị hồ sơ và tiền xử lý nhận diện PHI
python engine.py prepare "duong_dan/benh_an_goc.pdf" --job "HMU_JOBS/CASE_0001"

# 2. Duyệt tự động tất cả các trang theo đề xuất của nhận diện (Headless mode)
python -c "from engine import approve_all_pages; approve_all_pages('HMU_JOBS/CASE_0001')"

# 3. Xuất hồ sơ PDF đã khử định danh và tạo báo cáo QC
python engine.py export --job "HMU_JOBS/CASE_0001"
```

---

## 📋 Quy Trình Vận Hành 3 Bước

| Bước | Thao tác | Mô tả |
| :--- | :--- | :--- |
| **1. Mở hồ sơ** | Chọn PDF & Đánh dấu | Nhập mã hồ sơ (ví dụ `HMU_CASE_0001`), chọn PDF gốc. Công cụ tự động quét và phân tích vị trí các thực thể nhạy cảm. |
| **2. Duyệt trực tiếp** | Kiểm tra trên Canvas | - **Vùng màu đỏ**: Sẽ bị che xóa vĩnh viễn.<br>- **Vùng màu cam**: Ảnh/Ghi chú cần người dùng xác nhận.<br>- Có thể kéo thả thêm vùng xóa hoặc xóa bỏ vùng đánh dấu nhầm. |
| **3. Xuất hồ sơ** | Bàn giao kết quả | Bấm **"Xuất sau khi duyệt đủ trang"**. File PDF kết quả và báo cáo kiểm định chất lượng `QC.json` sẽ được lưu trong thư mục `exports/`. |

---

## 🔒 Cam Kết Bảo Mật Dữ Liệu Y Tế

- **Không lưu trữ PHI trong Git**: Toàn bộ file PDF bệnh án thật, ảnh trích xuất, thư mục `HMU_JOBS/` và các file `*_private*` đã được cấu hình loại trừ nghiêm ngặt trong `.gitignore`.
- **Bất biến & Truy xuất nguồn gốc**: Bản xuất được đánh số định danh theo thế hệ, kèm mã băm SHA-256 để đảm bảo tính toàn vẹn dữ liệu trong nghiên cứu y sinh học.
