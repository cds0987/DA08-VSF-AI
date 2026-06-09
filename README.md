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
cp src/hr-service/.env.example        src/hr-service/.env
cp src/frontend/chat/.env.local.example   src/frontend/chat/.env.local
cp src/frontend/admin/.env.local.example  src/frontend/admin/.env.local
# Xem hướng dẫn chi tiết: docs/env-setup.md

# 3. Start toàn bộ stack
docker compose up --build
```

Sau khi start: Chat (End User) http://localhost:3000 · Admin console http://localhost:3001

---

## Architecture

```
Browser → Nginx :80
               ├── /                → Chat app (Nuxt)    :3000  (End User)
               ├── /admin           → Admin console (Nuxt) :3001  (Admin)
               │       (2 micro-frontend dùng chung Nuxt base layer: auth + design system)
               ├── /api/user/*      → User Service          :8000  (/auth/login → Chat; /auth/admin/login → Admin only; /users → Admin only)
               ├── /api/documents/* → Document Service      :8002  (Upload, Admin only)
               ├── /api/query/*     → Query Service         :8001  (LLM, Conversation; SSE /query + /notifications)
               │                          └── MCP → MCP Tool Service :8003 (tool: rag_search, hr_query)
               │                                          ├── NATS :4222 → RAG Worker (Retrieval — no HTTP)
               │                                          └── internal HTTP/gRPC → HR Service :8004
               └── /api/mcp/*       → MCP Tool Service      :8003

Ingestion: Document Service → NATS doc.ingest → RAG Worker (OCR, chunk, embed → Qdrant)
ACL projection: Document Service → NATS doc.access → Query Service query_db.document_access
Employee projection: HR Service → NATS hr.employee_profile.updated → Query Service query_db.user_access_profile
Infra: Qdrant :6333 | Redis :6379 | NATS :4222 (JetStream) | Langfuse :3100
PostgreSQL: GCP Cloud SQL PostgreSQL — 6 databases: user_db / doc_db / query_db / mcp_db / hr_db / langfuse_db
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
| HR Service | 8004 | Employee profile + HR data API (internal only; MCP Service gọi cho `hr_query`) |
| Chat app (frontend/chat) | 3000 | Nuxt UI — End User: chat SSE, notifications, document viewer |
| Admin console (frontend/admin) | 3001 | Nuxt UI — Admin: documents, users, analytics |
| Langfuse | 3100 | LLM observability dashboard (IT/DevOps only) |

> 2 micro-frontend dùng chung `frontend/base` (Nuxt layer: `useAuth` + `useApi` + middleware + design system) — build-time, không phải container. Trang `/login` tách riêng: Chat dùng `POST /auth/login`, Admin dùng `POST /auth/admin/login` (admin only).
> `hr-service` deploy cùng Docker Compose nhưng internal only, không route public qua Nginx. `mcp-service` gọi bằng `HR_SERVICE_URL=http://hr-service:8004`.

API docs (local): http://localhost:8000/docs | http://localhost:8001/docs | http://localhost:8002/docs | http://localhost:8003 (MCP endpoint) | http://localhost:8004/docs (internal)

---

## Query History & Sources

Query Service lưu lịch sử hội thoại trong `query_db`:

- `query_svc.conversations`: phiên/cuộc trò chuyện, summary buffer.
- `query_svc.messages`: từng user/assistant message.
- `query_svc.messages.sources`: JSONB citation metadata, chỉ set cho assistant message có source từ `rag_search`.

`sources` lưu theo từng assistant message để khi reload conversation, frontend vẫn render lại citation/source đúng câu trả lời.

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
