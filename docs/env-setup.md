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

# OpenAI — LLM (streaming + tool_call) + Embedding
OPENAI_API_KEY=...
OPENAI_LLM_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# MCP Tool Service (gọi tool rag_search, hr_query qua MCP)
MCP_SERVICE_URL=http://mcp-service:8003
MCP_TIMEOUT_SECONDS=10

# NATS (subscribe doc.access + notify.doc_new + hr.employee_profile.updated)
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
| `OPENAI_LLM_MODEL` | Model LLM — streaming + Function Calling | `gpt-4o-mini` |
| `OPENAI_EMBEDDING_MODEL` | Model embedding — 1536 dims | `text-embedding-3-small` |
| `MCP_SERVICE_URL` | Endpoint MCP server (rag_search, hr_query) | `http://mcp-service:8003` |
| `NATS_URL` | URL kết nối NATS (doc.access, notify.doc_new, hr.employee_profile.updated) | `nats://nats:4222` |
| `LANGFUSE_*` | LLM observability (traces, token cost, latency) | Self-hosted tại `:3100` |

---

## RAG Worker — `src/rag-worker/.env.example`

```env
# RAG Worker KHÔNG dùng PostgreSQL (no DATABASE_URL) — chỉ Qdrant + Cloud Storage (GCS) + NATS.
# Không expose HTTP nên không verify JWT.

# OpenAI Embedding — 1536 dims
OPENAI_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Gemini Vision API — OCR cho PDF scan
GEMINI_API_KEY=...

# NATS (subscribe doc.ingest, publish doc.status)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=rag_chatbot

# GCP Cloud Storage
GCS_BUCKET=rag-chatbot-docs
GCP_PROJECT_ID=vsf-rag-chatbot
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json  # local dev only; GCE dùng instance service account

# Langfuse
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://langfuse:3100
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `OPENAI_API_KEY` | Key gọi OpenAI Embedding API | platform.openai.com → API keys |
| `OPENAI_EMBEDDING_MODEL` | Model embedding 1536 dims | `text-embedding-3-small` |
| `GEMINI_API_KEY` | Key gọi Gemini Vision API — OCR PDF scan tiếng Việt | console.cloud.google.com → APIs & Services → Credentials |
| `NATS_URL` | URL kết nối NATS broker | `nats://nats:4222` |
| `QDRANT_URL` | Vector DB endpoint | `http://qdrant:6333` (Docker) hoặc `http://localhost:6333` (local) |
| `QDRANT_COLLECTION` | Tên collection Qdrant | Giữ nguyên `rag_chatbot` |
| `GCS_BUCKET` | Tên GCS bucket chứa file gốc | GCP Console → Cloud Storage → Create bucket |
| `GCP_PROJECT_ID` | GCP project ID | GCP Console → Project selector |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path tới service account JSON (local dev) | GCP Console → IAM → Service Accounts → Keys |

---

## MCP Tool Service — `src/mcp-service/.env.example`

```env
# Database (Cloud SQL — mcp_db, chỉ chứa tool metadata/config nếu cần)
DATABASE_URL=postgresql+asyncpg://user:password@<cloud-sql-ip>:5432/mcp_db

# JWT (verify token nội bộ do Query Service truyền — optional)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# NATS (request-reply rag.search tới RAG Worker)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# OpenAI (query rewrite trong tool rag_search)
OPENAI_API_KEY=...
OPENAI_LLM_MODEL=gpt-4o-mini

# BGE-Reranker-v2-m3 (load inline trong container)
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_TOP_N=3

# HR Service (tool hr_query gọi nội bộ)
HR_SERVICE_URL=http://hr-service:8004
HR_SERVICE_TIMEOUT_SECONDS=5

# MCP server
MCP_TRANSPORT=streamable-http
MCP_PORT=8003
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Cloud SQL IP — database `mcp_db` (tool metadata/config nếu cần) |
| `JWT_SECRET_KEY` | Phải khớp với User Service (nếu verify token nội bộ) | Dùng cùng key đã generate |
| `NATS_URL` | URL kết nối NATS (gọi rag.search tới RAG Worker) | `nats://nats:4222` |
| `OPENAI_API_KEY` | Key gọi OpenAI (query rewrite) | platform.openai.com → API keys |
| `RERANKER_MODEL` | Model rerank cross-encoder | `BAAI/bge-reranker-v2-m3` |
| `HR_SERVICE_URL` | Endpoint HR Service nội bộ cho tool `hr_query` | `http://hr-service:8004` |
| `MCP_TRANSPORT` / `MCP_PORT` | Transport + port MCP server | `streamable-http` / `8003` |

---

## HR Service — `src/hr-service/.env.example`

```env
# Database (Cloud SQL — hr_db)
DATABASE_URL=postgresql+asyncpg://user:password@<cloud-sql-ip>:5432/hr_db

# JWT (optional, nếu endpoint internal cần verify token/service token)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# NATS (publish hr.employee_profile.updated cho Query Service projection)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# HR server
HR_SERVICE_PORT=8004
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Cloud SQL IP — database `hr_db` |
| `JWT_SECRET_KEY` | Dùng cùng key nếu endpoint internal verify JWT/service token | Dùng cùng key đã generate |
| `NATS_URL` | URL kết nối NATS để publish `hr.employee_profile.updated` | `nats://nats:4222` |
| `HR_SERVICE_PORT` | Port internal của HR Service | `8004` |

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

> **Production note:** Frontend deploy cùng GCE với backend. Nginx route `/api/user/*` → `user-service:8000`, `/api/documents/*` → `document-service:8002`, `/api/query/*` → `query-service:8001`, `/api/mcp/*` → `mcp-service:8003` nếu cần debug/tool gateway. Không cần CORS config vì cùng domain. `hr-service:8004` deploy cùng Docker Compose nhưng **internal only**, không route public qua Nginx; MCP Service gọi nội bộ bằng `HR_SERVICE_URL`.

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
