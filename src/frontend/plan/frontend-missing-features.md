# Frontend Missing Features Tracking

Tài liệu này liệt kê chi tiết các tính năng hiện đang thiếu hoặc chưa hoàn thiện trong mã nguồn Frontend (`admin`, `chat`, `base`) so với `frontend-feature-checklist.md`. Tài liệu này được thiết kế để AI có thể đọc, cập nhật và sử dụng làm cơ sở cho các nhiệm vụ lập trình tiếp theo.

## 1. Chat App (Persona: End User)

### 1.1 Xác thực (Auth)
- [ ] **Microsoft SSO (Azure AD)**: Hiện mới chỉ có Email/Password. Cần tích hợp thư viện `@azure/msal-browser` và logic login provider.

### 1.2 Giao diện Chat
- [x] **Markdown Rendering nâng cao**: Đã tích hợp `markdown-it`, `dompurify` và `@tailwindcss/typography`. Hỗ trợ table, code block và link.
- [x] **Đổi tên hội thoại (Rename)**: Đã thêm nút Edit trong `ChatHistory.vue`, hỗ trợ chỉnh sửa inline và gọi API `PATCH /conversations/{id}` qua `chat.ts` store.

### 1.3 Trình xem tài liệu (Document Viewer) - *Trọng tâm*
- [x] **Tích hợp PDF.js**: `SourcePanel.vue` hiện mới chỉ hiện text thô. Cần một Viewer thực thụ để hiển thị file PDF từ presigned URL.
- [x] **Deep Linking & Highlighting**:
    - [x] Tự động chuyển đến trang (page) dựa trên metadata của Citation.
    - [x] Tô màu (Highlight) đoạn văn bản mà Bot đã trích dẫn trong file PDF.

### 1.4 Nghiệp vụ HR (Agentic Flow) - *Chưa bắt đầu*
- [ ] **Tra cứu thông tin cá nhân**: Giao diện hiển thị ngày nghỉ còn lại, thông tin lương (gọi qua HR Service).
- [ ] **Quy trình đơn nghỉ phép**:
    - [ ] UI hiển thị component **Draft Leave Request** khi AI trích xuất xong thông tin từ chat.
    - [ ] Nút "Xác nhận gửi đơn" để gọi API chính thức.
- [ ] **Cổng duyệt đơn (Manager)**: Trang riêng hoặc tab riêng cho Manager để Approve/Reject các yêu cầu từ nhân viên cấp dưới.

---

## 2. Admin Console (Persona: Admin)

### 2.1 Xác thực
- [ ] **MFA (TOTP)**: Luồng đăng nhập Admin cần thêm bước nhập mã 6 số từ Google Authenticator/Microsoft Authenticator.

### 2.2 Quản lý tài liệu
- [ ] **Trigger Re-index**: Thêm nút trong danh sách tài liệu để gửi command re-index thủ công cho một file cụ thể mà không cần upload lại.

### 2.3 Báo cáo & Phân tích (Analytics)
- [ ] **Sử dụng UI Charts**: Tích hợp các component từ `@unovis/vue` (đã có trong `components/ui/chart`) vào `admin/app/pages/index.vue` để vẽ biểu đồ xu hướng câu hỏi.
- [ ] **Knowledge Gap UI**: Trang thống kê các câu hỏi có độ tự tin thấp (confidence score < 0.7) để HR/Admin biết cần bổ sung tài liệu nào.

---

## 3. Tiêu chuẩn kỹ thuật & Bảo mật (Cross-cutting)

### 3.1 Bảo mật (Security)
- [ ] **Email Masking**: Toàn bộ email hiện trên bảng User và Audit Logs cần được che (`a***@company.com`).
- [ ] **Masking User ID**: Hạn chế hiện raw UUID của user trên giao diện.

### 3.2 Hiệu suất (Performance)
- [ ] **Optimistic Updates**: Cập nhật UI ngay lập tức khi xóa hội thoại hoặc đánh dấu thông báo đã đọc trước khi API trả về kết quả.

---
*Ghi chú cho AI: Khi thực hiện xong một tính năng, hãy cập nhật trạng thái [x] vào file này và checklist gốc.*
