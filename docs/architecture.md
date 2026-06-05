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

src/mcp-service/                    ← Container 5: MCP Tool Service (:8003)
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── tool_io.py          # RagSearchInput/Result, HrQueryInput
│   │   └── repositories/
│   │       └── rerank_service.py           # Abstract RerankService (BGE-Reranker)
│   ├── application/
│   │   └── tools/
│   │       ├── rag_search.py       # (rewrite) → NATS rag.search → rerank → Top-3
│   │       └── hr_query.py         # query mcp_db.hr_mock filter user_id
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py                   # hr_mock.* (mcp_db)
│   │   │   └── postgres_hr_repository.py
│   │   ├── nats_rag_client.py      # NATS request-reply rag.search → RAG Worker
│   │   └── bge_reranker_client.py  # BGE-Reranker-v2-m3 (loaded inline, Top-5→Top-3)
│   ├── interfaces/
│   │   └── mcp_server.py           # Expose tool qua MCP (Streamable HTTP/SSE)
│   └── main.py                     # MCP server :8003

src/frontend/base/                  ← Nuxt Layer dùng chung (auth /auth + design system + useApi) — build-time, KHÔNG container
src/frontend/chat/                  ← Container 6: Chat app End User (:3000) — extends frontend/base → Query Service
src/frontend/admin/                 ← Container 7: Admin console (:3001) — extends frontend/base → Document + User /users + metrics
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

> **Lưu ý Microservices:** Query Service không gọi Qdrant/RAG Worker trực tiếp — nó là **MCP client**, gọi tool ở mcp-service (`MCPClient`). Chính mcp-service mới giao tiếp với RAG Worker qua NATS request-reply (`rag.search`). User Service không gọi RAG Worker — chỉ xử lý auth/user data.

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

# src/mcp-service/app/interfaces/mcp_server.py  (tool dependencies)
def get_rag_search_tool() -> RagSearchTool:
    nats_client = NatsClient(url=settings.NATS_URL)   # NATS request-reply rag.search → RAG Worker
    reranker = BGERerankerClient()                    # implement RerankService
    return RagSearchTool(nats_client, reranker)

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
