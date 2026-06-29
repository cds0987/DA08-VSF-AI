# Taxonomy tài liệu nội bộ — Corpus của đề tài

> Định nghĩa **các loại tài liệu nội bộ công ty** mà hệ RAG này phục vụ. Mục đích: (1) khoanh vùng *corpus* để sinh/seed dữ liệu, (2) làm cơ sở cho **golden dataset** ([golden-dataset-criteria.md](golden-dataset-criteria.md)), (3) định hướng **phân loại mật + ACL theo phòng ban**. Đây là tài liệu **miền nghiệp vụ** (không phải kiến trúc) — kiến trúc xem [architecture.md](architecture.md), payload Qdrant xem [data-schema.md](data-schema.md).

## 1. Cách taxonomy gắn vào metadata hệ thống

Mỗi tài liệu khi ingest mang metadata (payload Qdrant — xem [data-schema.md](data-schema.md)):

| Trường | Giá trị | Vai trò |
|---|---|---|
| `file_type` | `pdf` · `docx` · `xlsx`/`xls` · `pptx` · `csv` · `txt` · `md` · `html` · ảnh (`png/jpg/…`) | Định dạng FILE rag-worker parse được (nguồn: `document-service/app/supported_formats.json`) |
| `classification` | `public` · `internal` · `secret` · `top_secret` (mặc định `internal`) | Mức mật → chặn/cho phép truy hồi |
| `allowed_departments` / `allowed_user_ids` | vd `["Engineering","Finance"]` | ACL: ai được search ra tài liệu (Query Service inject từ JWT/profile, **không tin LLM**) |

> **Khối nghiệp vụ ≠ phòng ban ≠ mức mật.** Một khối (vd Tài chính) có thể vừa có tài liệu `internal` (quy chế trợ cấp) vừa `secret` (bảng lương). Khi seed corpus, gán cả 3 trục cho mỗi tài liệu.

### Luật ACL theo `classification` (CHÍNH XÁC theo code — `document-service/.../documents/common.py`)

| `classification` | Ai đọc được | Ràng buộc bắt buộc khi tạo |
|---|---|---|
| `public` | **Mọi người** | — |
| `internal` (mặc định) | Chỉ tài khoản `account_type == "internal"` (nhân viên; khách/guest KHÔNG) | — |
| `secret` | Nhân viên **VÀ** `department` (lấy SỐNG từ hr-service) ∈ `allowed_departments` | `allowed_departments` **bắt buộc** (non-empty) |
| `top_secret` | Chỉ user có `id` ∈ `allowed_user_ids` | `allowed_user_ids` **bắt buộc** (non-empty) |

> `admin` đọc được tất cả. Với `secret`, department được lấy **sống từ hr-service** (không đọc từ JWT); hr-service lỗi → coi như không có quyền (**fail-closed**).
>
> ⚠️ **`department` là chuỗi tự do** (không phải enum cứng — fixtures hiện có "Engineering", "Fin", "Ops"…). Code so khớp **đúng chuỗi** (đã trim). → Team PHẢI **chuẩn hoá danh sách tên phòng ban** dùng thống nhất ở cả document `allowed_departments` lẫn employee profile (hr-service), nếu không secret-doc sẽ deny nhầm.

### Danh sách phòng ban chuẩn (đề xuất — team chốt giá trị cuối, PHẢI khớp employee profile)

| Khối nghiệp vụ | `department` (giá trị dùng trong `allowed_departments` + profile) |
|---|---|
| Hành chính & Vận hành | `Admin` |
| Nhân sự (HR) | `HR` |
| Tài chính – Kế toán | `Finance` |
| Kỹ thuật / IT | `Engineering` |
| Kinh doanh & Marketing | `Sales` |
| Kho vận / Nhà máy | `Operations` |

> Dùng **đúng các chuỗi này** (tiếng Anh, không dấu, khớp fixtures sẵn có như `Engineering`) cho cả 2 phía. Nếu công ty muốn tên tiếng Việt, đổi đồng loạt ở cả document `allowed_departments` lẫn hr-service profile.

**Gợi ý định dạng theo khối** (tận dụng đa định dạng để corpus phong phú):
- Nhiều **con số/bảng** (lương, định mức, BHXH) → **`xlsx`/`csv`**.
- **Quy trình/quy định văn xuôi** (nội quy, quy chế) → **`pdf`/`docx`/`md`**.
- **Trình bày/đào tạo** (onboarding, an toàn) → **`pptx`**.
- **Biên bản/scan** (diễn tập PCCC, biên bản vi phạm) → **`pdf` scan → OCR** (`OCR_MODEL`).

---

## 2. Khối Hành chính & Vận hành cơ sở vật chất

> Dễ nhân bản theo **số Tầng / số Phòng**. Mức mật thường `public`/`internal` (toàn công ty đọc); tài liệu nhạy cảm hơn → `secret` với `allowed_departments=["Admin"]`.

- **Phòng cháy chữa cháy (PCCC):** quy trình thoát hiểm; nội quy tiêu lệnh PCCC; quy định bảo dưỡng bình cứu hỏa; chế tài hút thuốc/thiết bị sinh nhiệt sai nơi; biên bản diễn tập PCCC định kỳ.
- **An ninh & Ra vào:** quy định quẹt thẻ/camera/vân tay; đăng ký khách ra vào; cấp phát & thu hồi thẻ nhân viên; chế tài làm mất thẻ / cho mượn thẻ.
- **Quản lý tài sản & Vệ sinh:** vệ sinh chung Pantry/WC; mượn–trả thiết bị phòng họp; tiết kiệm điện/nước, tắt thiết bị trước khi về; chế tài phá hoại/làm hỏng tài sản công ty.
- **Công tác & Di chuyển:** phê duyệt đi công tác trong/ngoài nước; định mức công tác phí (khách sạn, máy bay, ăn uống); tạm ứng & hoàn ứng chi phí công tác.

---

## 3. Khối Nhân sự (HR), chế độ & quy chế ứng xử

> Tập trung con người, quyền lợi, kỷ luật. Gắn được với **HR Service** (leave, employee profile). Nội quy chung → `internal`; biên bản kỷ luật/NDA → `secret` `allowed_departments=["HR"]`; hồ sơ cá nhân nhạy cảm → `top_secret` `allowed_user_ids=[...]`.

- **Thời gian làm việc & Nghỉ phép:** nội quy giờ giấc (check-in/out); xin nghỉ phép năm / ốm / không lương; làm việc từ xa (WFH); đăng ký OT + cách tính lương OT.
- **Tuyển dụng & Thử việc:** quy trình phỏng vấn & tiếp nhận; đánh giá kết thúc thử việc; thưởng giới thiệu nhân sự (Referral).
- **Kỷ luật & Xử phạt:** chế tài đi muộn/về sớm; bảo mật thông tin doanh nghiệp (NDA) + chế tài rò rỉ; quy trình xử lý kỷ luật lao động (khiển trách → kéo dài nâng lương → sa thải); biên bản vi phạm nội quy.
- **Nghỉ việc & Sa thải:** bàn giao tài sản khi nghỉ; thủ tục đơn phương chấm dứt HĐLĐ; xử lý nhân sự bị sa thải do vi phạm pháp luật/nghiêm trọng.

> Liên kết tính năng: nghỉ phép gắn trực tiếp với HR workflow (`leave_write` / `leave_approvals` / `leave_types`) — xem [api-spec.md](api-spec.md).

---

## 4. Khối Tài chính, Bảo hiểm & Phúc lợi (cơ chế tiền bạc)

> Nhiều **con số** → ưu tiên render `xlsx`/`csv`. Quy chế trợ cấp chung → `internal`; bảng lương → `secret` `allowed_departments=["Finance"]` (hoặc `top_secret` `allowed_user_ids=[...]` nếu chỉ cá nhân được xem).

- **Bảo hiểm:** quy trình đóng & hưởng BHXH / BHYT / BHTN; chế độ thai sản, ốm đau, tai nạn lao động; bảo hiểm lao động (BHLĐ) + trang bị bảo hộ theo bộ phận.
- **Lương & Trợ cấp:** quy chế chi trả lương & **bảo mật bảng lương**; trợ cấp (ăn trưa, xăng xe, điện thoại, trang phục); xét duyệt tăng lương định kỳ.
- **Khen thưởng & Phúc lợi:** thưởng hiệu suất (KPI), thưởng dự án, thưởng lễ/Tết; hiếu hỷ, sinh nhật, thăm ốm; du lịch công ty (Company Trip) + Team building.

---

## 5. Khối Phòng ban chuyên môn (IT, Kinh doanh, Kho vận, Marketing)

> Tạo **khác biệt nội dung sâu** giữa các file. Phần lớn `secret` theo từng phòng ban: IT → `allowed_departments=["Engineering"]`, Sales/Marketing → `["Sales"]`, Kho vận → `["Operations"]`. Tài liệu phổ biến (quy chuẩn chung) có thể để `internal`.

- **Kỹ thuật / IT:** an toàn an ninh mạng nội bộ; cấp phát laptop + phân quyền tài khoản; sao lưu (backup) dữ liệu hệ thống; quy chuẩn viết mã (Coding Convention) + quy trình deploy.
- **Kinh doanh (Sales) & Marketing:** quy chế tính hoa hồng (commission); quản lý & tiếp cận data khách hàng; phát ngôn mạng xã hội + bảo vệ thương hiệu.
- **Kho vận / Nhà máy:** nội quy an toàn vận hành máy móc; nhập – xuất – kiểm kê kho; xử lý hàng hóa hỏng hóc/lỗi kỹ thuật.

---

## 6. Dùng taxonomy này thế nào

- **Seed corpus / sinh tài liệu giả lập:** mỗi mục ở §2–§5 = 1 (hoặc nhiều) tài liệu; gán `file_type` theo gợi ý §1, `classification` + `allowed_departments` theo từng khối. Nhân bản theo Tầng/Phòng/Phòng ban để tăng số lượng.
- **Golden dataset:** mỗi tài liệu kèm ≥1 câu hỏi vàng (tiếng Việt/Anh) + keyword kỳ vọng — theo khuôn `rag-worker/eval/validation/manifest.json`. Tiêu chí: [golden-dataset-criteria.md](golden-dataset-criteria.md).
- **Kiểm thử ACL:** chọn vài cặp (tài liệu `secret` của phòng A) × (user phòng B) để xác nhận search **không** rò rỉ chéo phòng/mức mật.
