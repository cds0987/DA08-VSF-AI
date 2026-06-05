# document-service

`document-service` la FastAPI service quan ly tai lieu, chay o cong `8002`.
Service nay:

- so huu bang `doc_svc.documents`
- luu file goc len GCS
- phat event qua NATS
- nhan trang thai tu worker qua `doc.status`

## API

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/file`
- `DELETE /documents/{document_id}`
- `GET /health`

## Yeu cau moi truong

- Python 3.11+
- PostgreSQL
- NATS
- GCP Cloud Storage

File cau hinh mau nam o [src/document-service/.env.example](D:/DA08-VSF/src/document-service/.env.example).

## Chay service cuc bo

```powershell
cd src/document-service
copy .env.example .env
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\uvicorn.exe app.interfaces.api.main:app --reload --port 8002
```

Neu ban khong dung virtualenv cua Windows, hay thay bang Python environment dang co san.

## Chay test tu dong hien co

Test unit va API hien co dung fake repository, fake storage va fake publisher, nen khong can ket noi toi he thong that:

```powershell
cd src/document-service
.\venv\Scripts\python.exe -m pytest
```

`pytest` se chay cac test trong `src/document-service/tests/`, hien tai chu yeu kiem tra:

- validate upload
- logic ACL
- publish `doc.ingest`
- publish `doc.access`
- list/get/delete API bang dependency override

No khong kiem tra PostgreSQL that, NATS that hay GCP Cloud Storage that.

## Huong dan test that voi user-service

Tai lieu nay huong dan test `document-service` theo dung flow that:

1. Dang nhap o `user-service`
2. Lay `access_token`
3. Dem token sang `document-service`
4. Goi cac API upload, list, detail, file, delete

Muc tieu la chay song song ca `user-service` va `document-service` tren may local ma khong bi loi auth.

## 1. Kien truc test local

Khi test theo flow nay, chung ta chay:

- `PostgreSQL` tren `localhost:5432`
- `NATS` tren `localhost:4222`
- `user-service` tren `localhost:8000`
- `document-service` tren `localhost:8002`

Hai service co the dung chung 1 PostgreSQL database, chi can tach schema:

- `user_svc` cho `user-service`
- `doc_svc` cho `document-service`

Dieu quan trong nhat:

- `JWT_SECRET_KEY` trong `src/user-service/.env` va `src/document-service/.env` phai giong nhau
- `document-service` khong co `/auth/login`
- login phai goi vao `user-service`, sau do lay token sang `document-service`

## 2. Luu y quan trong truoc khi chay

### 2.1 Khong goi login o document-service

`document-service` chi co cac route:

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/file`
- `DELETE /documents/{document_id}`
- `GET /health`

Neu goi:

```text
http://localhost:8002/auth/login
```

thi se bi `404 Not Found` la dung.

Route login nam o:

```text
http://localhost:8000/auth/login
```

### 2.2 Storage hien tai la GCP Cloud Storage

Code hien tai dung [gcs_client.py](D:/DA08-VSF/src/document-service/app/infrastructure/storage/gcs_client.py).

De test `upload`, `get file`, `delete` on dinh, ban nen dung:

- GCS bucket that, vi du `rag-chatbot-docs`
- Service account co quyen doc/ghi object trong bucket

Neu GCP credentials hoac bucket sai:

- upload se fail
- presigned URL se fail
- delete file se fail

## 3. Dung ha tang local

### 3.1 Chay PostgreSQL

Mo Docker Desktop, sau do chay:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 5432:5432 `
  -d postgres:16
```

Neu container da ton tai nhung dang tat:

```powershell
docker start da08-postgres
```

Kiem tra:

```powershell
docker ps
```

### 3.2 Chay NATS

```powershell
docker run --name da08-nats `
  -p 4222:4222 `
  -p 8222:8222 `
  -d nats:2.10 -js
```

Neu container da ton tai nhung dang tat:

```powershell
docker start da08-nats
```

Kiem tra:

```powershell
docker ps
```

## 4. Tao schema va bang cho ca 2 service

Mo `psql`:

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot
```

Trong man hinh `psql`, paste toan bo SQL ben duoi.

### 4.1 Schema va bang cho user-service

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

### 4.2 Schema va bang cho document-service

```sql
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

CREATE INDEX IF NOT EXISTS idx_doc_documents_status
ON doc_svc.documents(status);

CREATE INDEX IF NOT EXISTS idx_doc_documents_uploaded_by
ON doc_svc.documents(uploaded_by);

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

CREATE INDEX IF NOT EXISTS idx_doc_audit_actor_id
ON doc_svc.audit_logs(actor_id);
```

## 5. Tao admin va user de login

Van trong `psql`, insert 1 admin va 1 user thuong:

```sql
INSERT INTO user_svc.users (
    email,
    hashed_password,
    auth_provider,
    role,
    is_active,
    department
)
VALUES
(
    'admin@company.com',
    crypt('***REDACTED-SEED-ADMIN-PW***', gen_salt('bf')),
    'local',
    'admin',
    true,
    'IT'
),
(
    'user01@company.com',
    crypt('DemoUserPassword123!', gen_salt('bf')),
    'local',
    'user',
    true,
    'HR'
)
ON CONFLICT (email) DO UPDATE SET
    hashed_password = EXCLUDED.hashed_password,
    auth_provider = EXCLUDED.auth_provider,
    role = EXCLUDED.role,
    is_active = EXCLUDED.is_active,
    department = EXCLUDED.department,
    updated_at = now();
```

Thoat `psql`:

```sql
\q
```

Tai khoan test:

- admin: `admin@company.com` / `***REDACTED-SEED-ADMIN-PW***`
- user: `user01@company.com` / `DemoUserPassword123!`

## 6. Cau hinh .env cho ca 2 service

### 6.1 user-service

Tao `src/user-service/.env` voi noi dung:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot
JWT_SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_TTL_MINUTES=480
REFRESH_TOKEN_TTL_DAYS=7
FAILED_LOGIN_THRESHOLD=5
LOCKOUT_MINUTES=15
```

### 6.2 document-service

Sua `src/document-service/.env` thanh:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
NATS_URL=nats://localhost:4222
NATS_JETSTREAM_ENABLED=true
GCS_BUCKET=rag-chatbot-docs
GCP_PROJECT_ID=vsf-rag-chatbot
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

`JWT_SECRET_KEY` o hai file phai giong nhau.

## 7. Chay song song 2 service

Dung 2 terminal rieng.

### Terminal 1: user-service

```powershell
cd D:\DA08-VSF\src\user-service
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --reload --host 127.0.0.1 --port 8000
```

### Terminal 2: document-service

```powershell
cd D:\DA08-VSF\src\document-service
copy .env.example .env
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --reload --host 127.0.0.1 --port 8002
```

Sau khi `copy .env.example .env`, nho mo `src/document-service/.env` va sua lai dung gia tri o Muc 6.2 truoc khi chay server.

### 7.1 Cach chay song song ma khong loi

Can dam bao:

- chi chay 1 PostgreSQL container tren `5432`
- chi chay 1 NATS container tren `4222`
- `user-service` dung port `8000`
- `document-service` dung port `8002`
- hai service cung `JWT_SECRET_KEY`
- hai service co the cung tro ve cung 1 database `rag_chatbot`, vi moi service dung schema rieng

Neu sua `.env` ma service van hanh xu cu:

- dung server
- chay lai `uvicorn`

## 8. Dang nhap qua user-service de lay access token

### 8.1 Login bang admin

```powershell
$AdminLogin = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/auth/login `
  -ContentType "application/json" `
  -Body (@{
    email = "admin@company.com"
    password = "***REDACTED-SEED-ADMIN-PW***"
  } | ConvertTo-Json)

$AdminToken = $AdminLogin.access_token
$AdminToken
```

### 8.2 Login bang user thuong

```powershell
$UserLogin = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/auth/login `
  -ContentType "application/json" `
  -Body (@{
    email = "user01@company.com"
    password = "DemoUserPassword123!"
  } | ConvertTo-Json)

$UserToken = $UserLogin.access_token
$UserToken
```

Kiem tra token admin dung:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri http://127.0.0.1:8000/auth/me `
  -Headers @{ Authorization = "Bearer $AdminToken" }
```

## 9. Test document-service bang access token tu user-service

### 9.1 Upload document bang admin token

Chuan bi 1 file test. Ban co the dung ngay file da co san:

```text
D:\DA08-VSF\src\document-service\README.md
```

Goi API:

```powershell
$Upload = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8002/documents/upload `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
  -Form @{
    classification = "internal"
    file = Get-Item "D:\DA08-VSF\src\document-service\README.md"
  }

$Upload | ConvertTo-Json -Depth 10
$DocId = $Upload.document_id
```

Ket qua mong doi:

- `status = queued`
- co `document_id`
- `message = Ingestion started`

### 9.2 Kiem tra record da vao DB va status = queued

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot -c "SELECT id, name, status, classification, gcs_key, chunk_count, error_message, deleted_at FROM doc_svc.documents WHERE id = '$DocId';"
```

### 9.3 Xem event doc.ingest

Mo 1 terminal khac:

```powershell
docker run --rm -it natsio/nats-box:latest sh -lc "nats --server nats://host.docker.internal:4222 sub doc.ingest"
```

Upload lai 1 file nua, ban se thay payload co cac truong:

- `doc_id`
- `gcs_key`
- `document_name`
- `file_type`
- `classification`
- `allowed_departments`
- `allowed_user_ids`

### 9.4 Xem event doc.access

Mo 1 terminal khac:

```powershell
docker run --rm -it natsio/nats-box:latest sh -lc "nats --server nats://host.docker.internal:4222 sub doc.access"
```

Khi upload:

- `deleted = false`

Khi delete:

- `deleted = true`

### 9.5 Goi GET /documents

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents?status=queued&limit=10&offset=0" `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

### 9.6 Goi GET /documents/{id}

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents/$DocId" `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

### 9.7 Goi GET /documents/{id}/file

Neu document la `internal`, user thuong cung co the lay URL.

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents/$DocId/file" `
  -Headers @{ Authorization = "Bearer $UserToken" } `
| ConvertTo-Json -Depth 10
```

Ket qua mong doi:

- co `url`
- co `file_type`
- `expires_in = 300`

Neu muon test ACL:

- upload voi `classification = secret` va `allowed_departments = HR`
- dang nhap user department `HR` thi duoc xem
- user khac department thi bi `403`

Vi du upload `secret`:

```powershell
$UploadSecret = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8002/documents/upload `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
  -Form @{
    classification = "secret"
    allowed_departments = "HR"
    file = Get-Item "D:\DA08-VSF\src\document-service\README.md"
  }

$SecretDocId = $UploadSecret.document_id
```

### 9.8 Gui doc.status=indexed hoac failed

Indexed:

```powershell
docker run --rm -it natsio/nats-box:latest sh -lc "nats --server nats://host.docker.internal:4222 pub doc.status '{\"doc_id\":\"$DocId\",\"status\":\"indexed\",\"chunk_count\":3}'"
```

Failed:

```powershell
docker run --rm -it natsio/nats-box:latest sh -lc "nats --server nats://host.docker.internal:4222 pub doc.status '{\"doc_id\":\"$DocId\",\"status\":\"failed\",\"error\":\"indexing failed\"}'"
```

### 9.9 Kiem tra update status va notify.doc_new

Kiem tra DB:

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot -c "SELECT id, status, chunk_count, error_message, updated_at FROM doc_svc.documents WHERE id = '$DocId';"
```

Mo 1 terminal khac de xem `notify.doc_new`:

```powershell
docker run --rm -it natsio/nats-box:latest sh -lc "nats --server nats://host.docker.internal:4222 sub notify.doc_new"
```

Neu ban gui `doc.status=indexed`, event nay se xuat hien.

### 9.10 Xoa document

```powershell
Invoke-RestMethod `
  -Method Delete `
  -Uri "http://127.0.0.1:8002/documents/$DocId" `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

Kiem tra soft delete:

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot -c "SELECT id, status, deleted_at FROM doc_svc.documents WHERE id = '$DocId';"
```

Ket qua mong doi:

- record van con trong bang
- `deleted_at` khong con `NULL`

## 10. Nhin ket qua o dau

Khi test xong, ban co the doi chieu ket qua o cac noi sau:

- login thanh cong: response cua `user-service` va `GET /auth/me`
- upload thanh cong: response `POST /documents/upload`
- record `queued/indexed/failed`: bang `doc_svc.documents`
- audit log: bang `doc_svc.audit_logs`
- event NATS: `doc.ingest`, `doc.access`, `notify.doc_new`
- file da upload: bucket GCS that trong Google Cloud Console
- signed URL: response `GET /documents/{id}/file`
- xoa mem: cot `deleted_at` trong `doc_svc.documents`

## 11. Loi thuong gap

### 11.1 404 o /auth/login

Ban dang goi nham vao `document-service`.

Dung:

```text
http://127.0.0.1:8000/auth/login
```

Khong dung:

```text
http://127.0.0.1:8002/auth/login
```

### 11.2 401 Not authenticated o document-service

Thuong la do:

- token khong hop le
- `JWT_SECRET_KEY` cua 2 service khac nhau

### 11.3 403 Admin only

Ban dang dung token cua user thuong de goi:

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{id}`
- `DELETE /documents/{id}`

Hay dung admin token.

### 11.4 Upload fail

Thuong la do:

- GCP credentials sai
- bucket GCS khong ton tai
- NATS chua chay
- DB/schema chua tao

### 11.5 Thay doi .env nhung app khong nhan

Tat `uvicorn` va chay lai.

## Ghi chu thiet ke

- `upload` chi cho admin.
- `file` endpoint kiem tra ACL theo `classification`, `allowed_departments`, `allowed_user_ids`.
- Khi publish event that bai sau khi luu file, document se duoc danh dau `FAILED`.
- Khi xoa tai lieu, service chi xoa metadata va file, con vector delete la TODO cho contract NATS rieng.
