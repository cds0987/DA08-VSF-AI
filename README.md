# RAG-based Internal Q&A Chatbot — VinSmartFuture

Hệ thống chatbot nội bộ giúp ~800 DAU nhân viên truy vấn tài liệu công ty qua giao diện hội thoại, sử dụng RAG pipeline + OpenAI GPT-4o mini + LlamaIndex FunctionCallingAgent (MCP client) gọi tool qua **MCP Tool Service**. Trả lời stream qua **SSE**.

---

## Quick Start

```bash
# 1. Clone
git clone <repo-url>

# 2. Copy env files và điền API keys
cp src/user-service/.env.example      src/user-service/.env
cp src/document-service/.env.example  src/document-service/.env
cp src/query-service/.env.example     src/query-service/.env
cp src/rag-worker/.env.example        src/rag-worker/.env
cp src/mcp-service/.env.example       src/mcp-service/.env
cp src/frontend/.env.local.example    src/frontend/.env.local
# Xem hướng dẫn chi tiết: docs/env-setup.md

# 3. Start toàn bộ stack
docker compose up --build
```

Sau khi start: mở http://localhost:3000

---

## Architecture

```
Browser → Nginx :80
               ├── /                → Nuxt Frontend      :3000
               ├── /api/user/*      → User Service          :8000  (Auth, JWT)
               ├── /api/documents/* → Document Service      :8002  (Upload, Admin only)
               ├── /api/query/*     → Query Service         :8001  (LLM, Conversation; SSE /query + /notifications)
               │                          └── MCP → MCP Tool Service :8003 (tool: rag_search, hr_query)
               │                                          └── NATS :4222 → RAG Worker (Retrieval — no HTTP)
               └── /api/mcp/*       → MCP Tool Service      :8003

Ingestion: Document Service → NATS doc.ingest → RAG Worker (OCR, chunk, embed → Qdrant)
Infra: Qdrant :6333 | Redis :6379 | NATS :4222 (JetStream) | Langfuse :3100
PostgreSQL: AWS RDS db.t3.micro — 5 databases: user_db / doc_db / query_db / mcp_db / langfuse_db
```

---

## Service Ports

| Service | Port | Mô tả |
|---------|------|-------|
| User Service | 8000 | Auth, User management |
| Query Service | 8001 | LLM Orchestration, FunctionCallingAgent (MCP client), Conversation, SSE |
| Document Service | 8002 | Document upload & management (Admin only) |
| RAG Worker | — | NATS subscriber — Ingestion + Retrieval (no HTTP port, no DB) |
| MCP Tool Service | 8003 | MCP server — tool `rag_search`, `hr_query` (dùng chung cho mọi agent) |
| Frontend | 3000 | Nuxt UI |
| Langfuse | 3100 | LLM observability dashboard (IT/DevOps only) |

API docs (local): http://localhost:8000/docs | http://localhost:8001/docs | http://localhost:8002/docs | http://localhost:8003 (MCP endpoint)

---

## Docs

| File | Dành cho |
|------|---------|
| [docs/setup.md](docs/setup.md) | Tất cả — hướng dẫn cài đặt và chạy local |
| [docs/SA_RAG_Chatbot_Final.md](docs/SA_RAG_Chatbot_Final.md) | SA, tất cả Dev — kiến trúc tổng thể (source of truth) |
| [docs/architecture.md](docs/architecture.md) | SA, tất cả Dev — Clean Architecture 4 layer |
| [docs/contracts.md](docs/contracts.md) | SA, Dev Infra, Dev Use Case — Domain interfaces |
| [docs/api-spec.md](docs/api-spec.md) | Frontend Dev, AI/Agent Eng — HTTP endpoints |
| [docs/data-schema.md](docs/data-schema.md) | Backend Dev, RAG Eng — PostgreSQL + Qdrant schema |
| [docs/env-setup.md](docs/env-setup.md) | Tất cả — biến môi trường và API keys |
| [docs/team-ownership.md](docs/team-ownership.md) | SA, Team Lead — ai làm file nào |
| [docs/roadmap.md](docs/roadmap.md) | PM, SA — lộ trình 5 tuần |
