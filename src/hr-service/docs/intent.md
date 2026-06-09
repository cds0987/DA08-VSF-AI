# HR Service — Intent & Scope

> Tổng hợp từ `docs/` gốc: `architecture.md`, `api-spec.md`, `data-schema.md`, `contracts.md`.

---

## Mục đích

HR Service là **Container 6** trong hệ thống RAG Chatbot, chạy trên port `:8004`, **internal only** (không expose ra ngoài). Service sở hữu toàn bộ dữ liệu nhân sự (employee profile, phép, lương) và là **source of truth** cho các thông tin HR. Tool `hr_query` trong mcp-service gọi vào đây qua HTTP nội bộ.

---

## Vị trí trong kiến trúc

```
query-service
    │  chat request
    ▼
mcp-service  [tool: hr_query — HTTP proxy]
    │  POST /internal/hr/...
    │  Header: X-Internal-Token
    ▼
hr-service (:8004, internal only)
    │  WHERE user_id = :current_user_id
    ▼
hr_db (PostgreSQL, schema hr_svc)
```

**Nguyên tắc bất biến:**
- `user_id` luôn inject từ JWT bởi MCP client — tool không tin LLM tự điền.
- Query Service **không gọi trực tiếp** HR Service trên hot path chat — dùng projection NATS.
- `external` accounts không có HR personal data.

---

## Database — `hr_db`, schema `hr_svc`

| Bảng | Mô tả | Ghi chú |
|---|---|---|
| `hr_svc.departments` | Danh mục phòng ban (`code`, `name`) | |
| `hr_svc.employees` | Hồ sơ nhân viên: `user_id`, `department`, `job_title`, `manager_user_id`, `employment_status` | `user_id` là logical ref sang `user_db` |
| `hr_svc.leave_balance` | Phép năm/ốm còn lại per user (`annual_leave_total/used`, `sick_leave_total/used`) | |
| `hr_svc.leave_requests` | Đơn nghỉ phép: `leave_type`, `start/end_date`, `status`, `approver_user_id` | `approver = employees.manager_user_id` |
| `hr_svc.payroll_summary` | Bảng lương theo `period YYYY-MM`: `gross_salary`, `deductions`, `net_salary` | Schema tạo sẵn, **chưa expose** — chờ SA-3 |

Migration: Alembic, thư mục `migrations/` riêng trong service.

---

## Internal API

> Base URL local: `http://localhost:8004`
> Auth: `Authorization: Bearer <token>` hoặc `X-Internal-Token: <shared secret>`

### `GET /internal/hr/me`
Hồ sơ nhân viên hiện tại.
```
Response 200:
{
  "user_id": "uuid",
  "employee_code": "E001",
  "department": "Engineering",
  "job_title": "Engineering Manager",
  "manager_user_id": "uuid|null",
  "employment_status": "active"
}
```

### `POST /internal/hr/leave-requests`
Tạo đơn nghỉ. HR Service tự set `approver_user_id = employees.manager_user_id`.
```
Request body: { "leave_type": "annual", "start_date": "2026-06-20", "end_date": "2026-06-21", "reason": "Family" }
Response 201: { "id": "uuid", "status": "pending", "approver_user_id": "manager-user-id" }
```
> AI/Agent flow: Query Service phải hỏi/hiển thị draft và chờ user xác nhận trước khi gọi — không để LLM tự gọi.

### `GET /internal/hr/leave-requests/pending-approval`
Danh sách đơn nghỉ chờ sếp duyệt (lọc theo `approver_user_id = current_user_id`).

### `POST /internal/hr/leave-requests/{id}/approve`
```
Request body: { "comment": "OK" }
Response 200: { "id": "uuid", "status": "approved" }
```

### `POST /internal/hr/leave-requests/{id}/reject`
```
Request body: { "comment": "..." }
Response 200: { "id": "uuid", "status": "rejected" }
```

### `GET /health`
```
Response 200: { "status": "ok" }
```
Dùng bởi `HrQueryTool.verify()` trong mcp-service lúc startup (fail-closed).

---

## NATS Event (publish)

| Subject | Payload | Trigger |
|---|---|---|
| `hr.employee_profile.updated` | `{ event_id, event_version, occurred_at, user_id, account_type, department, employment_status }` | Khi employee profile, department hoặc employment_status thay đổi |

Query Service subscribe (JetStream durable) → upsert projection `query_svc.user_access_profile` để ACL pre-filter tài liệu theo `account_type + department + user_id`.

---

## MVP Scope — Giai đoạn 1

4 intent được `hr_query` tool hỗ trợ:

| Intent | Dữ liệu trả về |
|---|---|
| `leave_balance` | Số phép năm/ốm còn lại |
| `leave_requests` | Danh sách đơn nghỉ + trạng thái |
| `attendance` | Chấm công |
| `onboarding` | Thông tin onboarding |

`payroll` → tạo sẵn schema `hr_svc.payroll_summary`, **chưa expose** — chặn bởi SA-3 (nguồn role gate cho intent nhạy cảm).

---

## Cấu trúc thư mục (theo architecture.md)

```
src/hr-service/
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── employee.py              # EmployeeProfile, Department, HR records
│   │   └── repositories/
│   │       └── employee_repository.py
│   ├── application/
│   │   └── services/
│   │       └── employee_profile_service.py  # publish hr.employee_profile.updated
│   ├── infrastructure/
│   │   ├── db/
│   │   │   └── models.py                # hr_svc.* (hr_db)
│   │   └── nats_publisher.py
│   └── interfaces/
│       └── api/
│           └── routes.py                # internal HR endpoints
├── migrations/                          # Alembic
├── alembic.ini
├── docs/                                # ← đang ở đây
├── tests/
├── config.yaml
├── Dockerfile
└── requirements.txt
```

---

## SA Blockers còn mở

| # | Câu hỏi | Chặn |
|---|---|---|
| SA-3 | JWT claim nào để gate intent nhạy cảm (`payroll`, `performance`) | Mở rộng Giai đoạn 2 |
| SA-4 | Reserved-param contract `user_id`/`document_ids` trong `_inject_reserved` (phía query-service) | Tích hợp query-service ↔ mcp-service |

SA-1, SA-2 đã resolved — xem `src/mcp-service/docs/maintool/hr_query.md`.
