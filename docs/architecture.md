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
│   ├── agents/                     # MOSA multi-agent (Orchestrator-Workers)
│   │   ├── agents.yaml             # HOT-CONFIG: mode (react | orchestrator_workers), roles, memory — đổi không cần sửa code
│   │   ├── manifest.py             # load agents.yaml; fallback-safe về mode=react nếu lỗi/thiếu
│   │   ├── graph_builder.py        # build LangGraph fan-out động (DAG) khi mode=orchestrator_workers
│   │   └── planners/orchestrator_workers.py  # phân rã câu hỏi → DAG worker → join → (verify) → synthesize
│   │
│   ├── application/
│   │   └── use_cases/
│   │       └── query/
│   │           └── orchestration.py       # Agent loop (react mặc định / MOSA khi AGENT_MODE=orchestrator_workers) → tool MCP → stream qua ai-router (SSE); lưu thoughts/trace vào messages.metadata.agent
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
src/rag-worker/                     ← Container 4: Ingest worker (NATS + health/status API + metadata DB)
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── document.py         # Document, Section (xử lý in-memory)
│   │   └── repositories/
│   │       ├── vector_repository.py       # Abstract VectorRepository + SearchResult
│   │       └── embedding_service.py       # Abstract EmbeddingService (OpenAI interface)
│   │
│   ├── application/
│   │   └── use_cases/
│   │       ├── ingestion/
│   │       │   └── ingest_document_use_case.py  # Parse/OCR → Markdown artifact → Chunk → Embed → Upsert Qdrant
│   │       └── query/
│   │           └── retrieval.py    # Embed → Hybrid search (vector+BM25 RRF) → Top-K=5 → SearchResult
│   │
│   ├── infrastructure/
│   │   ├── vector/
│   │   │   └── qdrant_vector_repository.py
│   │   └── external/
│   │       ├── openai_embedding_client.py  # OpenAI text-embedding-3-small (1536 dims)
│   │       ├── ai_provider.py              # OCR/model gateway for image/PDF scan extraction
│   │       ├── s3_parser.py                # Read raw source from GCS/S3-compatible object storage
│   │       ├── s3_artifact_store.py        # Write canonical Markdown artifact to GCS
│   │       └── langfuse_client.py          # Trace ingestion + retrieval
│   │
│   └── main.py                     # NATS subscriber + health/status API + metadata DB

src/mcp-service/                    ← Container 5: MCP Tool Service (:8003) — search-only routing
├── app/
│   ├── core/                       # logic search self-contained (KHÔNG dùng NATS; đọc Qdrant trực tiếp)
│   │   ├── config.py               # McpSettings + load_settings (config.yaml + ${ENV})
│   │   ├── vectorstore.py          # SearchHit + reader Qdrant (chỉ ĐỌC; rag-worker là bên ghi)
│   │   ├── embedding.py            # embed query (text-embedding-3-small)
│   │   ├── rerank.py               # Reranker Protocol: none | lexical | llm (fallback NoopReranker)
│   │   ├── search.py               # SearchService: embed → retrieve Qdrant → rerank → top-k
│   │   └── contract.py             # verify_contract fail-closed (fingerprint khớp rag-worker)
│   ├── domain/
│   │   └── entities/
│   │       └── tool_io.py          # CHỈ RagSearchInput (DTO HR đã chuyển sang hr-service)
│   ├── tools/                      # registry tool pluggable (OCP)
│   │   ├── registry.py, base.py    # Registry + McpTool Protocol + register/resolve_tool
│   │   ├── rag_search.py           # RagSearchTool → {"results": [...]} (đọc Qdrant)
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
│   │   ├── routes.py              # READ: POST /hr/query, /hr/profile, /hr/leave-types, /hr/departments, GET /health
│   │   ├── leave_write_routes.py # WRITE: tạo/PATCH/cancel/approve/reject đơn + GET pending-approval, /mine, /{id}
│   │   └── admin_routes.py       # /hr/admin/employees, /hr/admin/leave-requests, /hr/admin/departments
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
├── ai_router/                      # selector (sticky_rotation_soft), multi-pool key (OpenAI + OpenRouter), quota/cost mỗi key
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

> **Lưu ý Microservices:** Query Service không gọi Qdrant/RAG Worker trực tiếp — nó là **MCP client**, gọi tool ở mcp-service (`MCPClient`). mcp-service (tool `rag_search`) **đọc Qdrant trực tiếp** để retrieve (KHÔNG gọi RAG Worker qua NATS; ghép với RAG Worker chỉ qua Qdrant). User Service không gọi RAG Worker — chỉ xử lý auth/user data.

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
    #   embed query → đọc Qdrant trực tiếp → rerank (none|lexical|llm) → top-k
    # KHÔNG có NATS, KHÔNG có BGEReranker self-host.
    ...

# src/rag-worker/app/interfaces/api/dependencies.py
def get_retrieval_use_case() -> RetrievalUseCase:
    vector_repo = QdrantVectorRepository()       # implement VectorRepository
    embedding_svc = OpenAIEmbeddingService()      # implement EmbeddingService — text-embedding-3-small
    return RetrievalUseCase(vector_repo, embedding_svc)

def get_ingest_use_case() -> IngestDocumentUseCase:
    vector_repo = QdrantVectorRepository()
    embedding_svc = OpenAIEmbeddingService()      # dùng chung interface, cùng 1 instance
    return IngestDocumentUseCase(vector_repo, embedding_svc)   # RAG Worker không ghi DB — publish doc.status

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
- **Bind nội bộ**: `ai-router` (127.0.0.1:8010) và `langfuse` (127.0.0.1:3100) KHÔNG ra Internet — truy cập qua SSH tunnel / subdomain Basic-Auth (`langfuse|grafana|qdrant.vsfchat.cloud`).
- **Observability** (overlay `docker-compose.observability.yml`, dùng chung network): Prometheus + Grafana + Alertmanager (Slack) + node-exporter + otel-collector (OTLP) + Tempo (trace) + Loki (log).
- **CI/CD** `.github/workflows/deploy-develop.yml`: push/merge `develop` (bỏ qua `docs/**`, `**.md`) → detect service đổi → test → build+push image (`:develop` + `:<sha>`) → deploy bằng Workload Identity Federation (keyless OIDC) qua IAP SSH. E2E gate enforce `AGENT_MODE=orchestrator_workers` (prod & e2e phải khớp).
