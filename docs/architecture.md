# Clean Architecture — RAG Chatbot Backend

## Tổng quan

Backend FastAPI tuân theo **Clean Architecture** với 4 layer lồng nhau.
Quy tắc cốt lõi: **layer trong không được biết layer ngoài tồn tại**.

```
┌─────────────────────────────────────────┐
│  Frameworks & Drivers (interfaces/api)  │
│  ┌───────────────────────────────────┐  │
│  │  Infrastructure                   │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Application (Use Cases)    │  │  │
│  │  │  ┌───────────────────────┐  │  │  │
│  │  │  │  Domain               │  │  │  │
│  │  │  │  (Entities + Repos)   │  │  │  │
│  │  │  └───────────────────────┘  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Hướng dependency (chỉ được import vào trong):**
```
interfaces/api  →  application  →  domain
infrastructure  →  application  →  domain
```

---

## Folder Structure

Mỗi service là 1 folder riêng, dùng Clean Architecture độc lập bên trong.

```
src/user-service/                   ← Container 1: Auth / User management (:8000)
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── user.py             # User
│   │   └── repositories/
│   │       └── user_repository.py         # Abstract UserRepository
│   │
│   ├── application/
│   │   └── use_cases/
│   │       └── auth/
│   │           ├── login_use_case.py
│   │           └── verify_token_use_case.py
│   │
│   ├── infrastructure/
│   │   └── db/
│   │       ├── models.py
│   │       └── postgres_user_repository.py
│   │
│   └── interfaces/
│       └── api/
│           ├── main.py
│           ├── dependencies.py
│           ├── routers/
│           │   └── auth.py
│           └── schemas/
│               └── auth.py
│
src/query-service/                  ← Container 2: LLM Orchestration, Conversation
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── conversation.py     # Conversation, Message
│   │   └── repositories/
│   │       └── conversation_repository.py # Abstract ConversationRepository
│   │
│   ├── agents/                     # Multi-Agent — Orchestrator-Workers (agents.yaml gọi tắt "MOSA")
│   │   ├── agents.yaml             # HOT-CONFIG: mode (react | orchestrator_workers), roles, memory — đổi không cần sửa code
│   │   ├── manifest.py             # load agents.yaml; fallback-safe về mode=react nếu lỗi/thiếu
│   │   ├── graph_builder.py        # build LangGraph fan-out động (DAG) khi mode=orchestrator_workers
│   │   └── planners/orchestrator_workers.py  # phân rã câu hỏi → DAG worker (fan-out) → join → verify_answer (gộp verify + synthesis + citation)
│   │
│   ├── application/
│   │   └── use_cases/
│   │       └── query/
│   │           └── orchestration.py       # Agent loop (react mặc định / Orchestrator-Workers khi AGENT_MODE=orchestrator_workers) → tool MCP → stream qua ai-router (SSE); lưu thoughts/trace vào messages.metadata.agent
│   │
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py           # messages có cột metadata (JSONB): agent thoughts/trace + leave action state
│   │   │   └── postgres_conversation_repo.py
│   │   ├── external/
│   │   │   ├── openai_client.py    # OpenAI SDK, base_url=http://ai-router:8010/v1 (rỗng = thẳng OpenAI, kill-switch); 'model' = ALIAS capability
│   │   │   ├── hr_leave_client.py  # gọi hr-service (X-Internal-Token): create/cancel/approve/reject/pending-approval/mine
│   │   │   └── mcp_client.py       # MCP client → mcp-service (rag_search, hr_query, leave_write, leave_approvals, leave_types, resolve_date)
│   │   ├── sse/                    # connection_manager + notify_subscriber (SSE /notifications)
│   │   └── memory/                # Redis short-term memory
│   │
│   └── interfaces/
│       └── api/
│           ├── main.py
│           ├── dependencies.py
│           ├── routers/
│           │   ├── query.py
│           │   └── conversations.py
│           └── schemas/
│               ├── query.py        # QueryRequest, QueryResponse
│               └── conversation.py
│
src/document-service/               ← Container 3: Document management (Admin)
├── app/
│   ├── domain/ ...
│   ├── application/ ...
│   ├── infrastructure/
│   │   └── external/
│   │       └── nats_client.py      # Publish doc.ingest, subscribe doc.status
│   └── interfaces/
│       └── api/
│           └── routers/
│               └── documents.py    # upload, list, GET /{id}/file(/raw), bulk-delete, DELETE, audit-logs, supported-formats
│
src/rag-worker/                     ← Container 4: RAG worker — ingest (NATS) + query-search (/api/search :8000) + metadata DB
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── document.py         # Document, Section (xử lý in-memory)
│   │   └── repositories/
│   │       ├── vector_repository.py       # Abstract VectorRepository + SearchResult
│   │       └── embedding_service.py       # Abstract EmbeddingService (provider-agnostic; resolve_dimension)
│   │
│   ├── application/
│   │   └── use_cases/
│   │       ├── ingestion/
│   │       │   └── ingest_document_use_case.py  # Parse/OCR → Markdown artifact → Chunk → Embed (multi-collection) → Upsert Qdrant
│   │       └── search/
│   │           └── search_use_case.py # Embed query → VectorStore.search (vector+BM25 hybrid) → candidates (CHƯA rerank)
│   │
│   ├── core_engine/
│   │   ├── embedding/service.py    # ProviderEmbeddingService — embed qua ai-router; EMBED_MODEL=qwen3-8b (4096 native)
│   │   ├── multi_embed.py          # forward-write nhiều collection (embeddings.yaml) khi MULTI_EMBED_ENABLED=1
│   │   ├── contract.py             # resolve_dimension + index_id (rag_chatbot__{tag}__d{dim}[__s{sparse}])
│   │   └── concurrency/adaptive_limiter.py  # AIMD limiter cho embed/OCR sub-batch
│   │
│   ├── infrastructure/
│   │   └── external/
│   │       ├── s3_parser.py                # Read raw source from GCS/S3-compatible object storage
│   │       ├── s3_artifact_store.py        # Write canonical Markdown artifact to GCS
│   │       └── nats_client.py              # NATS subscribe doc.ingest / publish doc.status
│   │
│   └── interfaces/api/main.py      # FastAPI :8000 nội bộ — /api/search + /api/ingest + health/metrics; NATS ingest (rag-ingest-worker ×8 ở prod)

src/mcp-service/                    ← Container 5: MCP Tool Service (:8003) — THIN search interface
├── app/
│   ├── core/                       # mcp KHÔNG embed/đọc Qdrant — gọi rag-worker /api/search rồi rerank
│   │   ├── config.py               # McpSettings + load_settings (config.yaml + ${ENV}); rag_worker_url
│   │   ├── models.py               # SearchHit (shape candidate, map 1:1 với rag-worker /api/search)
│   │   ├── rerank.py               # Reranker Protocol: lexical | llm (cohere qua ai-router; fallback giữ thứ tự)
│   │   ├── search.py               # gọi rag-worker HTTP /api/search → rerank → top-k
│   │   └── text_utils.py           # hash_embed byte-identical rag-worker (đảm bảo khớp)
│   ├── domain/
│   │   └── entities/
│   │       └── tool_io.py          # CHỈ RagSearchInput (DTO HR đã chuyển sang hr-service)
│   ├── tools/                      # registry tool pluggable (OCP)
│   │   ├── registry.py, base.py    # Registry + McpTool Protocol + register/resolve_tool
│   │   ├── rag_search.py           # RagSearchTool → {"results": [...]} (rag-worker /api/search + rerank)
│   │   ├── hr_query.py             # HrQueryTool → HTTP proxy POST /hr/query sang hr-service
│   │   ├── leave_write.py          # tạo/sửa/hủy đơn nghỉ (proxy hr-service)
│   │   ├── leave_approvals.py      # pending-approval + approve/reject (proxy hr-service)
│   │   ├── leave_types.py          # taxonomy loại nghỉ (4 rổ luật LĐ VN)
│   │   └── resolve_date.py         # chuẩn hoá ngày tương đối ("thứ 6 tới") → ISO
│   ├── interfaces/
│   │   └── mcp_server.py           # build_mcp lái bằng registry; expose qua MCP Streamable HTTP
│   └── main.py                     # MCP server :8003 (verify_contract trước khi serve)

src/hr-service/                     ← Container 6: HR Service (:8004, internal only)
├── app/
│   ├── api/
│   │   ├── auth.py                 # require_internal_token (X-Internal-Token) + require_admin (JWT) cho /hr/admin/*
│   │   ├── routes.py              # READ: /hr/query, /hr/profile, /hr/leave-types, /hr/departments, /health
│   │   │                          # + WRITE leave: tạo/PATCH/cancel/approve/reject + GET pending-approval, /mine, /{id}
│   │   └── hr_admin.py           # /hr/admin/employees (list, /{id}, /{id}/details, PATCH, DELETE) — JWT admin
│   ├── core/
│   │   └── config.py              # HrSettings
│   ├── domain/
│   │   ├── entities/dtos.py       # DTO HR (9 loại)
│   │   └── repositories/          # hr_repository (READ) + leave_write_repository (WRITE)
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py          # hr_svc.* (9 bảng, hr_db) — leave_requests có idempotency_key, cancelled_at
│   │   │   └── postgres_hr_repository.py
│   │   └── nats_publisher.py      # ĐÃ wire: publish hr.leave_request.{created,updated,cancelled,approved,rejected}, hr.employee_profile.updated, hr.department.renamed
│   └── main.py                     # FastAPI :8004

src/ai-router/                      ← Container 9: AI Router (:8010, internal/127.0.0.1 only) — gateway LLM tương thích OpenAI
├── app/                            # FastAPI: /v1/chat/completions, /v1/embeddings, /v1/rerank, /v1/route, /admin/*, /health, /metrics
├── ai_router/                      # selector default banded_rotation + override adaptive_balanced (AIMD/TPM-headroom), multi-pool key (OpenAI + OpenRouter), quota/cost mỗi key
├── routing.yaml                    # HOT-RELOAD: capability→tier→model, quality floor, thuật toán selector
└── config/model_catalog.json       # build từ OpenRouter /models mỗi deploy (model + giá); fail → giữ seed
# Stateless, zero-dependency: service đổi base_url=http://ai-router:8010/v1, 'model' = ALIAS capability (answer/worker/think/plan/embed/summary).
# AN TOÀN: không service nào depends_on ai-router → router chết KHÔNG kéo sập app (query-service set base_url rỗng = fallback thẳng OpenAI).

src/frontend/base/                  ← Nuxt Layer dùng chung (useAuth + useApi + middleware/auth + design system) — build-time, KHÔNG container
src/frontend/chat/                  ← Container 7: Chat app End User (:3000) — /login gọi POST /auth/login (user + admin) → Query Service
src/frontend/admin/                 ← Container 8: Admin console (:3001) — /login gọi POST /auth/admin/login (admin only) → Document + User /users + metrics
```

---

## Luật Dependency — Ví dụ Đúng / Sai

### SAI — Use Case biết về FastAPI
```python
# application/use_cases/query/query_document_use_case.py
from fastapi import HTTPException  # ❌ SAI — application không được import framework
```

### ĐÚNG — Use Case chỉ biết Domain
```python
# application/use_cases/query/query_document_use_case.py
from app.domain.repositories.vector_repository import VectorRepository  # ✅
from app.domain.entities.conversation import Message                     # ✅

class QueryDocumentUseCase:
    def __init__(self, vector_repo: VectorRepository):  # nhận interface, không biết Qdrant
        self.vector_repo = vector_repo
```

### SAI — Domain import Infrastructure
```python
# domain/entities/document.py
from sqlalchemy import Column  # ❌ SAI — Domain không được biết DB tồn tại
```

### ĐÚNG — Infrastructure implement Domain interface
```python
# infrastructure/vector/qdrant_vector_repository.py
from app.domain.repositories.vector_repository import VectorRepository  # ✅

class QdrantVectorRepository(VectorRepository):  # implement interface từ domain
    def search(self, vector, top_k):
        # gọi Qdrant SDK ở đây
        ...
```

---

## Dependency Injection

FastAPI router nhận use case qua `Depends()` — use case nhận repository qua constructor.

> **Lưu ý Microservices:** Query Service không gọi Qdrant/RAG Worker trực tiếp — nó là **MCP client**, gọi tool ở mcp-service (`MCPClient`). mcp-service (tool `rag_search`) gọi **rag-worker `POST /api/search`** (rag-worker embed query + vector search Qdrant → trả candidates) rồi **rerank** ở mcp; mcp KHÔNG còn embed/đọc Qdrant. User Service không gọi RAG Worker — chỉ xử lý auth/user data.

```python
# src/user-service/app/interfaces/api/dependencies.py
def get_login_use_case() -> LoginUseCase:
    user_repo = PostgresUserRepository()
    return LoginUseCase(user_repo)

# src/query-service/app/interfaces/api/dependencies.py
def get_orchestration_use_case() -> OrchestrationUseCase:
    mcp_client = MCPClient(url=settings.MCP_SERVICE_URL)   # gọi tool rag_search / hr_query
    conversation_repo = PostgresConversationRepo()
    doc_access_repo = PostgresDocumentAccessRepo()        # projection ACL (query_db)
    openai_client = OpenAIClient()                        # OpenAI GPT-4o mini — streaming + tool_call
    return OrchestrationUseCase(mcp_client, conversation_repo, doc_access_repo, openai_client)

# src/mcp-service/app/interfaces/mcp_server.py  (build_mcp lái bằng registry)
def build_mcp(settings: McpSettings) -> tuple[FastMCP, list[McpTool]]:
    # mỗi tool enabled → resolve_tool → tool.register(mcp). rag_search build SearchService:
    #   HTTP rag-worker /api/search (rag-worker embed + vector search) → rerank (lexical|llm) → top-k
    # mcp KHÔNG embed/đọc Qdrant; KHÔNG có BGEReranker self-host.
    ...

# src/rag-worker/app/interfaces/api/dependencies.py
def get_search_use_case() -> SearchUseCase:
    vector_store = QdrantVectorStore()           # vector + BM25 hybrid search
    embedding_svc = ProviderEmbeddingService()    # EMBED_MODEL=qwen3-8b (4096 native) qua ai-router
    return SearchUseCase(embedding_svc, vector_store)   # POST /api/search → candidates (CHƯA rerank; rerank ở mcp)

def get_ingest_use_case() -> IngestDocumentUseCase:
    vector_repo = QdrantVectorRepository()
    embedding_svc = ProviderEmbeddingService()    # dùng chung interface; MULTI_EMBED_ENABLED=1 → ghi nhiều collection
    return IngestDocumentUseCase(vector_repo, embedding_svc)   # rag-ingest-worker ×8 (prod) — publish doc.status

# src/query-service/app/interfaces/api/routers/query.py
@router.post("/query")
async def query(request: QueryRequest, use_case = Depends(get_orchestration_use_case)):
    return await use_case.execute(request.question, request.user_id)
```

---

## Nguyên tắc khi code

1. **Thêm field vào Entity** → báo SA trước, ảnh hưởng tất cả layer
2. **Thêm method vào Repository interface** → SA viết, Dev Infra implement
3. **Không import chéo** giữa `use_cases/query/` và `use_cases/ingestion/`
4. **Mọi external call** (LLM/OCR provider, OpenAI Embeddings, Qdrant, GCS/S3-compatible storage) chỉ được gọi từ `infrastructure/`

---

## Hạ tầng vận hành (runtime topology)

Triển khai trên 1 GCP VM (`vsf-rag-demo-vm`, zone `asia-southeast1-a`) bằng Docker Compose; TLS kết thúc ở Cloudflare → nginx :80.

**Gateway nginx** (image baked, không bind-mount) định tuyến theo path:

| Path | Upstream |
|---|---|
| `/api/user/` | user-service:8000 |
| `/api/documents/` | document-service:8002 |
| `/api/query/` | `query_pool` (round-robin 8 replica `query-service` + `query-service-2..8`:8001) |
| `/api/hr/` | hr-service:8004 |
| `/api/mcp/` | mcp-service:8003 |
| `/admin/` | frontend-admin:3001 |
| `/` | frontend-chat:3000 |

- **8 replica query-service**: SSE-safe (1 process/container), tránh nghẽn CPU khi burst. `/api/query/{query,notifications}` tắt proxy_buffering, timeout 3600s.
- **rag-worker tách vai trò** (cùng image): `rag-worker` (1 bản, `INGEST_ENABLED=false`) phục vụ `/api/search` + health trên `:8000` nội bộ cho mcp; `rag-ingest-worker` (×8 replica, `INGEST_ENABLED=true`, `MULTI_EMBED_ENABLED=1`) chạy NATS ingest — tách để search nhẹ không bị ingest giành tài nguyên. Migrate qua `rag-migrate` (alembic) + `rag-embed-migrate` (`multi_embed_migrate.py`).
- **gotenberg** (`gotenberg/gotenberg:8`): convert office (docx/xlsx/pptx) → PDF cho pipeline OCR của rag-worker.
- **Bind nội bộ**: `ai-router` (127.0.0.1:8010) và `langfuse` (127.0.0.1:3100) KHÔNG ra Internet — truy cập qua SSH tunnel / subdomain Basic-Auth (`langfuse|grafana|qdrant.vsfchat.cloud`).
- **Observability** (overlay `docker-compose.observability.yml`, dùng chung network): Prometheus + Grafana + Alertmanager (Slack) + node-exporter + otel-collector (OTLP) + Tempo (trace) + Loki (log).
- **CI/CD** `.github/workflows/deploy-develop.yml`: push/merge `develop` (bỏ qua `docs/**`, `**.md`) → detect service đổi → test → build+push image (`:develop` + `:<sha>`) → deploy bằng Workload Identity Federation (keyless OIDC) qua IAP SSH. E2E gate enforce `AGENT_MODE=orchestrator_workers` (prod & e2e phải khớp).
