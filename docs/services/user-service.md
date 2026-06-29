---
service: user-service
path: src/user-service
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/user-service/app/interfaces/api/main.py
  - src/user-service/app/interfaces/api/routers/auth.py
  - src/user-service/app/interfaces/api/routers/users.py
  - src/user-service/app/interfaces/api/routers/audit_logs.py
  - src/user-service/app/interfaces/api/dependencies.py
  - src/user-service/app/infrastructure/security/jwt_token_service.py
  - src/user-service/app/application/use_cases/auth/login_use_case.py
  - src/user-service/app/core/config.py
  - src/user-service/app/domain/entities/user.py
  - src/user-service/app/infrastructure/db/models.py
  - src/user-service/app/infrastructure/messaging/user_event_publisher.py
  - src/user-service/migrations/versions/0001_baseline.py
  - src/user-service/migrations/versions/0002_drop_department_from_users.py
  - infra/auth/jwt-claims-contract.yaml
---
# User Service

FastAPI service (Clean Architecture: domain / application / infrastructure / interfaces).
Entry: `app.interfaces.api.main:app`, chạy uvicorn cổng 8000 (Dockerfile, bọc New Relic).

## Trách nhiệm
- Đăng nhập / phát JWT access token + refresh token (cookie httponly).
- Quản lý người dùng (tạo / liệt kê / vô hiệu hoá / kích hoạt lại / xoá) — admin-only.
- Khoá tài khoản sau N lần sai mật khẩu; ghi audit log.
- Phát event vòng đời user lên NATS JetStream cho hr-service đồng bộ (best-effort).
- LÀ producer JWT; query/document/hr-service chỉ giải mã (xem hợp đồng claims).

## API / giao diện
Router KHÔNG có prefix `/api/user` trong code; prefix do nginx thêm (`/api/user/ -> :8000/`).
Đường dẫn dưới đây là path nội bộ service.

Auth (`/auth`):
- `POST /auth/login` — body JSON `{email,password}` hoặc form `username/password`; trả `{access_token, token_type}`, set cookie `refresh_token`.
- `POST /auth/admin/login` — như trên + ép `role=="admin"`; cookie riêng `eka.admin.refresh_token`.
- `POST /auth/logout`, `POST /auth/admin/logout` — 204, idempotent, xoá cookie.
- `POST /auth/refresh`, `POST /auth/admin/refresh` — xoay token từ cookie refresh.
- `GET /auth/me` — `{id,email,role,account_type}` (Bearer token).

Users (`/users`, tất cả `require_admin`):
- `POST /users` — 201, body `{email,password(min 8),role(user|admin),account_type(internal|external)}`.
- `GET /users?is_active&limit(1..200)&offset` — `{items,total}`.
- `PATCH /users/{user_id}/deactivate` · `PATCH /users/{user_id}/reactivate` — `{id,is_active}`.
- `DELETE /users/{user_id}` — 204.

Khác:
- `GET /audit-logs?limit&offset` — admin-only.
- `GET /health` — kiểm tra DB (`select 1`); 503 `degraded` nếu DB không tới được.

CORS: `allow_credentials=True`, origins từ `CORS_ORIGINS`.

## Auth / JWT
Encode HS256, secret `JWT_SECRET_KEY`, access TTL mặc định 15 phút (`jwt_token_service.py`).
Claims phát: `sub`, `user_id` (cả hai = user id), `role`, `account_type`, `jti`, `iat`, `exp`.
Decode bắt buộc có `sub`, `jti`, `account_type`.
KHÔNG có claim `department` — cố ý: department thuộc hr-service (nguồn sự thật). Hợp đồng
1-nguồn ở `infra/auth/jwt-claims-contract.yaml` + linter CI ép producer↔consumer khớp.
`role` chỉ có `admin` / `user` (enum `UserRole`). `account_type`: `internal` / `external`.
Refresh token: lưu hashed (bcrypt) trong DB, TTL `REFRESH_TOKEN_TTL_DAYS` (mặc định 7), xoay ở mỗi refresh.
Khoá: sai mật khẩu >= `FAILED_LOGIN_THRESHOLD` (5) lần -> khoá `LOCKOUT_MINUTES` (15) -> HTTP 423.

## Config / ENV
- `USER_SERVICE_DATABASE_URL` / `DATABASE_URL` — Postgres asyncpg DSN.
- `JWT_SECRET_KEY` — bắt buộc; service raise nếu rỗng/giá trị default yếu.
- `ACCESS_TOKEN_TTL_MINUTES` (15), `REFRESH_TOKEN_TTL_DAYS` (7).
- `FAILED_LOGIN_THRESHOLD` (5), `LOCKOUT_MINUTES` (15), `COOKIE_SECURE` (false).
- `NATS_URL`, `NATS_JETSTREAM_ENABLED` (true), `USER_EVENTS_ENABLED` (true).
- `CORS_ORIGINS` (localhost:3000,3001).

## Phụ thuộc
- PostgreSQL (schema `user_svc`: `users`, `refresh_tokens`, `audit_logs`) qua SQLAlchemy async + Alembic.
- NATS JetStream — stream `USER_EVENTS`, subjects `user.created/updated/deactivated/deleted`
  (payload: event_id, event_version, occurred_at, user_id, email, role, account_type, is_active —
  KHÔNG có department). Publish best-effort (lỗi chỉ log).
- bcrypt (mật khẩu + hash refresh token), python-jose (JWT).

## Code map
- Entry/wiring: [main.py](src/user-service/app/interfaces/api/main.py), [dependencies.py](src/user-service/app/interfaces/api/dependencies.py)
- Routers: [auth.py](src/user-service/app/interfaces/api/routers/auth.py), [users.py](src/user-service/app/interfaces/api/routers/users.py), [audit_logs.py](src/user-service/app/interfaces/api/routers/audit_logs.py)
- Auth logic: [login_use_case.py](src/user-service/app/application/use_cases/auth/login_use_case.py), [jwt_token_service.py](src/user-service/app/infrastructure/security/jwt_token_service.py)
- Domain/DB: [user.py](src/user-service/app/domain/entities/user.py), [models.py](src/user-service/app/infrastructure/db/models.py)
- Config: [config.py](src/user-service/app/core/config.py)
- Events: [user_event_publisher.py](src/user-service/app/infrastructure/messaging/user_event_publisher.py), [user_event_emitter.py](src/user-service/app/infrastructure/messaging/user_event_emitter.py)
- Migrations: [0001_baseline.py](src/user-service/migrations/versions/0001_baseline.py), [0002_drop_department_from_users.py](src/user-service/migrations/versions/0002_drop_department_from_users.py)
