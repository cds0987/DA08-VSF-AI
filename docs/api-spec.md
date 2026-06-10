# API Specification — RAG Chatbot

Danh sách đầy đủ endpoint của các services. Frontend Dev dùng file này để biết chính xác path, method, header, request/response format.

> **Base URL local:**
> - User Service: `http://localhost:8000`
> - Document Service: `http://localhost:8002` _(Admin only)_
> - Query Service: `http://localhost:8001`
> - MCP Service: `http://localhost:8003` _(internal MCP tool gateway)_
> - HR Service: `http://localhost:8004` _(internal only)_
> - RAG Worker: không expose HTTP — giao tiếp qua NATS :4222 _(internal)_
>
> **Auth header** (trừ `/auth/login` và `/auth/admin/login`): `Authorization: Bearer <jwt_token>`

---

## User Service — `/auth`

### `POST /auth/login`

Dùng cho **Chat app** (`:3000/login`). Chấp nhận cả `role=user` và `role=admin` — sau login đều vào chat.

```
Request:
  Content-Type: application/json
  Body: { "email": "user@company.com", "password": "string" }

Response 200:  { "access_token": "eyJ...", "token_type": "bearer" }
Response 401:  { "detail": "Invalid credentials" }
Response 423:  { "detail": "Account locked. Try again after 15 minutes." }
```

### `POST /auth/admin/login`

Dùng cho **Admin app** (`:3001/login`). Chỉ chấp nhận `role=admin`.
`role=user` trả 401 generic — không lộ lý do thật để tránh account enumeration.

```
Request:
  Content-Type: application/json
  Body: { "email": "admin@company.com", "password": "string" }

Response 200:  { "access_token": "eyJ...", "token_type": "bearer" }
Response 401:  { "detail": "Invalid credentials" }
Response 423:  { "detail": "Account locked. Try again after 15 minutes." }
```

### `GET /auth/me`

```
Request:  Authorization: Bearer <token>

Response 200:  { "id": "uuid", "email": "string", "role": "user" | "admin", "account_type": "internal" | "external", "department": "string" }
Response 401:  { "detail": "Not authenticated" }
```

### `POST /auth/refresh`

```
Request Body: { "refresh_token": "string" }

Response 200:  { "access_token": "eyJ...", "refresh_token": "new_refresh_token", "token_type": "bearer" }
Response 401:  { "detail": "Invalid or expired refresh token" }
```

> Refresh Token TTL 7 ngày, rotate-on-use — mỗi lần gọi endpoint này trả về refresh token mới, invalidate cái cũ. Lưu refresh token hash trong `user_svc.refresh_tokens` (không lưu raw token).

### `GET /health`

```
Response 200:  { "status": "ok", "database": "ok" }
Response 503:  { "status": "degraded", "degraded_reasons": ["database unreachable"] }
```

---

## User Service — `/users` (Quản lý user — Admin)

> **Admin only** — tất cả endpoint yêu cầu role `admin`. Backing cho trang `admin/users` của Frontend.

### `GET /users`

```
Query params: ?is_active=true|false&limit=50&offset=0

Response 200:
  {
    "items": [
      { "id": "uuid", "email": "string", "role": "user" | "admin",
        "account_type": "internal" | "external", "department": "string", "is_active": true }
    ],
    "total": 12
  }
Response 403:  { "detail": "Admin only" }
```

### `PATCH /users/{user_id}/deactivate`

```
Response 200:  { "id": "uuid", "is_active": false }
Response 403:  { "detail": "Admin only" }
Response 404:  { "detail": "User not found" }
```

> Deactivate → user không đăng nhập được; token đang hoạt động bị từ chối ở bước verify (kiểm tra `is_active`).

### `PATCH /users/{user_id}/reactivate`

```
Response 200:  { "id": "uuid", "is_active": true }
Response 403:  { "detail": "Admin only" }
Response 404:  { "detail": "User not found" }
```

---

## Document Service — `/documents`

> **Admin only** — tất cả endpoint yêu cầu role `admin`. End User không có quyền truy cập Document Service.
> Upload xong → status `queued` ngay, Document Service publish NATS `doc.ingest` → RAG Worker tự xử lý (không qua bước approve/reject).

### `POST /documents/upload`

```
Request:
  Content-Type: multipart/form-data
  Authorization: Bearer <admin_token>
  Fields:
    file: <binary> (max 50MB, pdf/docx/txt/xlsx/csv/pptx/md)
    classification: "public" | "internal" | "secret" | "top_secret"
    allowed_departments?: ["HR", "Finance"]   # bắt buộc nếu secret
    allowed_user_ids?: ["uuid"]               # bắt buộc nếu top_secret

Response 202:  { "document_id": "uuid", "status": "queued", "message": "Ingestion started" }
Response 400:  { "detail": "File type not supported" | "File exceeds 50MB" }
Response 403:  { "detail": "Admin only" }
```

### `GET /documents`

```
Query params: ?status=queued|processing|indexed|failed&limit=50&offset=0

Response 200:
  {
    "items": [
      { "id": "uuid", "name": "string", "file_type": "string", "status": "string",
        "classification": "string", "uploaded_by": "uuid", "chunk_count": 42, "created_at": "iso8601" }
    ],
    "total": 10
  }
```

### `GET /documents/{document_id}`

```
Response 200:  { ...same as item above..., "error_message": null | "string" }
Response 404:  { "detail": "Document not found" }
```

### `DELETE /documents/{document_id}`

```
Response 200:  { "message": "Document deleted" }
Response 403:  { "detail": "Admin only" }
```

### `GET /documents/{document_id}/file`

> Trả **presigned GCS URL** (TTL ngắn) để Frontend Document Viewer mở file gốc + highlight citation. Kiểm tra ACL theo user.

```
Response 200:  { "url": "https://<bucket>.s3.../...&X-Amz-Expires=300", "file_type": "pdf", "expires_in": 300 }
Response 403:  { "detail": "Không có quyền xem tài liệu này" }
Response 404:  { "detail": "Document not found" }
```

### `GET /health`

```
Response 200:  { "status": "ok", "database": "ok", "nats": "ok" }
Response 503:  { "status": "degraded", "degraded_reasons": ["nats unreachable"] }
```

---

## Query Service — `/query`, `/conversations`, `/feedback`

### `POST /query`

Streaming câu trả lời qua **Server-Sent Events (SSE)** — request-scoped: mở stream cho 1 câu hỏi, trả xong thì đóng.

```
Request:
  Authorization: Bearer <token>
  Body: { "question": "string (max 500 ký tự)", "user_id": "uuid" }

Response 200 (SSE):
  data: {"token": "Theo "}
  data: {"token": "chính sách..."}
  data: {"done": true, "sources": [{"document_id": "uuid", "document_name": "string", "caption": "string", "heading_path": ["string"], "score": 0.85, "source_gcs_uri": "gs://..."}], "session_id": "uuid"}

Response 429:  { "detail": "Rate limit exceeded. Max 20 requests/minute." }
```

### `GET /notifications`

Stream **SSE app-level** (mở sẵn sau đăng nhập, giữ lâu) để server **đẩy thông báo** xuống client — ví dụ "có tài liệu mới". Một chiều server → client.

```
Request:
  Authorization: Bearer <token>
  (EventSource giữ kết nối; server push khi có sự kiện)

Response 200 (SSE):
  data: {"type": "notify", "event": "doc_new", "message": "Có tài liệu mới: Chính sách công tác 2026", "doc_id": "uuid"}

Server gửi comment `:keep-alive` định kỳ (~25s) để giữ kết nối qua proxy. Client (EventSource) tự reconnect khi rớt.
```

> **Vì sao SSE (không WebSocket):** chỉ cần server đẩy 1 chiều (stream trả lời + thông báo) → SSE đủ và đơn giản hơn. Tương tác 2 chiều (typing, multi-user) để Phase 2 mới cân nhắc WebSocket.

### `GET /notifications/history`

> Lịch sử thông báo đã lưu (cho Notification Center). Realtime qua SSE ở trên; cái này để xem lại khi offline/reload.

```
Query params: ?limit=20&offset=0&unread_only=false
Response 200:
  {
    "items": [
      { "id": "uuid", "event": "doc_new", "message": "Có tài liệu mới: ...", "doc_id": "uuid",
        "is_read": false, "created_at": "iso8601" }
    ],
    "total": 8
  }
```

### `GET /notifications/unread-count`

```
Response 200:  { "unread": 3 }
```

### `POST /notifications/{notification_id}/read`

```
Response 200:  { "id": "uuid", "is_read": true }
```

### `GET /conversations`

```
Query params: ?limit=20&offset=0
Response 200:
  {
    "messages": [
      {
        "role": "user" | "assistant",
        "content": "string",
        "sources": [{"document_id": "uuid", "document_name": "string", "caption": "string", "heading_path": ["string"], "score": 0.85, "source_gcs_uri": "gs://..."}],
        "created_at": "iso8601"
      }
    ]
  }
```

> `sources` chỉ có ý nghĩa với assistant message. User message hoặc câu trả lời không dùng tài liệu nội bộ có thể trả `sources: []`.

### `DELETE /conversations`

```
Response 200:  { "message": "Conversation history cleared" }
```

### `POST /feedback`

```
Request Body: { "session_id": "uuid", "score": 1 | -1 }   # 1 = thumbs up, -1 = thumbs down
Response 200:  { "message": "Feedback recorded" }
```

### `GET /admin/metrics`  (Admin only)

> Dữ liệu cho Admin Analytics Dashboard. Đọc từ `query_db` (messages, feedback). Admin only.

```
Query params: ?from=2026-06-01&to=2026-06-03
Response 200:
  {
    "total_questions": 1280,
    "by_day": [ { "date": "2026-06-01", "count": 420 } ],
    "feedback": { "up": 310, "down": 24, "rate": 0.93 },
    "top_questions": [ { "question": "Chính sách nghỉ phép?", "count": 57 } ]
  }
Response 403:  { "detail": "Admin only" }
```

### `GET /health`

```
Response 200:  { "status": "ok", "database": "ok", "mcp_service": "ok" }
Response 503:  { "status": "degraded", "degraded_reasons": ["rag_worker unreachable"] }
```

---

## RAG Worker — NATS Internal Only

> Không expose HTTP. Chỉ giao tiếp qua NATS :4222.
> **Subject contract do Backend Dev làm chủ** (đăng ký ở `infra/nats/subjects.md`).
>
> ⚠️ **Theo code:** RAG Worker là **ingest-only** — chỉ subscribe `doc.ingest` và publish `doc.status`. KHÔNG có subject `rag.search`/request-reply retrieval. Retrieval do mcp-service đọc Qdrant trực tiếp (ghép với RAG Worker chỉ qua Qdrant).

| Subject | Type | Payload | Mô tả |
|---------|------|---------|-------|
| `doc.ingest` | Subscribe | `{ doc_id, gcs_key, file_type, classification, allowed_departments, allowed_user_ids }` | Document Service publish khi Admin upload. RAG Worker nhận → chạy pipeline ingestion. |
| `doc.status` | Publish | `{ doc_id, status: "indexed"\|"failed", chunk_count?, error? }` | RAG Worker publish sau khi ingestion xong. Document Service subscribe để cập nhật PostgreSQL. |

---

## Document Service → Query Service — NATS Event (ACL event-driven)

> Database-per-service: Query Service **không đọc thẳng `doc_db`**. Document Service phát event quyền truy cập; Query Service giữ bản sao trong `query_db.document_access` (eventual consistency).

| Subject | Type | Payload | Mô tả |
|---------|------|---------|-------|
| `doc.access` | Publish (Document Service) / Subscribe (Query Service) | `{ doc_id, classification, allowed_departments, allowed_user_ids, deleted: bool }` | Document Service publish mỗi khi upload / đổi quyền / xóa tài liệu. Query Service subscribe (JetStream durable) → upsert/xóa bản ghi trong projection `document_access`. Dùng cho ACL pre-filter. |
| `notify.doc_new` | Publish (Document Service) / Subscribe (Query Service) | `{ doc_id, document_name, classification, allowed_departments, allowed_user_ids }` | Document Service publish khi tài liệu ingest xong (nhận `doc.status=indexed`). Query Service subscribe → lọc các user **đang online** (trong `connection_manager`) có quyền xem theo ACL → đẩy `{type:"notify", event:"doc_new"}` xuống stream **SSE `GET /notifications`** của các user đó. |

---

## HR Service → Query Service — NATS Event (Employee access projection)

> **Đây là WRITE / event-propagation path, KHÔNG phải read `hr_query`.** Tool `hr_query` (`POST /hr/query`) là đường đọc đồng bộ, không đụng NATS. NATS chỉ dùng khi HR data **bị ghi/đổi** (employee profile, sau này cả leave-request) → publish event để service khác đồng bộ read-model của họ (eventual consistency), thay vì gọi HR trực tiếp trên hot path.
>
> HR Service là source of truth cho employee profile/department. Query Service **không gọi trực tiếp HR Service** trong hot path chat; thay vào đó giữ projection `query_svc.user_access_profile` được cập nhật bằng JetStream durable consumer.
>
> ⏳ **Trạng thái code:** scaffold, **chưa wire** — `src/hr-service/app/infrastructure/nats_publisher.py` (`NatsPublisher.publish` no-op) + `app/application/services/employee_profile_service.py` chưa được instantiate; `requirements.txt` chưa có `nats-py`; cũng chưa có endpoint ghi employee profile để trigger.

| Subject | Type | Payload | Mô tả |
|---------|------|---------|-------|
| `hr.employee_profile.updated` | Publish (HR Service) / Subscribe (Query Service) | `{ event_id, event_version, occurred_at, user_id, account_type, department, employment_status }` | HR Service publish khi employee profile, department hoặc employment status thay đổi. Query Service upsert projection `user_access_profile` để ACL pre-filter theo `account_type + department + user_id`. |
| `hr.leave_request.created` | Publish (HR Service) / Subscribe (Query Service) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, leave_type, start_date, end_date, days_count, status }` | HR Service publish **sau khi commit** đơn `pending`. Query Service (Notification Center) đẩy SSE cho **sếp** (`approver_user_id`): "có đơn cần duyệt". Thay cho việc sếp polling `pending-approval`. |
| `hr.leave_request.approved` | Publish (HR Service) / Subscribe (Query Service) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, status }` | Publish sau khi approve (đã trừ balance). Query Service đẩy SSE cho **nhân viên** (`requester_user_id`): "đơn được duyệt". |
| `hr.leave_request.rejected` | Publish (HR Service) / Subscribe (Query Service) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, status, rejected_reason }` | Publish sau khi reject. Query Service đẩy SSE cho **nhân viên**: "đơn bị từ chối". |

> **Ranh giới (leave request):** hr-service **chỉ publish** event sau commit (`event_id` để consumer idempotent). **Không** đẩy thẳng tới user. Bên **query-service** thêm subscriber (giống `notify_subscriber` cho `doc_new`) để route SSE theo `approver_user_id`/`requester_user_id`. Đây là contract bàn giao — query-service tự implement phía consume. ⏳ Cả publisher (hr-service) lẫn subscriber (query-service) **chưa implement**.

> HR Service deploy như backend service thật nhưng internal only (không qua API Gateway, chỉ gọi nội bộ bằng header `X-Internal-Token`). Endpoint **thật theo `src/hr-service/app/api/routes.py`**: chỉ `POST /hr/query` + `GET /health`. mcp-service tool `hr_query` là HTTP proxy gọi vào `POST /hr/query`.

### `POST /hr/query` — truy vấn HR cá nhân (self-access)

```
Request:
  Header: X-Internal-Token: <internal token>
  Body: {
    "user_id": "uuid",                  # MCP client inject từ JWT — KHÔNG để LLM tự điền
    "intent": "leave_balance"           # Literal: leave_balance | leave_requests | attendance
                                        #          | onboarding | payroll | benefits | performance
  }

Response 200:
  { "intent": "leave_balance", "data": { ... }, "summary": "..." }   # data là dict tùy intent

Lỗi:
  422  intent không nằm trong Literal (Pydantic validation)
  404  user không có HR data cho intent này  ("no HR data for this user")
  401  thiếu/sai X-Internal-Token
```

> Mọi query lọc cứng `WHERE user_id = <token user>`. Intent nhạy cảm (`payroll`/`benefits`/`performance`) là self-access (data của chính user) nên **không cần role-gate**; hr-service ghi **audit log** mỗi lần truy cập (mask user_id, không log số liệu) — xem `SENSITIVE_INTENTS` trong `routes.py`. `external` accounts không có HR personal data → 404.

### `GET /health`

```
Response 200:
  { "status": "ok" }
```

> Dùng bởi `HrQueryTool.verify()` lúc mcp-service startup (best-effort — hr-service down KHÔNG làm sập mcp-service/rag_search).

### 🟡 Leave request WRITE flow — THIẾT KẾ ĐÃ CHỐT, chưa implement

> Các endpoint dưới đây **chưa có** trong `routes.py` — đã chốt thiết kế, chờ implement (cần SA approve contract).
> Bảng `hr_svc.leave_requests` đã sẵn cột (`status`, `approver_user_id`, `approved_at`, `rejected_at`, `rejected_reason`, …).
> Thiết kế đầy đủ: [`src/hr-service/docs/intent.md`](../src/hr-service/docs/intent.md) (section WRITE flow).

**Nguyên tắc:** hr-service chỉ **ghi DB + publish NATS event**, KHÔNG đẩy thẳng tới user. Báo cho user (sếp/nhân viên) do **query-service (Notification Center) consume event → SSE** (xem section NATS bên dưới). Định danh: `user_id`/`approver_user_id` luôn từ JWT/token, không tin LLM.

#### `POST /hr/leave-requests` — tạo đơn (mcp-service gọi, qua tool `create_leave_request`)
```
Header: X-Internal-Token
Body:   { "user_id": "uuid", "leave_type": "annual|sick|personal",
          "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "reason": "..." }
hr-service: days_count = end-start+1 (ngày lịch, server tính);
            approver_user_id = employees.manager_user_id OR HR_DEFAULT_APPROVER;
            INSERT status='pending' → commit → publish hr.leave_request.created
Response 201: { "id", "status": "pending", "approver_user_id", "days_count" }
```

#### `GET /hr/leave-requests/pending-approval` — đơn chờ sếp duyệt (PULL)
```
Header: X-Internal-Token  (caller truyền approver_user_id = current_user của sếp)
hr-service: SELECT WHERE approver_user_id = :current AND status='pending'
Response 200: { "items": [ { id, requester_user_id, leave_type, start_date, end_date, days_count, reason } ] }
```

#### `POST /hr/leave-requests/{id}/approve` | `.../reject` — quyết định (signal)
```
Header: X-Internal-Token  (caller truyền approver_user_id của người duyệt)
Guard:  đơn.approver_user_id == approver_user_id truyền vào AND status=='pending' (KHÔNG dùng app-role)
approve: TRANSACTION { status='approved', approved_at=now; trừ leave_balance theo leave_type
                       (annual→annual_used, sick→sick_used, personal→không trừ); thiếu phép → 409, giữ pending }
         → commit → publish hr.leave_request.approved
reject:  { status='rejected', rejected_at=now, rejected_reason } → commit → publish hr.leave_request.rejected
Response 200: { "id", "status" }
```

> **Tool MCP:** chỉ `create_leave_request` là MCP tool (mcp-service proxy). `approve/reject/pending-approval` **KHÔNG** phải MCP tool — gọi HTTP nội bộ (`X-Internal-Token`).
> **Hoãn (additive):** `cancel` đơn, ngày-làm-việc (holiday calendar), audit table riêng.

---

## Pydantic Schemas (tham khảo thêm)

```python
# query-service/interfaces/api/schemas/query.py
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

# document-service/interfaces/api/schemas/document.py
class UploadResponse(BaseModel):
    document_id: str
    status: str             # always "queued" for Admin upload
    message: str

# user-service/interfaces/api/schemas/auth.py
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

# user-service/interfaces/api/schemas/user.py  (Quản lý user — Admin)
class UserItem(BaseModel):
    id: str
    email: str
    role: str               # "user" | "admin"
    account_type: str       # "internal" | "external"
    department: str
    is_active: bool

class UserList(BaseModel):
    items: List[UserItem]
    total: int
```
