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

Project có **5 backend services** độc lập (user-service, document-service, query-service, rag-worker, mcp-service). Mỗi service có `requirements.txt` riêng.

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

# MCP Tool Service (AI/Agent Engineer)
cd ../mcp-service
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> Mỗi thành viên chỉ cần setup service mình phụ trách. Setup tất cả nếu chạy full local.
> (AI/Agent Engineer phụ trách `query-service`; **RAG Engineer** phụ trách `rag-worker` + `mcp-service`.)

---

## 3. Environment variables

Mỗi service có file `.env` riêng. Copy từ `.env.example` trong từng folder:

```bash
cp src/user-service/.env.example    src/user-service/.env
cp src/document-service/.env.example  src/document-service/.env
cp src/query-service/.env.example   src/query-service/.env
cp src/rag-worker/.env.example      src/rag-worker/.env
cp src/mcp-service/.env.example     src/mcp-service/.env
cp src/hr-service/.env.example      src/hr-service/.env
```

Xem đầy đủ nội dung từng file và hướng dẫn lấy API keys tại **[docs/env-setup.md](env-setup.md)**.

> **Quan trọng:** `JWT_SECRET_KEY` phải giống nhau ở các service cần verify JWT. Generate bằng `openssl rand -hex 32` rồi điền vào `.env` tương ứng. JWT cần có `user_id`, `role`, `account_type`.
>
> **NATS URL:** Tất cả services kết nối NATS qua `NATS_URL=nats://nats:4222` (Docker network) hoặc `nats://localhost:4222` (local dev).

---

## 4. Chạy PostgreSQL + Qdrant local (Docker)

**Production:** PostgreSQL chạy trên GCP Cloud SQL — không có container. Xem chi tiết tại [docs/env-setup.md](env-setup.md).

**Local dev:** Có thể dùng PostgreSQL Docker để test nhanh mà không cần Cloud SQL:

```bash
# PostgreSQL local — tạo 6 databases riêng như production
docker run -d \
  --name rag-postgres \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:15

# Tạo 6 databases
docker exec -it rag-postgres psql -U user -c "
  CREATE DATABASE user_db;
  CREATE DATABASE doc_db;
  CREATE DATABASE query_db;
  CREATE DATABASE mcp_db;
  CREATE DATABASE hr_db;
  CREATE DATABASE langfuse_db;
"

# Qdrant — mount volume để persist data khi restart container
docker run -d \
  --name rag-qdrant \
  -p 6333:6333 \
  -v qdrant_data:/qdrant/storage \
  qdrant/qdrant

# Redis — JWT blacklist + rate limiting + semantic cache
docker run -d \
  --name rag-redis \
  -p 6379:6379 \
  redis:7-alpine
```

Tạo tables bằng Alembic (mỗi service có `alembic/` riêng):

```bash
cd src/user-service    && alembic upgrade head   # user_db
cd ../document-service  && alembic upgrade head   # doc_db
cd ../query-service    && alembic upgrade head   # query_db (conversations, messages, document_access, user_access_profile)
cd ../mcp-service      && alembic upgrade head   # mcp_db (tool metadata/config nếu cần)
cd ../hr-service       && alembic upgrade head   # hr_db (employee profile + HR mock data)
cd ../rag-worker       && alembic upgrade head   # rag_db (ingest job/document state)
```

> RAG Worker có migration riêng cho metadata DB; Document Service vẫn quản lý document catalog, còn rag-worker chỉ giữ ingest job/document state phục vụ retry, status và vận hành.
> Schema thay đổi → tạo migration mới (`alembic revision --autogenerate -m "..."`) thay vì sửa DDL trực tiếp.

---

## 5. Chạy services local

Mỗi service chạy trên port riêng. Mở 7 terminal (hoặc dùng Docker Compose — Section 8):

```bash
# Terminal 0 — NATS (cần chạy trước)
docker run -d --name rag-nats -p 4222:4222 -p 8222:8222 nats:latest

# Terminal 1 — User Service (port 8000)
cd src/user-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8000

# Terminal 2 — Document Service (port 8002)
cd src/document-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8002

# Terminal 3 — Query Service (port 8001)
cd src/query-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8001

# Terminal 4 — RAG Worker (no port — NATS subscriber)
cd src/rag-worker
venv\Scripts\activate
python app/main.py

# Terminal 5 — MCP Tool Service (port 8003)
cd src/mcp-service
venv\Scripts\activate
python app/main.py        # khởi MCP server (Streamable HTTP/SSE) :8003

# Terminal 6 — HR Service (port 8004, internal only)
cd src/hr-service
venv\Scripts\activate
uvicorn app.interfaces.api.main:app --reload --port 8004
```

API docs tự động:
- User Service: http://localhost:8000/docs
- Document Service: http://localhost:8002/docs
- Query Service: http://localhost:8001/docs
- MCP Service: http://localhost:8003 (MCP endpoint — không phải OpenAPI /docs)
- HR Service: http://localhost:8004/docs (internal only)
- NATS Monitoring: http://localhost:8222

---

## 6. Frontend setup — 2 micro-frontend (Nuxt 4)

> Tách theo bounded context: **Chat app** (End User) + **Admin console** (Admin), dùng chung **Nuxt layer** `frontend/base` (auth + design system). `frontend/base` không chạy riêng — 2 app `extends` nó.

```bash
# Chat app (End User) — port 3000
cd src/frontend/chat
npm install                 # tự kéo frontend/base qua extends
cp .env.local.example .env.local
# Điền:
#   NUXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000   # auth /auth
#   NUXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001  # chat SSE + notifications
npm run dev                 # http://localhost:3000

# Admin console (Admin) — port 3001
cd ../frontend/admin
npm install
cp .env.local.example .env.local
# Điền:
#   NUXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000      # auth /auth + /users
#   NUXT_PUBLIC_DOCUMENT_SERVICE_URL=http://localhost:8002  # quản lý tài liệu
#   NUXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001     # /admin/metrics
npm run dev -- --port 3001  # http://localhost:3001
```

Frontend: Chat (End User) http://localhost:3000 · Admin console http://localhost:3001

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

# MCP Tool Service
cd src/mcp-service
pytest tests/ -v

# Với coverage (ví dụ RAG Worker)
cd src/rag-worker
pytest --cov=app tests/
```

---

## 8. Docker Compose — Chạy toàn bộ stack

Thay vì chạy từng terminal/service riêng, dùng Docker Compose để start tất cả cùng lúc:

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
| nginx | 80 / 443 | Reverse proxy, entry point — route `/` → nuxt-chat, `/admin` → nuxt-admin, `/api/*` → backend |
| nuxt-chat | 3000 | Chat app — End User (production build, extends frontend/base) |
| nuxt-admin | 3001 | Admin console — Admin (production build, extends frontend/base) |
| user-service | 8000 | Auth / User management |
| document-service | 8002 | Document management (Admin only) |
| query-service (+ query-service-2..8) | 8001 | User chat / LLM Orchestration (MCP client + MOSA agent) — SSE `/query` + `/notifications`. **8 replica** sau nginx `query_pool` (SSE-safe). |
| rag-worker | — | NATS Worker — ingestion pipeline (no HTTP port cho client; có health/status nội bộ) |
| mcp-service | 8003 | MCP server — 6 tool: `rag_search`, `hr_query`, `leave_write`, `leave_approvals`, `leave_types`, `resolve_date` |
| hr-service | 8004 | Employee profile + HR data + leave write/approve API (internal only) |
| ai-router | 127.0.0.1:8010 | Gateway LLM tương thích OpenAI (multi-pool key, cost/load routing). KHÔNG ra Internet — chỉ service nội bộ + SSH tunnel. |
| nats | 4222 / 8222 | Message broker — JetStream enabled (4222: client, 8222: monitoring UI) |
| qdrant | 6333 | Vector database |
| redis | 6379 | JWT blacklist + rate limiting + semantic cache + ai-router state |
| langfuse | 127.0.0.1:3100 | LLM observability dashboard (qua SSH tunnel) |

> **Observability (overlay `docker-compose.observability.yml`, dùng chung network):** Prometheus + Grafana + Alertmanager (Slack) + node-exporter + otel-collector (OTLP) + Tempo (trace) + Loki (log). Truy cập qua subdomain Basic-Auth (`grafana|langfuse|qdrant.vsfchat.cloud`).
>
> **PostgreSQL:** Local dev & demo VM dùng container `app-postgres:16` (shared) với các database `user_db`, `doc_db`, `query_db`, `rag_db`, `hr_db` (+ `langfuse_db` ở container riêng). Mỗi service kết nối database của mình qua cùng 1 host.

---

## Troubleshooting

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `Connection refused 5432` | PostgreSQL chưa chạy | Chạy lại docker run postgres |
| `Connection refused 6333` | Qdrant chưa chạy | Chạy lại docker run qdrant |
| `Connection refused 6379` | Redis chưa chạy | Chạy lại docker run redis |
| `Invalid signature` (JWT) | `JWT_SECRET_KEY` không khớp giữa services | Kiểm tra `.env` của các service verify JWT phải dùng cùng key |
| `Invalid API Key` | `.env` chưa điền đúng | Kiểm tra lại `.env` |
| `ModuleNotFoundError` | Chưa activate venv đúng service | `cd <service-folder> && venv\Scripts\activate` |
| `QDRANT_URL not set` | Thiếu env var | Kiểm tra `src/rag-worker/.env` |
| `Connection refused 8002` (Document Service) | Document Service chưa chạy | Start Document Service trước |
| `Connection refused 8001` (Query Service) | Query Service chưa chạy | Start Query Service trước |
