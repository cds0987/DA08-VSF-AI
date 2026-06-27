# API Specification — RAG Chatbot

Danh sách đầy đủ endpoint của các services. Frontend Dev dùng file này để biết chính xác path, method, header, request/response format.

> **Base URL local:**
> - User Service: `http://localhost:8000`
> - Document Service: `http://localhost:8002` _(Admin only)_
> - Query Service: `http://localhost:8001`
> - MCP Service: `http://localhost:8003` _(internal MCP tool gateway)_
> - HR Service: `http://localhost:8004` _(internal only)_
> - AI Router: `http://localhost:8010` _(internal/127.0.0.1 only — gateway LLM tương thích OpenAI)_
> - RAG Worker: không expose HTTP cho client — chỉ NATS :4222 + health/status nội bộ _(internal)_
>
> **Qua API Gateway (prod, nginx):** `/api/user`, `/api/documents`, `/api/query`, `/api/hr`, `/api/mcp` → service tương ứng. `ai-router` KHÔNG ra Internet.
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

### `POST /documents/bulk-delete`

> Xóa nhiều tài liệu trong 1 request (trang admin chọn nhiều rồi xóa). Mỗi id xử lý độc lập — id lỗi không chặn cả lô.

```
Request Body: { "document_ids": ["uuid", ...] }   # 1..200 id
Response 202:  { "deleted": ["uuid"], "not_found": ["uuid"], "failed": [{ "id": "uuid", "error": "string" }] }
Response 403:  { "detail": "Admin only" }
```

### `GET /documents/{document_id}/file`

> Trả **presigned GCS URL** (TTL ngắn) để Frontend Document Viewer mở file gốc + highlight citation. Kiểm tra ACL theo user.

```
Response 200:  { "url": "https://<bucket>.s3.../...&X-Amz-Expires=300", "file_type": "pdf", "expires_in": 300 }
Response 403:  { "detail": "Không có quyền xem tài liệu này" }
Response 404:  { "detail": "Document not found" }
```

### `GET /documents/{document_id}/file/raw`

> Proxy-stream nội dung file (không trả presigned URL) — kiểm tra ACL mỗi request. Dùng khi cần che URL GCS khỏi client.

```
Response 200:  <binary stream> (Content-Type theo file_type)
Response 403:  { "detail": "Không có quyền xem tài liệu này" }
Response 404:  { "detail": "Document not found" }
```

### `GET /documents/supported-formats`

```
Response 200:  { "extensions": ["pdf","docx","txt","xlsx","csv","pptx","md"], "max_file_bytes": 52428800 }
```

### `GET /documents/audit-logs`  (Admin only)

```
Query params: ?limit=50&offset=0
Response 200:  { "items": [ { "id", "actor_id", "actor_role", "action", "resource_id", "detail", "created_at" } ], "total": 0 }
Response 403:  { "detail": "Admin only" }
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
  Body: { "question": "string (max 500 ký tự)", "user_id": "uuid", "conversation_id": "uuid (optional)", "conversation_title": "string (optional)" }

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

### `DELETE /notifications/{notification_id}`

> Người dùng bấm X để xóa hẳn 1 thông báo (không chỉ đánh dấu đã đọc). Badge unread giảm real-time nếu thông báo đang chưa đọc.

```
Response 200:  { "message": "Notification deleted" }
Response 404:  { "detail": "Notification not found" }
```

### `GET /conversations`

Trả danh sách các cuộc trò chuyện của user, mới nhất trước.

```
Query params: ?limit=20&offset=0&include_legacy_messages=true (`limit` từ 1 đến 500)
Response 200:
  {
    "conversations": [
      {
        "id": "uuid",
        "title": "string",
        "created_at": "iso8601",
        "updated_at": "iso8601"
      }
    ],
    "messages": []
  }
```

`messages` là compatibility field tạm thời cho frontend phiên bản cũ và chứa tối đa 500 tin gần nhất của conversation mới nhất. Frontend mới gửi `include_legacy_messages=false` và dùng endpoint detail bên dưới để tránh truy vấn thừa.

### `GET /conversations/{conversation_id}`

```
Query params: ?limit=500&offset=0 (`limit` tối đa 500; `offset` tính từ tin mới nhất). Response luôn sắp xếp tăng dần theo thời gian và mặc định trả 500 tin gần nhất.
Response 200:
  {
    "id": "uuid",
    "title": "string",
    "created_at": "iso8601",
    "updated_at": "iso8601",
    "messages": [
      {
        "id": "uuid",
        "role": "user" | "assistant",
        "content": "string",
        "session_id": "string | null",
        "sources": [],
        "feedback": 1 | -1 | null,
        "metadata": { "agent": { "thoughts": [], "plan": [], "trace": [], "models": [] }, "actions": {} },
        "created_at": "iso8601"
      }
    ]
  }
```

> `metadata.agent` lưu "suy nghĩ của agent" (thoughts/plan/trace/models) để tái hiện sau reload (không còn lệ thuộc localStorage). `metadata.actions[idempotency_key]` lưu trạng thái action đơn nghỉ (status/request_id/leave_status) để render lại form trong tin nhắn.

### `POST /conversations/{conversation_id}/messages/{message_id}/actions`

> Ghi/cập nhật trạng thái action (vd nút "Gửi đơn nghỉ" trong câu trả lời) — idempotent.

```
Request Body: { "idempotency_key": "string", "status": "submitted", "request_id": "uuid", "leave_status": "pending" }
Response 200:  { "message": "Action state saved" }
```

### `PATCH /conversations/{conversation_id}`

```
Request Body: { "title": "string (1-120 ký tự)" }
Response 200: { "message": "Conversation renamed" }
```

### `DELETE /conversations/{conversation_id}`

```
Response 200: { "message": "Conversation deleted" }
```

### `DELETE /conversations`

```
Response 200: { "message": "Conversation history cleared" }
```

`conversation_id` nhận diện một chat gồm nhiều lượt hỏi. `session_id` nhận diện riêng
một câu trả lời assistant để feedback và tracing.

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

### Leave requests — proxy sang HR Service

> Frontend gọi query-service (JWT) → query-service trích `user_id`/`approver_user_id` **từ token** (KHÔNG tin client) → gọi hr-service bằng `X-Internal-Token`. hr-service không xác thực user nên KHÔNG được expose thẳng ra browser. Lỗi nghiệp vụ của hr (403/404/409/422) được map nguyên trạng.

```
POST   /leave-requests                       Body { leave_type, start_date, end_date, reason, idempotency_key?, confirm_overlap? } → 201 { id, status:"pending", approver_user_id, days_count }
POST   /leave-requests/{request_id}/cancel   → 200 { id, status:"cancelled" }
POST   /leave-requests/{request_id}/approve  → 200 { id, status:"approved" }      (approver từ JWT)
POST   /leave-requests/{request_id}/reject   Body { reason } → 200 { id, status:"rejected" }
GET    /leave-requests/pending-approval      → { items:[...], count }   (đơn chờ chính mình duyệt)
GET    /leave-requests/mine                  → { items:[...], count }   (mọi đơn của chính mình, mọi trạng thái)
GET    /leave-requests/{request_id}          → đơn theo id (chủ đơn / người duyệt)
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
> ✅ **Trạng thái code:** ĐÃ wire — `nats_publisher.py` connect NATS JetStream thật (stream `HR_EVENTS`); query-service có durable consumer cho từng subject. Mỗi event mang `event_id` để consumer idempotent.

| Subject | Type | Payload | Mô tả |
|---------|------|---------|-------|
| `hr.employee_profile.updated` | Publish (HR) / Subscribe (Query) | `{ event_id, event_version, occurred_at, user_id, account_type, department, employment_status }` | Publish khi employee profile/department/employment status đổi (gồm sync từ `user.*`). Query upsert projection `user_access_profile`. |
| `hr.leave_request.created` | Publish (HR) / Subscribe (Query) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, leave_type, start_date, end_date, days_count, status }` | Publish sau commit đơn `pending`. Query đẩy SSE cho **sếp** (`approver_user_id`): "có đơn cần duyệt". |
| `hr.leave_request.updated` | Publish (HR) / Subscribe (Query) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, mode, status }` | Publish khi đơn được sửa (`mode`: updated/replaced). |
| `hr.leave_request.cancelled` | Publish (HR) / Subscribe (Query) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, status }` | Publish khi chủ đơn hủy đơn pending. |
| `hr.leave_request.approved` | Publish (HR) / Subscribe (Query) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, status }` | Publish sau approve (đã trừ balance). Query đẩy SSE cho **nhân viên**: "đơn được duyệt". |
| `hr.leave_request.rejected` | Publish (HR) / Subscribe (Query) | `{ event_id, occurred_at, request_id, requester_user_id, approver_user_id, status, rejected_reason }` | Publish sau reject. Query đẩy SSE cho **nhân viên**: "đơn bị từ chối". |
| `hr.department.renamed` | Publish (HR) / Subscribe (Query) | `{ event_id, occurred_at, old_name, new_name }` | Publish khi đổi tên phòng ban (cascade employees). Query rename trong `document_access` + flush ACL cache. |

> Ngoài ra query-service subscribe `user.deleted` (từ user-service): xóa lịch sử hội thoại + notifications + `user_access_profile` của user bị xóa.
>
> **Ranh giới (leave request):** hr-service **chỉ publish** event sau commit; **không** đẩy thẳng tới user. query-service có subscriber (giống `notify_subscriber` cho `doc_new`) route SSE theo `approver_user_id`/`requester_user_id`.

> HR Service deploy như backend service thật nhưng internal only (không qua API Gateway, chỉ gọi nội bộ bằng `X-Internal-Token`; nhóm `/hr/admin/*` dùng JWT admin). Endpoint thật (theo `app/api/`): READ `POST /hr/query`, `POST /hr/profile`, `GET /hr/leave-types`, `GET /hr/departments`, `GET /health`; WRITE leave (xem dưới); admin `/hr/admin/*`. mcp-service tool `hr_query` proxy vào `POST /hr/query`.

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

### ✅ Leave request WRITE flow — ĐÃ implement

> Tất cả endpoint dưới đây đã có trong hr-service (`app/api/leave_write_routes.py`). Header `X-Internal-Token`; `user_id`/`approver_user_id` do query-service inject **từ JWT**, không tin LLM/client. hr-service chỉ **ghi DB + publish NATS event** (không đẩy thẳng tới user); báo user do query-service consume event → SSE.

```
POST   /hr/leave-requests                       Body { user_id, leave_type, start_date, end_date, reason, idempotency_key?, confirm_overlap? }
                                                → 201 { id, status:"pending", approver_user_id, days_count }
                                                  (days_count server tính; approver = employees.manager_user_id || HR_DEFAULT_APPROVER;
                                                   idempotency_key chống tạo trùng; overlap/duplicate → 409 trừ khi confirm_overlap)
PATCH  /hr/leave-requests/{request_id}           sửa đơn (mode update|replace) → publish hr.leave_request.updated
POST   /hr/leave-requests/{request_id}/cancel    chủ đơn hủy đơn pending → publish hr.leave_request.cancelled
POST   /hr/leave-requests/{request_id}/approve   Body { approver_user_id } → trừ balance theo loại; thiếu phép → 409 (giữ pending) → publish ...approved
POST   /hr/leave-requests/{request_id}/reject    Body { approver_user_id, reason } → publish hr.leave_request.rejected
GET    /hr/leave-requests/pending-approval?approver_user_id=X   → { items, count }
GET    /hr/leave-requests/mine?user_id=X         mọi đơn của chính chủ (mọi trạng thái) → { items, count }
GET    /hr/leave-requests/{request_id}?user_id=X → đơn theo id
```
> Guard approve/reject: `đơn.approver_user_id == approver_user_id truyền vào AND status=='pending'` (không dùng app-role). Route tĩnh (`/pending-approval`, `/mine`) khai báo TRƯỚC `/{request_id}` để không bị nuốt.

### HR — read mở rộng & admin

```
POST   /hr/profile            Body { user_id } → gộp 7 mục HR + thông tin nhân viên cơ bản trong 1 call
GET    /hr/leave-types        taxonomy loại nghỉ (4 rổ theo luật LĐ VN) — public
GET    /hr/departments        danh sách phòng ban — public
POST   /hr/departments/{old_name}/rename   (X-Internal-Token) đổi tên + cascade employees → publish hr.department.renamed
GET    /hr/admin/employees                 (JWT admin) list nhân viên (paginated)
GET    /hr/admin/employees/{employee_id}   (JWT admin) chi tiết + HR data liên quan
PATCH  /hr/admin/employees/{employee_id}   (JWT admin) cập nhật hồ sơ
GET    /hr/admin/leave-requests            (JWT admin) mọi đơn (filter + paginated)
GET    /hr/admin/departments               (JWT admin) phòng ban distinct
```

> **Tool MCP leave:** `leave_write` (tạo/sửa/hủy), `leave_approvals` (pending + approve/reject), `leave_types`, `resolve_date` — đều proxy hr-service qua `X-Internal-Token`.

---

## AI Router — `/v1/*`, `/admin/*` (internal, :8010)

> Gateway tương thích OpenAI, **stateless**, đa pool key (OpenAI + OpenRouter). Service đổi `base_url=http://ai-router:8010/v1`, dùng OpenAI SDK như cũ; field `model` = **ALIAS capability** (vd `answer`, `worker`, `think`, `plan`, `embed`, `summary`) — router map sang model thật + key tối ưu chi phí/tải. KHÔNG ra Internet (bind 127.0.0.1).

```
POST /v1/chat/completions   chat + tool + stream (alias ở field model)
POST /v1/embeddings         embed (model pin theo contract)
POST /v1/rerank             Cohere rerank passthrough (model = rerank_api alias)
POST /v1/route              resolver: { capability, est_tokens, has_tools } → triple (model, endpoint, api_key) cho client động
GET  /health                trạng thái
GET  /metrics               Prometheus
GET  /admin/quota           giám sát quota/RPM/cost mỗi key (live)
POST /admin/reload          hot-reload routing.yaml + model_catalog.json
POST /admin/key/{key_id}/drain    rút 1 key khỏi vòng xoay (HITL)
POST /admin/key/{key_id}/resume   đưa key trở lại
```

> Cấu hình: `routing.yaml` (selector `sticky_rotation_soft`, capability→tier→model, quality floor — hot-reload) + `config/model_catalog.json` (build từ OpenRouter `/models` mỗi deploy). An toàn: không service nào `depends_on` ai-router → router chết không kéo sập app (query-service set `OPENAI_BASE_URL` rỗng = fallback gọi thẳng OpenAI).

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
