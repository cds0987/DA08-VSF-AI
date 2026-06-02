# Environment Variables — RAG Chatbot

Mỗi service có file `.env` riêng. Copy từ `.env.example` rồi điền giá trị thực.

```bash
cp src/user-service/.env.example      src/user-service/.env
cp src/document-service/.env.example  src/document-service/.env
cp src/query-service/.env.example     src/query-service/.env
cp src/rag-worker/.env.example        src/rag-worker/.env
```

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở cả 4 services. User Service phát hành token; Document Service, Query Service và RAG Worker verify locally bằng cùng secret — không gọi network qua User Service mỗi request.

---

## User Service — `src/user-service/.env.example`

```env
# Database (RDS — user_db)
DATABASE_URL=postgresql+asyncpg://user:password@<rds-endpoint>:5432/user_db

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
| `DATABASE_URL` | Connection string PostgreSQL | RDS endpoint — database `user_db` |
| `JWT_SECRET_KEY` | Secret ký JWT — phải khớp cả 4 services | Tự generate: `openssl rand -hex 32` |
| `JWT_EXPIRE_MINUTES` | Thời gian hết hạn token (phút) | Mặc định 480 = 8 giờ |
| `MICROSOFT_CLIENT_ID` | App ID đăng ký trên Azure | Azure Portal → App registrations → Application (client) ID |
| `MICROSOFT_CLIENT_SECRET` | Secret key của Azure App | Azure Portal → App registrations → Certificates & secrets |
| `MICROSOFT_TENANT_ID` | Tenant scope | `common` (mọi account) hoặc tenant ID cụ thể của công ty |

---

## Document Service — `src/document-service/.env.example`

```env
# Database (RDS — doc_db)
DATABASE_URL=postgresql+asyncpg://user:password@<rds-endpoint>:5432/doc_db

# JWT (shared secret — verify locally, không gọi User Service)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# NATS (publish doc.ingest, subscribe doc.status)
NATS_URL=nats://nats:4222
NATS_JETSTREAM_ENABLED=true

# AWS S3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET=rag-chatbot-docs
AWS_REGION=ap-southeast-1
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | RDS endpoint — database `doc_db` |
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `NATS_URL` | URL kết nối NATS broker | `nats://nats:4222` (Docker) hoặc `nats://localhost:4222` (local dev) |
| `NATS_JETSTREAM_ENABLED` | Bật JetStream để persist message — RAG Worker restart không mất job | `true` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Credentials upload file lên S3 | AWS Console → IAM → Users → Security credentials |
| `AWS_S3_BUCKET` | Tên S3 bucket chứa file gốc | Tạo bucket trong AWS Console |
| `AWS_REGION` | AWS region | `ap-southeast-1` (Singapore) |

---

## Query Service — `src/query-service/.env.example`

```env
# Database (RDS — query_db)
DATABASE_URL=postgresql+asyncpg://user:password@<rds-endpoint>:5432/query_db

# JWT (shared secret — verify locally)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# Redis — JWT blacklist + rate limiting + semantic cache
REDIS_URL=redis://redis:6379/0

# OpenAI — LLM (streaming + tool_call) + Embedding
OPENAI_API_KEY=...
OPENAI_LLM_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# NATS (request-reply rag.search)
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
| `DATABASE_URL` | Connection string PostgreSQL | RDS endpoint — database `query_db` |
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `OPENAI_API_KEY` | Key gọi OpenAI API (LLM + Embedding) | platform.openai.com → API keys |
| `OPENAI_LLM_MODEL` | Model LLM — streaming + Function Calling | `gpt-4o-mini` |
| `OPENAI_EMBEDDING_MODEL` | Model embedding — 1536 dims | `text-embedding-3-small` |
| `NATS_URL` | URL kết nối NATS broker | `nats://nats:4222` |
| `LANGFUSE_*` | LLM observability (traces, token cost, latency) | Self-hosted tại `:3100` |

---

## RAG Worker — `src/rag-worker/.env.example`

```env
# Database (RDS — doc_db, dùng chung với Document Service)
DATABASE_URL=postgresql+asyncpg://user:password@<rds-endpoint>:5432/doc_db

# JWT (shared secret — verify locally)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

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

# AWS S3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET=rag-chatbot-docs
AWS_REGION=ap-southeast-1

# Langfuse
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://langfuse:3100
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | RDS endpoint — database `doc_db` |
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `OPENAI_API_KEY` | Key gọi OpenAI Embedding API | platform.openai.com → API keys |
| `OPENAI_EMBEDDING_MODEL` | Model embedding 1536 dims | `text-embedding-3-small` |
| `GEMINI_API_KEY` | Key gọi Gemini Vision API — OCR PDF scan tiếng Việt | console.cloud.google.com → APIs & Services → Credentials |
| `NATS_URL` | URL kết nối NATS broker | `nats://nats:4222` |
| `QDRANT_URL` | Vector DB endpoint | `http://qdrant:6333` (Docker) hoặc `http://localhost:6333` (local) |
| `QDRANT_COLLECTION` | Tên collection Qdrant | Giữ nguyên `rag_chatbot` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Credentials download file từ S3 | AWS Console → IAM → Users → Security credentials |
| `AWS_REGION` | AWS region | `ap-southeast-1` (Singapore) |

---

## Frontend — `src/frontend/.env.local.example`

```env
# Local development — trỏ trực tiếp tới từng service
NEXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000
NEXT_PUBLIC_DOCUMENT_SERVICE_URL=http://localhost:8002
NEXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001
```

```env
# Production (AWS) — cùng domain, Nginx route theo path prefix
NEXT_PUBLIC_USER_SERVICE_URL=/api/user
NEXT_PUBLIC_DOCUMENT_SERVICE_URL=/api/documents
NEXT_PUBLIC_QUERY_SERVICE_URL=/api/query
```

| Biến | Mô tả |
|------|-------|
| `NEXT_PUBLIC_USER_SERVICE_URL` | URL login / lấy user info |
| `NEXT_PUBLIC_DOCUMENT_SERVICE_URL` | URL upload document / quản lý tài liệu (Admin only) |
| `NEXT_PUBLIC_QUERY_SERVICE_URL` | URL query / conversations / feedback |

> **Production note:** Frontend deploy cùng EC2 với backend. Nginx route `/api/user/*` → `user-service:8000`, `/api/documents/*` → `document-service:8002`, `/api/query/*` → `query-service:8001`. Không cần CORS config vì cùng domain.

---

## Langfuse — Environment Variables (docker-compose.yml)

```env
LANGFUSE_PORT=3100
LANGFUSE_NEXTAUTH_SECRET=...      # generate: openssl rand -hex 32
LANGFUSE_SALT=...                  # generate: openssl rand -hex 32
DATABASE_URL=postgresql://user:password@<rds-endpoint>:5432/langfuse_db
```

> Langfuse chạy trên port **:3100** (tránh conflict với Next.js frontend :3000). Truy cập dashboard tại `http://<ec2-ip>:3100` — IT/DevOps only.

---

## Generate JWT_SECRET_KEY

```bash
# Option 1 — OpenSSL
openssl rand -hex 32

# Option 2 — Python
python -c "import secrets; print(secrets.token_hex(32))"
```

Dùng cùng output này cho `JWT_SECRET_KEY` trong cả 4 file `.env`.
