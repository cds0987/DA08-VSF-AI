# Tool `hr_query`

> Trạng thái: 🟢 Đã chạy ở mcp-service qua HTTP proxy sang hr-service với 4 intent MVP `leave_balance` / `leave_requests` / `attendance` / `onboarding`. Các phần chưa hoàn thiện xem ở [`docs/gap/gap2.md`](../gap/gap2.md).

> ⚠️ **Implement guide đầy đủ nằm ở [`docs/refactor/tool-registry.md` — Phần B (B1–B8)](../refactor/tool-registry.md#5-phần-b--hr_query-đầy-đủ-mcp-service).**
> File này mô tả scope + boundary. Trước khi code, đọc tool-registry.md mục 1 (file phải nắm), mục 2 (invariants không được phá), và mục 6 (thứ tự PR).
> **hr_query là PR 5** — chỉ bắt đầu sau khi PR 1–4 (khung tool pluggable + discovery query-service) đã xanh và 4 SA blockers bên dưới đã được chốt.

---

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

---

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

---

## ⚠️ SA Blockers — phải chốt trước khi code phần liên quan

Bốn câu hỏi dưới đây đang **chặn code**. Ghi quyết định vào [`docs/contracts.md`](../../../../docs/contracts.md) và [`docs/data-schema.md`](../../../../docs/data-schema.md) trước khi mở PR tương ứng.

| # | Câu hỏi | Trạng thái | Chặn bước nào |
|---|---|---|---|
| SA-1 | **DB instance cho `mcp_db`** — chung Postgres (schema riêng) hay DB tách? | ✅ **RESOLVED** — cùng Cloud SQL instance, schema riêng `hr_mock` trong `mcp_db`. | B1 (migration) |
| SA-2 | **Nguồn `employee_profile` / `org_structure`** — user-service hay HRIS? | ✅ **RESOLVED** — lấy từ JWT claim, **không tạo bảng** trong mcp_db. Tránh trùng ownership. | B2 (schema) |
| SA-3 | **Nguồn role cho intent nhạy cảm** — JWT claim nào query-service truyền để gate `payroll` / `recruitment`. | ⚠️ **OPEN** — chặn Giai đoạn 2 (`payroll`, `benefits`, `performance`). | B6 (role-gate) |
| SA-4 | **Reserved-param contract** — `user_id` / `document_ids` / `top_k` tiêm thế nào trong `_inject_reserved`. | ⚠️ **OPEN** — chặn query-service Phần D4. Ghi vào `docs/contracts.md` khi chốt. | D4 (guardrail) |

---

## Output Contract — `HrQueryResult`

Mọi response của `hr_query` theo envelope sau. `summary` là text tự nhiên, LLM dùng thẳng để trả lời user; không nhúng số lương/dữ liệu nhạy cảm cao vào `summary`.

```json
{
  "intent": "<tên intent>",
  "data": { },
  "summary": "<câu mô tả ngắn gọn bằng tiếng Việt>"
}
```

Shape của `data` theo từng intent (placeholder — SA chốt xong bổ sung vào [`docs/contracts.md`](../../../../docs/contracts.md)):

| Intent | `data` shape (dự kiến) |
|---|---|
| `leave_balance` | `{ annual_remaining: int, sick_remaining: int }` |
| `leave_requests` | `{ requests: [{ id, type, from_date, to_date, status }] }` |
| `payroll` | `{ period: str, gross: float, deductions: [...], net: float }` — **Cao** |
| `attendance` | `{ work_days: int, late_count: int, absent_count: int }` |
| `onboarding` | `{ status: str, checklist: [{ task, done }] }` |
| `performance` | `{ period: str, rating: str, kpi: [...] }` — **Cao** |
| `benefits` | `{ items: [{ name, value }] }` — **Cao** |
| `recruitment` | `{ positions: [...] }` — **Cao**, chỉ hiring manager |

Intent độ nhạy **Cao**: không để số/chi tiết lộ ra `summary`; chỉ xác nhận đã gửi data.

---

## Scope MVP

**Làm theo 2 giai đoạn, không làm toàn bộ cùng lúc:**

**Giai đoạn 1 — MVP (PR 5):** chỉ `leave_balance` + `leave_requests` + `attendance` + `onboarding`.
- Không cần role-gate (độ nhạy Thấp/Trung bình).
- `Literal` trong tool signature chỉ liệt kê 4 intent này.
- Intent ngoài danh sách → `NotImplementedError` với message rõ ràng (không lộ data).

**Giai đoạn 2 — mở rộng (PR sau):** `payroll`, `benefits`, `performance`, `recruitment`.
- Chờ SA-3 (nguồn role) chốt xong.
- Cần audit/trace log mỗi lần query intent Cao.
- `employee_profile` / `org_structure`: chờ SA-2 chốt xong.

---

## Plan

> Triết lý: hạ tầng (tool + filter theo `user_id`) thiết kế chung; thêm intent sau không sửa khung (OCP).
> Thứ tự chi tiết xem [tool-registry.md mục 6](../refactor/tool-registry.md#6-thứ-tự-pr--checkpoint--rollback).

- [ ] **[SA-1]** Chốt DB instance → tạo schema HR trong `mcp_db` cho intent MVP: `leave_balance`, `leave_requests`, `attendance`, `onboarding`.
- [ ] Migration `0001_create_hr_schema` + seed dữ liệu mẫu, khớp `user_id` của user-service.
- [ ] **[SA-4]** Định nghĩa output contract `HrQueryResult` + DTO cho intent MVP — đồng bộ với `docs/contracts.md` + khớp DTO query-service (`tool_decision.py` / `mcp_client.py`).
- [ ] Repository đọc DB HR, **luôn tự filter `user_id`** (không nhận tham số định danh khác). Map `intent → handler` nội bộ.
- [ ] **[SA-2]** `employee_profile` / `org_structure`: chốt nguồn trước khi tạo bảng — tách sub-task.
- [ ] **[SA-3]** Intent Cao (`payroll`, `benefits`, `performance`, `recruitment`): chờ nguồn role chốt + audit/trace; không lộ qua `summary`.
- [ ] Đăng ký tool `hr_query(user_id, intent)` qua MCP (cạnh `rag_search`); bật `app/tools/__init__.py` + `TOOL_HR_QUERY_ENABLED=1`.
- [ ] Thay bản mock ở query-service bằng tool thật; cập nhật `list_tools()` để lộ `hr_query`.
- [ ] Test: user A không xem được data user B; intent ngoài MVP Literal → lỗi rõ ràng; contract `HrQueryResult` ổn định.
- [ ] (Tương lai) thay DB mock bằng nối HRIS thật (BambooHR/Workday/Odoo... qua API hoặc sync).

---

## Implement

- **Đã có tool ở mcp-service.** `hr_query` đã đăng ký và hoạt động như HTTP proxy sang hr-service cho 4 intent MVP. Các gap còn lại về validation intent, soft-fail 404, logging/audit, role-gate và mở rộng intent được theo dõi tại [`docs/gap/gap2.md`](../gap/gap2.md).
- Hiện chỉ có **mock in-memory phía client** trong query-service (dict `MOCK_HR_DATA` + fake MCP client) để chạy thử luồng router → orchestration; không phải database.
- Real MCP client của query-service đã có sẵn lời gọi `hr_query(user_id, intent)` nhưng sẽ lỗi nếu route vào, vì server chưa expose tool này.

> **Bước tiếp theo:** chốt SA-1 + SA-4 → mở PR 5 theo [tool-registry.md Phần B](../refactor/tool-registry.md#5-phần-b--hr_query-đầy-đủ-mcp-service).
