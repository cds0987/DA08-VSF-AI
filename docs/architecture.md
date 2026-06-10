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
│   ├── application/
│   │   └── use_cases/
│   │       └── query/
│   │           └── orchestration.py       # FunctionCallingAgent (MCP client) → tool rag_search/hr_query ở mcp-service → stream OpenAI (SSE)
│   │
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── postgres_conversation_repo.py
│   │   ├── external/
│   │   │   ├── openai_client.py    # OpenAI GPT-4o mini — streaming + tool_call
│   │   │   └── mcp_client.py       # MCP client → mcp-service (tool rag_search, hr_query)
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
│               └── documents.py    # POST /documents/upload, GET /documents, DELETE
│
src/rag-worker/                     ← Container 4: Ingestion + Retrieval (NATS only, KHÔNG dùng DB)
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
│   │       │   └── ingest_document_use_case.py  # Parse → Chunk (Parent-Child) → Embed → Upsert Qdrant
│   │       └── query/
│   │           └── retrieval.py    # Embed → Hybrid search (vector+BM25 RRF) → Top-K=5 → SearchResult
│   │
│   ├── infrastructure/
│   │   ├── vector/
│   │   │   └── qdrant_vector_repository.py
│   │   └── external/
│   │       ├── openai_embedding_client.py  # OpenAI text-embedding-3-small (1536 dims)
│   │       ├── gemini_ocr_client.py        # Gemini Vision API — OCR PDF scan
│   │       └── langfuse_client.py          # Trace ingestion + retrieval
│   │
│   └── main.py                     # NATS subscriber — không có HTTP server, không có DB

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
│   │   ├── rag_search.py           # RagSearchTool → {"results": [...]}
│   │   └── hr_query.py             # HrQueryTool → HTTP proxy POST /hr/query sang hr-service
│   ├── interfaces/
│   │   └── mcp_server.py           # build_mcp lái bằng registry; expose qua MCP Streamable HTTP
│   └── main.py                     # MCP server :8003 (verify_contract trước khi serve)

src/hr-service/                     ← Container 6: HR Service (:8004, internal only)
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── employee.py         # EmployeeProfile, Department, HR records
│   │   └── repositories/
│   │       └── employee_repository.py
│   ├── application/
│   │   └── services/
│   │       └── employee_profile_service.py  # publish hr.employee_profile.updated
│   ├── infrastructure/
│   │   ├── db/
│   │   │   └── models.py           # hr_svc.* (hr_db)
│   │   └── nats_publisher.py       # NATS event publisher
│   ├── interfaces/
│   │   └── api/
│   │       └── routes.py           # internal HR data endpoints
│   └── main.py                     # FastAPI :8004

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
4. **Mọi external call** (OpenAI GPT-4o mini, OpenAI Embeddings, Qdrant, Gemini Vision API) chỉ được gọi từ `infrastructure/`
