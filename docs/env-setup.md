# Environment Variables — RAG Chatbot

Mỗi service có file `.env` riêng. Copy từ `.env.example` rồi điền giá trị thực.

```bash
cp user-service/.env.example  user-service/.env
cp chat-service/.env.example  chat-service/.env
cp rag-service/.env.example   rag-service/.env
```

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở cả 3 services. User Service phát hành token; Chat Service và RAG Service verify locally bằng cùng secret — không gọi network qua User Service mỗi request.

---

## User Service — `user-service/.env.example`

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

# OpenAI
OPENAI_API_KEY=sk-...

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
| `OPENAI_API_KEY` | Key gọi LLM + Embedding | platform.openai.com → API Keys |
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

# OpenAI (Embedding only)
OPENAI_API_KEY=sk-...

# Gemini (OCR)
GEMINI_API_KEY=...

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
| `OPENAI_API_KEY` | Gọi Embedding API | platform.openai.com → API Keys |
| `GEMINI_API_KEY` | OCR cho file scan/image | aistudio.google.com → Get API Key |
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
