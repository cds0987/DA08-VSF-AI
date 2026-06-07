# How to use the current system

Cap nhat: 2026-06-07

Pham vi file nay: trang thai repo sau khi pull code moi nhat (`HEAD 9d08e0f`) va sau patch query-service de gui `X-Internal-Token` toi mcp-service khi co cau hinh `MCP_INTERNAL_TOKEN`.

## 1. Cap nhat moi sau pull

- `9d08e0f`: document-service co S3-compatible storage backend; mcp-service co HTTP fix; co validate e2e cloud ingest/search.
- `deploy/env/*.env` va `deploy/env/*.env.example` da co san cho user/document/query/rag/mcp. Khong nen commit gia tri secret moi.
- user-service da co `requirements.txt` va `.env.example`.
- document-service co them storage backend `gcs|s3`, phu hop local/MinIO/R2/GCS S3-interop.
- mcp-service da co app-layer auth bang `MCP_INTERNAL_TOKEN` va header `X-Internal-Token`.
- mcp-service code hien tai da loc Qdrant theo `document_ids`. Luu y: mot so docs cu van noi `document_ids` la no-op, phan do da stale.
- query-service da dung MCP SDK Streamable HTTP, khong con raw JSON-RPC client cu.

Patch trong lan nay:

- query-service doc `MCP_INTERNAL_TOKEN` tu `Settings`.
- `MCPStreamableHttpClient` gui `X-Internal-Token` neu token duoc cau hinh; neu token rong thi khong gui header nay.
- Them `MCP_INTERNAL_TOKEN` vao query-service env examples va env deploy/local.
- Them `MCP_INTERNAL_TOKEN` rong vao `deploy/env/mcp-service.env` de contract config ro rang.
- Harden `deploy/env/query-service.env`: `APP_ENV=production`, `AUTH_MODE=user_service`, `MCP_MODE=real`, `RATE_LIMITER_MODE=redis`, `ENABLE_DEV_ENDPOINTS=false`, `RAG_RESULT_LIMIT=3`.

## 2. MCP internal token

mcp-service doc token tu `MCP_INTERNAL_TOKEN` trong `config.yaml`. Neu token co gia tri, mcp-service se reject moi request thieu/sai header:

```text
X-Internal-Token: <shared-secret>
```

Quy tac van hanh:

- Neu muon bat auth noi bo, dien cung mot gia tri vao `deploy/env/mcp-service.env` va `deploy/env/query-service.env`.
- Neu `MCP_INTERNAL_TOKEN` rong o mcp-service, auth noi bo dang tat; query-service co the khong gui header.
- Khuyen nghi production: bat token va dung secret dai/ngau nhien.
- `MCP_MODE=real` la mode chinh. `MCP_MODE=mcp` van duoc query-service chap nhan nhu alias cu, nhung nen doi sang `real`.

## 3. Muc dap ung thiet ke

| Thanh phan | Da dap ung | Con thieu/le huong |
|---|---|---|
| user-service | `/auth/login`, `/auth/me`, `/auth/refresh`, `/users`, deactivate/reactivate, health DB, reject JWT secret yeu. | Chua co `/auth/admin/login`; chua thay base migration SQL/Alembic; `deploy/env/user-service.env.example` con dung `JWT_EXPIRE_MINUTES` trong khi code doc `ACCESS_TOKEN_TTL_MINUTES` va `REFRESH_TOKEN_TTL_DAYS`. |
| document-service | Upload/list/get/delete/file; publish `doc.ingest`, `doc.access`; subscribe `doc.status`; publish `notify.doc_new`; GCS va S3-compatible storage; health DB/NATS. | Chua thay base migration tao schema `doc_svc`, chi co migration rename `s3_key` -> `gcs_key`; local storage S3/MinIO can cau hinh rieng. |
| rag-worker | FastAPI health/readiness; NATS ingest; Alembic metadata DB; parse/chunk/embed/upsert Qdrant; Qdrant contract stamp; S3 parser cho GCS S3-interop. | Root `deploy/env/rag-worker.env.example` con dung mot so key cu (`QDRANT_URL`, `OPENAI_EMBEDDING_MODEL`); config chinh nen dung `VECTOR_DB_URL`, `VECTOR_DB_API_KEY`, `VECTOR_COLLECTION`, `EMBED_MODEL`. |
| mcp-service | Streamable HTTP `/mcp`; fail-closed Qdrant contract verify; `rag_search`; internal-token auth; Qdrant filter theo `document_ids`; rerank `none|lexical|llm`. | Chua expose `hr_query`; README/docs cu co cho noi `document_ids` no-op va can update. |
| query-service | `/query` SSE, conversation, feedback, notification, admin metrics; MCP SDK real client; ACL allow-list truoc khi goi MCP va post-filter ket qua; Redis rate limiter; Postgres repos; bounded NATS dedup; production config guards. | `/health` moi check mode/config, chua live-ping day du DB/Redis/MCP/NATS/Auth/LLM; semantic cache van in-memory; HR question se fallback neu MCP real chua co `hr_query`. |
| root docker-compose | Co NATS, Redis, 5 backend service va nginx route `/api/*`. | Chua dung Postgres/Qdrant/MinIO/frontend/Langfuse local; co bind mount service-account JSON bang duong dan Linux co dinh, can sua theo may chay. |

Ket luan: he thong co the chay luong backend that neu ban da co Cloud SQL/Qdrant/GCS va env dung. He thong chua phai local one-command full stack.

## 4. Checklist truoc khi chay full backend

1. Dung chung JWT secret cho user/document/query neu cac service verify JWT.
2. Neu query-service dung `AUTH_MODE=user_service`, dam bao `USER_SERVICE_URL=http://user-service:8000` trong Docker hoac `http://localhost:8000` khi chay local.
3. Neu bat MCP auth, dat cung token:

```env
# deploy/env/mcp-service.env
MCP_INTERNAL_TOKEN=<shared-internal-token>

# deploy/env/query-service.env
MCP_INTERNAL_TOKEN=<shared-internal-token>
```

4. Dung chung vector config cho rag-worker va mcp-service:

```env
VECTOR_DB_URL=<qdrant-url>
VECTOR_DB_API_KEY=<qdrant-api-key-if-any>
VECTOR_COLLECTION=rag_chatbot
EMBED_MODEL=text-embedding-3-small
EMBED_DIMENSION=1536
```

5. Query-service production config nen la:

```env
APP_ENV=production
AUTH_MODE=user_service
MCP_MODE=real
NATS_MODE=nats
LLM_MODE=openai
RATE_LIMITER_MODE=redis
ENABLE_DEV_ENDPOINTS=false
RAG_RESULT_LIMIT=3
```

6. Neu chay root compose tren may local, sua 2 dong volume service-account trong `docker-compose.yml`:

```yaml
volumes:
  - <local-path-to-gcp-sa.json>:/secrets/gcp-sa.json:ro
```

7. Bootstrap DB schema:

```powershell
# query-service schema
Get-Content src/query-service/migrations/001_create_query_schema.sql |
  docker exec -i <postgres-container> psql -U <user> -d <query_db>

# rag-worker metadata schema
cd src/rag-worker
$env:DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>:5432/<rag_db>"
python -m alembic upgrade head
```

user-service va document-service chua co base migration ro rang trong repo, nen can them migration/bootstrap schema truoc khi chay DB moi tinh.

8. Bootstrap NATS JetStream streams neu moi dung NATS:

```powershell
nats stream add DOC_EVENTS --subjects "doc.ingest,doc.status,doc.access" --storage file --retention limits --discard old --max-age 7d --dupe-window 2m --ack
nats stream add NOTIFY_EVENTS --subjects "notify.doc_new" --storage file --retention limits --discard old --max-age 3d --dupe-window 2m --ack
```

## 5. Luong full backend voi Docker Compose

Dung khi env dang tro toi ha tang that hoac ha tang ngoai da chay san.

```powershell
# Tu root repo
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Kiem tra health/log:

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8002/health
curl.exe http://localhost:8001/health
docker compose logs -f mcp-service
docker compose logs -f rag-worker
```

mcp-service khong co `/health` rieng trong code hien tai; xem log can co `mcp_contract_verified` va `mcp_auth mode=internal-token` neu token bat.

Test API flow:

```powershell
# 1) Login. Admin va user deu dung /auth/login hien tai.
curl.exe -X POST http://localhost:8000/auth/login `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"<email>\",\"password\":\"<password>\"}"

# Luu access_token thanh $TOKEN / $ADMIN_TOKEN theo cach cua ban.

# 2) Upload document bang admin token.
curl.exe -X POST http://localhost:8002/documents/upload `
  -H "Authorization: Bearer <ADMIN_TOKEN>" `
  -F "file=@D:\path\policy.pdf" `
  -F "classification=internal"

# 3) Theo doi document status.
curl.exe -H "Authorization: Bearer <ADMIN_TOKEN>" "http://localhost:8002/documents?limit=20"

# 4) Query SSE. user_id trong body phai khop user trong token.
curl.exe -N -X POST http://localhost:8001/query `
  -H "Authorization: Bearer <USER_TOKEN>" `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"Tom tat chinh sach trong tai lieu vua upload\",\"user_id\":\"<USER_ID_FROM_AUTH_ME>\"}"
```

Luong mong doi:

```text
document-service upload -> doc.ingest + doc.access
rag-worker ingest -> Qdrant + doc.status
document-service nhan doc.status -> document indexed + notify.doc_new
query-service nhan doc.access -> cap nhat ACL projection
query-service /query -> MCP rag_search(document_ids) -> mcp-service -> Qdrant -> SSE answer
```

## 6. Luong thay the: query-service mock local

Dung de test chat/conversation/feedback/notification ma khong can DB, NATS, MCP, OpenAI.

`src/query-service/.env`:

```env
APP_ENV=development
AUTH_MODE=mock
LLM_MODE=mock
MCP_MODE=mock
NATS_MODE=mock
DATABASE_URL=
RATE_LIMITER_MODE=memory
ENABLE_DEV_ENDPOINTS=true
```

Chay:

```powershell
cd src/query-service
python -m pip install -r requirements.txt
python -m uvicorn app.interfaces.api.main:app --reload --port 8001
```

Mock token:

| Token | user_id | Role/department |
|---|---|---|
| `mock-user-hr` | `11111111-1111-4111-8111-111111111111` | user / HR |
| `mock-user-finance` | `22222222-2222-4222-8222-222222222222` | user / Finance |
| `mock-admin` | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | admin / Admin |

Goi thu:

```powershell
curl.exe -N -X POST http://localhost:8001/query `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"Chinh sach nghi phep la gi?\",\"user_id\":\"11111111-1111-4111-8111-111111111111\"}"
```

## 7. Luong thay the: MCP + RAG search local

Dung de test search plumbing that giua rag-worker/Qdrant/mcp-service, khong can full user/document/query.

```powershell
docker run -d --name vsf-nats -p 4222:4222 -p 8222:8222 nats:2.10 -js
docker run -d --name vsf-qdrant -p 6333:6333 qdrant/qdrant
```

Seed/ingest bang script cua rag-worker tuy theo corpus/env ban co. Cac script e2e trong `src/rag-worker/scripts` va `src/rag-worker/tests/e2e` yeu cau `NATS_URL`, `S3_ENDPOINT_URL`, `VECTOR_DB_URL`.

Chay mcp-service sau khi Qdrant da co collection va contract stamp:

```powershell
cd src/mcp-service
$env:VECTOR_DB_URL="http://localhost:6333"
$env:VECTOR_COLLECTION="rag_chatbot"
$env:AI_PROVIDER="offline"
$env:RERANK_PROVIDER="lexical"
$env:MCP_INTERNAL_TOKEN=""
python -m app.main
```

Neu mcp-service thoat voi `mcp_contract_verify_failed`, Qdrant chua co contract stamp dung. Can ingest/seed lai bang rag-worker voi cung `VECTOR_COLLECTION`, `EMBED_MODEL`, `EMBED_DIMENSION`.

## 8. Verification commands

Sau khi cai dependencies:

```powershell
python -m pytest src/query-service/tests -q
python -m pytest src/mcp-service/tests -q
```

Rieng test patch MCP token:

```powershell
python -m pytest src/query-service/tests/test_mcp_streamable_client.py -q
```

Kiem tra compose:

```powershell
docker compose config --quiet
```

## 9. Troubleshooting

| Loi | Nguyen nhan hay gap | Cach xu ly |
|---|---|---|
| query-service goi mcp-service bi `401` | mcp-service bat `MCP_INTERNAL_TOKEN`, query-service thieu/sai token | Dat cung `MCP_INTERNAL_TOKEN` o hai env file, restart ca hai service |
| mcp-service exit code 1 | Qdrant collection/contract stamp thieu hoac lech | Ingest bang rag-worker voi cung vector config |
| HR question fallback sang RAG | mcp-service chua expose `hr_query` | Tam chap nhan fallback hoac implement `hr_query` trong mcp-service |
| `/auth/admin/login` 404 | Endpoint nay chua co trong user-service | Dung `/auth/login` cho admin hien tai, hoac implement endpoint rieng |
| query-service startup fail production | Mock mode/dev endpoint/rate limiter/JWT secret khong dat policy | Set mode real/nats/openai/user_service, `RATE_LIMITER_MODE=redis`, secret manh |
| `docker compose up` khong thay Postgres/Qdrant | Root compose khong dung cac infra nay | Dung external/cloud infra hoac them service Postgres/Qdrant vao compose |
| document upload fail storage | Sai GCS credential hoac S3-compatible config | Kiem tra `STORAGE_BACKEND`, bucket, service account/HMAC key, volume `/secrets/gcp-sa.json` |
| rag-worker health 503 | Production thieu `DATABASE_URL`, vector URL, storage preflight, hoac NATS | Kiem tra `/health`, logs va env theo checklist |
