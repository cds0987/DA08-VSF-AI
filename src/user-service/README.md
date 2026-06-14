# user-service

`user-service` là FastAPI service phụ trách đăng nhập, JWT, refresh token, quản lý người dùng và audit log.

## Endpoint chính

- `POST /auth/login`
- `POST /auth/admin/login`
- `GET /auth/me`
- `POST /auth/refresh`
- `GET /users`
- `PATCH /users/{user_id}/deactivate`
- `PATCH /users/{user_id}/reactivate`
- `GET /audit-logs`
- `GET /health`

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## Cấu hình local

File `.env` tối thiểu:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot
JWT_SECRET_KEY=kmkmskcmskcmksmcksmcksmkscmsk
REFRESH_TOKEN_TTL_DAYS=7
FAILED_LOGIN_THRESHOLD=5
LOCKOUT_MINUTES=15
```

`JWT_SECRET_KEY` phải giống với `document-service` để token dùng được giữa hai service.
Nếu muốn đổi thời gian sống access token, thêm `ACCESS_TOKEN_TTL_MINUTES=<số phút>`.

## Chạy local

```powershell
cd D:\DA08-VSF\src\user-service
py -3.11 -m pip install -r requirements.txt
py -3.11 -m uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8000
```

Kiểm tra health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## PostgreSQL schema tối thiểu

Tạo PostgreSQL local:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 5432:5432 `
  -d postgres:16
```

Tạo schema, bảng và tài khoản demo:

```powershell
docker exec da08-postgres psql -U user -d rag_chatbot
```

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS user_svc;

CREATE TABLE IF NOT EXISTS user_svc.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    account_type VARCHAR(20) NOT NULL DEFAULT 'internal' CHECK (account_type IN ('internal', 'external')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    department VARCHAR(100) NOT NULL DEFAULT '',
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_account_type ON user_svc.users(account_type);

CREATE TABLE IF NOT EXISTS user_svc.refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_svc.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_svc.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id UUID NOT NULL,
    actor_role VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id UUID,
    detail JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

INSERT INTO user_svc.users (
    email, hashed_password, auth_provider, role, account_type, is_active, department
)
VALUES
('admin@company.com', crypt('DemoAdminPassword123!', gen_salt('bf')), 'local', 'admin', 'internal', true, 'IT'),
('user@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'HR'),
('external01@partner.com', crypt('DemoExternalPassword123!', gen_salt('bf')), 'local', 'user', 'external', true, 'Partner')
ON CONFLICT (email) DO UPDATE SET
    hashed_password = EXCLUDED.hashed_password,
    auth_provider = EXCLUDED.auth_provider,
    role = EXCLUDED.role,
    account_type = EXCLUDED.account_type,
    is_active = EXCLUDED.is_active,
    department = EXCLUDED.department,
    updated_at = now();
```

## Tài khoản demo

- Admin: `admin@company.com` / `DemoAdminPassword123!`
- Internal user: `user@company.com` / `DemoUserPassword123!`
- External user: `external01@partner.com` / `DemoExternalPassword123!`

## Test nhanh API

Login admin:

```powershell
$AdminLogin = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/auth/login `
  -ContentType "application/json" `
  -Body (@{
    email = "admin@company.com"
    password = "DemoAdminPassword123!"
  } | ConvertTo-Json)

$AdminToken = $AdminLogin.access_token
```

Kiểm tra token:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri http://127.0.0.1:8000/auth/me `
  -Headers @{ Authorization = "Bearer $AdminToken" }
```

Liệt kê user:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/users?limit=10&offset=0" `
  -Headers @{ Authorization = "Bearer $AdminToken" }
```

## Test

```powershell
cd D:\DA08-VSF\src\user-service
py -3.11 -m pytest
```
