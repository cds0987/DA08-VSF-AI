# Contracts — Repository Interfaces

Đây là **"hợp đồng"** giữa các thành viên. SA định nghĩa, Dev Infra implement, Dev Use Case gọi.
Không ai được thay đổi file này mà không có approval của SA.

---

## user-service — Domain

```python
# src/user-service/app/domain/entities/user.py
from dataclasses import dataclass
from typing import Optional
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"

@dataclass
class User:
    id: str
    email: str
    role: UserRole
    is_active: bool = True
    department: str = ""                        # dùng để check Secret-level access
    hashed_password: Optional[str] = None       # None nếu đăng nhập qua Microsoft SSO
    auth_provider: str = "local"                # "local" | "microsoft"
```

```python
# src/user-service/app/domain/repositories/user_repository.py
from abc import ABC, abstractmethod
from typing import Optional
from app.domain.entities.user import User

class UserRepository(ABC):

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """Tìm user theo email (dùng cho login)."""

    @abstractmethod
    async def get_by_id(self, user_id: str) -> Optional[User]:
        """Tìm user theo ID (dùng cho JWT verify)."""

    @abstractmethod
    async def create(self, user: User) -> User:
        """Tạo user mới."""
```

---

## chat-service — Domain

```python
# src/chat-service/app/domain/entities/conversation.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class Message:
    role: str           # "user" | "assistant"
    content: str
    created_at: datetime

@dataclass
class ConversationContext:
    summary: Optional[str]          # LLM-generated summary của các turns cũ (None nếu chưa đủ để compress)
    recent_messages: List[Message]  # 5 turns gần nhất giữ nguyên verbatim

@dataclass
class Conversation:
    id: str
    user_id: str
    messages: List[Message] = field(default_factory=list)
```

```python
# src/chat-service/app/domain/repositories/conversation_repository.py
from abc import ABC, abstractmethod
from typing import Optional
from app.domain.entities.conversation import ConversationContext

class ConversationRepository(ABC):

    @abstractmethod
    async def get_context(self, user_id: str, recent_k: int = 5) -> ConversationContext:
        """Lấy context cho LLM: summary của history cũ + recent_k turns gần nhất verbatim."""

    @abstractmethod
    async def save_message(self, user_id: str, role: str, content: str) -> None:
        """Lưu 1 tin nhắn vào lịch sử."""

    @abstractmethod
    async def update_summary(self, user_id: str, summary: str) -> None:
        """Cập nhật summary sau khi LLM compress các turns cũ."""

    @abstractmethod
    async def clear_history(self, user_id: str) -> None:
        """Xóa toàn bộ lịch sử và summary của user."""
```

```python
# src/chat-service/app/domain/repositories/rerank_service.py
from abc import ABC, abstractmethod
from typing import List
from app.domain.entities.search_result import SearchResult

class RerankService(ABC):

    @abstractmethod
    async def rerank(self, query: str, sections: List[SearchResult], top_n: int = 3) -> List[SearchResult]:
        """Rerank sections bằng BGE-Reranker-v2-m3, trả về top_n có score cao nhất."""
```

```python
# src/chat-service/app/domain/repositories/document_access_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional

class DocumentAccessRepository(ABC):

    @abstractmethod
    async def get_allowed_doc_ids(self, user_id: str, role: str, department: str) -> Optional[List[str]]:
        """Query PostgreSQL rag_svc.documents → trả list doc_id user được phép đọc.
        None = user chỉ có quyền đọc public docs.
        Logic:
          admin       → None (search tất cả)
          user/public → None (chỉ public)
          internal    → list tất cả doc không phải secret/top_secret
          secret      → doc có allowed_departments contains department
          top_secret  → doc có allowed_user_ids contains user_id
        Kết quả nên được cache Redis TTL ~60s.
        """
```

---

## rag-service — Domain

```python
# src/rag-service/app/domain/entities/document.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class DocumentStatus(str, Enum):
    PENDING = "pending"         # End User upload, chờ Admin approve
    QUEUED = "queued"           # Admin upload trực tiếp, hoặc đã được approve
    PROCESSING = "processing"
    INDEXED = "indexed"         # Đã ingest và index vào Qdrant thành công
    FAILED = "failed"
    REJECTED = "rejected"       # Admin reject

@dataclass
class Document:
    id: str
    name: str
    file_type: str              # pdf, docx, txt, xlsx, csv, pptx, md
    s3_key: str
    status: DocumentStatus
    uploaded_by: str            # user_id
    created_at: datetime
    section_count: int = 0
    error_message: Optional[str] = None
    classification: str = "internal"                                # public | internal | secret | top_secret
    allowed_departments: List[str] = field(default_factory=list)   # bắt buộc nếu secret
    allowed_user_ids: List[str] = field(default_factory=list)      # bắt buộc nếu top_secret

@dataclass
class Section:
    section_id: str             # format: {doc_id}_section_{index}
    document_id: str
    section_content: str        # processed Markdown — đưa thẳng vào LLM prompt
    caption: str                # nhãn ngắn (AI-generated hoặc heuristic từ heading)
    heading_path: List[str]     # breadcrumb: ["Chính sách công tác", "Hoàn tiền vé máy bay"]
    source_s3_uri: str          # URI file gốc — dùng để cite nguồn
    markdown_s3_uri: str        # URI full document Markdown — dùng khi cần context rộng hơn
```

```python
# src/rag-service/app/domain/repositories/document_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.entities.document import Document, DocumentStatus

class DocumentRepository(ABC):

    @abstractmethod
    async def create(self, document: Document) -> Document:
        """Tạo document record mới."""

    @abstractmethod
    async def get_by_id(self, document_id: str) -> Optional[Document]:
        """Lấy document theo ID."""

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> List[Document]:
        """Liệt kê tất cả documents."""

    @abstractmethod
    async def update_status(self, document_id: str, status: DocumentStatus, error: Optional[str] = None) -> None:
        """Cập nhật trạng thái ingestion."""

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        """Soft delete document."""
```

```python
# src/rag-service/app/domain/repositories/embedding_service.py
from abc import ABC, abstractmethod
from typing import List

class EmbeddingService(ABC):

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed 1 đoạn text → vector 1024 dims (BGE-M3)."""

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed nhiều text cùng lúc — dùng khi ingestion chunking."""
```

```python
# src/rag-service/app/domain/repositories/vector_repository.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class SearchResult:
    section_id: str
    document_id: str
    document_name: str
    caption: str
    section_content: str    # processed Markdown — đưa thẳng vào LLM prompt
    heading_path: List[str] # breadcrumb từ root đến section
    score: float            # similarity score sau vector search và threshold filter
    source_s3_uri: str      # URI file gốc — dùng để cite nguồn
    markdown_s3_uri: str    # URI full document Markdown

class VectorRepository(ABC):

    @abstractmethod
    async def upsert(self, section_id: str, vector: List[float], payload: dict) -> None:
        """Lưu vector + metadata vào Qdrant."""

    @abstractmethod
    async def hybrid_search(
        self,
        vector: List[float],
        query_text: str,
        top_k: int = 20,
        document_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Hybrid search (vector + BM25 RRF).
        document_ids: filter chỉ search trong các doc này.
        None = chỉ search public docs (fail-secure default).
        Chat Service tự query allowed_doc_ids từ PostgreSQL trước khi gọi.
        """

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Xóa toàn bộ vectors của một document."""
```

---

## API Schemas (Pydantic)

Contract giữa **Frontend Dev** và **Backend Dev / AI/Agent Engineer**.

```python
# src/chat-service/app/interfaces/api/schemas/query.py
from pydantic import BaseModel
from typing import List

class Source(BaseModel):
    document_name: str
    page_number: int
    score: float
    chunk_text: str         # đoạn văn bản gốc được retrieve — dùng để highlight trên viewer

class QueryRequest(BaseModel):
    question: str
    user_id: str

class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    session_id: str

# src/chat-service/app/interfaces/api/schemas/document.py
class UploadResponse(BaseModel):
    document_id: str
    status: str             # "queued" (Admin upload) | "pending" (End User upload)
    message: str

# src/user-service/app/interfaces/api/schemas/auth.py
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

---

## API Endpoint Spec

> Đã tách ra file riêng: **[docs/api-spec.md](api-spec.md)**

---

## DB Schema

> Đã tách ra file riêng: **[docs/data-schema.md](data-schema.md)**

---

## Quy trình thay đổi contract

1. Mở issue trên GitHub tag SA
2. SA review + approve
3. SA cập nhật file này
4. Các Dev liên quan update implementation của mình
5. Merge — không được tự ý thay đổi interfaces
