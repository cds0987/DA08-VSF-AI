---
title: Kiến trúc hệ thống — Tổng quan topology
last-verified: 59551e39 (2026-06-29)
code-refs:
  - docker-compose.yml
  - infra/nats/subjects.md
  - infra/nats/event-contracts.yaml
  - src/query-service/app/agents/
  - src/ai-router/
  - src/mcp-service/app/core/search.py
  - nginx/nginx.conf
---

# Tổng quan kiến trúc — VSF RAG Chatbot

> Nguồn sự thật: `docker-compose.yml` + code service. Mọi mũi tên dưới đây kiểm chứng được trong code/compose.
> Đi kèm: [data-flow.md](data-flow.md), [ai-architecture.md](ai-architecture.md), [contracts.md](contracts.md).

## Triển khai

Một **GCP VM** duy nhất chạy toàn bộ qua `docker compose` (nguyên tắc 1-VM: không host DB/vector ngoài VM).
Domain công khai **vsfchat.cloud**; TLS kết thúc ở **Cloudflare → nginx :80** (image nginx baked config, không bind-mount).
Browser luôn đi qua nginx ⇒ FE và `/api/*` cùng origin (không CORS). CI/CD build+push image lên Docker Hub; VM chỉ `pull`.

## 8 service ứng dụng

| Service | Port (nội bộ) | Vai trò |
|---|---|---|
| frontend-chat / frontend-admin | 3000 / 3001 | Nuxt 4 SSR; chỉ nginx proxy tới (không bind host port) |
| user-service | 8000 | Auth/JWT, quản lý user |
| query-service (×8 replica) | 8001 | Orchestrate hội thoại, SSE chat, MOSA orchestrator |
| document-service | 8002 | Vòng đời tài liệu, upload → GCS, bảng `documents` |
| mcp-service | 8003 | MCP tool server (rag_search, hr_query, leave_*…) |
| hr-service | 8004 | Sở hữu HR data (`hr_db`), internal-only (X-Internal-Token) |
| rag-worker | 8000 (nội bộ) | `/api/search` (1 bản, INGEST off) + `rag-ingest-worker` ×8 (NATS ingest) |
| ai-router | 8010 (127.0.0.1) | Gateway LLM OpenAI-compatible, quota-aware |

## Hạ tầng dùng chung

| Thành phần | Vai trò | Lộ ra ngoài? |
|---|---|---|
| Qdrant (v1.18) | Vector store; chỉ trong compose network | Không (qdrant.vsfchat.cloud + Basic Auth qua nginx) |
| Postgres (app-postgres) | 5 DB: user/doc/query/rag/hr | Không |
| Redis | Memory hội thoại + state/quota ai-router (db1) | Không |
| NATS JetStream | Event bus (DOC/HR/USER/NOTIFY_EVENTS) | Không |
| GCS | Lưu file gốc + Markdown artifact + signed URL viewer | — (GCP) |
| OpenRouter / OpenAI | Provider LLM + embed thật (ai-router giữ key) | — (provider) |
| Langfuse (self-host v2) | Trace LLM | langfuse.vsfchat.cloud + Basic Auth |
| Grafana/Prometheus | Metrics (overlay `docker-compose.observability.yml`) | grafana.vsfchat.cloud |
| gotenberg | Office → PDF cho OCR pipeline | Không |

## Ai gọi ai (verify từ compose + code)

```
                         Cloudflare TLS
                              │
                          nginx :80  ──/admin/──> frontend-admin
            /──────────────┬─┴────────────\        / ──> frontend-chat
   /api/user  /api/documents  /api/query   /api/hr   /api/mcp
      │             │           │ (pool×8)    │         │
 user-service  document-svc  query-service  hr-service  mcp-service
      │             │           │   │  │
      │ (NATS)      │ (NATS)     │   │  └─HTTP─> ai-router ──> OpenAI/OpenRouter
      │             │           │   └──HTTP MCP─> mcp-service ─┬HTTP /api/search─> rag-worker ─> Qdrant
      │             │           │                              └HTTP proxy──────> hr-service
      │             │           └──HTTP /v1──────> ai-router ──> OpenAI/OpenRouter (LLM chính)
      │             └──GCS upload──> GCS ──NATS doc.ingest──> rag-ingest-worker ─embed(ai-router)─> Qdrant
      └─ NATS user.* ──> hr-service
```

Các quan hệ AI↔AI then chốt (kiểm chứng được):
- **query-service → ai-router**: mọi LLM call qua OpenAI SDK `base_url=http://ai-router:8010/v1`, `model`=alias capability (`openai_client.py`). Rỗng base_url = fallback thẳng OpenAI (kill-switch).
- **query-service → mcp-service**: MCP Streamable HTTP (`mcp_client.py`) để gọi tool.
- **mcp-service → rag-worker**: HTTP `POST /api/search` (`config.yaml: rag_worker_url=http://rag-worker:8000`, `core/search.py`). *(Hợp đồng NATS `rag.search` còn trong subjects.md nhưng đường chạy thật là HTTP.)*
- **mcp-service → hr-service**: HTTP proxy `X-Internal-Token` (tool hr_query/leave_*).
- **rag-worker / rag-ingest-worker → ai-router**: embed (`EMBED_API_KEY=AIROUTER_INTERNAL_TOKEN`), capability `embed`.
- **mcp-service → ai-router**: rerank (`rerank_api`, Cohere qua OpenRouter) khi `RERANK_PROVIDER=llm`.

## Nguyên tắc an toàn (từ compose)

- **Không service nào `depends_on` ai-router / langfuse / Qdrant-dashboard** ⇒ chúng chết KHÔNG kéo sập app.
- ai-router bind `127.0.0.1:8010`, langfuse `127.0.0.1:3100` ⇒ không ra Internet (chỉ SSH tunnel / subdomain Basic-Auth).
- Mỗi service 1 DB riêng (database-per-service); migration là job one-shot `*-migrate` (`condition: service_completed_successfully`).
- query-service scale bằng **replica** (mỗi container 1 uvicorn = SSE-safe), nginx `upstream query_pool` round-robin 8 replica.
- rag-worker tách vai trò: search-only (1) vs ingest-only (×8) để search không bị ingest giành CPU.
