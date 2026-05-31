# Environment Variables — RAG Chatbot

Mỗi service có file `.env` riêng. Copy từ `.env.example` rồi điền giá trị thực.

```bash
cp src/user-service/.env.example  src/user-service/.env
cp chat-service/.env.example  chat-service/.env
cp rag-service/.env.example   rag-service/.env
```

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở cả 3 services. User Service phát hành token; Chat Service và RAG Service verify locally bằng cùng secret — không gọi network qua User Service mỗi request.

---

## User Service — `src/user-service/.env.example`

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot

# JWT (phải khớp với Chat Service và RAG Service)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480

# Redis
REDIS_URL=redis://localhost:6379/0

# Microsoft SSO (Azure AD)
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_TENANT_ID=common    # "common" = chấp nhận mọi Microsoft account
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `DATABASE_URL` | Connection string PostgreSQL | Docker local hoặc RDS endpoint |
| `JWT_SECRET_KEY` | Secret ký JWT — phải khớp cả 3 services | Tự generate: `openssl rand -hex 32` |
| `JWT_EXPIRE_MINUTES` | Thời gian hết hạn token (phút) | Mặc định 480 = 8 giờ |
| `MICROSOFT_CLIENT_ID` | App ID đăng ký trên Azure | Azure Portal → App registrations → Application (client) ID |
| `MICROSOFT_CLIENT_SECRET` | Secret key của Azure App | Azure Portal → App registrations → Certificates & secrets |
| `MICROSOFT_TENANT_ID` | Tenant scope | `common` (mọi account) hoặc tenant ID cụ thể của công ty |

---

## Chat Service — `chat-service/.env.example`

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot

# JWT (shared secret — verify locally, không gọi User Service)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# Redis
REDIS_URL=redis://localhost:6379/0

# Azure OpenAI — LLM (Chat Completion + Streaming)
AZURE_OPENAI_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-02-01

# Service URLs (internal)
RAG_SERVICE_URL=http://localhost:8002

# Langfuse
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://localhost:3000
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `AZURE_OPENAI_KEY` | Key gọi Azure OpenAI LLM | Azure Portal → resource → Keys and Endpoint |
| `AZURE_OPENAI_ENDPOINT` | Endpoint của Azure OpenAI resource | Azure Portal → resource → Keys and Endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | Tên deployment model trên Azure | Azure OpenAI Studio → Deployments |
| `RAG_SERVICE_URL` | URL nội bộ tới RAG Service | `http://localhost:8002` (local) hoặc tên container trong Docker Compose |
| `LANGFUSE_*` | LLM observability | langfuse.com → Project Settings |

---

## RAG Service — `rag-service/.env.example`

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot

# JWT (shared secret — verify locally)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256

# Azure OpenAI — dùng cho Query Rewriting (sinh 3 biến thể câu hỏi trước khi search, tăng recall)
# Phase 1 MVP chưa dùng — chuẩn bị sẵn cho Phase 2
AZURE_OPENAI_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-02-01

# Azure Document Intelligence — OCR cho PDF scan
AZURE_DOC_INTEL_KEY=...
AZURE_DOC_INTEL_ENDPOINT=https://your-resource.cognitiveservices.azure.com

# BGE-M3 Embedding Service (self-hosted)
BGE_M3_URL=http://localhost:8003
BGE_M3_MODEL=BAAI/bge-m3

# BGE Reranker (self-hosted)
BGE_RERANKER_URL=http://localhost:8004
BGE_RERANKER_MODEL=BAAI/bge-reranker-v2-m3

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=rag_chatbot

# AWS S3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET=rag-chatbot-docs
AWS_REGION=ap-southeast-1

# Langfuse
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://localhost:3000
```

| Biến | Mô tả | Lấy ở đâu |
|------|-------|-----------|
| `JWT_SECRET_KEY` | Phải khớp với User Service | Dùng cùng key đã generate |
| `AZURE_OPENAI_KEY` | Key gọi Azure OpenAI — dùng cho Query Rewriting (Phase 2), **không** dùng cho embedding | Azure Portal → resource → Keys and Endpoint |
| `AZURE_OPENAI_ENDPOINT` | Endpoint của Azure OpenAI resource | Azure Portal → resource → Keys and Endpoint |
| `AZURE_DOC_INTEL_KEY` | Key gọi Azure Document Intelligence OCR | Azure Portal → resource → Keys and Endpoint |
| `AZURE_DOC_INTEL_ENDPOINT` | Endpoint Azure Document Intelligence | Azure Portal → resource → Keys and Endpoint |
| `BGE_M3_URL` | URL tới BGE-M3 Embedding service (self-hosted) | EC2 nội bộ hoặc `http://localhost:8003` local |
| `BGE_RERANKER_URL` | URL tới BGE-Reranker service (self-hosted) | EC2 nội bộ hoặc `http://localhost:8004` local |
| `QDRANT_URL` | Vector DB endpoint | `http://localhost:6333` (local Docker) |
| `QDRANT_COLLECTION` | Tên collection Qdrant | Giữ nguyên `rag_chatbot` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Credentials upload file lên S3 | AWS Console → IAM → Users → Security credentials |
| `AWS_S3_BUCKET` | Tên S3 bucket chứa file gốc | Tạo bucket trong AWS Console |
| `AWS_REGION` | AWS region | `ap-southeast-1` (Singapore) |

---

## Frontend — `frontend/.env.local.example`

```env
# Local development — trỏ trực tiếp tới từng service
NEXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000
NEXT_PUBLIC_CHAT_SERVICE_URL=http://localhost:8001
```

```env
# Production (AWS) — cùng domain, Nginx route theo path prefix
NEXT_PUBLIC_USER_SERVICE_URL=/api/user
NEXT_PUBLIC_CHAT_SERVICE_URL=/api/chat
```

| Biến | Mô tả |
|------|-------|
| `NEXT_PUBLIC_USER_SERVICE_URL` | URL login / lấy user info |
| `NEXT_PUBLIC_CHAT_SERVICE_URL` | URL upload document / query / conversations |

> **Production note:** Frontend deploy cùng EC2 với backend. Nginx route `/api/user/*` → `user-service:8000`, `/api/chat/*` → `chat-service:8001`. Không cần CORS config vì cùng domain.

---

## Generate JWT_SECRET_KEY

```bash
# Option 1 — OpenSSL
openssl rand -hex 32

# Option 2 — Python
python -c "import secrets; print(secrets.token_hex(32))"
```

Dùng cùng output này cho `JWT_SECRET_KEY` trong cả 3 file `.env`.
