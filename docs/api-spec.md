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
  data: {"done": true, "sources": [{"document_name": "string", "page_number": 1, "score": 0.85}], "session_id": "uuid"}

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
Query params: ?status=pending|queued|processing|completed|failed|rejected&limit=50&offset=0

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

---

## RAG Service — Internal Only

> Không expose ra ngoài. Chỉ Chat Service gọi qua Docker internal network.

### `POST /ingest`

```
Request: { "document_id": "uuid", "s3_key": "string", "file_type": "string",
           "classification": "string", "allowed_departments": [], "allowed_user_ids": [] }
Response 202: { "message": "Ingestion started", "document_id": "uuid" }
```

### `POST /search`

```
Request: { "query": "string", "top_k": 20, "user_id": "uuid", "user_role": "string", "user_department": "string" }
Response 200:
  { "results": [{ "chunk_id": "uuid", "document_id": "uuid", "document_name": "string",
                  "page_number": 1, "content": "string", "score": 0.85, "rerank_score": 0.92 }] }
```

> top_k=20 là số candidates trước rerank. BGE-Reranker-v2-m3 rerank → trả về Top-3 parent chunks cho LLM prompt.

---

## Pydantic Schemas (tham khảo thêm)

```python
# chat-service/interfaces/api/schemas/query.py
class Source(BaseModel):
    document_name: str
    page_number: int
    score: float

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
