# HR Service — Intent & Scope

> Tổng hợp từ `docs/` gốc: `architecture.md`, `api-spec.md`, `data-schema.md`, `contracts.md`.

---

## Mục đích

HR Service là **Container 6** trong hệ thống RAG Chatbot, chạy trên port `:8004`, **internal only** (không expose ra ngoài, không route public qua Nginx). Service sở hữu toàn bộ dữ liệu nhân sự (employee profile, phép, lương, chấm công, onboarding, phúc lợi, đánh giá) và là **source of truth** cho thông tin HR.

## Hai nhánh tách bạch: READ vs WRITE

HR Service phục vụ 2 đường khác hẳn nhau — đừng trộn:

| | **READ path** (đã chạy) | **WRITE / event-propagation path** (thiết kế, chưa wire) |
|---|---|---|
| Vào bằng | mcp-service tool `hr_query` → `POST /hr/query` (HTTP, đồng bộ) | Ghi dữ liệu HR (tạo/duyệt đơn nghỉ, đổi profile) → publish **NATS event** |
| Bản chất | Chỉ đọc, `WHERE user_id`, trả thẳng cho LLM cite | Ghi DB rồi **lan truyền** sang read-model của service khác (eventual consistency) |
| Trạng thái code | ✅ `routes.py` + `PostgresHrRepository` | ⏳ Scaffold (`NatsPublisher` stub + `EmployeeProfileService`), **chưa nối**; endpoint write cũng chưa có |

→ **NATS KHÔNG nằm trên hot path chat / không liên quan `hr_query` read.** Nó chỉ dùng cho việc **write rồi đồng bộ DB của service khác** (ví dụ: cập nhật projection `query_svc.user_access_profile` để ACL, hoặc lan truyền thay đổi employee profile sang `user_db`).

---

## Vị trí trong kiến trúc

```
READ (đồng bộ, đã chạy):
  query-service ──chat──► mcp-service [tool hr_query] ──POST /hr/query (X-Internal-Token)──► hr-service :8004 ──WHERE user_id──► hr_db (hr_svc)

WRITE / propagation (bất đồng bộ, chưa wire):
  hr-service (ghi đơn nghỉ / đổi profile) ──publish NATS hr.*──► JetStream ──► Query Service / User Service cập nhật read-model
```

**Nguyên tắc bất biến:**
- `user_id` luôn inject từ JWT bởi MCP client — tool không tin LLM tự điền.
- Query Service **không gọi trực tiếp** HR Service trên hot path chat cho dữ liệu ACL — dùng projection cập nhật qua NATS (write path).
- `external` accounts không có HR personal data.

---

## Database — `hr_db`, schema `hr_svc`

| Bảng | Mô tả | Migration |
|---|---|---|
| `hr_svc.departments` | Danh mục phòng ban (`code`, `name`) | 0001 |
| `hr_svc.employees` | Hồ sơ NV: `user_id`, `department`, `job_title`, `manager_user_id`, `employment_status` | 0001 |
| `hr_svc.leave_balance` | Phép năm/ốm còn lại per user | 0001 |
| `hr_svc.leave_requests` | Đơn nghỉ: `leave_type`, `start/end_date`, `status`, `approver_user_id` (= `employees.manager_user_id`) | 0001 |
| `hr_svc.attendance` | Chấm công theo kỳ `YYYY-MM` (`work_days`, `late_count`, `absent_count`) | 0001 |
| `hr_svc.onboarding` | Checklist onboarding (`status`, `checklist` JSONB) | 0001 |
| `hr_svc.payroll_summary` | Bảng lương theo `period`: `gross/deductions/net` | 0001 |
| `hr_svc.benefits` | Phúc lợi (`items` JSONB) | 0002 |
| `hr_svc.performance_reviews` | Đánh giá hiệu suất theo `period` (`rating`, `kpi`) | 0002 |

Migration: Alembic, thư mục `migrations/` riêng (`0001_create_hr_schema`, `0002_add_benefits_performance`).

---

## Internal API — endpoint THẬT (theo `app/api/routes.py`)

> Base URL nội bộ: `http://hr-service:8004`. Auth: `X-Internal-Token: <shared secret>`.
> Hiện chỉ có **2 endpoint** (READ path). Leave-request CRUD (WRITE path) chưa implement — xem mục dưới.

### `POST /hr/query` — READ, self-access
```
Request:
  Header: X-Internal-Token: <token>
  Body:   { "user_id": "uuid", "intent": "<một trong 7 intent>" }

Response 200: { "intent": "...", "data": { ... }, "summary": "..." }   # data là dict tùy intent
Lỗi: 422 intent sai Literal | 404 user không có data | 401 thiếu/sai token
```
Mọi query lọc cứng `WHERE user_id`. Intent nhạy cảm (`payroll`/`benefits`/`performance`) = self-access (data của chính user) → **không cần role-gate**; hr-service ghi audit log mỗi lần truy cập (mask user_id, không log số liệu) — `SENSITIVE_INTENTS` ở `routes.py`.

### `GET /health`
```
Response 200: { "status": "ok" }
```
Dùng bởi `HrQueryTool.verify()` trong mcp-service lúc startup (best-effort — hr down KHÔNG sập mcp).

### 🟡 WRITE path — Leave request (THIẾT KẾ ĐÃ CHỐT, chưa implement)

> Endpoint **chưa có** trong `routes.py`. Đây là thiết kế đã thống nhất, chờ implement (cần SA approve contract).
> Đồng bộ với [`docs/api-spec.md`](../../../docs/api-spec.md) + [`docs/contracts.md`](../../../docs/contracts.md).
> 🛠️ **Hướng dẫn implement cẩn thận (không phá codebase):** [`leave-request-write-implementation.md`](./leave-request-write-implementation.md).

**Mô hình tổng thể (đã chốt):**
```
TẠO (chat — self):
  query ──MCP tool create_leave_request──► mcp ──POST /hr/leave-requests──► hr-service
                                                                              │ ghi pending + approver + publish event
DUYỆT (HTTP — sếp, async "signal"):
  (caller sếp) ──POST /hr/leave-requests/{id}/approve|reject (X-Internal-Token)──► hr-service
                                                                              │ update + trừ balance + publish event
BÁO USER:  hr-service publish NATS ──► query-service (Notification Center) ──SSE──► sếp / nhân viên
```

**hr-service chịu trách nhiệm — 3 endpoint + publish event (KHÔNG đẩy thẳng tới user):**

1. `POST /hr/leave-requests` — mcp gọi (tool `create_leave_request`).
   - `days_count = end - start + 1` (ngày lịch, **server tính**, không tin LLM).
   - `approver_user_id = employees.manager_user_id` **OR** `HR_DEFAULT_APPROVER` (config) nếu không có sếp.
   - INSERT `status='pending'` → commit → publish `hr.leave_request.created`.
2. `GET /hr/leave-requests/pending-approval` — đọc đơn chờ duyệt (`WHERE approver_user_id = :current AND status='pending'`). PULL.
3. `POST /hr/leave-requests/{id}/approve|reject` — HTTP `X-Internal-Token` (**không** phải MCP tool).
   - Guard: `đơn.approver_user_id == approver truyền vào AND status='pending'` — **KHÔNG dùng app-role** (`admin|user`).
   - approve: **TRANSACTION** { `status='approved'`, `approved_at`; trừ `leave_balance` (`annual→annual_used`, `sick→sick_used`, `personal→không trừ`); thiếu phép → 409 giữ `pending` } → publish `hr.leave_request.approved`.
   - reject: { `status='rejected'`, `rejected_at`, `rejected_reason` } → publish `hr.leave_request.rejected`.

**State machine:** `pending → approved | rejected`. (cancel hoãn.)

---

## NATS Event — WRITE / propagation path

> Nhánh **đồng bộ sau khi WRITE**, tách hẳn `hr_query` read. hr-service **chỉ publish sau commit**; báo tới user là việc của query-service (Notification Center + SSE). `event_id` để consumer idempotent.

| Subject | Payload | Trigger | Consumer đẩy SSE cho |
|---|---|---|---|
| `hr.employee_profile.updated` | `{ event_id, event_version, occurred_at, user_id, account_type, department, employment_status }` | employee profile/department/employment_status đổi | Query Service → upsert `user_access_profile` (ACL) |
| `hr.leave_request.created` | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, leave_type, start_date, end_date, days_count, status }` | sau khi tạo đơn `pending` | **sếp** (`approver_user_id`): "có đơn cần duyệt" |
| `hr.leave_request.approved` | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, status }` | sau approve | **nhân viên** (`requester_user_id`) |
| `hr.leave_request.rejected` | `{ ... , rejected_reason }` | sau reject | **nhân viên** |

**Trạng thái code:** scaffold, **chưa hoạt động** — cần implement khi làm WRITE:
- `app/infrastructure/nats_publisher.py` — `NatsPublisher.publish()` còn **no-op**; `requirements.txt` chưa có `nats-py`.
- `app/application/services/employee_profile_service.py` — chưa được instantiate/wire.
- `docker-compose` đã `depends_on: nats` (hạ tầng sẵn), nhưng app chưa mở connection.

**Việc phải làm (role hr-service):** thêm `nats-py`, implement `NatsPublisher` thật (connect JetStream), publish 3 event leave request + event profile sau commit.
**Ngoài role (query-service):** subscriber nhận event → route SSE theo `approver_user_id`/`requester_user_id` (giống `notify_subscriber` cho `doc_new`). Bàn giao qua contract event trên.

---

## Scope — 7 intent `hr_query` đã expose (READ)

| Intent | Dữ liệu trả về | Nhạy cảm (audit) |
|---|---|---|
| `leave_balance` | Số phép năm/ốm còn lại | |
| `leave_requests` | Danh sách đơn nghỉ + trạng thái | |
| `attendance` | Chấm công kỳ hiện tại | |
| `onboarding` | Checklist + tiến độ onboarding | |
| `payroll` | Bảng lương theo kỳ | ✅ |
| `benefits` | Phúc lợi | ✅ |
| `performance` | Đánh giá hiệu suất | ✅ |

> `recruitment` **hoãn** (cross-user, không hợp self-access). `employee_profile`/`org_structure` lấy từ JWT claim (user-service sở hữu), không tạo bảng.
> Tập 7 intent này được mcp-service publish qua interface MCP (`list_tools()`/schema); client discover qua interface — hr/mcp không quản cách client nội bộ dùng bao nhiêu intent.

---

## Cấu trúc thư mục (theo code thật)

```
src/hr-service/
├── app/
│   ├── api/
│   │   ├── auth.py                        # require_internal_token (X-Internal-Token)
│   │   └── routes.py                      # POST /hr/query + GET /health
│   ├── application/
│   │   └── services/
│   │       └── employee_profile_service.py  # WRITE path scaffold: publish hr.employee_profile.updated (chưa wire)
│   ├── core/
│   │   └── config.py                      # HrSettings (database_url, internal_token)
│   ├── domain/
│   │   ├── entities/dtos.py               # DTO HR (9 loại)
│   │   └── repositories/hr_repository.py  # ABC, 7 getter + ping/aclose
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py                  # hr_svc.* (9 bảng)
│   │   │   └── postgres_hr_repository.py  # READ impl
│   │   └── nats_publisher.py              # WRITE path scaffold: NatsPublisher stub (no-op)
│   └── main.py                            # FastAPI app
├── migrations/                            # Alembic (0001, 0002)
├── scripts/e2e_hr_integration.py          # e2e mcp→hr→Postgres (real Docker)
├── docs/                                  # ← đang ở đây
├── tests/
├── config.yaml
├── Dockerfile
└── requirements.txt
```

---

## SA Blockers

| # | Câu hỏi | Trạng thái |
|---|---|---|
| SA-1 | DB instance cho hr_db | ✅ Resolved |
| SA-2 | Nguồn employee_profile | ✅ Resolved |
| SA-3 | Role gate cho intent nhạy cảm (`payroll`/`benefits`/`performance`) | ✅ Resolved — chốt **self-access** (data của chính user, không cần role-gate) + audit log mỗi lần truy cập |
| SA-4 | Reserved-param contract `user_id`/`document_ids` (`_inject_reserved` phía query-service) | Đang tích hợp query-service ↔ mcp-service |

Chi tiết SA-1/SA-2: `src/mcp-service/docs/maintool/hr_query.md`.
