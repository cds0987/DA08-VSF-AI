# API Specification — RAG Chatbot

Danh sách đầy đủ endpoint của 3 services. Frontend Dev dùng file này để biết chính xác path, method, header, request/response format.

> **Base URL local:**
> - User Service: `http://localhost:8000`
> - Chat Service: `http://localhost:8001`
> - RAG Service: `http://localhost:8002` _(internal — Frontend không gọi trực tiếp)_
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

## Chat Service — `/query`, `/documents`, `/conversations`, `/feedback`

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

### `POST /documents/upload`

Admin → `queued`. End User → `pending`.

```
Request:
  Content-Type: multipart/form-data
  Fields:
    file: <binary> (max 50MB, pdf/docx/txt/xlsx/csv/pptx/md)
    classification: "public" | "internal" | "secret" | "top_secret"
    allowed_departments?: ["HR", "Finance"]   # bắt buộc nếu secret
    allowed_user_ids?: ["uuid"]               # bắt buộc nếu top_secret

Response 202:  { "document_id": "uuid", "status": "queued" | "pending", "message": "string" }
Response 400:  { "detail": "File type not supported" | "File exceeds 50MB" }
```

### `GET /documents`

Admin thấy tất cả, End User chỉ thấy tài liệu mình upload.

```
Query params: ?status=pending|queued|processing|indexed|failed|rejected&limit=50&offset=0

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
Response 200:  { ...same as item above..., "error_message": null | "string", "rejection_reason": null | "string" }
Response 404:  { "detail": "Document not found" }
```

### `POST /documents/{document_id}/approve`  _(Admin only)_

```
Response 200:  { "document_id": "uuid", "status": "queued" }
Response 403:  { "detail": "Admin only" }
```

### `POST /documents/{document_id}/reject`  _(Admin only)_

```
Request Body: { "reason": "string" }
Response 200:  { "document_id": "uuid", "status": "rejected" }
```

### `DELETE /documents/{document_id}`  _(Admin only)_

```
Response 200:  { "message": "Document deleted" }
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
Response 200:  { "status": "ok", "database": "ok", "rag_service": "ok", "reranker": "ok" }
Response 503:  { "status": "degraded", "degraded_reasons": ["rag_service unreachable"] }
```

---

## RAG Service — Internal Only

> Không expose ra ngoài. Chỉ Chat Service gọi qua Docker internal network.

### `POST /search`

Consumer endpoint chính. Chat Service gọi sau khi đã query `allowed_doc_ids` từ PostgreSQL.

```
Request:
  Content-Type: application/json
  X-Request-ID: <caller-generated-uuid>   (optional — dùng để trace xuyên service)
  Body:
    {
      "query": "string (bắt buộc, max 2000 ký tự)",
      "top_k": 20,                          (1–50, default 20)
      "document_ids": ["doc_1", "doc_5"]    (optional — None = chỉ search public docs)
    }

Response 200:
  {
    "request_id": "uuid",
    "results": [
      {
        "section_id": "doc_123_section_0007",
        "document_id": "doc_123",
        "document_name": "travel_policy.pdf",
        "caption": "Quy định về mức hoàn tiền tối đa cho vé máy bay công tác",
        "section_content": "## Hoàn tiền vé máy bay\n...\n",
        "heading_path": ["Chính sách công tác", "Hoàn tiền vé máy bay"],
        "score": 0.91,
        "source_s3_uri": "s3://bucket/raw/hr/travel_policy.pdf",
        "markdown_s3_uri": "s3://bucket/rag-derived/markdown/doc_123.md"
      }
    ]
  }

Response 422:  { "detail": "query is required" | "top_k must be between 1 and 50" }
```

> **ACL flow:** Chat Service query PostgreSQL `rag_svc.documents` → lấy `allowed_doc_ids` → truyền vào `document_ids`. Kết quả cache Redis TTL ~60s. `document_ids=None` mặc định chỉ search public docs (fail-secure).
>
> **Tracing:** `X-Request-ID` từ caller được echo lại trong response body (`request_id`) và header (`X-Request-ID`) để correlate log xuyên service.
>
> **Score threshold:** RAG filter kết quả dưới 0.5 trước khi trả. Số results thực tế có thể ít hơn `top_k`.
>
> **Reranking:** Chat Service tự rerank bằng `RerankService` (BGE-Reranker-v2-m3) sau khi nhận results.

### `POST /ingest`

Trigger ingest một document cụ thể. Gọi sau khi Admin approve.

```
Request: { "document_id": "uuid", "s3_key": "string", "file_type": "string",
           "classification": "string", "allowed_departments": [], "allowed_user_ids": [] }
Response 202: { "message": "Ingestion started", "document_id": "uuid" }
Response 409: { "detail": "Document is already being processed" }
```

### `POST /scan`

Operational endpoint — trigger scan toàn bộ S3 bucket và enqueue ingest jobs cho các doc chưa được index.

```
Request: { "bucket": "optional-string", "prefix": "optional-string" }
Response 200: { "status": "scan started", "queued": 2 }
Response 409: { "detail": "scan already in progress" }
```

### `GET /status/{doc_id}`

```
Response 200:
  {
    "doc_id": "doc_123",
    "status": "pending" | "indexing" | "indexed" | "failed",
    "file_path": "s3://...",
    "section_count": 7,
    "parser_version": "pipeline.parsers.v1",
    "caption_model": "heuristic",
    "embedding_model": "bge-m3",
    "uploaded_at": "2026-05-31T10:15:00+00:00",
    "processed_at": "2026-05-31T10:15:08+00:00"   (null nếu chưa xong)
  }
Response 404: { "detail": "Document not found" }
```

### `GET /health`

```
Response 200:  { "status": "ok", "vector_store": "ok", "metadata_store": "ok",
                 "ai_provider": "ok", "scanner": "enabled", "dispatcher": {...}, "degraded_reasons": [] }
Response 503:  { "status": "degraded", ..., "degraded_reasons": ["qdrant unreachable"] }
```

---

## Pydantic Schemas (tham khảo thêm)

```python
# chat-service/interfaces/api/schemas/query.py
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

# chat-service/interfaces/api/schemas/document.py
class UploadResponse(BaseModel):
    document_id: str
    status: str             # "queued" | "pending"
    message: str

# user-service/interfaces/api/schemas/auth.py
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```
