# Use System - Audit va huong dan chay he thong

Cap nhat: 2026-06-06

Tai lieu nay tong hop trang thai that cua repo hien tai sau khi pull code moi va sau phan hardening `query-service`. Muc tieu la tra loi 3 cau hoi:

- He thong hien tai da dap ung tai lieu kien truc den dau?
- Con diem nao chua lam duoc, loi/config nao can sua?
- Nen chay he thong hien tai nhu the nao de test tong hop?

## 1. Ket luan nhanh

He thong hien tai da co khung microservice dung huong: `user-service`, `document-service`, `query-service`, `rag-worker`, `mcp-service`, NATS event, Redis, Qdrant va PostgreSQL per-service. Rieng `query-service` hien da duoc harden them: MCP SDK Streamable HTTP client, ACL post-filter, Redis rate limiter, Postgres conversation repo, notification online-users, bounded NATS dedup, config fail-fast cho production.

Nhung he thong chua dat trang thai "full architecture one-command run". Cac blocker lon:

- `docker compose up` hien fail vi thieu cac file `deploy/env/*.env`.
- `src/user-service/Dockerfile` copy `requirements.txt` va `.env.example`, nhung `src/user-service` hien khong co 2 file nay.
- `docker-compose.yml` chua khai bao PostgreSQL, Qdrant, MinIO/GCS emulator, frontend chat/admin, Langfuse, trong khi docs tong quan cu dang mo ta co cac thanh phan do.
- `user-service` chua co endpoint `/auth/admin/login`.
- `mcp-service` hien chi expose `rag_search`; `hr_query` chua implement.
- ACL "truoc Qdrant" chua the dam bao bang query-service mot minh, vi `mcp-service` dang nhan `document_ids` nhung khong filter truoc khi search Qdrant. Query-service da post-filter de khong leak source, nhung van chua phai ACL-before-vector-search.

## 2. Doi chieu voi kien truc

| Hang muc | Trang thai hien tai | Danh gia |
|---|---|---|
| Tach microservice | Da co 5 backend service rieng trong `src/`. | Dat phan lon |
| Clean Architecture | Moi service co domain/application/infrastructure/interfaces o muc do khac nhau. | Dat tuong doi |
| User Service auth/user management | Co `/auth/login`, `/auth/me`, `/auth/refresh`, `/users`, deactivate/reactivate, JWT weak secret fail-closed. | Thieu `/auth/admin/login` |
| Document Service | Co upload/list/get/delete/file, publish `doc.ingest`, publish `doc.access`, subscribe `doc.status`, publish `notify.doc_new`. | Dat phan lon, can DB schema bootstrap ro rang |
| Query Service | Co `/query` SSE, conversations, feedback, notifications, admin metrics, MCP SDK real client, mock mode, production config guard. | Dat phan lon |
| MCP Service | Co MCP Streamable HTTP `/mcp`, tool `rag_search`, fail-closed Qdrant contract verify, reranker `none|lexical|llm`. | Thieu `hr_query`; `document_ids` no-op |
| RAG Worker | Co FastAPI health/status, NATS ingest, durable metadata/job repo, parse/chunk/embed/upsert Qdrant, contract stamp. | Dat phan lon, nhung docs cu "khong DB/no HTTP" da lech |
| NATS contract | Co `doc.ingest`, `doc.status`, `doc.access`, `notify.doc_new`; JetStream config documented. | Dat phan lon |
| Database per service | Code co schema/model rieng. Query-service co SQL migration. | Chua dong nhat migration/Alembic cho tat ca service |
| Full Docker Compose | Compose co nats/redis/backend/nginx. | Chua dat, thieu env va nhieu infra/service |
| Frontend | Co folder frontend, README cu co nhac chat/admin. | Compose chua chay frontend |

## 3. Diem da dap ung tot

### Query Service

- `MCP_MODE=real` va legacy `MCP_MODE=mcp` deu dung `MCPStreamableHttpClient` qua official MCP Python SDK, khong con raw JSON-RPC client cu.
- `rag_search` truyen `top_k=RAG_RESULT_LIMIT`, default 3.
- Sau khi MCP tra ket qua, query-service drop ket qua co `document_id` nam ngoai ACL allow-list va log `acl_post_filter_violation`.
- `APP_ENV=production` fail startup neu `AUTH_MODE`, `MCP_MODE`, `NATS_MODE`, `LLM_MODE` con `mock`.
- `ENABLE_DEV_ENDPOINTS` default false; production bat dev endpoints se fail.
- `AUTH_MODE=jwt` reject weak/default `JWT_SECRET_KEY`.
- `/notifications/history` gioi han `limit <= 100`.
- Co `RedisRateLimiter`; production yeu cau `RATE_LIMITER_MODE=redis`.
- Notification real path gui cho `connection_manager.online_users()`, khong con hardcoded mock users.
- NATS dedup co TTL va max-size.
- Khong con hardcoded summary "Tom tat mock..."; mock summary lay tu message that.
- Co `PostgresConversationRepository` va migration `src/query-service/migrations/001_create_query_schema.sql`.

### MCP Service

- MCP endpoint: `http://localhost:8003/mcp`, transport Streamable HTTP.
- Startup fail-closed bang `verify_contract()` voi Qdrant contract stamp.
- `rag_search(query, document_ids?, top_k=5)` tra shape co `source_gcs_uri`, `markdown_gcs_uri`.
- Co reranker `none`, `lexical`, `llm`; LLM reranker loi thi fallback ve vector-order.

### Document Service

- Admin upload tao document status queued, upload file len GCS, publish `doc.ingest`.
- Publish `doc.access` de query-service co projection ACL.
- Subscribe `doc.status`; khi indexed thi publish `notify.doc_new`.
- Health check database va NATS.

### RAG Worker

- NATS ingest qua `doc.ingest`.
- Co health `/livez`, `/readyz`, `/health`.
- Co metadata/job repo va worker loop; khong chi la worker in-memory nua.
- Ghi contract stamp cho Qdrant de mcp-service verify.

## 4. Diem chua lam duoc hoac dang lech docs

1. `user-service` thieu `/auth/admin/login`.

   `docs/api-spec.md` va README tong quan co mo ta Admin app dung `/auth/admin/login`, nhung code hien chi co `/auth/login`, `/auth/me`, `/auth/refresh`.

2. `mcp-service` thieu `hr_query`.

   Query-service mock co `hr_query`, va LLM/tool decision co the chon `hr_query`. Trong real mode, query-service chi chap nhan tool do MCP list tra ve, nen HR questions se fallback an toan sang `rag_search` neu MCP server chua expose `hr_query`.

3. ACL-before-Qdrant chua dat.

   Query-service da lay ACL allow-list truoc khi goi MCP va da post-filter ket qua, nen khong expose unauthorized source trong SSE. Tuy nhien `mcp-service` hien khong dung `document_ids` lam Qdrant filter, nen vector search van chay tren toan collection. Neu yeu cau kien truc bat buoc "ACL enforced truoc Qdrant", can sua `mcp-service` hoac vector search layer de filter `document_id` truoc khi search.

4. Full Docker Compose chua chay duoc ngay.

   Lenh `docker compose config` hien fail o file env dau tien bi thieu. Vi du:

   ```text
   env file deploy/env/document-service.env not found
   ```

   Ngoai ra, sau khi copy env, user-service van co nguy co build fail vi Dockerfile dang `COPY requirements.txt` va `COPY .env.example`, nhung folder `src/user-service` khong co hai file do.

5. Compose thieu infra ma docs cu dang mo ta.

   `docker-compose.yml` hien co NATS, Redis, user/document/query/rag/mcp/nginx. Chua co PostgreSQL, Qdrant, MinIO/GCS emulator, frontend chat/admin, Langfuse. Vi vay docs cu noi "docker compose up chay toan bo stack" la chua dung voi file compose hien tai.

6. Env example cho RAG/MCP can canh chinh.

   `mcp-service/config.yaml` va `rag-worker/config.yaml` doc cac bien chinh la:

   ```env
   VECTOR_DB_URL=...
   VECTOR_DB_API_KEY=...
   VECTOR_COLLECTION=rag_chatbot
   EMBED_MODEL=text-embedding-3-small
   AI_PROVIDER=offline|auto
   ```

   Trong khi `deploy/env/mcp-service.env.example` va `deploy/env/rag-worker.env.example` dang dung `QDRANT_URL`, `QDRANT_COLLECTION`, `OPENAI_EMBEDDING_MODEL`. Can dong bo de real Qdrant path khong bi roi ve in-process/offline ngoai y muon.

7. Query-service `/health` chua ping live tat ca dependency.

   Hien health chu yeu bao mode/config va mot so degraded reason nhu thieu OpenAI key, thieu DB khi NATS on. Chua active ping database, Redis, MCP service, NATS.

8. Migration chua dong nhat.

   - Query-service co SQL migration thu cong.
   - Rag-worker co Alembic.
   - Document-service chi co migration rename `s3_key` sang `gcs_key`, chua thay base migration trong folder.
   - User-service chua thay migration folder.

9. Mot so docs goc da cu.

   - README tong quan van noi mcp-service co `hr_query`.
   - `docs/contracts.md` van mo ta mcp-service theo DDD + HR mock/BGE reranker trong khi code hien search-only core.
   - `docs/setup.md` noi RAG Worker khong DB/khong HTTP, trong khi code hien co metadata DB va health/status HTTP.

## 5. Config production khuyen nghi

### Query Service

```env
APP_ENV=production
AUTH_MODE=user_service
USER_SERVICE_URL=http://user-service:8000
MCP_MODE=real
MCP_SERVICE_URL=http://mcp-service:8003
NATS_MODE=nats
LLM_MODE=openai
OPENAI_API_KEY=<openai-key>
RATE_LIMITER_MODE=redis
REDIS_URL=redis://redis:6379/0
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/query_db
ENABLE_DEV_ENDPOINTS=false
RAG_RESULT_LIMIT=3
RAG_SCORE_THRESHOLD=0.70
```

### MCP Service va RAG Worker

Dung cung mot Qdrant va cung vector contract:

```env
VECTOR_DB_PROVIDER=qdrant
VECTOR_DB_URL=http://qdrant:6333
VECTOR_DB_API_KEY=
VECTOR_COLLECTION=rag_chatbot
EMBED_MODEL=text-embedding-3-small
AI_PROVIDER=auto
OPENAI_API_KEY=<openai-key>
```

Neu chay offline/e2e plumbing khong can OpenAI:

```env
AI_PROVIDER=offline
RERANK_PROVIDER=lexical
```

### Document Service

Can GCS that neu dung upload API hien tai:

```env
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/doc_db
JWT_SECRET_KEY=<shared-strong-secret>
NATS_URL=nats://localhost:4222
GCS_BUCKET=<bucket>
GCP_PROJECT_ID=<project-id>
GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account.json>
```

## 6. Cach chay hien tai

### Muc A - Verify nhanh bang tests

Day la cach on dinh nhat de kiem tra code hien tai.

```powershell
# Tu root repo
python -m pip install -r src/query-service/requirements.txt
python -m pip install -r src/mcp-service/requirements.txt

python -m pytest src/query-service/tests -q
python -m pytest src/mcp-service/tests -q
```

Ky vong gan nhat:

```text
query-service: 57 passed
mcp-service: 18 passed
```

Neu muon chay document-service:

```powershell
python -m pip install -r src/document-service/requirements.txt
python -m pytest src/document-service/tests -q
```

User-service hien chua co `requirements.txt`, nen can tao/sua file nay truoc khi cai dependency rieng cho service.

### Muc B - Chay query-service mock mode de test UI/API chat

Phu hop de test `/query`, conversation, feedback, notification mock ma khong can DB/NATS/MCP/OpenAI.

Trong `src/query-service/.env`:

```env
APP_ENV=development
AUTH_MODE=mock
LLM_MODE=mock
MCP_MODE=mock
NATS_MODE=mock
DATABASE_URL=
OPENAI_API_KEY=
RATE_LIMITER_MODE=memory
ENABLE_DEV_ENDPOINTS=true
```

Chay service:

```powershell
cd src/query-service
python -m pip install -r requirements.txt
python -m uvicorn app.interfaces.api.main:app --reload --port 8001
```

Goi thu:

```powershell
curl.exe -N -X POST "http://localhost:8001/query" `
  -H "Authorization: Bearer mock-user-hr" `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"Chinh sach nghi phep la gi?\",\"user_id\":\"11111111-1111-4111-8111-111111111111\"}"
```

Mock tokens co san:

| Token | Vai tro |
|---|---|
| `mock-user-hr` | user phong HR |
| `mock-user-finance` | user phong Finance |
| `mock-admin` | admin |

### Muc C - Chay backend infra co that

Chay infra nen dung rieng thay vi `docker compose up` hien tai:

```powershell
docker run -d --name vsf-nats -p 4222:4222 -p 8222:8222 nats:2.10 -js
docker run -d --name vsf-redis -p 6379:6379 redis:7-alpine
docker run -d --name vsf-qdrant -p 6333:6333 qdrant/qdrant
docker run -d --name vsf-postgres `
  -e POSTGRES_USER=user `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=postgres `
  -p 5432:5432 `
  postgres:15
```

Tao databases:

```powershell
docker exec -it vsf-postgres psql -U user -c "CREATE DATABASE user_db;"
docker exec -it vsf-postgres psql -U user -c "CREATE DATABASE doc_db;"
docker exec -it vsf-postgres psql -U user -c "CREATE DATABASE query_db;"
docker exec -it vsf-postgres psql -U user -c "CREATE DATABASE mcp_db;"
```

Tao NATS streams neu dung JetStream durable:

```powershell
# Can cai NATS CLI truoc. Neu chua co CLI, cac service/test co the van dung core NATS,
# nhung JetStream publish/subscribe production se can stream.
nats stream add DOC_EVENTS --subjects "doc.ingest,doc.status,doc.access" --storage file --retention limits --discard old --max-age 7d --dupe-window 2m --ack
nats stream add NOTIFY_EVENTS --subjects "notify.doc_new" --storage file --retention limits --discard old --max-age 3d --dupe-window 2m --ack
```

Apply query-service schema:

```powershell
Get-Content src/query-service/migrations/001_create_query_schema.sql | docker exec -i vsf-postgres psql -U user -d query_db
```

Rag-worker metadata schema dung Alembic:

```powershell
cd src/rag-worker
$env:DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/query_db"
python -m pip install -r requirements.txt
python -m alembic upgrade head
```

Luu y: user-service va document-service can schema rieng (`user_svc`, `doc_svc`). Repo hien co SQLAlchemy models nhung chua thay base migration day du. Can them migration hoac dung script bootstrap rieng truoc khi chay real DB.

### Muc D - Chay MCP + RAG real search

Dieu kien:

- Qdrant dang chay.
- Rag-worker da ingest it nhat mot document va da ghi contract stamp.
- mcp-service va rag-worker dung cung `VECTOR_DB_URL`, `VECTOR_COLLECTION`, `EMBED_MODEL`.

Chay rag-worker:

```powershell
cd src/rag-worker
$env:APP_ENV="development"
$env:DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/query_db"
$env:VECTOR_DB_PROVIDER="qdrant"
$env:VECTOR_DB_URL="http://localhost:6333"
$env:VECTOR_COLLECTION="rag_chatbot"
$env:AI_PROVIDER="offline"
$env:NATS_URL="nats://localhost:4222"
python -m uvicorn app.interfaces.api.main:app --reload --port 8004
```

Chay mcp-service:

```powershell
cd src/mcp-service
$env:VECTOR_DB_PROVIDER="qdrant"
$env:VECTOR_DB_URL="http://localhost:6333"
$env:VECTOR_COLLECTION="rag_chatbot"
$env:AI_PROVIDER="offline"
$env:RERANK_PROVIDER="lexical"
python -m app.main
```

Chay query-service real MCP nhung van mock auth/LLM:

```powershell
cd src/query-service
$env:APP_ENV="development"
$env:AUTH_MODE="mock"
$env:LLM_MODE="mock"
$env:MCP_MODE="real"
$env:MCP_SERVICE_URL="http://localhost:8003"
$env:NATS_MODE="mock"
$env:RATE_LIMITER_MODE="memory"
python -m uvicorn app.interfaces.api.main:app --reload --port 8001
```

Neu mcp-service thoat ngay voi `mcp_contract_verify_failed`, nghia la Qdrant chua co collection/contract stamp dung. Can ingest bang rag-worker truoc hoac chay e2e seed cua rag-worker/mcp-service.

### Muc E - Docker Compose

Khong nen coi `docker compose up --build` la cach chay full hien tai. Truoc khi chay compose can sua/copy:

```powershell
Copy-Item deploy/env/user-service.env.example deploy/env/user-service.env
Copy-Item deploy/env/document-service.env.example deploy/env/document-service.env
Copy-Item deploy/env/query-service.env.example deploy/env/query-service.env
Copy-Item deploy/env/rag-worker.env.example deploy/env/rag-worker.env
Copy-Item deploy/env/mcp-service.env.example deploy/env/mcp-service.env
```

Sau do van can sua tiep:

- Them `src/user-service/requirements.txt`.
- Them `src/user-service/.env.example` hoac bo dong copy trong Dockerfile.
- Them PostgreSQL va Qdrant vao `docker-compose.yml`, hoac tro env den service ngoai.
- Sua env RAG/MCP tu `QDRANT_URL` sang `VECTOR_DB_URL` de khop `config.yaml`.
- Neu muon chay frontend, them service `frontend/chat` va `frontend/admin` vao compose hoac chay bang npm rieng.

Kiem tra compose:

```powershell
docker compose config
```

Chi khi lenh tren pass moi nen build:

```powershell
docker compose up --build
```

## 7. Thu tu can sua de dat full architecture

1. Them `requirements.txt` va `.env.example` cho user-service hoac sua Dockerfile.
2. Implement `/auth/admin/login` trong user-service.
3. Dong bo env examples RAG/MCP: `VECTOR_DB_URL`, `VECTOR_COLLECTION`, `EMBED_MODEL`.
4. Bo sung PostgreSQL, Qdrant, optional MinIO/GCS emulator, frontend, Langfuse vao compose neu muon one-command local stack.
5. Them migration/base schema cho user-service va document-service.
6. Implement `hr_query` trong mcp-service hoac cap nhat contracts/docs de danh dau ro la future work.
7. Neu yeu cau security bat buoc, implement Qdrant filter theo `document_ids` trong mcp-service/vectorstore de dat ACL-before-Qdrant.
8. Nang query-service health thanh live checks: DB, Redis, MCP list_tools/ping, NATS connection, auth mode.
9. Cap nhat `docs/contracts.md`, `docs/setup.md`, README root de khop code hien tai.

## 8. Troubleshooting nhanh

| Loi | Nguyen nhan hay gap | Cach xu ly |
|---|---|---|
| `env file deploy/env/*.env not found` | Chua copy tu `.env.example` | Copy cac file trong `deploy/env` |
| `COPY requirements.txt` fail khi build user-service | `src/user-service/requirements.txt` khong ton tai | Them requirements hoac sua Dockerfile |
| `JWT_SECRET_KEY must be set...` | Dung default/weak secret | Generate secret >= 32 chars |
| Query-service production fail vi mock mode | `APP_ENV=production` nhung mode con `mock` | Set `AUTH_MODE=user_service`, `MCP_MODE=real`, `NATS_MODE=nats`, `LLM_MODE=openai` |
| Query-service 503 rate limiter | `RATE_LIMITER_MODE=redis` nhung Redis khong connect duoc | Kiem tra `REDIS_URL`, start Redis |
| mcp-service exit code 1 | Qdrant collection/contract stamp thieu hoac lech | Chay rag-worker ingest, dung cung vector config |
| HR question fallback sang RAG | Real mcp-service chua co `hr_query` | Implement HR tool hoac chap nhieu fallback tam thoi |
| Notification dev endpoint 404 | `ENABLE_DEV_ENDPOINTS=false` | Chi bat true trong local dev |
