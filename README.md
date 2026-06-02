# RAG-based Internal Q&A Chatbot — VinSmartFuture

Hệ thống chatbot nội bộ giúp ~4,000 nhân viên truy vấn tài liệu công ty qua giao diện hội thoại, sử dụng RAG pipeline + Azure OpenAI.

---

## Quick Start

```bash
# 1. Clone
git clone <repo-url>

# 2. Copy env files và điền API keys
cp src/user-service/.env.example  src/user-service/.env
cp src/chat-service/.env.example  src/chat-service/.env
cp src/rag-service/.env.example   src/rag-service/.env
cp src/frontend/.env.local.example src/frontend/.env.local
# Xem hướng dẫn chi tiết: docs/operations/env-setup.md

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

> **Trước khi thay đổi/thêm bất cứ gì:** đọc [GUIDELINE.md](GUIDELINE.md) — định hướng tư duy
> (đi từ "tại sao", không đổi gì trong im lặng, bảo vệ cái cốt lõi).
>
> Tài liệu tổ chức theo **chuỗi thiết kế 5 tầng**. Bắt đầu từ [docs/design-flow.md](docs/design-flow.md) —
> bản đồ giải thích trật tự đọc và cách truy vết. Mục lục đầy đủ: [docs/README.md](docs/README.md).

| Tầng | File | Dành cho |
|------|------|---------|
| 🗺️ Bản đồ | [docs/design-flow.md](docs/design-flow.md) | Tất cả — đọc đầu tiên |
| 0. Requirement | [docs/0-requirements/problem-and-market.md](docs/0-requirements/problem-and-market.md) | Tất cả — bài toán & thị trường |
| 1–2. Domain | [docs/1-domain/domain-model.md](docs/1-domain/domain-model.md) | SA, tất cả — WHAT + WHY |
| 3. Architecture | [docs/2-architecture/architecture-mapping.md](docs/2-architecture/architecture-mapping.md) | SA — ma trận truy vết rule→component |
| 3. Architecture | [docs/2-architecture/solution-architecture.md](docs/2-architecture/solution-architecture.md) | SA — kiến trúc giải pháp |
| 3. Architecture | [docs/2-architecture/clean-architecture.md](docs/2-architecture/clean-architecture.md) | Tất cả Dev — Clean Architecture 4 layer |
| 4. Technical | [docs/3-technical/contracts.md](docs/3-technical/contracts.md) | SA, Dev — Domain interfaces |
| 4. Technical | [docs/3-technical/api-spec.md](docs/3-technical/api-spec.md) | Frontend, AI/Agent Eng — HTTP endpoints |
| 4. Technical | [docs/3-technical/data-schema.md](docs/3-technical/data-schema.md) | Backend, RAG Eng — PostgreSQL + Qdrant schema |
| Delivery | [docs/delivery/roadmap.md](docs/delivery/roadmap.md) | Tất cả — lộ trình theo phase |
| Delivery | [docs/delivery/team-ownership.md](docs/delivery/team-ownership.md) | SA, Team Lead — ai làm file nào |
| Operations | [docs/operations/setup.md](docs/operations/setup.md) | Tất cả — cài đặt & chạy local |
| Operations | [docs/operations/env-setup.md](docs/operations/env-setup.md) | Tất cả — biến môi trường & API keys |
