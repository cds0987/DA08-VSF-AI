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
│   │           └── orchestration.py       # Function Calling Agent → rag_search_tool / hr_query_tool → stream OpenAI
│   │
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── postgres_conversation_repo.py
│   │   ├── external/
│   │   │   ├── openai_client.py    # OpenAI GPT-4o mini — streaming + tool_call
│   │   │   └── nats_client.py      # NATS request-reply rag.search
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
src/rag-worker/                     ← Container 4: OCR, Ingestion (NATS only)
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── document.py         # Document, Chunk
│   │   └── repositories/
│   │       ├── vector_repository.py       # Abstract VectorRepository + SearchResult
│   │       ├── document_repository.py     # Abstract DocumentRepository
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
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── postgres_document_repository.py
│   │   ├── vector/
│   │   │   └── qdrant_vector_repository.py
│   │   └── external/
│   │       ├── openai_embedding_client.py  # OpenAI text-embedding-3-small (1536 dims)
│   │       ├── gemini_ocr_client.py        # Gemini Vision API — OCR PDF scan
│   │       ├── bge_reranker_client.py      # BGE-Reranker-v2-m3 (loaded inline, Top-5→Top-3)
│   │       └── langfuse_client.py          # Trace ingestion + retrieval
│   │
│   └── main.py                     # NATS subscriber — không có HTTP server

src/frontend/                       ← AWS EC2 deployment (Next.js container, Docker Compose)
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

> **Lưu ý Microservices:** Query Service không gọi Qdrant trực tiếp — nó giao tiếp với RAG Worker qua NATS request-reply (`rag.search`). `NatsClient` là Infrastructure adapter đóng gói NATS call đó. User Service không gọi RAG Worker — chỉ xử lý auth/user data.

```python
# src/user-service/app/interfaces/api/dependencies.py
def get_login_use_case() -> LoginUseCase:
    user_repo = PostgresUserRepository()
    return LoginUseCase(user_repo)

# src/query-service/app/interfaces/api/dependencies.py
def get_orchestration_use_case() -> OrchestrationUseCase:
    nats_client = NatsClient(url=settings.NATS_URL)   # NATS request-reply rag.search
    conversation_repo = PostgresConversationRepo()
    openai_client = OpenAIClient()                    # OpenAI GPT-4o mini — streaming + tool_call
    return OrchestrationUseCase(nats_client, conversation_repo, openai_client)

# src/rag-worker/app/interfaces/api/dependencies.py
def get_retrieval_use_case() -> RetrievalUseCase:
    vector_repo = QdrantVectorRepository()       # implement VectorRepository
    embedding_svc = OpenAIEmbeddingService()      # implement EmbeddingService — text-embedding-3-small
    return RetrievalUseCase(vector_repo, embedding_svc)

def get_ingest_use_case() -> IngestDocumentUseCase:
    document_repo = PostgresDocumentRepository()
    vector_repo = QdrantVectorRepository()
    embedding_svc = OpenAIEmbeddingService()      # dùng chung interface, cùng 1 instance
    return IngestDocumentUseCase(document_repo, vector_repo, embedding_svc)

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
