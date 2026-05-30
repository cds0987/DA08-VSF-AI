# Contracts — Repository Interfaces

Đây là **"hợp đồng"** giữa các thành viên. SA định nghĩa, Dev Infra implement, Dev Use Case gọi.
Không ai được thay đổi file này mà không có approval của SA.

---

## VectorRepository

Dùng cho: Qdrant vector search (Dev 3 — RAG Engineer implement)

```python
# app/domain/repositories/vector_repository.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    document_name: str
    page_number: int
    content: str
    score: float

class VectorRepository(ABC):

    @abstractmethod
    async def upsert(self, chunk_id: str, vector: List[float], payload: dict) -> None:
        """Lưu vector + metadata vào vector DB."""

    @abstractmethod
    async def search(self, vector: List[float], top_k: int = 5) -> List[SearchResult]:
        """Tìm top_k chunks gần nhất theo cosine similarity."""

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Xóa toàn bộ vectors của một document."""
```

---

## DocumentRepository

Dùng cho: PostgreSQL document metadata (Dev 2 — Backend/DB implement)

```python
# app/domain/repositories/document_repository.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class DocumentStatus(str, Enum):
    PENDING = "pending"         # End User upload, chờ Admin approve
    QUEUED = "queued"           # Admin upload trực tiếp, hoặc đã được approve
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"       # Admin reject

@dataclass
class Document:
    id: str
    name: str
    file_type: str          # pdf, docx, txt, xlsx, csv, pptx, md
    s3_key: str
    status: DocumentStatus
    uploaded_by: str        # user_id
    created_at: datetime
    chunk_count: int = 0
    error_message: Optional[str] = None
    classification: str = "internal"                              # public | internal | secret | top_secret
    allowed_departments: List[str] = field(default_factory=list) # cho Secret: list tên phòng ban
    allowed_user_ids: List[str] = field(default_factory=list)    # cho Top Secret: thường = [uploaded_by]

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

---

## ConversationRepository

Dùng cho: Lịch sử hội thoại (Dev 2 — Backend/DB implement)

```python
# app/domain/repositories/conversation_repository.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from datetime import datetime

@dataclass
class Message:
    role: str           # "user" hoặc "assistant"
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
    messages: List[Message]

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

---

## UserRepository

Dùng cho: Auth + user management (Dev 2 — Backend Dev implement)

```python
# app/domain/repositories/user_repository.py
from abc import ABC, abstractmethod
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
    department: str = ""            # phòng ban — dùng để check Secret-level access (Phase 2)
    hashed_password: Optional[str] = None   # None nếu đăng nhập qua Microsoft SSO
    auth_provider: str = "local"    # "local" | "microsoft"

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

## API Schemas (Pydantic)

Đây là contract giữa **Frontend Dev** và **Backend Dev (User Service) / AI/Agent Engineer (Chat Service)**.

```python
# chat-service/interfaces/api/schemas/query.py
from pydantic import BaseModel
from typing import List

class Source(BaseModel):
    document_name: str
    page_number: int
    score: float
    chunk_text: str          # đoạn văn bản gốc được retrieve — dùng để highlight trên viewer

class QueryRequest(BaseModel):
    question: str
    user_id: str

class QueryResponse(BaseModel):
    answer: str             # streamed cuối cùng
    sources: List[Source]
    session_id: str

# chat-service/interfaces/api/schemas/document.py
class UploadResponse(BaseModel):
    document_id: str
    status: str             # "queued" (Admin upload) | "pending" (End User upload)
    message: str

# user-service/interfaces/api/schemas/auth.py
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

---

## API Endpoint Spec

> Đã tách ra file riêng để dễ tham khảo: **[docs/api-spec.md](api-spec.md)**
>
> Bao gồm: tất cả endpoint của User Service, Chat Service, RAG Service (internal) — path, method, request/response format đầy đủ.

---

## DB Schema

> Đã tách ra file riêng để dễ tham khảo: **[docs/data-schema.md](data-schema.md)**
>
> Bao gồm: SQL DDL cho 4 schemas (`user_svc`, `chat_svc`, `rag_svc`, `hr_mock`) + Qdrant payload format.

---

## Quy trình thay đổi contract

1. Mở issue trên GitHub tag SA
2. SA review + approve
3. SA cập nhật file này
4. Các Dev liên quan update implementation của mình
5. Merge — không được tự ý thay đổi interfaces
