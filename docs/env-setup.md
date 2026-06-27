# Environment Variables — RAG Chatbot

Mỗi service có file `.env` riêng. Copy từ `.env.example` rồi điền giá trị thực.

```bash
cp src/user-service/.env.example      src/user-service/.env
cp src/document-service/.env.example  src/document-service/.env
cp src/query-service/.env.example     src/query-service/.env
cp src/rag-worker/.env.example        src/rag-worker/.env
cp src/mcp-service/.env.example       src/mcp-service/.env
cp src/hr-service/.env.example        src/hr-service/.env
```

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở các service cần verify JWT. User Service phát hành token; Document Service và Query Service verify locally bằng cùng secret — không gọi network qua User Service mỗi request. JWT cần có `user_id`, `role`, `account_type`. (RAG Worker chỉ giao tiếp NATS, MCP Service và HR Service là internal.)

---

## User Service — `src/user-service/.env.example`

```env
# Database (Cloud SQL — user_db)
DATABASE_URL=postgresql+asyncpg://user:password@<cloud-sql-ip>:5432/user_db

# JWT (phải khớp với tất cả services)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480

# Redis
REDIS_URL=redis://redis:6379/0

# Microsoft SSO (Azure AD)
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_TENANT_ID=common    # "common" = chấp nhận mọi Microsoft account
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Cloud SQL IP — database `user_db` |
| `JWT_SECRET_KEY` | Secret ký JWT — phải khớp các services verify token | Tự generate: `openssl rand -hex 32` |
| `JWT_EXPIRE_MINUTES` | Thời gian hết hạn token (phút) | Mặc định 480 = 8 giờ |
| `MICROSOFT_CLIENT_ID` | App ID đăng ký trên Azure | Azure Portal → App registrations → Application (client) ID |
| `MICROSOFT_CLIENT_SECRET` | Secret key của Azure App | Azure Portal → App registrations → Certificates & secrets |
| `MICROSOFT_TENANT_ID` | Tenant scope | `common` (mọi account) hoặc tenant ID cụ thể của công ty |

---

## Document Service — `src/document-service/.env.example`

```env
# Database (Cloud SQL — doc_db)
DATABASE_URL=postgresql+asyncpg://user:password@<cloud-sql-ip>:5432/doc_db

# JWT (shared secret — verify locally, không gọi User Service)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# NATS (publish doc.ingest, subscribe doc.status)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# GCP Cloud Storage
GCS_BUCKET=rag-chatbot-docs
GCP_PROJECT_ID=vsf-rag-chatbot
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json  # local dev only; GCE dùng instance service account
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Cloud SQL IP — database `doc_db` |
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `NATS_URL` | URL kết nối NATS broker | `nats://nats:4222` (Docker) hoặc `nats://localhost:4222` (local dev) |
| `NATS_JETSTREAM_ENABLED` | Bật JetStream để persist message — RAG Worker restart không mất job | `true` |
| `GCS_BUCKET` | Tên GCS bucket chứa file gốc | GCP Console → Cloud Storage → Create bucket |
| `GCP_PROJECT_ID` | GCP project ID | GCP Console → Project selector |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path tới service account JSON (local dev) | GCP Console → IAM → Service Accounts → Keys |

---

## Query Service — `src/query-service/.env.example`

```env
# Database (Cloud SQL — query_db)
DATABASE_URL=postgresql+asyncpg://user:password@<cloud-sql-ip>:5432/query_db

# JWT (shared secret — verify locally)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# Redis — JWT blacklist + rate limiting + semantic cache
REDIS_URL=redis://redis:6379/0

# LLM/Embedding — đi qua ai-router (gateway tương thích OpenAI). OPENAI_BASE_URL rỗng = gọi THẲNG OpenAI (kill-switch).
OPENAI_API_KEY=...
OPENAI_BASE_URL=http://ai-router:8010/v1     # set = mọi LLM/embedding qua router; rỗng = thẳng OpenAI
AIROUTER_INTERNAL_TOKEN=                       # Bearer gửi cho ai-router (tách khỏi OPENAI_API_KEY)
OPENAI_LLM_MODEL=gpt-4o-mini                   # khi base_url=ai-router, 'model' dùng ALIAS capability (answer/worker/think/plan)
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Agent (MOSA Orchestrator-Workers). OVERRIDE agents.yaml; rỗng = theo manifest (commit là 'react').
AGENT_MODE=orchestrator_workers                # prod & e2e PHẢI khớp (test_e2e_and_prod_agent_mode_consistent)

# MCP Tool Service (rag_search, hr_query, leave_write, leave_approvals, leave_types, resolve_date)
MCP_SERVICE_URL=http://mcp-service:8003
MCP_TIMEOUT_SECONDS=10

# HR Service (proxy đơn nghỉ phép — leave-requests)
HR_SERVICE_URL=http://hr-service:8004
HR_SERVICE_INTERNAL_TOKEN=

# NATS (subscribe doc.access, notify.doc_new, hr.* leave/profile, hr.department.renamed, user.deleted)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# Qdrant (dùng cho semantic cache check)
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=rag_chatbot

# Langfuse — LLM observability
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://langfuse:3100
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Cloud SQL IP — database `query_db` |
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `OPENAI_API_KEY` | Key gọi OpenAI API (LLM + Embedding semantic cache) | platform.openai.com → API keys |
| `OPENAI_BASE_URL` | Gateway LLM (ai-router); rỗng = thẳng OpenAI | `http://ai-router:8010/v1` |
| `AGENT_MODE` | Override agent mode (MOSA) | `orchestrator_workers` |
| `OPENAI_LLM_MODEL` | Model/alias LLM (alias capability khi qua ai-router) | `gpt-4o-mini` |
| `OPENAI_EMBEDDING_MODEL` | Model embedding — 1536 dims | `text-embedding-3-small` |
| `MCP_SERVICE_URL` | Endpoint MCP server (6 tool) | `http://mcp-service:8003` |
| `NATS_URL` | URL kết nối NATS (doc.access, notify.doc_new, hr.employee_profile.updated) | `nats://nats:4222` |
| `LANGFUSE_*` | LLM observability (traces, token cost, latency) | Self-hosted tại `:3100` |

---

## RAG Worker — `src/rag-worker/.env.example`

```env
# RAG Worker chạy ingest async qua NATS, đọc/ghi GCS qua S3-compatible API, index Qdrant.
# Không verify JWT; ACL được đưa vào payload/chunk để query-service/mcp-service enforce lúc search.

# OpenAI Embedding — 1536 dims
OPENAI_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Metadata DB cho ingest job/document state
DATABASE_URL=postgresql+psycopg://user:password@postgres:5432/rag_db

# NATS (subscribe doc.ingest, publish doc.status)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=rag_chatbot

# Parser + GCP Cloud Storage qua S3-compatible API
PIPELINE_CONFIG=config.yaml
PARSER_IMPL=s3
S3_ENDPOINT_URL=https://storage.googleapis.com
S3_SOURCE_BUCKET=rag-chatbot-docs
S3_REGION=auto
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...

# Local fallback only. Production artifact phải nằm ở GCS, không dựa vào /tmp.
SOURCE_ROOT=/tmp
ARTIFACT_ROOT=/tmp/artifacts

# OCR / parse
OCR_MODEL=gpt-4o-mini
MAX_OCR_PAGES=25
PDF_OCR_SCALE=2.0

# Langfuse
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://langfuse:3100
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `OPENAI_API_KEY` | Key gọi OpenAI Embedding API | platform.openai.com → API keys |
| `OPENAI_EMBEDDING_MODEL` | Model embedding 1536 dims | `text-embedding-3-small` |
| `DATABASE_URL` | Metadata DB cho ingest job/document state của rag-worker | Cloud SQL/Postgres, driver `postgresql+psycopg://` |
| `NATS_URL` | URL kết nối NATS broker | `nats://nats:4222` |
| `QDRANT_URL` | Vector DB endpoint | `http://qdrant:6333` (Docker) hoặc `http://localhost:6333` (local) |
| `QDRANT_COLLECTION` | Tên collection Qdrant | Giữ nguyên `rag_chatbot` |
| `PIPELINE_CONFIG` | File config pipeline của rag-worker | Thường là `config.yaml` |
| `PARSER_IMPL` | Parser nguồn file; production GCP dùng `s3` | `s3` |
| `S3_ENDPOINT_URL` | Endpoint S3-compatible để trỏ tới GCS | `https://storage.googleapis.com` |
| `S3_SOURCE_BUCKET` | Bucket chứa file raw và Markdown artifact | GCP Cloud Storage bucket |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | HMAC key để boto3 đọc/ghi GCS | GCP Storage HMAC key hoặc secret manager |
| `OCR_MODEL` | Model OCR ảnh/PDF scan | `gpt-4o-mini` theo config hiện tại |
| `MAX_OCR_PAGES` | Giới hạn số trang OCR để tránh runaway cost | Theo budget ingestion |
| `PDF_OCR_SCALE` | Scale render PDF page trước OCR | `2.0` mặc định hợp lý |
| `ARTIFACT_ROOT` | Thư mục artifact local fallback | Chỉ dùng dev/local; production phải ghi GCS |

Production invariant của ingest:

```text
raw object in GCS -> parse/OCR -> gs://<S3_SOURCE_BUCKET>/artifacts/<document_id>/markdown.md -> chunk/embed -> Qdrant
```

Nếu `PARSER_IMPL=s3` và `S3_SOURCE_BUCKET` được cấu hình, rag-worker dùng GCS/S3 artifact store. Nếu thiếu một trong hai, service có thể rơi về local artifact store (`ARTIFACT_ROOT`), chỉ phù hợp dev/offline và không đạt chuẩn production trên GCP.

---

## MCP Tool Service — `src/mcp-service/.env.example`

```env
# MCP server / auth (mcp-service KHÔNG dùng PostgreSQL/NATS — search-only + hr proxy)
MCP_HOST=0.0.0.0
MCP_PORT=8003
MCP_INTERNAL_TOKEN=                 # shared secret cho header X-Internal-Token (trống = auth TẮT)
LOG_LEVEL=INFO

# Tool rag_search — embed query
EMBED_MODEL=text-embedding-3-small
EMBED_BASE_URL=
OPENAI_API_KEY=...
EMBED_DIMENSION=

# Tool rag_search — vector store (đọc Qdrant TRỰC TIẾP, không qua NATS/RAG Worker)
VECTOR_DB_PROVIDER=qdrant
VECTOR_COLLECTION=rag_chatbot
VECTOR_DB_URL=http://qdrant:6333
VECTOR_DB_API_KEY=

# Tool rag_search — reranker: none | lexical | llm (KHÔNG self-host BGE)
RERANK_PROVIDER=none
RERANK_MODEL=gpt-4o-mini            # chỉ dùng khi RERANK_PROVIDER=llm
RERANK_TIMEOUT_SECONDS=30
SEARCH_TOP_K=20                     # số candidates đọc từ Qdrant
RERANK_TOP_K=3                      # số kết quả sau rerank
RERANK_THRESHOLD=0.7

# Tool hr_query — HTTP proxy sang hr-service (mặc định TẮT)
TOOL_HR_QUERY_ENABLED=0
HR_SERVICE_URL=http://hr-service:8004
HR_SERVICE_INTERNAL_TOKEN=
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `MCP_HOST` / `MCP_PORT` | Host + port MCP server (Streamable HTTP, path `/mcp`) | `0.0.0.0` / `8003` |
| `MCP_INTERNAL_TOKEN` | Shared secret cho `X-Internal-Token`; trống = auth tắt (fail-open) | Tự generate |
| `EMBED_MODEL` / `OPENAI_API_KEY` | Model + key embed query | `text-embedding-3-small` |
| `VECTOR_DB_URL` / `VECTOR_COLLECTION` | Qdrant mcp-service đọc trực tiếp (cùng collection rag-worker ghi) | `http://qdrant:6333` / `rag_chatbot` |
| `RERANK_PROVIDER` | `none` \| `lexical` \| `llm` (fallback NoopReranker khi llm lỗi) | `none` |
| `RERANK_TOP_K` / `RERANK_THRESHOLD` | Số kết quả sau rerank + ngưỡng score | `3` / `0.7` |
| `TOOL_HR_QUERY_ENABLED` | Bật/tắt tool `hr_query` | `0` (tắt) |
| `HR_SERVICE_URL` / `HR_SERVICE_INTERNAL_TOKEN` | Endpoint + token hr-service cho tool `hr_query` | `http://hr-service:8004` |

---

## HR Service — `src/hr-service/.env.example`

```env
# Database (Cloud SQL — hr_db)
DATABASE_URL=postgresql+asyncpg://user:password@<cloud-sql-ip>:5432/hr_db

# JWT (optional, nếu endpoint internal cần verify token/service token)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# NATS (publish hr.leave_request.* + hr.employee_profile.updated + hr.department.renamed) — ĐÃ wire
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# Approver mặc định khi nhân viên không có manager
HR_DEFAULT_APPROVER=

# HR server
HR_SERVICE_PORT=8004
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Cloud SQL IP — database `hr_db` |
| `JWT_SECRET_KEY` | Verify JWT cho nhóm `/hr/admin/*` | Dùng cùng key đã generate |
| `NATS_URL` | Publish `hr.leave_request.*`, `hr.employee_profile.updated`, `hr.department.renamed` | `nats://nats:4222` |
| `HR_DEFAULT_APPROVER` | Approver fallback khi nhân viên thiếu `manager_user_id` | user_id 1 quản lý |
| `HR_SERVICE_PORT` | Port internal của HR Service | `8004` |

---

## AI Router — `src/ai-router/` (gateway LLM, :8010 internal)

```env
# Multi-pool key — auto-discover theo pattern (loại key đơn cũ)
OPENAI_API_KEY_1=sk-...
OPENROUTER_API_KEY_1=sk-or-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# State/quota: Redis (None = in-memory, chỉ dev)
AIROUTER_REDIS_URL=redis://redis:6379/3
AIROUTER_INTERNAL_TOKEN=                 # Bearer các service gửi khi route (có thể rỗng vì bind 127.0.0.1)

# Trần quota mỗi nhà cung cấp (spill khi chạm)
AIROUTER_OPENAI_TOKENS_PER_DAY=...
AIROUTER_OPENROUTER_REQ_PER_DAY=...
AIROUTER_OPENROUTER_RPM=...
AIROUTER_RECONCILE_ON_BOOT=0             # opt-in reconcile lúc khởi động
```

> Cấu hình thuật toán/model: `src/ai-router/routing.yaml` (selector `sticky_rotation_soft`, capability→tier→model, hot-reload qua `POST /admin/reload`) + `config/model_catalog.json` (build từ OpenRouter `/models` mỗi deploy). Bind `127.0.0.1:8010` — `/admin/*` truy cập qua SSH tunnel.

---

## Frontend — 2 micro-frontend (`frontend/base` layer không cần env riêng)

### Chat app — `src/frontend/chat/.env.local.example`
```env
# Local development
NUXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000   # auth /auth
NUXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001  # chat SSE + notifications
# Production (GCP) — cùng domain, Nginx route theo path prefix
# NUXT_PUBLIC_USER_SERVICE_URL=/api/user
# NUXT_PUBLIC_QUERY_SERVICE_URL=/api/query
```

### Admin console — `src/frontend/admin/.env.local.example`
```env
# Local development
NUXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000      # auth /auth + quản lý user /users
NUXT_PUBLIC_DOCUMENT_SERVICE_URL=http://localhost:8002  # quản lý tài liệu
NUXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001     # /admin/metrics
# Production (GCP)
# NUXT_PUBLIC_USER_SERVICE_URL=/api/user
# NUXT_PUBLIC_DOCUMENT_SERVICE_URL=/api/documents
# NUXT_PUBLIC_QUERY_SERVICE_URL=/api/query
```

| Biến | Mô tả | App |
|------|-------|-----|
| `NUXT_PUBLIC_USER_SERVICE_URL` | Auth `/auth` (cả 2 app) + `/users` (Admin) | Chat + Admin |
| `NUXT_PUBLIC_DOCUMENT_SERVICE_URL` | Upload / quản lý tài liệu (Admin only) | Admin |
| `NUXT_PUBLIC_QUERY_SERVICE_URL` | Query / conversations / feedback (Chat); `/admin/metrics` (Admin) | Chat + Admin |

> **Production note:** Frontend deploy cùng GCE với backend. Nginx route `/api/user/*` → `user-service:8000`, `/api/documents/*` → `document-service:8002`, `/api/query/*` → `query_pool` (8 replica query-service:8001), `/api/hr/*` → `hr-service:8004`, `/api/mcp/*` → `mcp-service:8003`. Không cần CORS vì cùng domain. `ai-router:8010` **không** route public (bind 127.0.0.1, chỉ service nội bộ + SSH tunnel). Frontend đơn nghỉ phép đi qua `/api/query/leave-requests` (query-service inject `user_id` từ JWT) — KHÔNG gọi thẳng hr-service.

---

## Langfuse — Environment Variables (docker-compose.yml)

```env
LANGFUSE_PORT=3100
LANGFUSE_NEXTAUTH_SECRET=...      # generate: openssl rand -hex 32
LANGFUSE_SALT=...                  # generate: openssl rand -hex 32
DATABASE_URL=postgresql://user:password@<cloud-sql-ip>:5432/langfuse_db
```

> Langfuse chạy trên port **:3100** (tránh conflict với Nuxt: chat :3000, admin :3001). Truy cập dashboard tại `http://<gce-ip>:3100` — IT/DevOps only.

---

## Generate JWT_SECRET_KEY

```bash
# Option 1 — OpenSSL
openssl rand -hex 32

# Option 2 — Python
python -c "import secrets; print(secrets.token_hex(32))"
```

Dùng cùng output này cho `JWT_SECRET_KEY` trong các file `.env` của service verify token (user-service, document-service, query-service; mcp-service nếu bật verify nội bộ).
