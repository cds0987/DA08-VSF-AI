---
service: hr-service
path: src/hr-service
last-verified: 88d8662b (2026-06-26)
code-refs:
  - src/hr-service/app/main.py
  - src/hr-service/app/api/routes.py
  - src/hr-service/app/api/hr_admin.py
  - src/hr-service/app/api/auth.py
  - src/hr-service/app/core/config.py
  - src/hr-service/config.yaml
  - src/hr-service/app/infrastructure/db/models.py
  - src/hr-service/app/domain/repositories/leave_write_repository.py
  - src/hr-service/app/domain/leave_policy.py
  - src/hr-service/app/infrastructure/user_events_subscriber.py
  - src/hr-service/app/infrastructure/nats_publisher.py
---
# HR Service

FastAPI service (`title="hr-service"`, default port 8004) quản lý dữ liệu nhân sự:
hồ sơ nhân viên, phép/đơn nghỉ, chấm công, onboarding, lương, phúc lợi, hiệu suất.

## Trách nhiệm
- Read API HR theo từng `intent` + endpoint gộp hồ sơ (`/hr/profile`) cho LLM/agent (qua query-service/MCP).
- Luồng WRITE đơn nghỉ phép đầy đủ (tạo/sửa/hủy/duyệt/từ chối) — tách interface khỏi read.
- Admin API quản trị nhân viên (JWT role=admin).
- Đồng bộ hồ sơ từ vòng đời user (subscribe NATS `user.*`), publish event HR ra NATS.
- Taxonomy loại nghỉ (Leave Type Registry, 4 rổ luật LĐ VN) là nguồn sự thật cho FE/agent.

## API / giao diện
Router chính (`router`) bảo vệ bằng header `X-Internal-Token` (`require_internal_token`).
`public_router` không yêu cầu token. `admin_router` prefix `/hr/admin` yêu cầu JWT admin.

Read / query (X-Internal-Token):
- `POST /hr/query` — body `{user_id, intent}`; intent ∈ {leave_balance, leave_requests, attendance, onboarding, payroll, benefits, performance}. Trả `{intent, data, summary}`. payroll/benefits/performance = SENSITIVE -> ghi audit (user_id hashed). Develop: thiếu data tự sinh mock; leave_balance auto-provision.
- `POST /hr/profile` — body `{user_id}`; gộp cả 7 section + `employee` (nhân thân, bỏ phone/dob), `manager_name`/`leave_approver`. Audit 1 lần intent=profile.

Leave write (X-Internal-Token):
- `POST /hr/leave-requests` (201) — tạo đơn pending. Validate ngày (YYYY-MM-DD, start≤end, không quá khứ theo Asia/Ho_Chi_Minh) + leave_type theo registry (per_event_cap). `confirm_overlap` bỏ qua cảnh báo chồng ngày.
- `PATCH /hr/leave-requests/{id}` — sửa (pending=updated tại chỗ; approved=replaced: hủy+hoàn phép+tạo mới).
- `POST /hr/leave-requests/{id}/cancel` — hủy (chủ đơn).
- `GET /hr/leave-requests/pending-approval?approver_user_id=` — hàng đợi duyệt.
- `GET /hr/leave-requests/mine?user_id=` — mọi đơn của chủ đơn.
- `GET /hr/leave-requests/{id}?user_id=` — 1 đơn (scope chủ đơn).
- `POST /hr/leave-requests/{id}/approve` | `/reject` — body `{approver_user_id, reason}`.
- `POST /hr/departments/{old_name}/rename` — đổi tên phòng ban (cascade) + publish `hr.department.renamed`.

Public (không token):
- `GET /hr/leave-types` — registry taxonomy.
- `GET /hr/departments` — danh sách tên phòng ban distinct.
- `GET /hr/employees/departments` — `[{user_id, department}]` cho admin FE.
- `GET /health` (trên `router`, vẫn cần token).

Admin (`/hr/admin`, JWT role=admin):
- `GET /employees` (filter department/status, limit/offset), `GET /employees/{id}`, `GET /employees/{id}/details`, `PATCH /employees/{id}`, `DELETE /employees/{id}` (204).

## Luồng nội bộ
- Tạo đơn nghỉ (draft -> confirm -> ghi DB): FE/agent dựng draft -> `POST /hr/leave-requests`.
  Resolve approver = `manager_user_id` || `default_approver` (rỗng -> 422 ApproverNotConfigured).
  Trùng TOÀN BỘ (loại+ngày+lý do, đơn active) -> 409 `leave_duplicate` (chặn).
  Chồng ngày khác nội dung + `confirm_overlap=False` -> 409 `leave_overlap` (cảnh báo, gửi lại với confirm_overlap=True). `idempotency_key` chống double-submit. days_count server tính.
- Duyệt: `approve` trừ quỹ phép (`deduct_pool` annual/sick) trong transaction (thiếu -> 409 InsufficientLeaveBalance, đơn giữ pending). Sai approver -> 403; đơn không pending -> 409.
- Mỗi write commit xong publish event NATS best-effort (created/updated/cancelled/approved/rejected); lỗi publish không làm sập write.
- Đồng bộ user: subscribe `user.created/updated/deactivated/deleted` (JetStream stream USER_EVENTS, durable HR_USER_LIFECYCLE). Upsert employee, ensure leave_balance (default từ config); `user.deleted` -> hard delete; publish `hr.employee_profile.updated`. Idempotent, lỗi -> nak/redeliver.

## Config / ENV
`config.yaml` (env override, syntax `${VAR:-default}`), load qua `HrSettings`:
- HR_HOST(0.0.0.0), HR_PORT(8004), LOG_LEVEL(INFO), APP_STAGE(production; `develop`=bật mock read-path)
- HR_DATABASE_URL, HR_INTERNAL_TOKEN, JWT_SECRET_KEY (BẮT BUỘC — thiếu raise ValueError)
- HR_AUTO_PROVISION_LEAVE_BALANCE(true), HR_DEFAULT_ANNUAL_LEAVE(12), HR_DEFAULT_SICK_LEAVE(10)
- NATS_URL(nats://nats:4222), NATS_JETSTREAM_ENABLED(true), HR_USER_EVENTS_ENABLED(true)
- HR_DEFAULT_APPROVER (rỗng -> tạo đơn 422 khi NV không có manager)

## Phụ thuộc
- Postgres (schema `hr_svc`, SQLAlchemy async). Bảng: departments, employees, leave_balance, leave_requests, attendance, onboarding, benefits, performance_reviews, payroll_summary. Migrations Alembic 0001–0006.
- NATS/JetStream: consume `user.*`, publish `hr.leave_request.*` / `hr.employee_profile.updated` / `hr.department.renamed`.
- JWT HS256 (admin API, secret dùng chung user-service); X-Internal-Token cho caller nội bộ (query-service/MCP gọi /hr/query, /hr/profile, leave write).

## Code map
- [app/main.py](src/hr-service/app/main.py) — create_app, lifespan (publisher + subscriber + seed dev)
- [app/api/routes.py](src/hr-service/app/api/routes.py) — query/profile + leave write + public
- [app/api/hr_admin.py](src/hr-service/app/api/hr_admin.py) — admin employee CRUD
- [app/api/auth.py](src/hr-service/app/api/auth.py) — internal token + admin JWT
- [app/core/config.py](src/hr-service/app/core/config.py) / [config.yaml](src/hr-service/config.yaml)
- [app/infrastructure/db/models.py](src/hr-service/app/infrastructure/db/models.py) — ORM models
- [app/infrastructure/db/postgres_hr_repository.py](src/hr-service/app/infrastructure/db/postgres_hr_repository.py)
- [app/domain/repositories/leave_write_repository.py](src/hr-service/app/domain/repositories/leave_write_repository.py) — write interface + lỗi nghiệp vụ
- [app/domain/leave_policy.py](src/hr-service/app/domain/leave_policy.py) — Leave Type Registry
- [app/infrastructure/user_events_subscriber.py](src/hr-service/app/infrastructure/user_events_subscriber.py)
- [app/infrastructure/nats_publisher.py](src/hr-service/app/infrastructure/nats_publisher.py)
