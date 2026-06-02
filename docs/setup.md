# Setup Guide — RAG Chatbot Local Development

## Prerequisites

| Tool | Version | Cài đặt |
|------|---------|---------|
| Python | 3.11+ | python.org |
| Node.js | 18+ | nodejs.org |
| Docker Desktop | Latest | docker.com |
| Git | Latest | git-scm.com |

---

## 1. Clone repo

```bash
git clone <repo-url>
cd rag-chatbot
```

---

## 2. Backend setup

Project có **4 backend services** độc lập. Mỗi service có `requirements.txt` riêng.

```bash
# User Service (Backend Dev)
cd src/user-service
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt

# Document Service (Backend Dev)
cd ../document-service
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Query Service (AI/Agent Engineer)
cd ../query-service
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# RAG Worker (RAG Engineer)
cd ../rag-worker
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> Mỗi thành viên chỉ cần setup service mình phụ trách. Setup tất cả nếu chạy full local.

---

## 3. Environment variables

Mỗi service có file `.env` riêng. Copy từ `.env.example` trong từng folder:

```bash
cp src/user-service/.env.example    src/user-service/.env
cp src/document-service/.env.example  src/document-service/.env
cp src/query-service/.env.example   src/query-service/.env
cp src/rag-worker/.env.example      src/rag-worker/.env
```

Xem đầy đủ nội dung từng file và hướng dẫn lấy API keys tại **[docs/env-setup.md](env-setup.md)**.

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở cả 4 services. Generate bằng `openssl rand -hex 32` rồi điền vào cả 4 file `.env`.
>
> **NATS URL:** Tất cả services kết nối NATS qua `NATS_URL=nats://nats:4222` (Docker network) hoặc `nats://localhost:4222` (local dev).

---

## 4. Chạy PostgreSQL + Qdrant local (Docker)

```bash
# PostgreSQL
docker run -d \
  --name rag-postgres \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=rag_chatbot \
  -p 5432:5432 \
  postgres:15

# Qdrant — mount volume để persist data khi restart container
docker run -d \
  --name rag-qdrant \
  -p 6333:6333 \
  -v qdrant_data:/qdrant/storage \
  qdrant/qdrant

# Redis — JWT blacklist + rate limiting
docker run -d \
  --name rag-redis \
  -p 6379:6379 \
  redis:7-alpine
```

Sau khi PostgreSQL chạy, tạo schemas và apply migrations:

```bash
docker exec -it rag-postgres psql -U user -d rag_chatbot -c "
  CREATE SCHEMA IF NOT EXISTS user_svc;
  CREATE SCHEMA IF NOT EXISTS ingest_svc;
  CREATE SCHEMA IF NOT EXISTS query_svc;
  CREATE SCHEMA IF NOT EXISTS rag_svc;
  CREATE SCHEMA IF NOT EXISTS hr_mock;
"
```

Tạo tables bằng Alembic (mỗi service có `alembic/` riêng):

```bash
cd src/user-service    && alembic upgrade head
cd ../document-service  && alembic upgrade head
cd ../query-service   && alembic upgrade head
cd ../rag-worker      && alembic upgrade head
```

> Schema thay đổi → tạo migration mới (`alembic revision --autogenerate -m "..."`) thay vì sửa DDL trực tiếp.

---

## 5. Chạy services local

Mỗi service chạy trên port riêng. Mở 5 terminal (hoặc dùng Docker Compose — Section 8):

```bash
# Terminal 0 — NATS (cần chạy trước)
docker run -d --name rag-nats -p 4222:4222 -p 8222:8222 nats:latest

# Terminal 1 — User Service (port 8000)
cd src/user-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8000

# Terminal 2 — Document Service (port 8001)
cd src/document-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8001

# Terminal 3 — Query Service (port 8002)
cd src/query-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8002

# Terminal 4 — RAG Worker (no port — NATS subscriber)
cd src/rag-worker
venv\Scripts\activate
python app/main.py
```

API docs tự động:
- User Service: http://localhost:8000/docs
- Document Service: http://localhost:8001/docs
- Query Service: http://localhost:8002/docs
- NATS Monitoring: http://localhost:8222

---

## 6. Frontend setup

```bash
cd src/frontend

npm install

cp .env.local.example .env.local
# Điền:
#   NEXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000
#   NEXT_PUBLIC_DOCUMENT_SERVICE_URL=http://localhost:8001
#   NEXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8002

npm run dev
```

Frontend tại: http://localhost:3000

---

## 7. Chạy tests

```bash
# User Service
cd src/user-service
pytest tests/ -v

# Document Service
cd src/document-service
pytest tests/ -v

# Query Service
cd src/query-service
pytest tests/ -v

# RAG Worker
cd src/rag-worker
pytest tests/ -v

# Với coverage (ví dụ RAG Worker)
cd src/rag-worker
pytest --cov=app tests/
```

---

## 8. Docker Compose — Chạy toàn bộ stack

Thay vì chạy 3 terminal riêng, dùng Docker Compose để start tất cả cùng lúc:

```bash
# Build + start tất cả services
docker compose up --build

# Chỉ start (đã build rồi)
docker compose up

# Xem log của 1 service cụ thể
docker compose logs -f query-service

# Stop
docker compose down
```

Services sau khi `docker compose up`:

| Container | Port | Mô tả |
|-----------|------|-------|
| nginx | 80 / 443 | Reverse proxy, entry point — route `/` → frontend, `/api/*` → backend |
| next-frontend | 3000 | Next.js UI (production build) |
| user-service | 8000 | Auth / User management |
| document-service | 8001 | Document management (Admin only) |
| query-service | 8002 | User chat / LLM Orchestration |
| rag-worker | — | NATS Worker — ingestion + retrieval (no HTTP port) |
| nats | 4222 / 8222 | Message broker (4222: client, 8222: monitoring UI) |
| qdrant | 6333 | Vector database |
| redis | 6379 | JWT blacklist + rate limiting + semantic cache |
| langfuse | 4000 | LLM observability dashboard (IT/DevOps only) |
| postgres | 5432 | PostgreSQL (shared, tách schema) |

---

## Troubleshooting

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `Connection refused 5432` | PostgreSQL chưa chạy | Chạy lại docker run postgres |
| `Connection refused 6333` | Qdrant chưa chạy | Chạy lại docker run qdrant |
| `Connection refused 6379` | Redis chưa chạy | Chạy lại docker run redis |
| `Invalid signature` (JWT) | `JWT_SECRET_KEY` không khớp giữa services | Kiểm tra `.env` của 3 services phải dùng cùng key |
| `Invalid API Key` | `.env` chưa điền đúng | Kiểm tra lại `.env` |
| `ModuleNotFoundError` | Chưa activate venv đúng service | `cd <service-folder> && venv\Scripts\activate` |
| `QDRANT_URL not set` | Thiếu env var | Kiểm tra `src/rag-worker/.env` |
| `Connection refused 8001` (Document Service) | Document Service chưa chạy | Start Document Service trước |
