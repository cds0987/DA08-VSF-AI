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

Project có **3 backend services** độc lập. Mỗi service có `requirements.txt` riêng.

```bash
# User Service (Backend Dev)
cd src/user-service
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt

# Chat Service (AI/Agent Engineer)
cd ../chat-service
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# RAG Service (RAG Engineer)
cd ../rag-service
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> Mỗi thành viên chỉ cần setup service mình phụ trách. Setup tất cả nếu chạy full local.

---

## 3. Environment variables

Mỗi service có file `.env` riêng. Copy từ `.env.example` trong từng folder:

```bash
cp src/user-service/.env.example  src/user-service/.env
cp src/chat-service/.env.example  src/chat-service/.env
cp src/rag-service/.env.example   src/rag-service/.env
```

Xem đầy đủ nội dung từng file và hướng dẫn lấy API keys tại **[docs/env-setup.md](env-setup.md)**.

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở cả 3 services. Generate bằng `openssl rand -hex 32` rồi điền vào cả 3 file `.env`.

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

# Qdrant
docker run -d \
  --name rag-qdrant \
  -p 6333:6333 \
  qdrant/qdrant
```

Sau khi PostgreSQL chạy, tạo schemas:

```bash
docker exec -it rag-postgres psql -U user -d rag_chatbot -c "
  CREATE SCHEMA IF NOT EXISTS user_svc;
  CREATE SCHEMA IF NOT EXISTS chat_svc;
  CREATE SCHEMA IF NOT EXISTS rag_svc;
  CREATE SCHEMA IF NOT EXISTS hr_mock;
"
```

---

## 5. Chạy 3 services local

Mỗi service chạy trên port riêng. Mở 3 terminal:

```bash
# Terminal 1 — User Service (port 8000)
cd src/user-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8000

# Terminal 2 — Chat Service (port 8001)
cd src/chat-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8001

# Terminal 3 — RAG Service (port 8002)
cd src/rag-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8002
```

API docs tự động:
- User Service: http://localhost:8000/docs
- Chat Service: http://localhost:8001/docs
- RAG Service: http://localhost:8002/docs

---

## 6. Frontend setup

```bash
cd src/frontend

npm install

cp .env.local.example .env.local
# Điền:
#   NEXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000
#   NEXT_PUBLIC_CHAT_SERVICE_URL=http://localhost:8001

npm run dev
```

Frontend tại: http://localhost:3000

---

## 7. Chạy tests

```bash
# User Service
cd src/user-service
pytest tests/ -v

# Chat Service
cd src/chat-service
pytest tests/ -v

# RAG Service
cd src/rag-service
pytest tests/ -v

# Với coverage (ví dụ RAG Service)
cd src/rag-service
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
docker compose logs -f chat-service

# Stop
docker compose down
```

Services sau khi `docker compose up`:

| Container | Port | Mô tả |
|-----------|------|-------|
| nginx | 80 / 443 | Reverse proxy, entry point — route `/` → frontend, `/api/*` → backend |
| next-frontend | 3000 | Next.js UI (production build) |
| user-service | 8000 | Auth / User management |
| chat-service | 8001 | LLM Orchestration / Conversation |
| rag-service | 8002 | Ingestion / Retrieval |
| qdrant | 6333 | Vector database |
| redis | 6379 | JWT blacklist + rate limiting |
| langfuse | 4000 | LLM observability dashboard (IT/DevOps only) |
| postgres | 5432 | PostgreSQL (shared, tách schema) |

---

## Troubleshooting

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `Connection refused 5432` | PostgreSQL chưa chạy | Chạy lại docker run postgres |
| `Connection refused 6333` | Qdrant chưa chạy | Chạy lại docker run qdrant |
| `Invalid signature` (JWT) | `JWT_SECRET_KEY` không khớp giữa services | Kiểm tra `.env` của 3 services phải dùng cùng key |
| `Invalid API Key` | `.env` chưa điền đúng | Kiểm tra lại `.env` |
| `ModuleNotFoundError` | Chưa activate venv đúng service | `cd <service-folder> && venv\Scripts\activate` |
| `QDRANT_URL not set` | Thiếu env var | Kiểm tra `src/rag-service/.env` |
| `Connection refused 8002` (từ Chat Service) | RAG Service chưa chạy | Start RAG Service trước |
