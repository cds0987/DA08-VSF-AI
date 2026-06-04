# Query Service ket noi User Service nhu the nao

> Ten file dang la `connect_with_ueser_service.md` theo yeu cau hien tai. Neu muon doi cho dung chinh ta, nen doi thanh `connect_with_user_service.md`.

## 1. User Service dung de lam gi?

`user-service` la service quan ly dang nhap va danh tinh user:

- `POST /auth/login`: nhan email/password, tra ve `access_token`.
- `GET /auth/me`: nhan `Authorization: Bearer <token>`, tra ve user hien tai.
- `POST /auth/refresh`: doi refresh token lay access token moi.
- `GET /users`, `PATCH /users/{id}/deactivate`, `PATCH /users/{id}/reactivate`: API admin quan ly user.

Noi ngan gon: `user-service` la noi tra loi cau hoi "request nay la cua ai, role gi, department nao, con active khong?".

## 2. Query Service lien quan gi toi User Service?

`query-service` can user identity de:

- Chan request khong co token.
- Lay `user_id`, `role`, `department` cua user dang chat.
- Check body `user_id` trong `POST /query` phai khop user trong token.
- Loc tai lieu theo ACL:
  - `admin` xem duoc tat ca.
  - `user` chi xem document phu hop voi classification/department/user_id.
- Goi tool HR bang dung `user_id` cua token, khong cho LLM tu dien user khac.
- Chan user da bi deactivate neu dung `AUTH_MODE=user_service`.

Luồng khi dung User Service thật:

```text
Frontend
  -> POST user-service /auth/login
  <- access_token

Frontend
  -> POST query-service /query
     Header: Authorization: Bearer <access_token>
     Body: { question, user_id }

Query Service
  -> GET user-service /auth/me
     Header: Authorization: Bearer <access_token>
  <- { id, email, role, department }

Query Service
  -> check body.user_id == auth_user.id
  -> dung role/department de loc tai lieu va stream cau tra loi
```

## 3. Vi sao User Service can Docker/PostgreSQL?

`user-service` khong phai mock service. No can database de luu:

- Bang `user_svc.users`: user, email, password hash, role, department, is_active.
- Bang `user_svc.refresh_tokens`: refresh token da hash, expiry, revoked state.
- Bang `user_svc.audit_logs`: log hanh dong login, deactivate/reactivate.

Lenh Docker trong README chi de chay PostgreSQL local nhanh:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 55432:5432 `
  -d postgres:16
```

No tao mot container PostgreSQL tai `localhost:55432`. User Service ket noi vao DB nay de login, verify token va doc user active/inactive.

Ly do dung `55432`: neu may da co PostgreSQL local chiem port `5432`, Docker se khong bind duoc `5432:5432` dung cach cho service tren host.

Neu khong chay PostgreSQL, `/health` cua user-service se tra degraded va `/auth/login`/`/auth/me` co the loi database.

## 4. Query Service co 3 che do auth

Trong `src/query-service/.env`:

### Mode 1: mock

Dung khi test Query Service doc lap, khong can User Service, khong can PostgreSQL.

```env
AUTH_MODE=mock
```

Token mock:

```text
mock-user-hr
mock-user-finance
mock-admin
```

Vi du:

```powershell
curl.exe http://localhost:8001/conversations `
  -H "Authorization: Bearer mock-user-hr"
```

### Mode 2: jwt

Query Service tu decode JWT bang shared secret, khong goi User Service.

```env
AUTH_MODE=jwt
JWT_SECRET_KEY=<same JWT_SECRET_KEY as user-service>
JWT_ALGORITHM=HS256
```

Mode nay nhanh hon, nhung co diem yeu: neu user bi deactivate sau khi token da phat, Query Service co the khong biet ngay neu token khong co `is_active=false`.

### Mode 3: user_service

Query Service goi User Service moi request de verify token:

```env
AUTH_MODE=user_service
USER_SERVICE_URL=http://localhost:8000
AUTH_HTTP_TIMEOUT_SECONDS=5
```

Mode nay nen dung khi test lien service, vi user da bi deactivate se bi User Service tu choi o `/auth/me`.

## 5. Cach chay User Service local

### Buoc 1: chay PostgreSQL bang Docker

Mo Docker Desktop, roi chay:

```powershell
docker start da08-postgres
```

Neu container chua ton tai:

```powershell
docker run --name da08-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=rag_chatbot `
  -p 55432:5432 `
  -d postgres:16
```

### Buoc 2: tao schema/table

```powershell
docker exec -it da08-postgres psql -U user -d rag_chatbot
```

Paste SQL trong `src/user-service/README.md` de tao:

```text
user_svc.users
user_svc.refresh_tokens
user_svc.audit_logs
```

### Buoc 3: tao user admin/user test

README cua `user-service` co huong dan tao bcrypt hash va insert admin:

```text
admin@company.com
***REDACTED-SEED-ADMIN-PW***
```

Co the insert them user thuong theo SQL cuoi README.

### Buoc 4: chay User Service

```powershell
cd src/user-service
$env:USER_SERVICE_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:55432/rag_chatbot"
$env:JWT_SECRET_KEY = "dev-query-user-shared-secret-with-at-least-32-bytes"
.\.venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --reload --host 127.0.0.1 --port 8000
```

Kiem tra:

```powershell
curl.exe http://localhost:8000/health
```

Expected:

```json
{"status":"ok","database":"ok"}
```

## 6. Cach chay Query Service ket noi User Service

Trong `src/query-service/.env`:

```env
AUTH_MODE=user_service
USER_SERVICE_URL=http://localhost:8000
AUTH_HTTP_TIMEOUT_SECONDS=5
LLM_MODE=mock
```

Chay Query Service:

```powershell
cd src/query-service
.\.venv\Scripts\python.exe -m uvicorn app.interfaces.api.main:app --reload --host 127.0.0.1 --port 8001
```

## 7. Test luong login -> query

### Buoc 1: login User Service lay token

```powershell
$loginBody = @{
  email = "admin@company.com"
  password = "***REDACTED-SEED-ADMIN-PW***"
} | ConvertTo-Json -Compress

$tokenResponse = Invoke-RestMethod `
  -Uri "http://localhost:8000/auth/login" `
  -Method Post `
  -ContentType "application/json" `
  -Body $loginBody

$accessToken = $tokenResponse.access_token
$headers = @{
  Authorization = "Bearer $accessToken"
}
```

### Buoc 2: xem user trong token

```powershell
$me = Invoke-RestMethod http://localhost:8000/auth/me -Headers $headers
$me
```

Ban can lay `id` trong `$me.id` de truyen vao Query Service.

### Buoc 3: goi Query Service

```powershell
$body = @{
  question = "Chinh sach nghi phep la gi?"
  user_id = $me.id
} | ConvertTo-Json -Compress

$bodyPath = Join-Path $env:TEMP "query-body.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8

curl.exe -N -X POST http://localhost:8001/query `
  -H "Authorization: Bearer $accessToken" `
  -H "Content-Type: application/json" `
  --data-binary "@$bodyPath"
```

Expected:

```text
data: {"token":"..."}
data: {"done":true,"sources":[...],"session_id":"..."}
```

## 8. Test bang Swagger

Can chay ca 2 service:

```text
user-service:  http://127.0.0.1:8000
query-service: http://127.0.0.1:8001
```

Trong `src/query-service/.env`, can de:

```env
AUTH_MODE=user_service
USER_SERVICE_URL=http://127.0.0.1:8000
LLM_MODE=mock
```

Sau khi sua `.env`, restart Query Service.

### Buoc 1: lay token tu User Service Swagger

Mo:

```text
http://127.0.0.1:8000/docs
```

Cach nhanh nhat:

1. Bam nut `Authorize` o goc phai.
2. Dien:
   - `username`: `admin@company.com`
   - `password`: `***REDACTED-SEED-ADMIN-PW***`
   - `client_id`: bo trong
   - `client_secret`: bo trong
3. Bam `Authorize`.
4. Goi `GET /auth/me` de kiem tra token da dung.

Cach khac: goi `POST /auth/login` trong Swagger voi body:

```json
{
  "email": "admin@company.com",
  "password": "***REDACTED-SEED-ADMIN-PW***"
}
```

Copy `access_token` trong response.

### Buoc 2: authorize Query Service Swagger

Mo:

```text
http://127.0.0.1:8001/docs
```

Bam `Authorize`, o muc `BearerAuth` paste `access_token`.

Neu Swagger da hien `BearerAuth`, chi paste token, khong can them chu `Bearer`.

### Buoc 3: goi `POST /query`

Trong User Service Swagger, goi `GET /auth/me` de lay `id`.

Sau do trong Query Service Swagger, goi `POST /query` voi body:

```json
{
  "question": "Chinh sach nghi phep la gi?",
  "user_id": "<id lay tu /auth/me>"
}
```

Neu dung admin token thi `user_id` phai la id cua admin. Neu dung user token thi `user_id` phai la id cua user do. Neu khac nhau Query Service se tra `403 user_id must match authenticated user`.

Luu y: Swagger co the hien response streaming khong dep bang terminal. Neu Swagger tra `200` va thay response dang `data: {...}` thi endpoint da chay dung; test UX streaming tot nhat van nen dung `curl.exe -N` hoac frontend.

## 9. Loi thuong gap

| Loi | Nguyen nhan | Cach xu ly |
|---|---|---|
| `503 user-service unavailable` | Query Service khong goi duoc User Service | Kiem tra user-service dang chay port `8000`, `USER_SERVICE_URL` dung |
| `401 Not authenticated` | Thieu token, token sai, token het han, user bi deactivate | Login lai hoac kiem tra `/auth/me` |
| `403 user_id must match authenticated user` | Body `user_id` khac `id` trong token | Lay `$me.id` tu `/auth/me` va dung no |
| `/health` user-service degraded | PostgreSQL chua chay/chua tao schema | Start Docker PostgreSQL va tao schema/table |
| Query Service van nhan mock token | `.env` dang de `AUTH_MODE=mock` | Doi sang `AUTH_MODE=user_service` va restart Query Service |
| `[WinError 10013]` khi chay Uvicorn port `8000` | Da co process khac dang chiem port `8000` | Chay lenh ben duoi de tim/stop process, hoac doi sang port khac |

Tim process dang chiem port `8000`:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

Stop process dang chay user-service:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*uvicorn*app.interfaces.api.main:app*8000*" -and $_.Name -like "python*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## 10. Khi nao khong can User Service?

Khi chi test rieng Query Service offline:

```env
AUTH_MODE=mock
LLM_MODE=mock
```

Luc nay khong can Docker PostgreSQL, khong can User Service. Dung mock token trong `Docs/API_test.md`.

Khi test lien service hoac can dam bao user deactivate bi chan, dung:

```env
AUTH_MODE=user_service
```
