# Chay va test API khong dung rag-worker

Tai lieu nay huong dan chay he thong hien tai voi 3 service:

- `user-service`: auth/JWT/user API, port `8000`
- `document-service`: document API + NATS events, port `8002`
- `query-service`: chat/notification API, port `8001`

Khong chay:

- `rag-worker`
- `mcp-service` that
- `qdrant`
- `redis`
- frontend/nginx/langfuse

Luu y quan trong:

- `docker-compose.yml` hien chi la TODO, chua chay duoc full stack.
- `user-service` hien **khong co `requirements.txt`**. Tai lieu nay khong huong dan tao moi Python env cho user-service; dung `.venv` co san trong repo. Neu `.venv` bi mat, can thanh vien phu trach user-service bo sung `requirements.txt` hoac `pyproject.toml`.
- Tai lieu nay **bo qua thiet lap DB/schema/seed**. Gia dinh DB da co san va service `.env` da tro dung DB. Chi huong dan Docker can chay gi va API goi nhu nao.

## 1. Docker can chay

Can toi thieu 2 container:

| Container | Dung de lam gi | Port |
| --- | --- | --- |
| `da08-postgres` | DB cho user/document/query service | thuong la `55432->5432` hoac `5432->5432` |
| `da08-nats` | NATS JetStream cho `doc.status`, `doc.access`, `notify.doc_new` | `4222` |

Kiem tra:

```powershell
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
```

Neu container da co san:

```powershell
docker start da08-postgres
docker start da08-nats
```

Neu chua co Postgres:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 55432:5432 `
  -d postgres:16
```

Neu chua co NATS:

```powershell
docker run --name da08-nats `
  -p 4222:4222 `
  -p 8222:8222 `
  -d nats:2.10 -js
```

Kiem tra port:

```powershell
Test-NetConnection 127.0.0.1 -Port 4222
Test-NetConnection 127.0.0.1 -Port 55432
```

Neu Postgres cua ban map `5432->5432`, kiem tra port `5432` thay vi `55432`.

## 2. Tao NATS streams

Neu stream da co san thi co the bo qua muc nay. Kiem tra streams:

```powershell
docker run --rm natsio/nats-box:latest `
  nats --server nats://host.docker.internal:4222 stream ls
```

Can co:

- `DOC_EVENTS`: `doc.ingest`, `doc.status`, `doc.access`
- `NOTIFY_EVENTS`: `notify.doc_new`

Tao `DOC_EVENTS`:

```powershell
docker run --rm natsio/nats-box:latest `
  nats --server nats://host.docker.internal:4222 stream add DOC_EVENTS `
  --subjects "doc.ingest,doc.status,doc.access" `
  --storage file `
  --retention limits `
  --discard old `
  --max-age 7d `
  --dupe-window 2m `
  --defaults
```

Tao `NOTIFY_EVENTS`:

```powershell
docker run --rm natsio/nats-box:latest `
  nats --server nats://host.docker.internal:4222 stream add NOTIFY_EVENTS `
  --subjects "notify.doc_new" `
  --storage file `
  --retention limits `
  --discard old `
  --max-age 3d `
  --dupe-window 2m `
  --defaults
```

Neu lenh bao stream da ton tai thi khong sao.

## 3. Chay services

Mo 3 terminal rieng.

### Terminal 1: user-service

```powershell
cd src/user-service
.\.venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8000
```

Khong chay `pip install -r requirements.txt` trong folder nay vi hien tai khong co file requirements.

### Terminal 2: document-service

```powershell
cd src/document-service
.\.venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8002
```

`document-service` can:

- DB dang reachable
- `NATS_URL` tro dung NATS
- `JWT_SECRET_KEY` giong user-service
- Neu test upload/file URL that: GCS config phai dung:
  - `GCS_BUCKET`
  - `GCP_PROJECT_ID`
  - `GOOGLE_APPLICATION_CREDENTIALS`

Upload file that con can GCS credentials/bucket dung. Neu chua co GCS credentials, bo qua upload/get file URL va test health/list/query/mock notification truoc.

### Terminal 3: query-service

Khuyen nghi test khong rag-worker:

```env
AUTH_MODE=mock
LLM_MODE=mock
MCP_MODE=mock
NATS_MODE=nats
ENABLE_DEV_ENDPOINTS=true
```

Nen dung `LLM_MODE=mock` khi smoke test API. Neu `.env` dang `LLM_MODE=openai`, `/health` van co the OK nhung `POST /query` co the goi OpenAI that.

Chay:

```powershell
cd src/query-service
.\.venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --host 127.0.0.1 --port 8001
```

Neu `query-service` loi `No module named nats` hoac `No module named asyncpg`, sync dependency cho rieng query-service:

```powershell
cd src/query-service
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

## 4. Health check

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8002/health
curl.exe http://127.0.0.1:8001/health
```

Expected:

- `user-service`: `status=ok`, `database=ok`
- `document-service`: `status=ok`, `database=ok`, `nats=ok`
- `query-service`: `status=ok`, `llm=mock`, `mcp_service=mock`, `nats=nats` hoac `nats=mock`

Swagger:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8002/docs`
- `http://127.0.0.1:8001/docs`

## 5. User Service API

Login admin:

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

Lay profile:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri http://127.0.0.1:8000/auth/me `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

Login user thuong:

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
```

Neu login tra `401 Invalid credentials`, DB local chua co user seed dung email/password. Tai lieu nay khong tao seed DB.

## 6. Document Service API

`document-service` dung JWT that tu `user-service`, khong dung mock token.

List documents bang admin:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents?limit=10&offset=0" `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

Get detail:

```powershell
$DocId = "<document_id>"

Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents/$DocId" `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

Get file URL:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8002/documents/$DocId/file" `
  -Headers @{ Authorization = "Bearer $UserToken" } `
| ConvertTo-Json -Depth 10
```

Upload document bang admin:

```powershell
$Upload = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8002/documents/upload `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
  -Form @{
    classification = "internal"
    file = Get-Item "src\document-service\README.md"
  }

$Upload | ConvertTo-Json -Depth 10
$DocId = $Upload.document_id
```

Luu y upload co the fail neu GCS credentials/bucket trong `.env` chua dung. Do la gioi han cua cau hinh storage hien tai, khong lien quan rag-worker.

Delete document:

```powershell
Invoke-RestMethod `
  -Method Delete `
  -Uri "http://127.0.0.1:8002/documents/$DocId" `
  -Headers @{ Authorization = "Bearer $AdminToken" } `
| ConvertTo-Json -Depth 10
```

## 7. Gia lap events khi khong co rag-worker

Neu can debug `doc.ingest`, contract moi dung `gcs_key` va `document_name`, khong dung `s3_key`. Vi flow nay khong chay rag-worker nen thuong khong can publish `doc.ingest`; chi can `doc.status`, `doc.access`, `notify.doc_new` de smoke test service integration.

### 7.1 Gia lap `doc.status=indexed`

RAG Worker that se publish `doc.status`. Khi bo qua rag-worker, co the publish bang Docker `nats-box`:

```powershell
$payload = @{
  event_id = [guid]::NewGuid().ToString()
  event_version = 1
  occurred_at = (Get-Date).ToUniversalTime().ToString("o")
  doc_id = $DocId
  status = "indexed"
  chunk_count = 3
} | ConvertTo-Json -Compress

docker run --rm natsio/nats-box:latest `
  nats --server nats://host.docker.internal:4222 pub doc.status "$payload"
```

Expected:

- `document-service` nhan event
- document status doi thanh `indexed`
- neu status `indexed`, `document-service` publish tiep `notify.doc_new`

### 7.2 Publish `doc.access` cho Query Service

`doc.access` giup Query Service cap nhat projection ACL trong `query_svc.document_access`.

```powershell
$payload = @{
  event_id = [guid]::NewGuid().ToString()
  event_version = 1
  occurred_at = (Get-Date).ToUniversalTime().ToString("o")
  doc_id = $DocId
  classification = "internal"
  allowed_departments = @("HR")
  allowed_user_ids = @()
  deleted = $false
} | ConvertTo-Json -Compress

docker run --rm natsio/nats-box:latest `
  nats --server nats://host.docker.internal:4222 pub doc.access "$payload"
```

### 7.3 Publish `notify.doc_new` cho Query Service

```powershell
$payload = @{
  event_id = [guid]::NewGuid().ToString()
  event_version = 1
  occurred_at = (Get-Date).ToUniversalTime().ToString("o")
  doc_id = $DocId
  document_name = "Integration Smoke Test.pdf"
  classification = "internal"
  allowed_departments = @("HR")
  allowed_user_ids = @()
} | ConvertTo-Json -Compress

docker run --rm natsio/nats-box:latest `
  nats --server nats://host.docker.internal:4222 pub notify.doc_new "$payload"
```

## 8. Query Service API

Mac dinh trong flow nay Query Service dung `AUTH_MODE=mock`, nen **khong dung JWT tu user-service**. Dung cac mock token sau:

| Token | User ID | Role | Department |
| --- | --- | --- | --- |
| `mock-user-hr` | `11111111-1111-4111-8111-111111111111` | `user` | `HR` |
| `mock-user-finance` | `22222222-2222-4222-8222-222222222222` | `user` | `Finance` |
| `mock-admin` | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | `admin` | `Admin` |

### 8.1 HR query

```powershell
$body = @{
  question = "Toi con bao nhieu ngay nghi phep?"
  user_id = "11111111-1111-4111-8111-111111111111"
} | ConvertTo-Json -Compress

$body | curl.exe -N --max-time 10 -X POST http://127.0.0.1:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

Expected: SSE tra loi tu HR mock, event done co `sources: []`.

### 8.2 Identity shortcut

```powershell
$body = @{
  question = "Ban la ai?"
  user_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
} | ConvertTo-Json -Compress

$body | curl.exe -N --max-time 10 -X POST http://127.0.0.1:8001/query `
  -H "Authorization: Bearer mock-admin" `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

Expected: tra loi gioi thieu tro ly, khong goi RAG/MCP.

### 8.3 RAG mock query

Neu `NATS_MODE=nats`, Query Service lay allowed document ids tu projection DB. Neu projection chua co document id khop mock MCP data, response co the fallback "khong tim thay".

De demo RAG mock co source ngay, restart Query Service voi:

```env
NATS_MODE=mock
MCP_MODE=mock
LLM_MODE=mock
```

Sau do goi:

```powershell
$body = @{
  question = "Chinh sach nghi phep la gi?"
  user_id = "11111111-1111-4111-8111-111111111111"
} | ConvertTo-Json -Compress

$body | curl.exe -N --max-time 10 -X POST http://127.0.0.1:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

Expected: event done co `sources`, source dung field `source_gcs_uri`.

### 8.4 Guardrail user_id

```powershell
$body = @{
  question = "test"
  user_id = "22222222-2222-4222-8222-222222222222"
} | ConvertTo-Json -Compress

$body | curl.exe -i -X POST http://127.0.0.1:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

Expected: `403 user_id must match authenticated user`.

## 9. Query notifications API

Mo SSE:

```powershell
curl.exe -N http://127.0.0.1:8001/notifications `
  -H "Authorization: Bearer mock-user-hr"
```

Trong terminal khac, ban dev event:

```powershell
$body = @{
  doc_id = $DocId
  document_name = "Integration Smoke Test.pdf"
  classification = "internal"
  allowed_departments = @("HR")
  allowed_user_ids = @()
} | ConvertTo-Json -Compress

$body | curl.exe -X POST http://127.0.0.1:8001/dev/mock-notifications/doc-new `
  -H "Authorization: Bearer mock-admin" `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

History:

```powershell
curl.exe "http://127.0.0.1:8001/notifications/history?limit=20&offset=0&unread_only=false" `
  -H "Authorization: Bearer mock-user-hr"
```

Unread count:

```powershell
curl.exe http://127.0.0.1:8001/notifications/unread-count `
  -H "Authorization: Bearer mock-user-hr"
```

## 10. Loi thuong gap

| Loi | Nguyen nhan | Cach xu ly |
| --- | --- | --- |
| `src/user-service/requirements.txt` khong ton tai | Repo hien chua co dependency manifest cho user-service | Dung `.venv` co san; neu mat `.venv`, can bo sung manifest |
| `Connection refused 4222` | NATS chua chay | `docker start da08-nats` |
| `nats NotFoundError` | Chua co JetStream stream | Tao `DOC_EVENTS`, `NOTIFY_EVENTS` |
| `database unreachable` | DB/DB URL/schema chua san sang | Kiem tra container DB va `.env`; tai lieu nay khong setup DB |
| `401` o document-service | Thieu JWT that tu user-service | Login user-service va dung `Bearer $AdminToken` |
| `401 Invalid mock token` o query-service | Dung JWT that trong `AUTH_MODE=mock` | Dung mock token hoac doi `AUTH_MODE` |
| `403 user_id must match authenticated user` | Body `user_id` khac mock token | Dung dung user id trong bang mock token |
| Upload document fail | GCS credentials/bucket chua dung | Test API khac truoc, hoac cau hinh GCS that |
| RAG query fallback | Khong co rag-worker/MCP/projection phu hop | Dung `NATS_MODE=mock` de demo RAG mock |

## 11. Tom tat flow test nhanh

1. `docker start da08-postgres da08-nats`
2. Kiem tra/tap stream NATS `DOC_EVENTS`, `NOTIFY_EVENTS`
3. Start `user-service`, `document-service`, `query-service`
4. `GET /health` ca 3 service
5. Login `user-service` lay JWT
6. Dung JWT goi `document-service`
7. Dung mock token goi `query-service`
8. Dung `nats-box` publish `doc.status`, `doc.access`, `notify.doc_new` de gia lap phan rag-worker/document events
