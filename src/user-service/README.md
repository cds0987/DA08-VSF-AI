# user-service

Backend service phụ trách xác thực, JWT, refresh token và quản lý người dùng cho hệ thống RAG Chatbot.

## Mục tiêu

- Cung cấp API đăng nhập và xác thực token.
- Quản lý vòng đời access token và refresh token.
- Cho phép admin liệt kê, khóa và mở lại tài khoản.
- Ghi audit log cho các hành động auth và quản trị user.

## Công nghệ chính

- FastAPI
- SQLAlchemy async
- PostgreSQL
- bcrypt
- JWT HS256

## Cấu trúc thư mục chính

- `app/domain`: entity và repository contract.
- `app/application`: use case và exception ở tầng nghiệp vụ.
- `app/infrastructure`: database, security adapter, persistence implementation.
- `app/interfaces/api`: router, dependency, schema và FastAPI app.
- `tests`: unit tests và API tests.

## API chính

- `POST /auth/login`
- `POST /auth/admin/login`
- `GET /auth/me`
- `POST /auth/refresh`
- `GET /users`
- `PATCH /users/{user_id}/deactivate`
- `PATCH /users/{user_id}/reactivate`
- `GET /health`

## Hướng dẫn chạy dự án từ đầu

## Hướng dẫn khởi chạy và Test API (Chuẩn)

### Bước 1: Di chuyển vào thư mục dịch vụ và chuẩn bị môi trường

```bash
cd src/user-service
python -m venv venv
```

Trên Windows (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

Hoặc trên Windows (CMD):

```bat
.\venv\Scripts\activate.bat
```

### Bước 2: Chạy dữ liệu Migration (Khởi tạo Database)

Cài đặt các thư viện cần thiết và chạy script cập nhật cấu trúc database. Đảm bảo file `.env` đã có `DATABASE_URL` hoặc các biến `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.

```bash
python -m pip install -r requirements.txt
python scripts/migrate.py
```

### Bước 3: Khởi chạy Server FastAPI

```bash
python -m uvicorn app.interfaces.api.main:app --reload --host 127.0.0.1 --port 8000
```

### Bước 4: Kiểm thử trên Swagger UI

Truy cập đường dẫn: `http://127.0.0.1:8000/docs`

Bấm vào nút Authorize ở góc phải màn hình.

Điền thông tin đăng nhập như sau để test:

- username: `admin@company.com`
- password: `***REDACTED-SEED-ADMIN-PW***`
- client_id: bỏ trống
- client_secret: bỏ trống

Bấm Authorize để lưu phiên đăng nhập và bắt đầu gọi thử các API cần quyền Admin.

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
    account_type VARCHAR(20) NOT NULL DEFAULT 'internal' CHECK (account_type IN ('internal', 'external')),
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
    account_type,
    is_active,
    department
)
VALUES (
    'admin@company.com',
    '<HASH_VUA_COPY>',
    'local',
    'admin',
    'internal',
    true,
    'IT'
)
ON CONFLICT (email) DO UPDATE SET
    hashed_password = EXCLUDED.hashed_password,
    role = EXCLUDED.role,
    account_type = EXCLUDED.account_type,
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
    account_type,
    is_active,
    department
)
VALUES
('user01@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'HR'),
('user02@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'Finance'),
('user03@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'IT'),
('user04@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'Sales'),
('user05@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'Marketing'),
('user06@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'HR'),
('user07@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'Finance'),
('user08@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'IT'),
('user09@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'external', true, 'Operations'),
('user10@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'external', true, 'Legal'),
('user11@company.com', crypt('DemoUserPassword123!', gen_salt('bf')), 'local', 'user', 'internal', true, 'HR')
ON CONFLICT (email) DO UPDATE SET
    hashed_password = EXCLUDED.hashed_password,
    auth_provider = EXCLUDED.auth_provider,
    role = EXCLUDED.role,
    account_type = EXCLUDED.account_type,
    is_active = EXCLUDED.is_active,
    department = EXCLUDED.department,
    updated_at = now();
```
