# Frontend Feature Checklist

Tài liệu này tổng hợp tất cả các tính năng cần có của Frontend dựa trên Solution Architecture (SA), Roadmap và các tài liệu kỹ thuật khác. Đây là bản đối chiếu để đảm bảo không thiếu tính năng trong quá trình phát triển.

## 1. Chat App (Persona: End User)

Ứng dụng dành cho nhân viên nội bộ tra cứu thông tin và thực hiện các nghiệp vụ HR cơ bản.

### 1.1 Xác thực & Phân quyền (Auth)
- [ ] **Đăng nhập Email/Password**: Sử dụng JWT token.
- [ ] **Microsoft SSO (Azure AD)**: Đăng nhập qua tài khoản Microsoft công ty.
- [ ] **Tự làm mới Token (Auto-refresh)**: Sử dụng Refresh Token để duy trì session.
- [ ] **Phân quyền End User**: Chỉ truy cập được các tính năng dành cho nhân viên.

### 1.2 Giao diện Chat (Core RAG)
- [ ] **Streaming Response (SSE)**: Chữ xuất hiện dần dần khi Bot trả lời (POST /query).
- [ ] **Hiển thị Markdown**: Hỗ trợ render Markdown trong câu trả lời của Bot.
- [ ] **Trích dẫn nguồn (Citations)**:
    - [ ] Hiển thị danh sách nguồn kèm theo mỗi câu trả lời (Tên file, trang, snippet).
    - [ ] Lưu trữ sources trong lịch sử hội thoại (reload vẫn hiện).
- [ ] **Hội thoại đa bước (Multi-turn)**: Hiểu ngữ cảnh các câu hỏi trước đó (Summary Buffer logic server-side).
- [ ] **Typing Indicator (Phase 2)**: Hiển thị trạng thái Bot đang xử lý/trả lời.
- [ ] **Feedback**: Nút Thumbs Up / Thumbs Down cho mỗi câu trả lời của Bot.

### 1.3 Trình xem tài liệu (Document Viewer)
- [ ] **Mở tài liệu từ Citation**: Click vào nguồn sẽ mở Viewer (sử dụng PDF.js).
- [ ] **Tải tài liệu an toàn**: Sử dụng Presigned GCS URL (GET /documents/{id}/file).
- [ ] **Nhảy đến vị trí trích dẫn**: Tự động scroll đến trang/đoạn văn bản được trích dẫn.
- [ ] **Highlight đoạn trích**: Làm nổi bật đoạn văn bản mà Bot đã sử dụng để trả lời.

### 1.4 Nghiệp vụ HR Cá nhân (Agentic Flow)
- [ ] **Tra cứu thông tin cá nhân**: Ngày nghỉ còn lại, trạng thái đơn nghỉ phép, thông tin lương (Phase 1 mock).
- [ ] **Tạo đơn nghỉ phép (Draft)**:
    - [ ] AI tự trích xuất thông tin (loại nghỉ, ngày, lý do) từ hội thoại.
    - [ ] Hiển thị bản nháp (Draft) để người dùng kiểm tra.
    - [ ] Nút xác nhận nộp đơn chính thức.
- [ ] **Duyệt đơn (Dành cho Manager)**:
    - [ ] Hiển thị danh sách đơn cần duyệt nếu người dùng là Manager của nhân viên khác.
    - [ ] Nút Approve / Reject kèm comment.

### 1.5 Trung tâm thông báo (Notification Center)
- [ ] **Thông báo Real-time (SSE)**: Nhận thông báo "Có tài liệu mới" hoặc "Đơn nghỉ phép đã được duyệt".
- [ ] **Notification Center UI**:
    - [ ] Badge hiển thị số thông báo chưa đọc.
    - [ ] Danh sách lịch sử thông báo (Dropdown).
    - [ ] Đánh dấu đã đọc (Mark as read).

### 1.6 Quản lý hội thoại
- [ ] **Danh sách hội thoại**: Xem lại các phiên chat cũ.
- [ ] **Quản lý**: Đổi tên, Xóa hội thoại.

---

## 2. Admin Console (Persona: Admin)

Ứng dụng dành cho quản trị viên hệ thống và bộ phận nhân sự.

### 2.1 Xác thực (Auth)
- [ ] **Đăng nhập Admin**: Chỉ cho phép tài khoản có Role Admin truy cập.
- [ ] **MFA (TOTP)**: Yêu cầu mã xác thực 2 lớp (Google Authenticator) khi đăng nhập Admin.

### 2.2 Quản lý tài liệu (Document Management)
- [ ] **Upload tài liệu**:
    - [ ] Hỗ trợ kéo thả (Drag-drop).
    - [ ] Hỗ trợ PDF, DOCX, TXT, XLSX, CSV, PPTX, MD (Max 50MB).
    - [ ] Lựa chọn Phân loại bảo mật (Public / Internal / Secret / Top Secret).
    - [ ] Chọn phòng ban/user được phép xem (đối với Secret/Top Secret).
- [ ] **Danh sách tài liệu**:
    - [ ] Hiển thị trạng thái Ingestion Real-time (Queued / Processing / Indexed / Failed).
    - [ ] Hiển thị số lượng Chunks đã cắt.
    - [ ] Hiển thị lỗi nếu Ingestion thất bại.
- [ ] **Thao tác**: Xóa tài liệu, Trigger re-index.

### 2.3 Quản lý người dùng
- [ ] **Danh sách nhân viên**: Xem danh sách user trong hệ thống.
- [ ] **Kiểm soát truy cập**: Khóa/Mở khóa (Deactivate/Reactivate) tài khoản.

### 2.4 Báo cáo & Phân tích (Analytics Dashboard)
- [ ] **Thống kê tổng quan**: Tổng số câu hỏi, tỉ lệ feedback tốt/xấu, top câu hỏi.
- [ ] **Biểu đồ xu hướng**: Lượng câu hỏi theo ngày/tuần.
- [ ] **Phát hiện lỗ hổng tri thức (Knowledge Gap)**:
    - [ ] Hiển thị danh sách câu hỏi mà Bot không trả lời được (Score < 0.7).
    - [ ] Giúp Admin biết cần bổ sung tài liệu gì.

---

## 3. Ràng buộc & Tiêu chuẩn kỹ thuật (FE Standards)

- [ ] **Nuxt 4 Layer Architecture**: Sử dụng `base` layer cho logic chung (Auth, API client).
- [ ] **SSE Implementation**:
    - [ ] Tắt buffering Nginx để streaming mượt.
    - [ ] Reconnect tự động nếu rớt mạng.
- [ ] **Security**:
    - [ ] Không hiển thị raw `user_id` trên UI.
    - [ ] Masking email (`h***@company.com`).
    - [ ] Chặn truy cập Admin app đối với Role User ngay tại route guard.
- [ ] **Performance**: First token latency < 2s.
- [ ] **Responsiveness**: Hoạt động tốt trên cả Desktop và Mobile (ưu tiên Desktop cho Admin).

---
*Tài liệu này là Living Document, sẽ được cập nhật khi có thay đổi về Architecture.*
