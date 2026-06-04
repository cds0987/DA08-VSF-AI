# user-service

Backend service phá»¥ trÃ¡ch xÃ¡c thá»±c, JWT, refresh token vÃ  quáº£n lÃ½ ngÆ°á»i dÃ¹ng cho há»‡ thá»‘ng RAG Chatbot.

## Má»¥c tiÃªu

- Cung cáº¥p API Ä‘Äƒng nháº­p vÃ  xÃ¡c thá»±c token.
- Quáº£n lÃ½ vÃ²ng Ä‘á»i access token vÃ  refresh token.
- Cho phÃ©p admin liá»‡t kÃª, khÃ³a vÃ  má»Ÿ láº¡i tÃ i khoáº£n.
- Ghi audit log cho cÃ¡c hÃ nh Ä‘á»™ng auth vÃ  quáº£n trá»‹ user.

## CÃ´ng nghá»‡ chÃ­nh

- FastAPI
- SQLAlchemy async
- PostgreSQL
- bcrypt
- JWT HS256

## Cáº¥u trÃºc thÆ° má»¥c chÃ­nh

- `app/domain`: entity vÃ  repository contract.
- `app/application`: use case vÃ  exception á»Ÿ táº§ng nghiá»‡p vá»¥.
- `app/infrastructure`: database, security adapter, persistence implementation.
- `app/interfaces/api`: router, dependency, schema vÃ  FastAPI app.
- `tests`: unit tests vÃ  API tests.

## API chÃ­nh

- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/refresh`
- `GET /users`
- `PATCH /users/{user_id}/deactivate`
- `PATCH /users/{user_id}/reactivate`
- `GET /health`

## Test

Cháº¡y test báº±ng:

```powershell
.\venv\Scripts\python.exe -m pytest
```

Cháº¡y compile check:

```powershell
.\venv\Scripts\python.exe -m compileall app
```

## HÆ°á»›ng dáº«n cháº¡y test

Mở DockerDesktop

Chạy ở PowerShell:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 5432:5432 `
  -d postgres:16
```

Kiểm tra DB đã chạy:

```powershell
docker ps
```

Sau đó tạo schema/table cho user-service:

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot
```

Trong màn hình psql, paste:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS user_svc;

CREATE TABLE IF NOT EXISTS user_svc.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT true,
    department VARCHAR(100) NOT NULL DEFAULT '',
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

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
```

Thoát psql:

```sql
\q
```

Tạo user admin để login

Từ thư mục service:

```powershell
cd D:\DA08-VSF\src\user-service
```

Tạo bcrypt hash cho password:

```powershell
.\venv\Scripts\python.exe -c "from app.infrastructure.security.password_hasher import BcryptPasswordHasher; print(BcryptPasswordHasher().hash('***REDACTED-SEED-ADMIN-PW***'))"
```

Copy chuỗi hash in ra, rồi mở lại psql:

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot
```

Insert admin, thay <HASH_VUA_COPY> bằng hash vừa tạo:

```sql
INSERT INTO user_svc.users (
    email,
    hashed_password,
    auth_provider,
    role,
    is_active,
    department
)
VALUES (
    'admin@company.com',
    '<HASH_VUA_COPY>',
    'local',
    'admin',
    true,
    'IT'
)
ON CONFLICT (email) DO UPDATE SET
    hashed_password = EXCLUDED.hashed_password,
    role = EXCLUDED.role,
    is_active = true,
    department = EXCLUDED.department;
```

Thoát:

```sql
\q
```

Chạy lại server

```powershell
cd D:\DA08-VSF\src\user-service
.\venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --reload --host 127.0.0.1 --port 8000
```

Mở:

```text
http://127.0.0.1:8000/docs
```

Trong Swagger Authorize, điền:

- username: admin@company.com
- password: ***REDACTED-SEED-ADMIN-PW***
- client_id: bỏ trống
- client_secret: bỏ trống

Sau đó test /auth/me hoặc /users.

Nếu container đã tồn tại nhưng đang tắt, chạy:

```powershell
docker start da08-postgres
```

Nếu port 5432 bị chiếm, kiểm tra:

```powershell
docker ps
```

Lúc này lỗi Errno 10061 sẽ hết khi PostgreSQL thực sự chạy và schema đã được tạo.

---

Dưới đây là câu lệnh SQL để insert 11 user thường để test deactivate và reactivate user.
Mình dùng cùng một mật khẩu cho dễ test: DemoUserPassword123!

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

INSERT INTO user_svc.users (
    email,
    hashed_password,
    auth_provider,
    role,
    is_active,
    department
)
VALUES
('user01@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'HR'),
('user02@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'Finance'),
('user03@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'IT'),
('user04@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'Sales'),
('user05@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'Marketing'),
('user06@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'HR'),
('user07@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'Finance'),
('user08@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'IT'),
('user09@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'Operations'),
('user10@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'Legal'),
('user11@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', true, 'HR')
ON CONFLICT (email) DO UPDATE SET
    hashed_password = EXCLUDED.hashed_password,
    auth_provider = EXCLUDED.auth_provider,
    role = EXCLUDED.role,
    is_active = EXCLUDED.is_active,
    department = EXCLUDED.department,
    updated_at = now();
```
