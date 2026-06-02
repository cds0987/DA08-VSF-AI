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
src/user-service/                   ← Container 1: Auth, User management
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
src/chat-service/                   ← Container 2: LLM Orchestration, Conversation
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
│   │           └── orchestration.py       # Build prompt, call Azure OpenAI, stream
│   │
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── postgres_conversation_repo.py
│   │   ├── external/
│   │   │   ├── openai_client.py    # Chat Completion wrapper
│   │   │   └── rag_service_client.py  # HTTP client gọi RAG Service
│   │   └── memory/                # Phase 2: Redis short-term memory
│   │
│   └── interfaces/
│       └── api/
│           ├── main.py
│           ├── dependencies.py
│           ├── routers/
│           │   ├── query.py
│           │   └── documents.py
│           └── schemas/
│               ├── query.py        # QueryRequest, QueryResponse
│               └── document.py
│
src/rag-service/                    ← Container 3: OCR, Ingestion, Retrieval
├── app/
│   ├── domain/
│   │   ├── entities/
│   │   │   └── document.py         # Document, Chunk
│   │   └── repositories/
│   │       ├── vector_repository.py       # Abstract VectorRepository + UserContext + SearchResult
│   │       ├── document_repository.py     # Abstract DocumentRepository
│   │       └── embedding_service.py       # Abstract EmbeddingService (BGE-M3 interface)
│   │
│   ├── application/
│   │   └── use_cases/
│   │       ├── ingestion/
│   │       │   └── ingest_document_use_case.py
│   │       └── query/
│   │           └── retrieval.py    # Embed → Hybrid search (vector+BM25 RRF) → BGE-Reranker Top-3 → Classification filter
│   │
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── postgres_document_repository.py
│   │   ├── vector/
│   │   │   └── qdrant_vector_repository.py
│   │   └── external/
│   │       ├── bge_m3_client.py         # BGE-M3 Embedding Service client (self-hosted)
│   │       ├── azure_doc_intel_client.py # OCR cho PDF scan (Azure Document Intelligence)
│   │       ├── bge_reranker_client.py   # Reranker client gọi BGE-Reranker service
│   │       └── langfuse_client.py       # Trace ingestion + retrieval
│   │
│   └── interfaces/
│       └── api/
│           ├── main.py
│           ├── routers/
│           │   ├── ingest.py       # POST /ingest
│           │   └── search.py       # POST /search
│           └── schemas/
│               ├── ingest.py
│               └── search.py       # SearchResult response

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

> **Lưu ý Microservices:** Chat Service không gọi Qdrant trực tiếp — nó gọi RAG Service qua HTTP. `RagServiceClient` là Infrastructure adapter đóng gói HTTP call đó. User Service không gọi RAG Service — chỉ xử lý auth/user data.

```python
# src/user-service/app/interfaces/api/dependencies.py
def get_login_use_case() -> LoginUseCase:
    user_repo = PostgresUserRepository()
    return LoginUseCase(user_repo)

# src/chat-service/app/interfaces/api/dependencies.py
def get_orchestration_use_case() -> OrchestrationUseCase:
    rag_client = RagServiceClient(base_url=settings.RAG_SERVICE_URL)  # HTTP client
    conversation_repo = PostgresConversationRepo()
    openai_client = OpenAIClient()
    return OrchestrationUseCase(rag_client, conversation_repo, openai_client)

# src/rag-service/app/interfaces/api/dependencies.py
def get_retrieval_use_case() -> RetrievalUseCase:
    vector_repo = QdrantVectorRepository()       # implement VectorRepository
    embedding_svc = BgeM3EmbeddingService()      # implement EmbeddingService
    return RetrievalUseCase(vector_repo, embedding_svc)

def get_ingest_use_case() -> IngestDocumentUseCase:
    document_repo = PostgresDocumentRepository()
    vector_repo = QdrantVectorRepository()
    embedding_svc = BgeM3EmbeddingService()      # dùng chung interface, cùng 1 instance
    return IngestDocumentUseCase(document_repo, vector_repo, embedding_svc)

# src/chat-service/app/interfaces/api/routers/query.py
@router.post("/query")
async def query(request: QueryRequest, use_case = Depends(get_orchestration_use_case)):
    return await use_case.execute(request.question, request.user_id)
```

---

## Nguyên tắc khi code

1. **Thêm field vào Entity** → báo SA trước, ảnh hưởng tất cả layer
2. **Thêm method vào Repository interface** → SA viết, Dev Infra implement
3. **Không import chéo** giữa `use_cases/query/` và `use_cases/ingestion/`
4. **Mọi external call** (Azure OpenAI, Qdrant, BGE-M3, Azure Document Intelligence) chỉ được gọi từ `infrastructure/`
