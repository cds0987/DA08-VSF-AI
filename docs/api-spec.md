# API Specification — RAG Chatbot

Danh sách đầy đủ endpoint của các services. Frontend Dev dùng file này để biết chính xác path, method, header, request/response format.

> **Base URL local:**
> - User Service: `http://localhost:8000`
> - Document Service: `http://localhost:8002` _(Admin only)_
> - Query Service: `http://localhost:8001`
> - RAG Worker: không expose HTTP — giao tiếp qua NATS :4222 _(internal)_
>
> **Auth header** (trừ `/auth/login`): `Authorization: Bearer <jwt_token>`

---

## User Service — `/auth`

### `POST /auth/login`

```
Request:
  Content-Type: application/json
  Body: { "email": "user@company.com", "password": "string" }

Response 200:  { "access_token": "eyJ...", "token_type": "bearer" }
Response 401:  { "detail": "Invalid credentials" }
Response 423:  { "detail": "Account locked. Try again after 15 minutes." }
```

### `GET /auth/me`

```
Request:  Authorization: Bearer <token>

Response 200:  { "id": "uuid", "email": "string", "role": "user" | "admin", "department": "string" }
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

### `GET /health`

```
Response 200:  { "status": "ok", "database": "ok", "nats": "ok" }
Response 503:  { "status": "degraded", "degraded_reasons": ["nats unreachable"] }
```

---

## Query Service — `/query`, `/conversations`, `/feedback`

### `POST /query`

Streaming response qua Server-Sent Events.

```
Request:
  Authorization: Bearer <token>
  Body: { "question": "string (max 500 ký tự)", "user_id": "uuid" }

Response 200 (SSE):
  data: {"token": "Theo "}
  data: {"token": "chính sách..."}
  data: {"done": true, "sources": [{"document_name": "string", "caption": "string", "heading_path": ["string"], "score": 0.85, "source_s3_uri": "s3://..."}], "session_id": "uuid"}

Response 429:  { "detail": "Rate limit exceeded. Max 20 requests/minute." }
```

### `GET /conversations`

```
Query params: ?limit=20&offset=0
Response 200:
  { "messages": [{ "role": "user" | "assistant", "content": "string", "created_at": "iso8601" }] }
```

### `DELETE /conversations`

```
Response 200:  { "message": "Conversation history cleared" }
```

### `POST /feedback`

```
Request Body: { "session_id": "uuid", "score": 1 | -1 }   # 1 = thumbs up, -1 = thumbs down
Response 200:  { "message": "Feedback recorded" }
```

### `GET /health`

```
Response 200:  { "status": "ok", "database": "ok", "rag_worker": "ok", "reranker": "ok" }
Response 503:  { "status": "degraded", "degraded_reasons": ["rag_worker unreachable"] }
```

---

## RAG Worker — NATS Internal Only

> Không expose HTTP. Chỉ giao tiếp qua NATS :4222.

| Subject | Type | Payload | Mô tả |
|---------|------|---------|-------|
| `doc.ingest` | Subscribe | `{ doc_id, s3_key, file_type, classification, allowed_departments, allowed_user_ids }` | Document Service publish khi Admin upload. RAG Worker nhận → chạy pipeline ingestion. |
| `doc.status` | Publish | `{ doc_id, status: "indexed"\|"failed", chunk_count?, error? }` | RAG Worker publish sau khi ingestion xong. Document Service subscribe để cập nhật PostgreSQL. |
| `rag.search` | Request-Reply | Request: `{ query_text, document_ids, top_k }` → Reply: `{ results: [...] }` | Query Service gửi request, RAG Worker xử lý và reply. Timeout 10s. |

---

## Pydantic Schemas (tham khảo thêm)

```python
# query-service/interfaces/api/schemas/query.py
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
```
