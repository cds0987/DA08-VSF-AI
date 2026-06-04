# Team Ownership — RAG Chatbot

## Tổng quan phân công

| Role | Người phụ trách | Phụ trách chính | Service / Folder | Bắt đầu sau |
|------|----------------|----------------|-----------------|-------------|
| **SA** | Lê Hữu Hưng | Domain design, contracts, API schemas, code review | `app/domain/` (cả 5 services) | Ngay — làm đầu tiên |
| **Frontend Dev** | Đặng Hồ Hải | 2 micro-frontend: Chat (End User) + Admin console, dùng chung base layer (auth, design system) | `src/frontend/chat/`, `src/frontend/admin/`, `src/frontend/base/` (Nuxt 4) | Sau khi SA freeze schemas |
| **Backend Dev** | Vũ Quang Dũng | User Service + Document Service: auth, JWT, document management + **chủ NATS subject contract & JetStream config** | `src/user-service/`, `src/document-service/`, `infra/nats/` | Sau khi SA freeze domain |
| **RAG Engineer** | Trần Thanh Nguyên | RAG Worker (ingestion + retrieval, NATS) + **MCP Tool Service** (tool rag_search/hr_query + rerank) | `src/rag-worker/app/`, `src/mcp-service/app/` | Sau khi SA freeze domain |
| **AI/Agent Engineer** | Phạm Quốc Dũng | Query Service: LLM orchestration, SSE streaming, notify, memory, MCP client | `src/query-service/app/` | Sau khi SA freeze domain |
| **DevOps** | Trần Hữu Gia Huy | Docker, AWS, CI/CD, Nginx, **deploy/vận hành NATS container**, monitoring | `infra/`, `docker-compose.yml` | Ngay — song song với SA |

---

## Chi tiết từng role

---

### SA (Solution Architect) — Lê Hữu Hưng

**Làm đầu tiên (Ngày 1–2). Team chờ SA freeze xong mới code.**

**Files SA tạo — user-service:**
```
src/user-service/app/domain/
├── entities/
│   └── user.py                  ← User dataclass, UserRole enum
└── repositories/
    └── user_repository.py       ← UserRepository ABC (get_by_email, get_by_id, create)
```

**Files SA tạo — query-service:**
```
src/query-service/app/domain/
├── entities/
│   └── conversation.py          ← Message, ConversationContext, Conversation dataclass
└── repositories/
    ├── conversation_repository.py  ← ConversationRepository ABC (get_context, save_message, ...)
    └── document_access_repository.py ← DocumentAccessRepository ABC (get_allowed_doc_ids)
```
> `RerankService` ABC **không còn ở query-service** — chuyển sang mcp-service (reranker nằm trong tool `rag_search`).

**Files SA tạo — mcp-service:**
```
src/mcp-service/app/domain/
├── entities/
│   └── tool_io.py              ← Dataclass I/O cho tool: RagSearchInput/Result, HrQueryInput/Result
└── repositories/
    └── rerank_service.py       ← RerankService ABC (rerank Top-5 → Top-3) — implement bằng BGE-Reranker
```

**Files SA tạo — rag-worker:**
```
src/rag-worker/app/domain/
├── entities/
│   └── document.py              ← Document, Section dataclass, DocumentStatus enum (dùng cho xử lý ingestion in-memory)
└── repositories/
    ├── vector_repository.py     ← SearchResult dataclass, VectorRepository ABC (document_ids filter)
    └── embedding_service.py     ← EmbeddingService ABC (embed, embed_batch) — OpenAI interface
```
> `DocumentRepository` (ghi bảng documents) **không còn ở rag-worker** — chuyển sang document-service (xem dưới). RAG Worker chỉ publish `doc.status`.

**Files SA tạo — document-service:**
```
src/document-service/app/domain/
├── entities/
│   └── document.py              ← Document entity + DocumentStatus enum (riêng của document-service — chủ vòng đời tài liệu)
└── repositories/
    └── document_repository.py   ← DocumentRepository ABC (create, get_by_id, list_all, update_status, delete)
```

**SA cũng define schemas (Pydantic) — nằm trong interfaces/api nhưng SA viết:**
```
src/query-service/app/interfaces/api/schemas/
├── query.py       ← QueryRequest, QueryResponse, Source
└── conversation.py ← ConversationHistory

src/user-service/app/interfaces/api/schemas/
├── auth.py        ← LoginRequest, TokenResponse
└── user.py        ← UserItem, UserList (quản lý user — Admin)

src/document-service/app/interfaces/api/schemas/
└── document.py    ← UploadResponse, DocumentItem, DocumentList
```

**SA KHÔNG làm:** infrastructure, application use cases, routers, Dockerfile.

**Deliverable:** Commit lên `develop`, tag team → mọi người checkout và bắt đầu.

---

### Frontend Dev — Đặng Hồ Hải

**Bắt đầu Ngày 3. Mock API bằng schemas SA đã viết — không chờ backend xong.**

**Stack: Nuxt 4 + Vue 3 + TypeScript + TailwindCSS.** Tách **micro-frontend** theo bounded context: 2 app deploy riêng + 1 **Nuxt layer** dùng chung.

**3 folder Frontend Dev tạo:**

#### `src/frontend/base/` — Nuxt Layer dùng chung (KHÔNG deploy riêng)
```
src/frontend/base/
├── nuxt.config.ts                  ← Khai báo là layer (base config: runtimeConfig NUXT_PUBLIC_*, tailwind)
├── app/
│   ├── composables/
│   │   ├── useApi.ts               ← `$fetch` base client, attach Bearer token
│   │   └── useAuth.ts              ← Auth qua User Service /auth (login/refresh/me), JWT cookie, auto-refresh
│   ├── middleware/
│   │   └── auth.ts                 ← Route guard: chưa login → /login; check role
│   ├── components/                 ← Design system dùng chung (Button, Input, Card, AppLayout…)
│   └── pages/
│       └── login.vue               ← Form đăng nhập (email/password + Microsoft SSO) — cả 2 app dùng
```
> **Auth (User Service `/auth/*`) là phần dùng chung** → đặt ở base layer. 2 app `extends: '../base'`.

#### `src/frontend/chat/` — App End User (container `nuxt-chat` :3000)
```
src/frontend/chat/
├── nuxt.config.ts                  ← extends '../base'; NUXT_PUBLIC_QUERY_SERVICE_URL
├── app/
│   ├── pages/
│   │   └── chat.vue                ← Chat chính, SSE consumer (End User)
│   ├── plugins/
│   │   └── notifications.client.ts ← Mở EventSource(`GET /notifications`) app-level sau đăng nhập
│   ├── components/
│   │   ├── ChatMessage.vue         ← Render 1 tin nhắn (user/bot) + source citations
│   │   ├── SourceCard.vue          ← Nguồn tài liệu; click → mở DocumentViewer
│   │   ├── StreamingText.vue       ← Nhận SSE token (POST /query), render token từng cái
│   │   ├── NotificationToast.vue   ← Toast realtime khi nhận event notify
│   │   ├── NotificationCenter.vue  ← badge số chưa đọc + dropdown lịch sử + mark-as-read
│   │   ├── DocumentViewer.vue      ← PDF.js: nhảy đúng trang + highlight đoạn citation
│   │   └── ConversationList.vue    ← lịch sử hội thoại: list / search / rename / delete
│   └── composables/
│       ├── useChat.ts              ← POST /query, đọc SSE bằng fetch + ReadableStream (token/done)
│       ├── useNotifications.ts     ← Stream /notifications realtime + history
│       └── useConversations.ts     ← GET/DELETE /conversations, rename
```
→ Gọi **Query Service** (chat/SSE/notifications) + `GET /documents/{id}/file` (presigned, để xem citation).

#### `src/frontend/admin/` — App Admin (container `nuxt-admin` :3001)
```
src/frontend/admin/
├── nuxt.config.ts                  ← extends '../base'; NUXT_PUBLIC_DOCUMENT/USER/QUERY_SERVICE_URL
├── app/
│   ├── pages/
│   │   ├── documents.vue           ← Upload + danh sách tài liệu + ingestion status
│   │   ├── users.vue               ← Quản lý user: deactivate/reactivate
│   │   └── analytics.vue           ← Dashboard: charts volume / feedback rate / top questions
│   ├── components/
│   │   ├── FileUpload.vue          ← Drag-drop upload, chọn classification
│   │   └── AnalyticsCharts.vue     ← charts (Chart.js / ApexCharts)
│   └── composables/
│       ├── useDocuments.ts         ← GET/POST/DELETE /documents (Document Service)
│       ├── useUsers.ts             ← GET /users, deactivate/reactivate (User Service /users)
│       └── useAnalytics.ts         ← GET /admin/metrics (Query Service)
```
→ Gọi **Document Service** (tài liệu) + **User Service `/users`** (quản lý user) + **Query Service `/admin/metrics`**.

**Phân chia theo persona (chuẩn microservice):**
- **Chat app** (End User) ↔ Query Service · **Admin app** (Admin) ↔ Document + User `/users` + metrics.
- **Auth (User Service `/auth`)** dùng chung → base layer. Identity là shared infra, cả 2 app verify JWT bằng cùng secret.
- 2 stream SSE (`POST /query` request-scoped + `GET /notifications` app-level) **chỉ ở Chat app**.

**Không được đụng:** bất kỳ file Python nào, docker-compose.yml.

---

### Backend Dev — Vũ Quang Dũng

**Phụ trách User Service + Document Service. Bắt đầu Ngày 3.**

#### User Service

**Files Backend Dev tạo — user-service:**
```
src/user-service/app/
├── application/
│   └── use_cases/
│       ├── auth/
│       │   ├── login_use_case.py          ← Verify email+password, issue JWT (HS256)
│       │   └── verify_token_use_case.py   ← Decode + validate JWT, trả về User
│       └── users/                         ← Quản lý user (Admin)
│           ├── list_users_use_case.py     ← Liệt kê user (phân trang)
│           └── set_user_active_use_case.py← Deactivate / reactivate user
│
├── infrastructure/
│   └── db/
│       ├── models.py                      ← SQLAlchemy ORM model cho bảng users, refresh_tokens, audit_logs (auth events)
│       └── postgres_user_repository.py    ← Implement UserRepository (async SQLAlchemy)
│
└── interfaces/
    └── api/
        ├── main.py                        ← FastAPI app init, include router
        ├── dependencies.py                ← get_login_use_case(), get_current_user(), require_admin()
        └── routers/
            ├── auth.py                    ← POST /auth/login, GET /auth/me
            └── users.py                   ← GET /users, PATCH /users/{id}/deactivate, /reactivate (admin only)
```

**Key logic — user-service:**
- `login_use_case.py`: bcrypt verify password → tạo JWT payload `{sub, role, department, jti}` → sign HS256
- `postgres_user_repository.py`: implement `get_by_email`, `get_by_id`, `create`, `list_all`, `set_active` từ `UserRepository` ABC
- `dependencies.py`: `get_current_user()` — decode JWT bằng shared secret, trả về `User`; `require_admin()` — chặn non-admin khỏi `/users`
- `users.py`: backing trang `admin/users` của Frontend (deactivate/reactivate). Chỉ Admin truy cập.

#### Document Service

**Files Backend Dev tạo — document-service:**
```
src/document-service/app/
├── application/
│   └── use_cases/
│       └── documents/
│           ├── upload_document_use_case.py   ← Lưu S3 → tạo record status=queued → publish doc.ingest
│           ├── list_documents_use_case.py    ← Liệt kê (filter status, phân trang)
│           ├── get_document_use_case.py       ← Chi tiết 1 document
│           ├── get_document_file_use_case.py  ← Trả presigned S3 URL (cho FE Document Viewer) — check ACL
│           └── delete_document_use_case.py    ← Xóa S3 + record + trigger xóa vectors Qdrant
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                          ← SQLAlchemy model bảng documents + audit_logs (document events) — chủ sở hữu doc_db
│   │   └── postgres_document_repository.py    ← Implement DocumentRepository
│   ├── storage/
│   │   └── s3_client.py                       ← Upload / xóa file gốc trên S3
│   └── messaging/
│       ├── nats_publisher.py                  ← Publish doc.ingest (RAG Worker) + doc.access (Query Service ACL)
│       │                                         + notify.doc_new (khi indexed → Query Service đẩy thông báo)
│       └── nats_subscriber.py                 ← Subscribe doc.status → update status indexed/failed + chunk_count;
│                                                 nếu indexed → publish notify.doc_new { doc_id, document_name, classification, allowed_departments, allowed_user_ids }
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                    ← require_admin(), get upload/list/delete use cases
        └── routers/
            └── documents.py                   ← POST /documents/upload, GET /documents, GET /documents/{id}, GET /documents/{id}/file (presigned), DELETE /documents/{id} (admin only)
```

**Key logic — document-service:**
- `upload_document_use_case.py`: validate file (≤50MB, đúng loại) → upload S3 → `doc_repo.create(status=queued)` → publish `doc.ingest` (RAG Worker xử lý) **và** `doc.access` (Query Service cập nhật phân quyền). Trả `202 { document_id, status:"queued" }`.
- `nats_subscriber.py`: lắng nghe `doc.status` từ RAG Worker → `doc_repo.update_status(indexed/failed, chunk_count)`. **Đây là nơi DUY NHẤT cập nhật trạng thái ingestion** — RAG Worker chỉ publish event, không ghi bảng documents. Khi `indexed` → publish thêm `notify.doc_new` để Query Service đẩy thông báo "có tài liệu mới".
- `delete_document_use_case.py`: xóa record + file S3, publish `doc.access { deleted:true }` (Query Service gỡ khỏi projection) + trigger xóa vectors Qdrant.
- **Event-driven ACL (database-per-service)**: mọi thay đổi quyền (upload / đổi classification / xóa) → publish `doc.access` lên NATS JetStream. Query Service tự giữ bản sao — **không ai đọc thẳng `doc_db` của service khác**.
- **Document Service là chủ duy nhất bảng `documents`** (create + update status). Khớp [api-spec.md](api-spec.md) — `doc.status`: "Document Service subscribe để cập nhật PostgreSQL".

#### NATS Subject Contract & Config (Backend Dev làm chủ)

> Vì Document Service là "nhạc trưởng" của hầu hết subject, Backend Dev **làm chủ thiết kế messaging** —
> giống cách SA làm chủ domain contract. DevOps chỉ deploy container theo cấu hình này.

```
infra/nats/
├── subjects.md                  ← Đăng ký subject + payload (source of truth): doc.ingest, doc.status,
│                                   doc.access, notify.doc_new  (rag.search payload do RAG Eng định nghĩa)
└── jetstream.conf               ← Cấu hình stream/retention cho các subject persist (doc.*, notify.*)
```
- **Backend Dev** quyết: tên subject, payload, stream nào persist (JetStream). Đổi subject/payload → **báo Backend Dev** (tất cả service follow).
- `rag.search` (request-reply giữa mcp-service ↔ rag-worker): payload do **RAG Eng** định nghĩa, nhưng vẫn đăng ký trong `subjects.md` để mọi người thấy.
- DevOps gắn `jetstream.conf` vào container NATS trong `docker-compose.yml`.
- **Chốt sớm (đầu Ngày 3)** — RAG Eng + AI Eng cần subject contract trước khi code NATS client của mình.

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong query-service hoặc rag-worker.

---

### RAG Engineer — Trần Thanh Nguyên

**Phụ trách rag-worker + mcp-service. Bắt đầu Ngày 3. Workload nặng nhất Phase 1 (cả đường RAG: retrieval + rerank + tool).**

**Files RAG Engineer tạo:**
```
src/rag-worker/app/
├── application/
│   └── use_cases/
│       ├── ingestion/
│       │   └── ingest_document_use_case.py   ← NATS subscribe doc.ingest → parse → chunk → embed → upsert Qdrant
│       └── query/
│           └── retrieval.py                  ← Nhận query + document_ids → embed → hybrid search → Top-K=5 → SearchResult[]
│
├── infrastructure/
│   │   # RAG Worker KHÔNG dùng PostgreSQL — không sở hữu bảng documents (Document Service quản lý),
│   │   # ingestion/audit log đẩy qua Langfuse. Chỉ publish doc.status qua NATS.
│   ├── vector/
│   │   └── qdrant_vector_repository.py       ← Implement VectorRepository (hybrid_search với document_ids filter, upsert, delete)
│   └── external/
│       ├── openai_embedding_client.py        ← Implement EmbeddingService — OpenAI text-embedding-3-small (1536 dims)
│       ├── gemini_ocr_client.py              ← Gọi Gemini Vision API — OCR PDF scan tiếng Việt
│       └── langfuse_client.py               ← Ghi trace ingestion + retrieval vào Langfuse
│
└── main.py                                   ← NATS subscriber — không có HTTP server
```

**Key logic cần implement:**

*Ingestion pipeline (`ingest_document_use_case.py`):*
1. Subscribe NATS `doc.ingest` (JetStream) → nhận `doc_id`, `s3_key`, `file_type`
2. Tải file từ S3 → detect loại: PDF scan / PDF text / DOCX / TXT / XLSX / ...
3. OCR (nếu PDF scan): gọi `gemini_ocr_client.py` — Gemini Vision API
4. Parse text: PyMuPDF (PDF text layer), python-docx (DOCX), openpyxl (XLSX)
5. Parent-Child Chunking: LlamaIndex HierarchicalNodeParser (config TBD)
6. Embed child nodes: gọi `openai_embedding_client.embed_batch()` — 1536 dims
7. Upsert Qdrant: `vector_repo.upsert()` với payload gồm `chunk_id`, `parent_text`, `child_text`, `document_id`, `classification`
8. Publish NATS `doc.status` → Document Service cập nhật status → INDEXED

*Retrieval pipeline (`retrieval.py`):*
1. Embed query: gọi `embedding_svc.embed(query_text)` — text-embedding-3-small
2. Hybrid search: `vector_repo.hybrid_search(vector, query_text, top_k=5, document_ids=document_ids)`
   - `document_ids` được Query Service truyền vào — RAG Worker không biết ACL logic
   - `None` → chỉ search public docs (fail-secure)
3. Score threshold filter: loại candidates dưới ngưỡng 0.5
4. Trả về `List[SearchResult]` qua NATS reply

*Failure Handling:*
- **Langfuse**: Fail silently — tất cả trace call bọc trong try/except, lỗi chỉ log console
- **OpenAI Embedding**: Nếu unreachable → ingestion fail, publish `doc.status` với status `failed`, Admin retry thủ công
- **Gemini Vision API**: Tương tự — fail ingestion, không ảnh hưởng query flow

#### MCP Tool Service (RAG Engineer cũng phụ trách)

> Service riêng expose tool qua giao thức **MCP** (transport Streamable HTTP/SSE, port 8003). Query Service
> agent — và agent tương lai (Teams bot…) — là MCP client dùng chung tool. Self-contained: mỗi tool tự lo backend.
> RAG Engineer ôm cả đường RAG: rag-worker (retrieval) + mcp-service (tool rag_search + rerank).

**Files RAG Engineer tạo — mcp-service:**
```
src/mcp-service/app/
├── interfaces/
│   └── mcp_server.py                         ← Khai báo + expose 2 tool qua MCP: rag_search, hr_query
├── application/
│   └── tools/
│       ├── rag_search.py                     ← (query rewrite) → NATS rag.search (Top-5) → rerank → Top-3 SearchResult
│       └── hr_query.py                        ← query mcp_db.hr_mock.* filter user_id → dữ liệu HR cá nhân
├── infrastructure/
│   ├── nats_rag_client.py                    ← NATS request-reply rag.search tới rag-worker (timeout 10s)
│   ├── bge_reranker_client.py                ← Implement RerankService — BGE-Reranker-v2-m3 (Top-5 → Top-3)
│   ├── langfuse_client.py                    ← Trace tool rag_search/hr_query (fail-silently)
│   └── db/
│       ├── models.py                          ← SQLAlchemy model hr_mock.* (mcp_db)
│       └── postgres_hr_repository.py          ← Query hr_mock filter user_id
└── main.py                                    ← Khởi MCP server (HTTP/SSE) :8003
```

**Key logic:**
- `rag_search(query, document_ids, top_k)`: nhận `document_ids` từ Query Service (đã lọc ACL) → NATS `rag.search` tới rag-worker → rerank Top-3. **Tool không tự quyết quyền** — chỉ dùng `document_ids` được truyền vào.
- `hr_query(user_id, intent)`: nhận `user_id` từ Query Service → query `mcp_db.hr_mock.*` với `WHERE user_id`. Không tin user_id do LLM bịa — Query Service inject từ JWT.
- **Bảo mật**: mọi tham số nhạy cảm (`document_ids`, `user_id`) do **MCP client (Query Service) inject**, không để LLM tự điền.

**Không được đụng:** `app/domain/` (SA owns), user-service, document-service, query-service.

---

### AI/Agent Engineer — Phạm Quốc Dũng

**Phụ trách query-service. Bắt đầu Ngày 3. Phase 1 nặng (FunctionCallingAgent + MCP client + SSE + notify).**

**Files AI/Agent Engineer tạo:**
```
src/query-service/app/
├── application/
│   └── use_cases/
│       └── query/
│           └── orchestration.py              ← FunctionCallingAgent (MCP client) → tool rag_search / hr_query ở mcp-service → stream OpenAI GPT-4o mini
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                         ← SQLAlchemy model cho conversations, messages, document_access (projection ACL), notifications
│   │   ├── postgres_conversation_repo.py     ← Implement ConversationRepository
│   │   └── postgres_document_access_repo.py  ← Implement DocumentAccessRepository — query bảng projection `document_access` trong query_db (KHÔNG đụng doc_db)
│   ├── messaging/
│   │   └── doc_access_subscriber.py          ← Subscribe NATS doc.access (JetStream) → upsert/xóa bản ghi trong projection document_access (query_db)
│   ├── cache/
│   │   └── redis_access_cache.py             ← Cache allowed_doc_ids theo user_id, TTL ~60s
│   ├── external/
│   │   ├── openai_client.py                  ← OpenAI GPT-4o mini — streaming + tool_call. Timeout 30s, không retry.
│   │   ├── mcp_client.py                     ← MCP client: kết nối mcp-service (Streamable HTTP/SSE), list + gọi tool (rag_search, hr_query).
│   │   │                                        Circuit Breaker (pybreaker, fail_max=5, reset_timeout=30s).
│   │   └── langfuse_client.py                ← Ghi trace query vào Langfuse: latency từng bước, token cost, retrieved chunks, feedback. Fail-silently.
│   ├── memory/                               ← Redis short-term memory
│   └── sse/
│       ├── connection_manager.py            ← Sổ đăng ký { user_id, role, department } → SSE stream /notifications đang mở
│       └── notify_subscriber.py             ← Subscribe notify.doc_new → lọc user đang online đủ quyền (ACL theo
│                                               classification/department/user_id) → LƯU vào bảng notifications + đẩy event xuống SSE /notifications
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                   ← get_orchestration_use_case()
        └── routers/
            ├── query.py                      ← POST /query (SSE): nhận question → stream token → done
            ├── notifications.py              ← GET /notifications (SSE) + GET /notifications/history, /unread-count, POST /{id}/read
            ├── conversations.py              ← GET /conversations, DELETE /conversations (+ rename)
            ├── admin.py                      ← GET /admin/metrics (Admin only) — volume, feedback rate, top questions
            └── feedback.py                   ← POST /feedback
```
> Reranker + NATS rag.search **không còn ở Query Service** — đã chuyển sang **mcp-service** (tool `rag_search`).
> Query Service giờ là **MCP client**, gọi tool qua `mcp_client.py`.

**Key logic cần implement:**

*Orchestration (`orchestration.py`):*
1. Lấy conversation context: `conv_repo.get_context(user_id, recent_k=5)` → summary + 5 turns gần nhất
2. **ACL pre-filter:** `doc_access_repo.get_allowed_doc_ids(user_id, role, department)` → đọc bản sao trong `query_db.document_access` (do `doc_access_subscriber` cập nhật qua event) → `allowed_doc_ids` (cache Redis TTL ~60s). **Không gọi sang Document Service** — Document Service chết vẫn query được.
3. **Semantic Cache check:** embed câu hỏi → cosine similarity > 0.95 → return cached response ngay
4. **LlamaIndex FunctionCallingAgent** (MCP client) liệt kê tool từ **mcp-service** → LLM tự chọn tool:
   - `rag_search`: MCP tool ở mcp-service → (query rewrite) → NATS `rag.search` → RRF → Top-5 → rerank → Top-3
   - `hr_query`: MCP tool ở mcp-service → query `mcp_db.hr_mock.*` filter `user_id`
   - **Bảo mật:** Query Service **tự inject** `document_ids = allowed_doc_ids` (từ bước 2) và `user_id = current_user` vào lời gọi tool — KHÔNG để LLM tự điền (tránh vượt quyền).
5. Build prompt: system prompt + summary + recent messages + retrieved context
6. Gọi OpenAI GPT-4o mini streaming: yield từng token → gửi SSE `data: {"token":"..."}`, kết thúc gửi `data: {"done":true,"sources":[...]}`
7. Lưu message: `conv_repo.save_message(user_id, "user", question)` + `save_message(user_id, "assistant", full_answer)`
8. Summary buffer: nếu conversation > 10 turns → gọi LLM compress → `conv_repo.update_summary()`

*Failure Handling:*
- **MCP call (query-service → mcp-service)**: Circuit Breaker (`pybreaker`, fail_max=5, reset_timeout=30s) trong `mcp_client.py` — Circuit Open → trả 503 ngay
- **OpenAI**: Timeout 30s, không retry — trả 503 ngay, log token count vào Langfuse trước khi fail
- **Redis**: Fail-open — nếu Redis unreachable, `redis_access_cache.py` fallback về query projection `document_access` trong query_db trực tiếp
- **Document Service down**: không ảnh hưởng query — ACL đọc từ projection local; chỉ là thay đổi quyền mới (eventual consistency) tạm chưa cập nhật tới khi Document Service sống lại và event `doc.access` được JetStream giao lại

*Realtime notify — "có tài liệu mới" (`notify_subscriber.py`):*
1. Khi client mở SSE `GET /notifications`: decode JWT → `connection_manager.add(user_id, role, department, sse_stream)`.
2. `notify_subscriber` nhận `notify.doc_new { doc_id, document_name, classification, allowed_departments, allowed_user_ids }`.
3. Duyệt user đang online trong `connection_manager`, áp ACL: public → tất cả; internal → mọi nhân viên; secret → khớp department; top_secret → khớp user_id.
4. Đẩy `{type:"notify", event:"doc_new", message:"Có tài liệu mới: <document_name>", doc_id}` tới các socket đủ quyền.
5. SSE `/notifications` đóng (client rời đi) → `connection_manager.remove`.

**Observability — AI/Agent Engineer làm chủ:**
- Định nghĩa **trace convention** chung (tên trace/span, field bắt buộc) để query-service, rag-worker và mcp-service log nhất quán vào cùng 1 Langfuse project.
- **RAGAS evaluation** (Phase 1.5, cuối tuần 3): chạy offline trên query trace data (retrieved chunks, scores) — Faithfulness, Answer Relevancy, Context Precision/Recall, Answer Correctness.

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service, document-service, rag-worker hoặc mcp-service.

---

### DevOps — Trần Hữu Gia Huy

**Bắt đầu ngay Ngày 1, song song với SA.**

**Files DevOps tạo:**
```
docker-compose.yml               ← 12 containers: nginx, nuxt-chat, nuxt-admin, user-service,
                                    document-service, query-service, rag-worker, mcp-service,
                                    nats (JetStream), qdrant, redis, langfuse :3100
                                    (PostgreSQL = AWS RDS external, không có container)

src/user-service/Dockerfile
src/document-service/Dockerfile
src/query-service/Dockerfile
src/rag-worker/Dockerfile
src/mcp-service/Dockerfile
src/frontend/chat/Dockerfile
src/frontend/admin/Dockerfile     ← (frontend/base là Nuxt layer, không có Dockerfile riêng)

nginx/
├── nginx.conf                   ← Route /api/user/*       → user-service:8000
│                                   Route /api/documents/* → document-service:8002
│                                   Route /api/query/*     → query-service:8001
│                                     • SSE /api/query/query + /api/query/notifications: tắt `proxy_buffering`,
│                                       `proxy_read_timeout` dài (vd 3600s) để giữ stream SSE lâu
│                                   Route /api/mcp/*        → mcp-service:8003
│                                   Route /                → nuxt-chat:3000   (End User)
│                                   Route /admin            → nuxt-admin:3001  (Admin console)
└── ssl/                         ← Let's Encrypt cert (production)

infra/
├── aws/
│   └── ec2-setup.sh             ← Script init EC2: install Docker, clone repo, start compose
└── scripts/
    ├── db-migrate.sh            ← Chạy CREATE SCHEMA + DDL scripts từ data-schema.md
    └── smoke-test.sh            ← 10 câu hỏi mẫu sau deploy, pass hết mới OK

.github/
└── workflows/
    └── deploy.yml               ← CI: test → build image → push ECR → SSH EC2 → docker compose pull + up
```

**Key setup cần làm:**
- **Langfuse server**: dựng + vận hành container `langfuse :3100` (DB backing, expose port, retention). Cấp **API key (public/secret) qua AWS Secrets Manager** cho rag-worker + query-service dùng chung 1 project. DevOps chỉ lo hạ tầng — **không** viết `langfuse_client.py` (chủ service tự nhúng client).
- **NATS container**: deploy + vận hành broker (port 4222, JetStream enabled). **Subject + stream config do Backend Dev quyết** (DevOps chỉ chạy container theo cấu hình đó).
- **CloudWatch alarm**: ngưỡng phải đồng bộ với Circuit Breaker (`fail_max`, `reset_timeout`) của `mcp_client.py` (query-service → mcp-service).

**Không được đụng:** bất kỳ file Python `.py` logic nào.

---

## Thứ tự bắt đầu

```
Ngày 1–2:
  SA        → domain entities + repositories + API schemas → commit → tag team
  DevOps    → Dockerfile + docker-compose.yml cơ bản + CI pipeline skeleton

Ngày 3+ (song song):
  Frontend  → frontend/base (auth + design system) trước → frontend/chat (chat SSE, notifications, document viewer) + frontend/admin (documents, users, analytics)
  Backend Dev       → user-service (auth, DB, JWT, quản lý user) + document-service (upload, S3, NATS doc.ingest/doc.status)
  RAG Engineer      → rag-worker (ingestion Parent-Child + Gemini OCR + retrieval) + mcp-service (tool rag_search/hr_query + rerank)
  AI/Agent Engineer → query-service (FunctionCallingAgent + MCP client + SSE streaming + notify + history)
  DevOps            → AWS EC2 setup + CI/CD + Langfuse server
```

---

## Ranh giới RAG Engineer ↔ AI/Agent Engineer

```
Câu hỏi user
     ↓
[AI/Agent Engineer]   orchestration.py: lấy conversation context từ DB
     ↓
[AI/Agent Engineer]   doc_access_repo: đọc projection query_db.document_access (fed by doc.access event) → allowed_doc_ids (cache Redis ~60s)
     ↓
[AI Eng / Query Service]   FunctionCallingAgent (MCP client): inject document_ids=allowed_doc_ids + user_id → gọi tool ở mcp-service
     ├── [RAG Eng] tool rag_search (mcp-service) → nats_rag_client: NATS request-reply rag.search { query, top_k=5, document_ids }
     │        ↓  NATS
     │   [RAG Eng] retrieval.py (rag-worker): embed → hybrid search → Top-5 → SearchResult[]
     │        ↓
     │   [RAG Eng] BGE-Reranker-v2-m3 (mcp-service): Top-5 → Top-3
     │
     └── [RAG Eng] tool hr_query (mcp-service) → query mcp_db.hr_mock.* WHERE user_id = current_user
     ↓
[AI Eng / Query Service]   build prompt → OpenAI GPT-4o mini streaming → SSE về FE
```

**Ranh giới dữ liệu:**
- **RAG Engineer** ôm cả đường RAG: rag-worker (embed + hybrid search Top-5) **và** mcp-service (tool `rag_search` =
  rag.search + **rerank Top-5→Top-3**; `hr_query` = đọc `mcp_db.hr_mock`). Tool self-contained, agent nào gọi cũng được.
- **AI/Agent Engineer** (Query Service, MCP client): quyết định `document_ids`/`user_id` (ACL), gọi tool qua MCP, build prompt, stream SSE.
- mcp-service không tự quyết quyền — chỉ nhận `document_ids`/`user_id` do Query Service inject.

---

## Workload theo Phase

| Role | Phase 1 (3 tuần) | Phase 2+ |
|------|-----------------|----------|
| SA | Nặng tuần 1 → nhẹ dần (review PR) | Review, không code |
| Frontend Dev | **Nặng** — 2 micro-frontend Nuxt 4: base layer (auth + design system) + Chat app (SSE + Notification Center + Document Viewer + conversation history) + Admin app (documents + users + Analytics Dashboard) | Trung bình — mở rộng dashboard, realtime 2 chiều |
| Backend Dev | **Nặng hơn trước** — user-service (auth + user CRUD) + document-service (upload, S3, NATS doc.ingest/doc.status, delete) + **chủ NATS subject contract** | Nhẹ — ít thay đổi |
| RAG Engineer | **Rất nặng** — rag-worker (ingestion Parent-Child + Gemini OCR + retrieval Top-5) + mcp-service (tool rag_search/hr_query + rerank) | Tune chất lượng, chunk config |
| AI/Agent Engineer | **Nặng** — query-service (FunctionCallingAgent + MCP client + SSE + notify + history) | Teams Bot (cũng là MCP client), dashboard analytics |
| DevOps | Trung bình — Docker + AWS setup | Nhẹ — maintain |

---

## Quy tắc không đụng nhau

### 1. Chỉ sửa folder mình owns
Muốn sửa file của người khác → mở PR + tag người đó review → chờ approve.

### 2. Không import chéo giữa use cases
```python
# BAD — orchestration không được import thẳng vào ingestion
from app.application.use_cases.ingestion import IngestDocumentUseCase  # ❌

# OK — cả 2 dùng chung domain entity
from app.domain.entities.document import Document  # ✅
```

### 3. Thay đổi contract → báo SA
Bất kỳ thay đổi nào trong `app/domain/` phải SA approve trước.

### 4. External client files — mỗi service có file riêng, độc lập
- `src/query-service/.../openai_client.py`: AI/Agent Engineer owns — OpenAI GPT-4o mini streaming + tool_call
- `src/rag-worker/.../openai_embedding_client.py`: RAG Engineer owns — OpenAI text-embedding-3-small (1536 dims)
- 2 file hoàn toàn độc lập, không import lẫn nhau.

---

## Branch Convention

```
main          ← production, protected
develop       ← integration branch, mọi người merge vào đây

feature branches:
  feat/[ten-nguoi]/[feature]
  Ví dụ:
  feat/nguyen/rag-ingestion
  feat/hung/auth-jwt
  feat/dung-pq/llm-orchestration
  feat/nguyen/mcp-service
  feat/huy/docker-setup
  feat/hai/fe-base
  feat/hai/fe-chat
  feat/hai/fe-admin
  feat/dung-vq/user-service
  feat/dung-vq/document-service
```

### PR Checklist
- [ ] Code chạy được local
- [ ] Không break code người khác
- [ ] Đã test tính năng chính
- [ ] 1 teammate review + approve

---

## Touch Points — Nơi dễ conflict

| Touch point | Người liên quan | Cách xử lý |
|-------------|----------------|------------|
| `app/domain/` (entities + repos) | SA owns, tất cả đọc | SA freeze trước khi team code — không ai tự sửa |
| `SearchResult` dataclass | SA define, RAG Engineer implement (trả về), AI/Agent Engineer consume (rerank + build prompt) | Sửa → báo SA → SA update contracts.md → tất cả update |
| `DocumentAccessRepository` ABC | SA define, AI/Agent Engineer implement (`postgres_document_access_repo.py`) | Sửa → báo SA |
| `RerankService` ABC | SA define, **RAG Engineer** implement trong **mcp-service** (`bge_reranker_client.py`) | Sửa → báo SA |
| MCP tool contract (`rag_search`, `hr_query` I/O) | SA define; **RAG Engineer** implement (mcp-service), AI Engineer consume (Query Service MCP client) | Đổi tên/tham số tool → báo cả RAG Eng + AI Eng |
| API schemas (Pydantic) | SA define, Backend Dev + AI/Agent Engineer implement, Frontend Dev consume | Sửa → báo SA |
| `requirements.txt` | Tất cả | Thêm package → mở PR, không tự pip install rồi push |
| `docker-compose.yml` | DevOps owns | Thêm env var mới → báo DevOps |
| NATS subject contract + JetStream config (`infra/nats/`) | **Backend Dev** owns (rag.search payload = RAG Eng) | Đổi tên subject / payload / stream → báo Backend Dev; DevOps deploy container theo config |
| `openai_client.py` (query-service) | AI/Agent Engineer owns | RAG Engineer không dùng, không đụng |
| `openai_embedding_client.py` (rag-worker) | RAG Engineer owns | AI/Agent Engineer không dùng, không đụng |
| `mcp_client.py` (query-service) | AI/Agent Engineer owns | Circuit Breaker (fail_max, reset_timeout) cho call query-service → mcp-service; đồng bộ CloudWatch alarm |
| `nats_rag_client.py` (mcp-service) | **RAG Engineer** owns | Trong tool rag_search của mcp-service (gọi rag-worker qua NATS) |
| `langfuse_client.py` (rag-worker) | RAG Engineer owns | Bắt buộc fail silently — không throw exception ra ngoài, không ảnh hưởng request |
| `langfuse_client.py` (query-service) | AI/Agent Engineer owns | File riêng, độc lập với client rag-worker. Bắt buộc fail silently |
| Langfuse trace schema/convention | AI/Agent Engineer define, RAG Engineer + AI/Agent Engineer tuân theo | Đổi tên trace/span hoặc field → báo AI/Agent Engineer để 2 service đồng bộ |
| Langfuse server (container :3100, keys) | DevOps owns | Đổi endpoint/key → báo cả 2 service owner |
| `bge_reranker_client.py` (mcp-service) | **RAG Engineer** owns — implement `RerankService` | Nằm trong tool `rag_search` của mcp-service; RAG Worker chỉ trả Top-5 qua NATS, rerank ở mcp-service |
| `langfuse_client.py` (mcp-service) | **RAG Engineer** owns | Trace tool rag_search/hr_query; fail-silently |
