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
from typing import List, Optional
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

    @abstractmethod
    async def list_all(self, is_active: Optional[bool] = None, limit: int = 50, offset: int = 0) -> List[User]:
        """Liệt kê user cho trang quản lý Admin (filter theo is_active, phân trang)."""

    @abstractmethod
    async def set_active(self, user_id: str, is_active: bool) -> None:
        """Deactivate / reactivate user (Admin)."""
```

---

## query-service — Domain

```python
# src/query-service/app/domain/entities/conversation.py
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
# src/query-service/app/domain/repositories/conversation_repository.py
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

    @abstractmethod
    async def save_feedback(self, session_id: str, score: int) -> None:
        """Lưu feedback (1 = thumbs up | -1 = down) vào cột `messages.feedback`
        của câu trả lời assistant gần nhất trong session (POST /feedback)."""
```

> `RerankService` ABC **đã chuyển sang mcp-service** (reranker nằm trong tool `rag_search`) — xem section mcp-service bên dưới.

```python
# src/query-service/app/domain/repositories/document_access_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional

class DocumentAccessRepository(ABC):

    @abstractmethod
    async def get_allowed_doc_ids(self, user_id: str, role: str, department: str) -> Optional[List[str]]:
        """Query bảng projection `document_access` trong query_db → trả list doc_id user được phép đọc.
        Database-per-service: KHÔNG đọc thẳng doc_db của Document Service. Projection này do
        `doc_access_subscriber` cập nhật từ event `doc.access` (NATS JetStream) — eventual consistency.
        None = user chỉ có quyền đọc public docs.
        Logic:
          admin       → None (search tất cả)
          user/public → None (chỉ public)
          internal    → list tất cả doc không phải secret/top_secret
          secret      → doc có allowed_departments contains department
          top_secret  → doc có allowed_user_ids contains user_id
        Kết quả nên được cache Redis TTL ~60s.
        """

    @abstractmethod
    async def upsert_access(self, document_id: str, classification: str,
                            allowed_departments: List[str], allowed_user_ids: List[str]) -> None:
        """`doc_access_subscriber` gọi khi nhận event `doc.access` → upsert projection."""

    @abstractmethod
    async def delete_access(self, document_id: str) -> None:
        """Xóa bản ghi projection khi nhận `doc.access { deleted:true }`."""
```

```python
# src/query-service/app/domain/entities/notification.py
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class Notification:
    id: str
    user_id: str
    event: str                  # 'doc_new' | ...
    message: str
    doc_id: Optional[str]
    is_read: bool
    created_at: datetime
```

```python
# src/query-service/app/domain/repositories/notification_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.entities.notification import Notification

class NotificationRepository(ABC):

    @abstractmethod
    async def save(self, user_id: str, event: str, message: str, doc_id: Optional[str]) -> Notification:
        """`notify_subscriber` ghi 1 bản ghi khi đẩy event SSE (cho Notification Center xem lại)."""

    @abstractmethod
    async def list_history(self, user_id: str, limit: int = 20, offset: int = 0,
                           unread_only: bool = False) -> List[Notification]:
        """GET /notifications/history — lịch sử thông báo (phân trang, lọc chưa đọc)."""

    @abstractmethod
    async def unread_count(self, user_id: str) -> int:
        """GET /notifications/unread-count — badge số chưa đọc."""

    @abstractmethod
    async def mark_read(self, notification_id: str) -> None:
        """POST /notifications/{id}/read — đánh dấu đã đọc."""
```

---

## mcp-service — Domain

MCP Tool Service expose tool qua giao thức MCP. Mỗi tool self-contained. `RerankService` nằm ở đây (trong tool `rag_search`).

```python
# src/mcp-service/app/domain/entities/search_result.py
# Bản sao contract NATS reply rag.search (database-per-service → mỗi service giữ bản riêng,
# đồng bộ shape qua infra/nats/subjects.md). CÙNG shape với SearchResult của rag-worker:
#   chunk_id, document_id, document_name, caption, parent_text, heading_path, score,
#   page_number, source_s3_uri, markdown_s3_uri
@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    parent_text: str
    heading_path: List[str]
    score: float
    page_number: Optional[int] = None
    source_s3_uri: str = ""
    markdown_s3_uri: str = ""
```

```python
# src/mcp-service/app/domain/repositories/rerank_service.py
from abc import ABC, abstractmethod
from typing import List
from app.domain.entities.search_result import SearchResult

class RerankService(ABC):

    @abstractmethod
    async def rerank(self, query: str, chunks: List[SearchResult], top_n: int = 3) -> List[SearchResult]:
        """Rerank chunks bằng BGE-Reranker-v2-m3, trả về top_n có score cao nhất."""
```

```python
# src/mcp-service/app/domain/entities/tool_io.py — I/O contract của MCP tool
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class RagSearchInput:
    query: str
    document_ids: Optional[List[str]]   # do MCP client (Query Service) inject sau khi lọc ACL; None = chỉ public
    top_k: int = 5

@dataclass
class HrQueryInput:
    user_id: str                        # do MCP client inject từ JWT — KHÔNG để LLM tự điền
    intent: str                         # 'leave_balance' | 'leave_requests' | 'payroll'

# --- Output DTO (field bám đúng schema hr_mock trong data-schema.md) ---
@dataclass
class LeaveBalanceDTO:
    annual_total: int
    annual_used: int
    annual_remaining: int               # = annual_total - annual_used
    sick_total: int
    sick_used: int
    sick_remaining: int                 # = sick_total - sick_used

@dataclass
class LeaveRequestDTO:
    leave_type: str                     # 'annual' | 'sick' | 'personal'
    start_date: str                     # 'YYYY-MM-DD'
    end_date: str                       # 'YYYY-MM-DD'
    days_count: int
    status: str                         # 'pending' | 'approved' | 'rejected'

@dataclass
class PayrollDTO:
    period: str                         # 'YYYY-MM'
    gross_salary: float
    deductions: float
    net_salary: float

@dataclass
class HrQueryResult:
    intent: str                                              # echo intent đã hỏi
    leave_balance: Optional[LeaveBalanceDTO] = None          # set khi intent='leave_balance'
    leave_requests: Optional[List[LeaveRequestDTO]] = None   # set khi intent='leave_requests'
    payroll: Optional[List[PayrollDTO]] = None               # set khi intent='payroll' (theo period)
    summary: str = ""                                        # câu tóm tắt tự nhiên cho LLM đưa vào câu trả lời
```

> **MCP tool**: `rag_search(RagSearchInput) -> List[SearchResult]` (Top-3 sau rerank);
> `hr_query(HrQueryInput) -> HrQueryResult` (output typed — tùy `intent` mà field tương ứng được set,
> kèm `summary` để LLM dùng trực tiếp). Query Service là MCP client; tham số nhạy cảm (`document_ids`, `user_id`)
> do client inject, không tin LLM.

```python
# src/mcp-service/app/domain/repositories/hr_repository.py — đọc hr_mock (mcp_db)
from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.entities.tool_io import LeaveBalanceDTO, LeaveRequestDTO, PayrollDTO

class HrRepository(ABC):
    """Query schema hr_mock trong mcp_db. LUÔN filter WHERE user_id (do MCP client inject từ JWT)."""

    @abstractmethod
    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]:
        """Số phép năm/ốm còn lại (hr_mock.leave_balance)."""

    @abstractmethod
    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]:
        """Danh sách đơn nghỉ phép + trạng thái (hr_mock.leave_requests)."""

    @abstractmethod
    async def get_payroll(self, user_id: str) -> List[PayrollDTO]:
        """Bảng lương theo period (hr_mock.payroll_summary)."""
```

---

## rag-worker — Domain

```python
# src/rag-worker/app/domain/entities/document.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class DocumentStatus(str, Enum):
    QUEUED = "queued"           # Admin upload → publish doc.ingest, chờ RAG Worker xử lý
    PROCESSING = "processing"   # RAG Worker đang ingest
    INDEXED = "indexed"         # Đã ingest và index vào Qdrant thành công
    FAILED = "failed"

@dataclass
class Document:
    id: str
    name: str
    file_type: str              # pdf, docx, txt, xlsx, csv, pptx, md
    s3_key: str
    status: DocumentStatus
    uploaded_by: str            # user_id
    created_at: datetime
    chunk_count: int = 0
    error_message: Optional[str] = None
    classification: str = "internal"                                # public | internal | secret | top_secret
    allowed_departments: List[str] = field(default_factory=list)   # bắt buộc nếu secret
    allowed_user_ids: List[str] = field(default_factory=list)      # bắt buộc nếu top_secret

@dataclass
class Chunk:                     # Parent-Child Chunking (LlamaIndex HierarchicalNodeParser)
    chunk_id: str               # uuid — point id trong Qdrant
    parent_id: str              # uuid của parent node
    document_id: str
    child_text: str             # đoạn nhỏ — dùng để EMBED + search
    parent_text: str            # đoạn cha lớn hơn — đưa vào LLM context khi child match
    caption: str                # nhãn ngắn (= section_title trong Qdrant payload; AI-gen/heuristic từ heading)
    heading_path: List[str]     # breadcrumb: ["Chính sách công tác", "Hoàn tiền vé máy bay"]
    page_number: Optional[int] = None
    source_s3_uri: str = ""     # URI file gốc — dùng để cite nguồn
    markdown_s3_uri: str = ""   # URI full document Markdown — dùng khi cần context rộng hơn
```

> `Document` + `Chunk` ở đây chỉ là **entity xử lý in-memory** cho ingestion (parse → **Parent-Child chunk** → embed).
> Việc ghi/đọc bảng `documents` (`DocumentRepository`) thuộc **document-service** — xem section riêng bên dưới.
> RAG Worker không ghi bảng documents, chỉ publish `doc.status`.

```python
# src/rag-worker/app/domain/repositories/embedding_service.py
from abc import ABC, abstractmethod
from typing import List

class EmbeddingService(ABC):

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed 1 đoạn text → vector 1536 dims (text-embedding-3-small)."""

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed nhiều text cùng lúc — dùng khi ingestion chunking."""
```

```python
# src/rag-worker/app/domain/repositories/vector_repository.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class SearchResult:           # = contract NATS reply rag.search (Top-K chunks sau threshold)
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    parent_text: str        # Parent-Child: trả parent_text để đưa vào LLM prompt (match trên child_text)
    heading_path: List[str] # breadcrumb từ root đến chunk
    score: float            # similarity của child_text sau vector search + threshold filter
    page_number: Optional[int] = None
    source_s3_uri: str = "" # URI file gốc — dùng để cite nguồn
    markdown_s3_uri: str = ""  # URI full document Markdown

class VectorRepository(ABC):

    @abstractmethod
    async def upsert(self, chunk_id: str, vector: List[float], payload: dict) -> None:
        """Lưu vector (embed từ child_text) + metadata Parent-Child vào Qdrant."""

    @abstractmethod
    async def hybrid_search(
        self,
        vector: List[float],
        query_text: str,
        top_k: int = 5,
        document_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Hybrid search (vector + BM25 RRF) trên child_text.
        document_ids: filter chỉ search trong các doc này. None = chỉ public docs (fail-secure default).
        document_ids do **mcp-service** truyền vào (Query Service đã lọc ACL từ projection
        `query_db.document_access` và inject qua MCP — rag-worker không biết logic ACL).
        """

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Xóa toàn bộ vectors của một document."""
```

---

## document-service — Domain

Document Service là **chủ sở hữu vòng đời tài liệu** và bảng `documents` (create khi upload, update status
khi nhận `doc.status` từ RAG Worker). Có entity riêng — không import từ rag-worker.

```python
# src/document-service/app/domain/entities/document.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum

class DocumentStatus(str, Enum):
    QUEUED = "queued"           # Admin upload → publish doc.ingest, chờ RAG Worker xử lý
    PROCESSING = "processing"
    INDEXED = "indexed"         # RAG Worker ingest + index Qdrant xong (cập nhật qua doc.status)
    FAILED = "failed"

@dataclass
class Document:
    id: str
    name: str
    file_type: str              # pdf, docx, txt, xlsx, csv, pptx, md
    s3_key: str
    status: DocumentStatus
    uploaded_by: str            # user_id (Admin)
    created_at: datetime
    chunk_count: int = 0
    error_message: Optional[str] = None
    classification: str = "internal"                                # public | internal | secret | top_secret
    allowed_departments: List[str] = field(default_factory=list)   # bắt buộc nếu secret
    allowed_user_ids: List[str] = field(default_factory=list)      # bắt buộc nếu top_secret
```

```python
# src/document-service/app/domain/repositories/document_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.entities.document import Document, DocumentStatus

class DocumentRepository(ABC):

    @abstractmethod
    async def create(self, document: Document) -> Document:
        """Tạo document record mới (status=queued) khi Admin upload."""

    @abstractmethod
    async def get_by_id(self, document_id: str) -> Optional[Document]:
        """Lấy document theo ID."""

    @abstractmethod
    async def list_all(self, status: Optional[DocumentStatus] = None, limit: int = 50, offset: int = 0) -> List[Document]:
        """Liệt kê documents (filter status, phân trang)."""

    @abstractmethod
    async def update_status(self, document_id: str, status: DocumentStatus, chunk_count: int = 0, error: Optional[str] = None) -> None:
        """Cập nhật trạng thái ingestion khi nhận doc.status từ RAG Worker."""

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        """Xóa document (record + báo xóa S3/Qdrant)."""
```

---

## API Schemas (Pydantic)

Contract giữa **Frontend Dev** và **Backend Dev / AI/Agent Engineer**.

```python
# src/query-service/app/interfaces/api/schemas/query.py
from pydantic import BaseModel
from typing import List

class Source(BaseModel):
    document_name: str
    caption: str
    heading_path: List[str]
    score: float
    source_s3_uri: str

class QueryRequest(BaseModel):
    question: str
    user_id: str

class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    session_id: str

# src/document-service/app/interfaces/api/schemas/document.py
class UploadResponse(BaseModel):
    document_id: str
    status: str             # "queued" — Admin upload đi thẳng vào ingestion, không qua approve
    message: str

class DocumentItem(BaseModel):
    id: str
    name: str
    file_type: str
    status: str             # queued | processing | indexed | failed
    classification: str
    uploaded_by: str
    chunk_count: int
    created_at: str

class DocumentList(BaseModel):
    items: List[DocumentItem]
    total: int

# src/user-service/app/interfaces/api/schemas/auth.py
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

# src/user-service/app/interfaces/api/schemas/user.py  (Quản lý user — Admin)
class UserItem(BaseModel):
    id: str
    email: str
    role: str               # "user" | "admin"
    department: str
    is_active: bool

class UserList(BaseModel):
    items: List[UserItem]
    total: int
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
