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
    account_type: str = "internal"              # "internal" | "external"
    department: str = ""                        # Phase 1 snapshot; production source of truth: HR Service
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
class Source:
    document_id: Optional[str]
    document_name: str
    caption: str
    heading_path: List[str]
    score: float
    source_gcs_uri: str

@dataclass
class Message:
    role: str           # "user" | "assistant"
    content: str
    created_at: datetime
    sources: Optional[List[Source]] = None  # chỉ có ở assistant message có citation

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
    async def save_message(self, user_id: str, role: str, content: str,
                           sources: Optional[List[Source]] = None,
                           latency_ms: Optional[int] = None) -> None:
        """Lưu 1 tin nhắn vào lịch sử.

        `sources` chỉ set cho assistant message khi câu trả lời có citation từ `rag_search`.
        User message, HR-only answer hoặc fallback answer để `sources=None`/`[]`.
        """

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

> Rerank **nằm trong mcp-service** (trong tool `rag_search`). Trong code thật reranker là một `Reranker` **Protocol** ở `app/core/rerank.py` (impl `none`/`lexical`/`llm`), KHÔNG phải `RerankService` ABC ở `domain/repositories/` — xem section mcp-service bên dưới.

```python
# src/query-service/app/domain/repositories/document_access_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional

class DocumentAccessRepository(ABC):

    @abstractmethod
    async def get_allowed_doc_ids(self, user_id: str, role: str, account_type: str,
                                  department: Optional[str]) -> Optional[List[str]]:
        """Query projection `document_access` + `user_access_profile` trong query_db
        → trả list doc_id user được phép đọc.
        Database-per-service: KHÔNG đọc thẳng doc_db của Document Service. Projection này do
        `doc_access_subscriber` cập nhật từ event `doc.access` (NATS JetStream) — eventual consistency.
        `user_access_profile_subscriber` cập nhật từ event `hr.employee_profile.updated`.
        None = user chỉ có quyền đọc public docs.
        Logic:
          admin       → None (search tất cả)
          public      → internal/external đều đọc được
          internal    → account_type == internal
          secret      → account_type == internal AND doc có allowed_departments contains department
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

MCP Tool Service expose tool qua giao thức MCP Streamable HTTP (`:8003`, path `/mcp`). **Search-only routing layer** —
KHÔNG sở hữu dữ liệu HR. Tool đăng ký qua registry (`app/tools/`); hiện có 2 tool built-in: `rag_search` (đọc Qdrant)
và `hr_query` (HTTP proxy sang **hr-service**).

> ⚠️ **Lưu ý đối chiếu code**: mcp-service KHÔNG có `domain/repositories/*.py` (không `RerankService`/`HrClient` ABC),
> KHÔNG có `domain/entities/search_result.py`. Shape kết quả search là `SearchHit` ở `app/core/vectorstore.py`;
> reranker là `Reranker` Protocol ở `app/core/rerank.py`. `app/domain/entities/tool_io.py` chỉ còn `RagSearchInput`.
> Toàn bộ DTO HR + `HrRepository` đã chuyển sang **hr-service** (xem section hr-service bên dưới).

```python
# src/mcp-service/app/core/vectorstore.py — shape 1 hit trả về cho client (KHÔNG phải domain entity).
# CÙNG field với SearchResult của rag-worker (ghép qua Qdrant: point_id uuid5 + payload keys phải khớp).
@dataclass
class SearchHit:
    chunk_id: str = ""
    document_id: str = ""
    document_name: str = ""
    caption: str = ""
    parent_text: str = ""
    heading_path: List[str] = field(default_factory=list)
    score: float = 0.0
    page_number: int | None = None
    source_gcs_uri: str = ""
    markdown_gcs_uri: str = ""
```

```python
# src/mcp-service/app/core/rerank.py — reranker là Protocol, KHÔNG phải ABC ở domain/.
# Impl: NoopReranker (giữ thứ tự vector score) | LexicalReranker (overlap) | LlmReranker (LLM chấm 0..1).
# build_reranker("none"|"lexical"|"llm"); "llm" lỗi/timeout → fallback NoopReranker (best-effort).
class Reranker(Protocol):
    async def rerank(self, query: str, hits: List[SearchHit],
                     top_k: int, threshold: float) -> List[SearchHit]: ...
```

```python
# src/mcp-service/app/domain/entities/tool_io.py — CHỈ còn input của rag_search.
@dataclass
class RagSearchInput:
    query: str
    document_ids: Optional[List[str]]   # MCP client (Query Service) inject sau khi lọc ACL; None = chỉ public.
                                        # mcp-service NHẬN nhưng search tool KHÔNG filter (no-op) — ACL do service khác.
    top_k: int = 5
```

> **MCP tool — chữ ký & output thật (theo code):**
> - `rag_search(query: str, document_ids: list[str] | None = None, top_k: int | None = None) -> dict`
>   → `{"results": [SearchHit-as-dict, ...]}` (đã rerank, top-k). Đăng ký tại `app/tools/rag_search.py`.
> - `hr_query(user_id: str, intent: str) -> dict` → **proxy** POST `/hr/query` sang hr-service,
>   trả thẳng body `{"intent": ..., "data": {...}, "summary": ...}`. Đăng ký tại `app/tools/hr_query.py`.
>   mcp-service KHÔNG typed output này; envelope do hr-service quyết.
> - Tham số nhạy cảm (`document_ids`, `user_id`) do MCP client inject từ ACL/JWT, **không tin LLM**.
> - `hr_query` mặc định **TẮT** (`TOOL_HR_QUERY_ENABLED=0`); bật khi hr-service sẵn sàng.
> - Tool tạo đơn nghỉ phép (`create_leave_request`) **chưa đăng ký là MCP tool** trong mcp-service — hr-service
>   đã có endpoint leave-request nhưng chưa expose qua MCP. (Roadmap/SA narrative còn ghi 3 tool — chưa khớp code.)

---

## hr-service — Domain

HR Service (**Container 6**, `:8004`, internal only) sở hữu toàn bộ HR data trong `hr_db` (schema **`hr_svc`** ở
production; code mock hiện seed schema này). mcp-service tool `hr_query` gọi vào qua HTTP nội bộ
(`X-Internal-Token`). Filter bắt buộc `WHERE user_id = :current_user_id`.

```python
# src/hr-service/app/domain/entities/dtos.py — DTO thật (đã chuyển từ mcp-service sang đây).
@dataclass(frozen=True)
class HrQueryInput:
    user_id: str                        # MCP client inject từ JWT — KHÔNG để LLM tự điền
    intent: str

@dataclass(frozen=True)
class LeaveBalanceDTO:
    annual_total: int
    annual_used: int
    annual_remaining: int
    sick_total: int
    sick_used: int
    sick_remaining: int

@dataclass(frozen=True)
class LeaveRequestDTO:                   # bản MVP đơn giản hóa (không có id/approver/rejected_reason)
    leave_type: str
    start_date: str                     # 'YYYY-MM-DD'
    end_date: str
    days_count: int
    status: str

@dataclass(frozen=True)
class PayrollDTO:                        # schema có sẵn nhưng intent payroll CHƯA expose (chờ SA-3)
    period: str                         # 'YYYY-MM'
    gross_salary: float
    deductions: float
    net_salary: float

@dataclass(frozen=True)
class AttendanceDTO:
    period: str
    work_days: int
    late_count: int
    absent_count: int

@dataclass(frozen=True)
class OnboardingItemDTO:
    task: str
    done: bool

@dataclass(frozen=True)
class OnboardingDTO:
    status: str
    checklist: list[OnboardingItemDTO] = field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0

@dataclass(frozen=True)
class HrQueryResult:                     # envelope chung — data là dict tùy intent (KHÔNG phải union typed field)
    intent: str
    data: dict
    summary: str
```

```python
# src/hr-service/app/domain/repositories/hr_repository.py — ABC, PostgresHrRepository implement.
# Mọi method nhận user_id và LUÔN filter WHERE user_id.
class HrRepository(ABC):
    async def ping(self) -> None: ...
    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]: ...
    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]: ...
    async def get_attendance(self, user_id: str) -> Optional[AttendanceDTO]: ...
    async def get_onboarding(self, user_id: str) -> Optional[OnboardingDTO]: ...
    async def get_payroll(self, user_id: str) -> List[PayrollDTO]: ...   # chưa expose qua endpoint
    async def aclose(self) -> None: ...
```

> **HTTP contract (hr-service, theo `app/api/routes.py`):**
> - `POST /hr/query` — body `{"user_id": str, "intent": Literal["leave_balance","leave_requests","attendance","onboarding"]}`,
>   header `X-Internal-Token`. Trả `{"intent", "data", "summary"}`. Intent không hợp lệ → 422; user không có HR data → 404.
> - `GET /health` → `{"status": "ok"}` (dùng bởi `HrQueryTool.verify()` lúc startup, fail-closed).
> - `payroll` schema có sẵn nhưng **chưa nằm trong `Literal` intent** — chặn bởi SA-3.
> - **Leave request MVP**: AI tạo draft, chỉ gọi tool tạo đơn sau khi user xác nhận; HR Service set `status='pending'`,
>   `approver_user_id = employees.manager_user_id`. (Endpoint tạo/duyệt đơn còn ở giai đoạn thiết kế, xem `src/hr-service/docs/intent.md`.)

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
    gcs_key: str
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
    source_gcs_uri: str = ""     # URI file gốc — dùng để cite nguồn
    markdown_gcs_uri: str = ""   # URI full document Markdown — dùng khi cần context rộng hơn
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
    source_gcs_uri: str = "" # URI file gốc — dùng để cite nguồn
    markdown_gcs_uri: str = ""  # URI full document Markdown

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
    gcs_key: str
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
        """Xóa document (record + báo xóa GCS/Qdrant)."""
```

---

## API Schemas (Pydantic)

Contract giữa **Frontend Dev** và **Backend Dev / AI/Agent Engineer**.

```python
# src/query-service/app/interfaces/api/schemas/query.py
from pydantic import BaseModel
from typing import List

class Source(BaseModel):
    document_id: Optional[str] = None
    document_name: str
    caption: str
    heading_path: List[str]
    score: float
    source_gcs_uri: str

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

# POST /auth/login       → Chat app (:3000) — nhận cả user lẫn admin
# POST /auth/admin/login → Admin app (:3001) — chỉ nhận admin; user trả 401 generic

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
