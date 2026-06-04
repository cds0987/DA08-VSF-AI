# Query Service API Test Guide

Huong dan nay test rieng `query-service` Phase 1 mock-first, khong can user-service, document-service, rag-worker hay mcp-service chay kem.

Theo docs 4/6 v2, tai lieu khong con buoc approve/reject: Admin upload -> `queued` -> ingest -> `indexed`. Query Service chi truy van cac tai lieu da indexed/da co trong projection mock.

## 1. Setup local

```powershell
cd src/query-service
uv venv --python 3.11 .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
Copy-Item .env.example .env
```

De test offline khong ton OpenAI key, sua `.env`:

```env
AUTH_MODE=mock
LLM_MODE=mock
ENABLE_DEV_ENDPOINTS=true
```

Neu muon goi OpenAI that:

```env
LLM_MODE=openai
OPENAI_API_KEY=<your_api_key>
OPENAI_LLM_MODEL=gpt-4o-mini
```

Chay server:

```powershell
uvicorn app.interfaces.api.main:app --reload --port 8001
```

Docs UI: `http://localhost:8001/docs`

Test tren Swagger UI:

1. Bam nut `Authorize` o goc phai.
2. Nhap token mock, vi du `mock-user-hr`.
3. Khong nhap chu `Bearer`; Swagger se tu gan `Authorization: Bearer mock-user-hr`.
4. Khi goi `POST /query`, body `user_id` phai khop token dang authorize.

## 2. Mock tokens va users

Tat ca endpoint tru `/health` can header `Authorization: Bearer <token>`.

| Token | User ID | Role | Department |
|---|---|---|---|
| `mock-user-hr` | `11111111-1111-4111-8111-111111111111` | `user` | `HR` |
| `mock-user-finance` | `22222222-2222-4222-8222-222222222222` | `user` | `Finance` |
| `mock-admin` | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | `admin` | `Admin` |

Mock documents:

| Document | Classification | Ai xem duoc |
|---|---|---|
| `Onboarding Handbook 2026.md` | `public` | Moi user |
| `Chinh_sach_nghi_phep_2026.pdf` | `internal` | Moi user noi bo |
| `Finance_Report_Guideline.xlsx` | `secret` | Finance + admin |
| `Executive_Compensation_Top_Secret.pdf` | `top_secret` | Admin |

## 3. Health

```powershell
curl.exe http://localhost:8001/health
```

Expected:

```json
{
  "status": "ok",
  "database": "mock",
  "mcp_service": "mock",
  "nats": "mock",
  "auth": "mock",
  "llm": "mock"
}
```

Neu `LLM_MODE=openai` ma thieu `OPENAI_API_KEY`, health tra `status: degraded`.

## 4. POST /query - SSE chat

Tren Windows PowerShell, cach on dinh nhat la dung `Invoke-RestMethod` hoac ghi JSON ra file tam cho `curl.exe` doc. Tranh truyen JSON truc tiep vao `curl.exe` vi PowerShell co the nuot dau quote.

PowerShell native:

```powershell
$body = @{
  question = "Chinh sach nghi phep la gi?"
  user_id = "11111111-1111-4111-8111-111111111111"
} | ConvertTo-Json -Compress

$headers = @{
  Authorization = "Bearer mock-user-hr"
}

Invoke-RestMethod `
  -Uri "http://localhost:8001/query" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

`Invoke-RestMethod` co the in response sau khi stream ket thuc. De quan sat realtime tung SSE event, dung `curl.exe -N` ben duoi.

Neu muon dung `curl.exe`:

```powershell
$body = @{
  question = "Chinh sach nghi phep la gi?"
  user_id = "11111111-1111-4111-8111-111111111111"
} | ConvertTo-Json -Compress

$bodyPath = Join-Path $env:TEMP "query-body.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8

curl.exe -N -X POST http://localhost:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data-binary "@$bodyPath"
```

Expected SSE:

```text
data: {"token":"Theo Chinh_sach_nghi_..."}
data: {"done":true,"sources":[...],"session_id":"..."}
```

Test HR personal Q&A:

```powershell
$body = @{
  question = "Toi con bao nhieu ngay nghi phep?"
  user_id = "22222222-2222-4222-8222-222222222222"
} | ConvertTo-Json -Compress

$bodyPath = Join-Path $env:TEMP "query-body.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8

curl.exe -N -X POST http://localhost:8001/query `
  -H "Authorization: Bearer mock-user-finance" `
  -H "Content-Type: application/json" `
  --data-binary "@$bodyPath"
```

Expected: `sources` rong vi dung tool `hr_query`, va du lieu HR duoc filter theo user trong token.

Test user mismatch:

```powershell
$body = @{
  question = "test"
  user_id = "22222222-2222-4222-8222-222222222222"
} | ConvertTo-Json -Compress

$bodyPath = Join-Path $env:TEMP "query-body.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8

curl.exe -i -X POST http://localhost:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data-binary "@$bodyPath"
```

Expected: `403`.

## 5. Conversations

```powershell
curl.exe http://localhost:8001/conversations `
  -H "Authorization: Bearer mock-user-hr"
```

Expected:

```json
{
  "messages": [
    {"role": "user", "content": "...", "created_at": "..."},
    {"role": "assistant", "content": "...", "created_at": "..."}
  ]
}
```

Clear history:

```powershell
curl.exe -X DELETE http://localhost:8001/conversations `
  -H "Authorization: Bearer mock-user-hr"
```

Expected:

```json
{"message": "Conversation history cleared"}
```

## 6. Feedback

Lay `session_id` tu event done cua `/query`, roi:

```powershell
$body = @{
  session_id = "<session_id>"
  score = 1
} | ConvertTo-Json -Compress

$bodyPath = Join-Path $env:TEMP "feedback-body.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8

curl.exe -X POST http://localhost:8001/feedback `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  --data-binary "@$bodyPath"
```

Expected:

```json
{"message": "Feedback recorded"}
```

`score` chi nhan `1` hoac `-1`; gia tri khac tra `422`.

## 7. Notifications

Muc dich nhom API nay:

- `GET /notifications`: SSE app-level, client mo ket noi lau de nhan thong bao realtime.
- `POST /dev/mock-notifications/doc-new`: API dev-only de gia lap Document Service publish event `notify.doc_new` khi tai lieu ingest xong. Endpoint nay KHONG upload tai lieu, KHONG tao document record, chi ban su kien test cho Query Service.
- `GET /notifications/history`, `/unread-count`, `POST /notifications/{id}/read`: test lich su thong bao, badge chua doc va mark-as-read.

`/dev/mock-notifications/doc-new` chi bat khi `ENABLE_DEV_ENDPOINTS=true` va chi `admin` duoc goi (`mock-admin`). Production khong dung endpoint nay. Luong production that se la Document Service publish NATS `notify.doc_new`, Query Service subscribe roi day qua SSE.

Mo SSE app-level:

```powershell
curl.exe -N http://localhost:8001/notifications `
  -H "Authorization: Bearer mock-user-hr"
```

Server gui keep-alive:

```text
:keep-alive
```

Neu bam Execute `GET /notifications` tren Swagger UI va thay loading mai, do la expected behavior cua SSE stream. Stream nay duoc thiet ke de mo lau cho den khi client dong ket noi. Swagger khong phu hop de test endpoint nay; dung `curl.exe -N` hoac frontend EventSource.

Trong terminal khac, ban mock event `doc_new`:

```powershell
$body = @{
  doc_id = "dddddddd-0002-4000-8000-000000000002"
  document_name = "Chinh_sach_nghi_phep_2026.pdf"
  classification = "internal"
  allowed_departments = @()
  allowed_user_ids = @()
} | ConvertTo-Json -Compress

$bodyPath = Join-Path $env:TEMP "notify-body.json"
$body | Set-Content -LiteralPath $bodyPath -NoNewline -Encoding utf8

curl.exe -X POST http://localhost:8001/dev/mock-notifications/doc-new `
  -H "Authorization: Bearer mock-admin" `
  -H "Content-Type: application/json" `
  --data-binary "@$bodyPath"
```

Expected SSE terminal nhan:

```text
data: {"type":"notify","event":"doc_new","message":"Có tài liệu mới: Chinh_sach_nghi_phep_2026.pdf","doc_id":"dddddddd-0002-4000-8000-000000000002"}
```

History:

```powershell
curl.exe "http://localhost:8001/notifications/history?limit=20&offset=0&unread_only=false" `
  -H "Authorization: Bearer mock-user-hr"
```

Unread count:

```powershell
curl.exe http://localhost:8001/notifications/unread-count `
  -H "Authorization: Bearer mock-user-hr"
```

Mark read:

```powershell
curl.exe -X POST http://localhost:8001/notifications/<notification_id>/read `
  -H "Authorization: Bearer mock-user-hr"
```

## 8. Admin metrics

Muc dich `GET /admin/metrics`: API cho Admin dashboard analytics. Endpoint doc tu conversation/feedback cua Query Service de hien thi tong so cau hoi, so cau hoi theo ngay, ti le feedback up/down va top questions. Chi role `admin` duoc goi.

User thuong bi chan:

```powershell
curl.exe -i http://localhost:8001/admin/metrics `
  -H "Authorization: Bearer mock-user-hr"
```

Expected: `403 Admin only`.

Admin:

```powershell
curl.exe "http://localhost:8001/admin/metrics?from=2026-06-01&to=2026-06-30" `
  -H "Authorization: Bearer mock-admin"
```

Expected:

```json
{
  "total_questions": 1,
  "by_day": [{"date": "2026-06-04", "count": 1}],
  "feedback": {"up": 0, "down": 0, "rate": 0.0},
  "top_questions": [{"question": "...", "count": 1}]
}
```

## 9. Automated tests

```powershell
cd src/query-service
.\.venv\Scripts\Activate.ps1
$env:LLM_MODE="mock"
pytest -v
```

## 10. Loi thuong gap

| Loi | Nguyen nhan | Cach xu ly |
|---|---|---|
| `401 Not authenticated` | Thieu Bearer token | Them `Authorization: Bearer mock-user-hr` |
| `403 user_id must match authenticated user` | Body `user_id` khac token | Dung dung user id cua token mock |
| `503 OPENAI_API_KEY is required` | `LLM_MODE=openai` nhung chua set key | Set key hoac doi `LLM_MODE=mock` |
| `429 Rate limit exceeded` | Qua 20 request/phut/user | Doi 60 giay hoac tang `QUERY_RATE_LIMIT_PER_MINUTE` khi dev |
