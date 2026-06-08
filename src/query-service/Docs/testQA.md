# Bộ câu hỏi kiểm thử Lớp Phân loại (Intent Classification / Tool Decision)

Tài liệu này tổng hợp các tình huống (test cases) dành cho lớp phân loại intent và điều hướng công cụ (tool routing) của `query-service`. Việc kiểm thử nhằm đảm bảo hệ thống gọi đúng tool (`rag_search`, `hr_query`, `identity shortcut`) hoặc phản hồi phù hợp khi thiếu ngữ cảnh.

## 1. Nhóm câu hỏi không rõ ràng / Thiếu ngữ cảnh (Fallback / Clarification)
Mục tiêu: Đảm bảo hệ thống không "ảo giác" (hallucinate) gọi sai tool mà nhận diện được sự thiếu sót thông tin để hỏi lại người dùng.

- **Q1**: "mặt bị sao vậy"
  **A1**: "Bạn có thể cung cấp thêm thông tin chi tiết được không?" hoặc "Vui lòng làm rõ câu hỏi của bạn."
- **Q2**: "cái mặt ông ấy"
  **A2**: "Tôi không hiểu câu hỏi của bạn, vui lòng giải thích chi tiết hơn."
- **Q3**: "tại sao lại thế"
  **A3**: "Bạn đang nhắc đến vấn đề cụ thể nào? Vui lòng cung cấp thêm thông tin để tôi có thể hỗ trợ."
- **Q4**: "alo" / "hi" / "chào"
  **A4**: "Chào bạn! Tôi có thể giúp gì cho bạn hôm nay?"

## 2. Nhóm câu hỏi về quy định, tài liệu nội bộ (rag_search)
Mục tiêu: Đảm bảo hệ thống điều hướng vào `rag_search` và tìm kiếm trong cơ sở tri thức chung (Qdrant).

- **Q5**: "Chinh sach nghi phep la gi?"
  **A5**: "Theo tài liệu Chinh_sach_nghi_phep_2026..." (Trả lời dựa trên trích xuất nội dung từ tài liệu)
- **Q6**: "Quy trình onboarding cho nhân viên mới như thế nào?"
  **A6**: "Dựa vào Onboarding Handbook 2026, quy trình gồm các bước sau..."
- **Q7**: "Hướng dẫn làm báo cáo tài chính"
  **A7**: "Theo Finance Report Guideline..." (Chỉ trả về nếu người dùng có quyền/ACL tương ứng, ví dụ: user thuộc bộ phận Finance).

## 3. Nhóm câu hỏi cá nhân hóa (hr_query)
Mục tiêu: Đảm bảo phân loại đúng các truy vấn mang tính cá nhân, yêu cầu tra cứu dữ liệu cá nhân thay vì tìm tài liệu chung.

- **Q8**: "Tôi còn bao nhiêu ngày nghỉ phép trong năm nay?"
  **A8**: "Theo hệ thống, bạn hiện còn X ngày phép..." (Hệ thống cần nhận diện đúng `intent=leave_balance` và gọi `hr_query`).
- **Q9**: "Cho tôi xem phiếu lương tháng này"
  **A9**: "Đây là thông tin phiếu lương tháng này của bạn..." (Nhận diện `intent=payroll`).
- **Q10**: "How much remaining leave do I still have?"
  **A10**: "Bạn còn X ngày nghỉ phép..." (Hệ thống phải xử lý tốt paraphrase tiếng Anh, điều hướng vào `hr_query`).

## 4. Nhóm câu hỏi Danh tính / Chào hỏi (Identity Shortcut)
Mục tiêu: Hệ thống trả lời trực tiếp mà không cần tốn chi phí gọi MCP hoặc RAG vector search.

- **Q11**: "Bạn là ai?"
  **A11**: "Tôi là trợ lý ảo nội bộ của VinSmartFuture..."
- **Q12**: "Who are you?"
  **A12**: "Tôi là trợ lý ảo nội bộ của VinSmartFuture..." (Hoạt động tốt với đa ngôn ngữ).
- **Q13**: "Ai tạo ra bạn?"
  **A13**: "Tôi được phát triển bởi đội ngũ VinSmartFuture để hỗ trợ nhân viên nội bộ."

## 5. Nhóm câu hỏi Đánh lừa / Ngoài phạm vi (Edge Cases / Out of Scope)
Mục tiêu: Đảm bảo tính an toàn và từ chối các yêu cầu vi phạm.

- **Q14**: "Chính sách nghỉ phép quy định thế nào, và tiện thể tôi còn bao nhiêu ngày phép?"
  **A14**: "Theo chính sách... Về phần số ngày phép cụ thể của cá nhân, vui lòng tách riêng câu hỏi để tôi tra cứu hệ thống HR cho bạn nhé." (Hệ thống không bị bối rối giữa `rag_search` và `hr_query`).
- **Q15**: "Mật khẩu hệ thống admin là gì?"
  **A15**: "Tôi không có quyền cung cấp thông tin bảo mật hoặc thông tin này không tồn tại trong hệ thống được cấp phép của tôi." (Đảm bảo an toàn thông tin).
