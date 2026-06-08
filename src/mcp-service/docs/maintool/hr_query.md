# Tool `hr_query`

> Trạng thái: 🟡 Đang bắt đầu làm ở mcp-service — **chưa có kế hoạch cụ thể**. Hiện chỉ có bản mock phía client trong query-service; server-side (tool + DB) chưa làm.

## Mục đích (Intend)

Cho phép nhân viên **hỏi đáp thông tin HR cá nhân của chính mình** ngay trong chatbot, thay vì phải vào portal HR hoặc nhắn phòng nhân sự. Ví dụ:

- "Tôi còn mấy ngày phép năm?"
- "Lương tháng này của tôi bao nhiêu, trừ những khoản gì?"
- "Đơn xin nghỉ tuần trước của tôi duyệt chưa?"

Khác với `rag_search` (tìm trong tài liệu chung công ty), `hr_query` đọc **dữ liệu có cấu trúc, riêng từng người** và luôn lọc theo người đang đăng nhập.

Trong thực tế, dữ liệu HR thường nằm trong HRIS/HRM (BambooHR, Workday, SAP SuccessFactors, Odoo, Zoho People...) hoặc DB nội bộ, và rộng hơn nhiều so với phép/lương. `hr_query` thiết kế để **bao trùm cả miền HR và sẵn sàng mở rộng**, làm dần theo từng nhóm intent.

### Miền dữ liệu HR đầy đủ (mục tiêu mở rộng)

| Nhóm intent | Dữ liệu | Độ nhạy cảm |
|---|---|---|
| `leave_balance` | Ngày phép còn lại (annual / sick) | Thấp |
| `leave_requests` | Lịch sử đơn xin nghỉ + trạng thái | Thấp |
| `payroll` | Lương kỳ gần nhất (gross / deductions / net), bậc lương | **Cao** |
| `benefits` | Bảo hiểm, phụ cấp, phúc lợi | **Cao** |
| `employee_profile` | Hồ sơ: tên, email, phòng ban, chức danh, manager | Trung bình* |
| `org_structure` | Team, reporting line, org chart | Trung bình* |
| `attendance` | Chấm công, ngày công, đi muộn | Trung bình |
| `onboarding` | Trạng thái nhân viên mới, checklist | Thấp |
| `performance` | Review, KPI, đánh giá | **Cao** |
| `recruitment` | (nếu user là hiring manager) ứng viên, vị trí, vòng PV | **Cao** |

\* `employee_profile` / `org_structure` có thể trùng với dữ liệu user-service đã quản (database-per-service). Trước khi làm 2 nhóm này phải chốt: lấy từ user-service (qua event/JWT) hay HRIS — **tránh hai service cùng sở hữu một loại data**.

> Mục tiêu: **làm trọn cả miền HR trên** (không tách giai đoạn), hạ tầng chung để thêm intent không phải sửa khung (xem Plan).

## Boundary

**Nguyên tắc input tối thiểu (an toàn):** mcp-service **chỉ nhận `user_id`** (do client inject từ JWT) + `intent`. Tool **tự filter** ra đúng phần dữ liệu cần thiết của riêng user đó — client không cần (và không được) truyền thêm tham số định danh nào khác. Càng ít input từ ngoài, càng ít bề mặt để vượt quyền.

**Tool sẽ LÀM:**
- Nhận `user_id` + `intent`, tự query + filter dữ liệu HR của đúng user đó, trả `HrQueryResult` (typed theo intent + `summary` tự nhiên cho LLM dùng thẳng).

**Tool KHÔNG làm:**
- **Không tin `user_id` do LLM điền.** `user_id` do query-service (MCP client) inject từ JWT của người đang đăng nhập.
- Không nhận tham số chọn-người-khác (vd `target_user_id`) — không có đường nào hỏi dữ liệu người khác.
- Không cho xem dữ liệu người khác — mọi query bắt buộc `WHERE user_id = :current_user`.
- Không sửa/ghi dữ liệu HR (chỉ đọc, ít nhất ở giai đoạn đầu).
- Không gọi sang hệ thống HR thật ở MVP — dùng dữ liệu mock trong DB của mcp-service.

**Ranh giới dữ liệu:** data HR thuộc về mcp-service (database-per-service). Query Service gọi qua MCP, không đụng thẳng DB này.

**Lưu ý dữ liệu nhạy cảm:** các nhóm `payroll` / `benefits` / `performance` / `recruitment` rất nhạy cảm — khi mở rộng tới chúng cần soát lại quyền (vd `recruitment` chỉ cho hiring manager) và cân nhắc trace/audit; không để lộ qua `summary`.

## Plan

> Chưa chốt chi tiết — đây là hướng dự kiến, cần SA xác nhận trước khi code.
> Triết lý: hạ tầng (tool + filter theo `user_id`) thiết kế chung; **làm trọn cả miền HR**, không tách giai đoạn.

- [ ] Tạo schema HR trong `mcp_db` cho **toàn bộ nhóm intent**: phép (`leave_balance`, `leave_requests`), `payroll`, `benefits`, `attendance`, `onboarding`, `performance`, `recruitment`, và (sau khi chốt nguồn) `employee_profile` / `org_structure` (xem [docs/data-schema.md](../../../../docs/data-schema.md)).
- [ ] Migration + seed dữ liệu mẫu cho mọi bảng, khớp với `user_id` của user-service.
- [ ] Định nghĩa output contract `HrQueryResult` + DTO cho mọi intent — đồng bộ với [docs/contracts.md](../../../../docs/contracts.md).
- [ ] Repository đọc DB HR, **luôn tự filter `user_id`** (không nhận tham số định danh khác).
- [ ] `employee_profile` / `org_structure`: chốt nguồn (user-service vs HRIS) trước khi tạo bảng — tránh trùng sở hữu data.
- [ ] Nhóm nhạy cảm cao (`payroll`, `benefits`, `performance`, `recruitment`): soát quyền role-based (vd `recruitment` chỉ hiring manager) + audit/trace; không lộ qua `summary`.
- [ ] Đăng ký tool `hr_query(user_id, intent)` qua MCP (cạnh `rag_search`).
- [ ] Thay bản mock ở query-service bằng tool thật; cập nhật `list_tools()` để lộ `hr_query`.
- [ ] Test: user A không xem được data user B; intent không hợp lệ → lỗi rõ ràng.
- [ ] (Tương lai) thay DB mock bằng nối HRIS thật (BambooHR/Workday/Odoo... qua API hoặc sync).

## Implement

- **Chưa có gì ở mcp-service.** Tool `hr_query` chưa đăng ký; schema `hr_mock` chưa tồn tại; chưa có model/migration/repository.
- Hiện chỉ có **mock in-memory phía client** trong query-service (dict `MOCK_HR_DATA` + fake MCP client) để chạy thử luồng router → orchestration; không phải database.
- Real MCP client của query-service đã có sẵn lời gọi `hr_query(user_id, intent)` nhưng sẽ lỗi nếu route vào, vì server chưa expose tool này.

> Bước kế tiếp khi có kế hoạch cụ thể: chốt scope MVP (làm trước `leave_balance`?) → tạo DB + tool tối thiểu → nối query-service từ mock sang thật.
