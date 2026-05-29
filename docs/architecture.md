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

```
app/
├── domain/
│   ├── entities/
│   │   ├── document.py         # Document, Chunk
│   │   ├── conversation.py     # Conversation, Message
│   │   └── user.py             # User
│   └── repositories/
│       ├── vector_repository.py       # Abstract VectorRepository
│       ├── document_repository.py     # Abstract DocumentRepository
│       ├── conversation_repository.py # Abstract ConversationRepository
│       └── user_repository.py         # Abstract UserRepository
│
├── application/
│   └── use_cases/
│       ├── auth/
│       │   ├── login_use_case.py
│       │   └── verify_token_use_case.py
│       ├── query/
│       │   └── query_document_use_case.py
│       └── ingestion/
│           └── ingest_document_use_case.py
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                        # SQLAlchemy ORM models
│   │   ├── postgres_document_repository.py  # Implements DocumentRepository
│   │   ├── postgres_conversation_repo.py    # Implements ConversationRepository
│   │   └── postgres_user_repository.py      # Implements UserRepository
│   ├── vector/
│   │   └── qdrant_vector_repository.py      # Implements VectorRepository
│   └── external/
│       ├── openai_client.py    # Embedding + Chat Completion wrapper
│       └── gemini_client.py    # Vision OCR wrapper
│
└── interfaces/
    └── api/
        ├── main.py             # FastAPI app init
        ├── dependencies.py     # Dependency injection
        ├── routers/
        │   ├── auth.py
        │   ├── query.py
        │   └── documents.py
        └── schemas/
            ├── query.py        # QueryRequest, QueryResponse
            ├── document.py     # UploadResponse, DocumentList
            └── auth.py         # LoginRequest, TokenResponse
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

```python
# interfaces/api/dependencies.py
def get_query_use_case() -> QueryDocumentUseCase:
    vector_repo = QdrantVectorRepository()       # infrastructure
    conversation_repo = PostgresConversationRepo()
    return QueryDocumentUseCase(vector_repo, conversation_repo)

# interfaces/api/routers/query.py
@router.post("/query")
async def query(request: QueryRequest, use_case = Depends(get_query_use_case)):
    return await use_case.execute(request.question, request.user_id)
```

---

## Nguyên tắc khi code

1. **Thêm field vào Entity** → báo SA trước, ảnh hưởng tất cả layer
2. **Thêm method vào Repository interface** → SA viết, Dev Infra implement
3. **Không import chéo** giữa `use_cases/query/` và `use_cases/ingestion/`
4. **Mọi external call** (OpenAI, Qdrant, Gemini) chỉ được gọi từ `infrastructure/`
