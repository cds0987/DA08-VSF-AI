# document-service

`document-service` là FastAPI service quản lý metadata tài liệu, upload file gốc lên Google Cloud Storage, phát event NATS và kiểm tra ACL khi người dùng mở file.

## Endpoint chính

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/file`
- `DELETE /documents/{document_id}`
- `GET /documents/audit-logs`
- `GET /health`

Swagger UI:

```text
http://127.0.0.1:8002/docs
```

Lưu ý: `document-service` không có `/auth/login`. Hãy login ở `user-service`, rồi dùng access token đó để gọi `document-service`.

## Cấu hình local

File `.env` tối thiểu:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot
JWT_SECRET_KEY=kmkmskcmskcmksmcksmcksmkscmsk
JWT_ALGORITHM=HS256
NATS_URL=nats://localhost:4222
NATS_JETSTREAM_ENABLED=true
GCS_BUCKET=rag-chatbot-docs
GCP_PROJECT_ID=vsf-rag-chatbot
GOOGLE_APPLICATION_CREDENTIALS=D:\DA08-VSF\src\document-service\gcp-key.json
```

`JWT_SECRET_KEY` phải giống `user-service`.

Nếu dùng GCS thật, không đặt `STORAGE_EMULATOR_HOST`. Chỉ bật biến này khi bạn có GCS emulator local:

```env
STORAGE_EMULATOR_HOST=http://localhost:4443
```

## Chạy local

```powershell
cd D:\DA08-VSF\src\document-service
py -3.11 -m pip install -r requirements.txt
py -3.11 -m uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8002
```

Kiểm tra health:

```powershell
Invoke-RestMethod http://127.0.0.1:8002/health
```

Kết quả OK:

```json
{"status":"ok","database":"ok","nats":"ok"}
```

## Hạ tầng local

PostgreSQL:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 5432:5432 `
  -d postgres:16
```

NATS có JetStream:

```powershell
docker run --name da08-nats `
  -p 4222:4222 `
  -p 8222:8222 `
  -d nats:2.10 -js
```

Nếu container đã tồn tại:

```powershell
docker start da08-postgres
docker start da08-nats
```

## PostgreSQL schema tối thiểu

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot
```

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS doc_svc;

CREATE TABLE IF NOT EXISTS doc_svc.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(500) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    gcs_key VARCHAR(1000) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    uploaded_by UUID NOT NULL,
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    allowed_departments TEXT[] NOT NULL DEFAULT '{}',
    allowed_user_ids TEXT[] NOT NULL DEFAULT '{}',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_doc_documents_status ON doc_svc.documents(status);
CREATE INDEX IF NOT EXISTS idx_doc_documents_uploaded_by ON doc_svc.documents(uploaded_by);

CREATE TABLE IF NOT EXISTS doc_svc.audit_logs (
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

CREATE INDEX IF NOT EXISTS idx_doc_audit_actor_id ON doc_svc.audit_logs(actor_id);
```
```thoát sql
\q
```
## Test nhanh API

Login ở `user-service`:

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

Upload file bằng `curl.exe` trên Windows:

```powershell
curl.exe -X POST http://127.0.0.1:8002/documents/upload `
  -H "Authorization: Bearer $AdminToken" `
  -F "classification=internal" `
  -F "file=@D:\DA08-VSF\src\document-service\README.md"
```

Kết quả mong đợi khi GCS credential hợp lệ:

```json
{"document_id":"...","status":"queued","message":"Ingestion started"}
```

Liệt kê tài liệu:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents?limit=10&offset=0" `
  -Headers @{ Authorization = "Bearer $AdminToken" }
```

Lấy file URL:
```powershell
$DocId = "<document_id của file vừa tạo>"
```

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents/$DocId/file" `
  -Headers @{ Authorization = "Bearer $AdminToken" }
```

Response thành công:

```json
{"url":"https://...","file_type":"pdf","expires_in":300}
```

## ACL

- `public`: mọi user đã đăng nhập xem được.
- `internal`: chỉ user có `account_type=internal`.
- `secret`: user `internal` và `department` nằm trong `allowed_departments`.
- `top_secret`: user id nằm trong `allowed_user_ids`.
- Admin luôn được phép.

## NATS

Service tự đảm bảo JetStream stream cho các subject:

- `doc.ingest`
- `doc.status`
- `doc.access`
- `notify.doc_new`

Khi upload thành công, service publish `doc.ingest` và `doc.access`. Khi nhận `doc.status=indexed`, service cập nhật DB và publish `notify.doc_new`.

## Lỗi thường gặp

### `503 Storage operation failed` khi upload hoặc lấy file

Nguyên nhân thường là GCS credential không hợp lệ, bucket sai hoặc service account thiếu quyền. Kiểm tra:

- `GOOGLE_APPLICATION_CREDENTIALS` trỏ tới JSON service account thật.
- `private_key` trong JSON còn đúng định dạng PEM.
- `GCS_BUCKET` tồn tại.
- Service account có quyền đọc/ghi object trong bucket.

### `/health` trả `nats unreachable`

Kiểm tra container NATS có map port host:

```powershell
docker ps
```

Cần thấy:

```text
0.0.0.0:4222->4222/tcp
```

Nếu không có, chạy lại NATS bằng lệnh ở phần hạ tầng local.

## Test

```powershell
cd D:\DA08-VSF\src\document-service
py -3.11 -m pytest
```
