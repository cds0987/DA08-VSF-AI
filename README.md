# RAG-based Internal Q&A Chatbot — VinSmartFuture

Hệ thống chatbot nội bộ giúp ~4,000 nhân viên truy vấn tài liệu công ty qua giao diện hội thoại, sử dụng RAG pipeline + Azure OpenAI.

---

## Quick Start

```bash
# 1. Clone
git clone <repo-url>
cd rag-chatbot

# 2. Copy env files và điền API keys
cp src/user-service/.env.example  src/user-service/.env
cp src/chat-service/.env.example  src/chat-service/.env
cp src/rag-service/.env.example   src/rag-service/.env
cp src/frontend/.env.local.example src/frontend/.env.local
# Xem hướng dẫn chi tiết: docs/env-setup.md

# 3. Start toàn bộ stack
docker compose up --build
```

Sau khi start: mở http://localhost:3000

---

## Architecture

```
Browser → Nginx :80
               ├── /           → Next.js Frontend :3000
               ├── /api/user/* → User Service     :8000  (Auth, JWT)
               └── /api/chat/* → Chat Service     :8001  (LLM, Conversation)
                                      └── gọi nội bộ → RAG Service :8002 (Ingestion, Retrieval)

Infra: PostgreSQL :5432 | Qdrant :6333 | Redis :6379 | Langfuse :4000
```

---

## Service Ports

| Service | Port | Mô tả |
|---------|------|-------|
| User Service | 8000 | Auth, User management |
| Chat Service | 8001 | LLM Orchestration, Conversation |
| RAG Service | 8002 | Document Ingestion, Vector Retrieval |
| Frontend | 3000 | Next.js UI |

API docs (local): http://localhost:8000/docs | http://localhost:8001/docs | http://localhost:8002/docs

---

## Docs

| File | Dành cho |
|------|---------|
| [docs/setup.md](docs/setup.md) | Tất cả — hướng dẫn cài đặt và chạy local |
| [docs/architecture.md](docs/architecture.md) | SA, tất cả Dev — Clean Architecture 4 layer |
| [docs/contracts.md](docs/contracts.md) | SA, Dev Infra, Dev Use Case — Domain interfaces |
| [docs/api-spec.md](docs/api-spec.md) | Frontend Dev, AI/Agent Eng — HTTP endpoints |
| [docs/data-schema.md](docs/data-schema.md) | Backend Dev, RAG Eng — PostgreSQL + Qdrant schema |
| [docs/env-setup.md](docs/env-setup.md) | Tất cả — biến môi trường và API keys |
| [docs/team-ownership.md](docs/team-ownership.md) | SA, Team Lead — ai làm file nào |
