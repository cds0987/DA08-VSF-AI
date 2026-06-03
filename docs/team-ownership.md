# Team Ownership — RAG Chatbot

## Tổng quan phân công

| Role | Người phụ trách | Phụ trách chính | Service / Folder | Bắt đầu sau |
|------|----------------|----------------|-----------------|-------------|
| **SA** | Lê Hữu Hưng | Domain design, contracts, API schemas, code review | `app/domain/` (cả 4 services) | Ngay — làm đầu tiên |
| **Frontend Dev** | Đặng Hồ Hải | Web UI chat, admin dashboard, streaming | `src/frontend/` (Next.js) | Sau khi SA freeze schemas |
| **Backend Dev** | Vũ Quang Dũng | User Service + Document Service: auth, JWT, document management | `src/user-service/`, `src/document-service/` | Sau khi SA freeze domain |
| **RAG Engineer** | Trần Thanh Nguyên | RAG Worker: ingestion pipeline + retrieval pipeline, NATS subscriber | `src/rag-worker/app/` | Sau khi SA freeze domain |
| **AI/Agent Engineer** | Phạm Quốc Dũng | Query Service: LLM orchestration, streaming, memory, NATS client | `src/query-service/app/` | Sau khi SA freeze domain |
| **DevOps** | Trần Hữu Gia Huy | Docker, AWS, CI/CD, Nginx, NATS setup, monitoring | `infra/`, `docker-compose.yml` | Ngay — song song với SA |

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
    ├── rerank_service.py           ← RerankService ABC (rerank)
    └── document_access_repository.py ← DocumentAccessRepository ABC (get_allowed_doc_ids)
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

**Files Frontend Dev tạo:**
```
src/frontend/
├── app/                         ← Next.js App Router
│   ├── (auth)/
│   │   └── login/page.tsx       ← Form đăng nhập (email/password + Microsoft SSO button)
│   ├── (main)/
│   │   ├── chat/page.tsx        ← Giao diện chat chính, SSE streaming consumer (End User only)
│   │   └── admin/
│   │       ├── documents/page.tsx  ← Upload file + danh sách tài liệu + ingestion status (Admin only)
│   │       └── users/page.tsx      ← Danh sách user, deactivate/reactivate (Admin only)
├── components/
│   ├── ChatMessage.tsx          ← Render 1 tin nhắn (user / bot), source citations
│   ├── SourceCard.tsx           ← Hiển thị nguồn tài liệu + highlight text
│   ├── FileUpload.tsx           ← Drag-drop upload, chọn classification
│   └── StreamingText.tsx        ← Nhận SSE stream, render token từng cái
├── hooks/
│   ├── useChat.ts               ← Gọi POST /query, handle SSE stream
│   ├── useDocuments.ts          ← Gọi GET/POST /documents
│   └── useAuth.ts               ← JWT lưu localStorage, auto-refresh
└── lib/
    └── api.ts                   ← Axios/fetch base client, attach Bearer token
```

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
│           └── delete_document_use_case.py    ← Xóa S3 + record + trigger xóa vectors Qdrant
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                          ← SQLAlchemy model bảng documents + audit_logs (document events) — chủ sở hữu doc_db
│   │   └── postgres_document_repository.py    ← Implement DocumentRepository
│   ├── storage/
│   │   └── s3_client.py                       ← Upload / xóa file gốc trên S3
│   └── messaging/
│       ├── nats_publisher.py                  ← Publish doc.ingest (cho RAG Worker) + doc.access (cho Query Service)
│       │                                         doc.access { doc_id, classification, allowed_departments, allowed_user_ids, deleted }
│       └── nats_subscriber.py                 ← Subscribe doc.status → update status indexed/failed + chunk_count
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                    ← require_admin(), get upload/list/delete use cases
        └── routers/
            └── documents.py                   ← POST /documents/upload, GET /documents, GET /documents/{id}, DELETE /documents/{id} (admin only)
```

**Key logic — document-service:**
- `upload_document_use_case.py`: validate file (≤50MB, đúng loại) → upload S3 → `doc_repo.create(status=queued)` → publish `doc.ingest` (RAG Worker xử lý) **và** `doc.access` (Query Service cập nhật phân quyền). Trả `202 { document_id, status:"queued" }`.
- `nats_subscriber.py`: lắng nghe `doc.status` từ RAG Worker → `doc_repo.update_status(indexed/failed, chunk_count)`. **Đây là nơi DUY NHẤT cập nhật trạng thái ingestion** — RAG Worker chỉ publish event, không ghi bảng documents.
- `delete_document_use_case.py`: xóa record + file S3, publish `doc.access { deleted:true }` (Query Service gỡ khỏi projection) + trigger xóa vectors Qdrant.
- **Event-driven ACL (database-per-service)**: mọi thay đổi quyền (upload / đổi classification / xóa) → publish `doc.access` lên NATS JetStream. Query Service tự giữ bản sao — **không ai đọc thẳng `doc_db` của service khác**.
- **Document Service là chủ duy nhất bảng `documents`** (create + update status). Khớp [api-spec.md](api-spec.md) — `doc.status`: "Document Service subscribe để cập nhật PostgreSQL".

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong query-service hoặc rag-worker.

---

### RAG Engineer — Trần Thanh Nguyên

**Phụ trách rag-worker toàn bộ. Bắt đầu Ngày 3. Workload nặng nhất Phase 1.**

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

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service, document-service hoặc query-service.

---

### AI/Agent Engineer — Phạm Quốc Dũng

**Phụ trách query-service toàn bộ. Bắt đầu Ngày 3. Phase 1 nặng (LlamaIndex FunctionCallingAgent).**

**Files AI/Agent Engineer tạo:**
```
src/query-service/app/
├── application/
│   └── use_cases/
│       └── query/
│           └── orchestration.py              ← FunctionCallingAgent → rag_search_tool / hr_query_tool → stream OpenAI GPT-4o mini
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                         ← SQLAlchemy model cho conversations, messages, document_access (projection ACL)
│   │   ├── postgres_conversation_repo.py     ← Implement ConversationRepository
│   │   └── postgres_document_access_repo.py  ← Implement DocumentAccessRepository — query bảng projection `document_access` trong query_db (KHÔNG đụng doc_db)
│   ├── messaging/
│   │   └── doc_access_subscriber.py          ← Subscribe NATS doc.access (JetStream) → upsert/xóa bản ghi trong projection document_access (query_db)
│   ├── cache/
│   │   └── redis_access_cache.py             ← Cache allowed_doc_ids theo user_id, TTL ~60s
│   ├── external/
│   │   ├── openai_client.py                  ← OpenAI GPT-4o mini — streaming + tool_call. Timeout 30s, không retry.
│   │   ├── nats_rag_client.py                ← NATS request-reply rag.search (timeout 10s).
│   │   │                                        Circuit Breaker (pybreaker, fail_max=5, reset_timeout=30s).
│   │   ├── bge_reranker_client.py            ← Implement RerankService — BGE-Reranker-v2-m3 (loaded inline trong container, Top-5→Top-3)
│   │   └── langfuse_client.py                ← Ghi trace query vào Langfuse: latency từng bước, token cost, retrieved chunks, feedback. Fail-silently.
│   └── memory/                               ← Redis short-term memory
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                   ← get_orchestration_use_case()
        └── routers/
            ├── query.py                      ← POST /query (streaming SSE)
            ├── conversations.py              ← GET /conversations, DELETE /conversations
            └── feedback.py                   ← POST /feedback
```

**Key logic cần implement:**

*Orchestration (`orchestration.py`):*
1. Lấy conversation context: `conv_repo.get_context(user_id, recent_k=5)` → summary + 5 turns gần nhất
2. **ACL pre-filter:** `doc_access_repo.get_allowed_doc_ids(user_id, role, department)` → đọc bản sao trong `query_db.document_access` (do `doc_access_subscriber` cập nhật qua event) → `allowed_doc_ids` (cache Redis TTL ~60s). **Không gọi sang Document Service** — Document Service chết vẫn query được.
3. **Semantic Cache check:** embed câu hỏi → cosine similarity > 0.95 → return cached response ngay
4. **LlamaIndex FunctionCallingAgent** nhận câu hỏi → tự quyết định gọi tool:
   - `rag_search_tool`: câu hỏi về tài liệu nội bộ → Query Rewriting (3 variations) → NATS `rag.search` → RRF merge → Top-5 candidates → rerank BGE-Reranker-v2-m3 Top-3
   - `hr_query_tool`: câu hỏi HR cá nhân → query `query_db.hr_mock.*` tables (cùng DB của Query Service) với filter `WHERE user_id = current_user`
5. Build prompt: system prompt + summary + recent messages + retrieved context
6. Gọi OpenAI GPT-4o mini streaming: yield từng token → SSE event `data: {"token": "..."}`
7. Lưu message: `conv_repo.save_message(user_id, "user", question)` + `save_message(user_id, "assistant", full_answer)`
8. Summary buffer: nếu conversation > 10 turns → gọi LLM compress → `conv_repo.update_summary()`

*Failure Handling:*
- **NATS RAG search**: Circuit Breaker (`pybreaker`, fail_max=5, reset_timeout=30s) — Circuit Open → trả 503 ngay
- **OpenAI**: Timeout 30s, không retry — trả 503 ngay, log token count vào Langfuse trước khi fail
- **Redis**: Fail-open — nếu Redis unreachable, `redis_access_cache.py` fallback về query projection `document_access` trong query_db trực tiếp
- **Document Service down**: không ảnh hưởng query — ACL đọc từ projection local; chỉ là thay đổi quyền mới (eventual consistency) tạm chưa cập nhật tới khi Document Service sống lại và event `doc.access` được JetStream giao lại

**Observability — AI/Agent Engineer làm chủ:**
- Định nghĩa **trace convention** chung (tên trace/span, field bắt buộc) để cả query-service và rag-worker log nhất quán vào cùng 1 Langfuse project.
- **RAGAS evaluation** (Phase 1.5, cuối tuần 3): chạy offline trên query trace data (retrieved chunks, scores) — Faithfulness, Answer Relevancy, Context Precision/Recall, Answer Correctness.

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service, document-service hoặc rag-worker.

---

### DevOps — Trần Hữu Gia Huy

**Bắt đầu ngay Ngày 1, song song với SA.**

**Files DevOps tạo:**
```
docker-compose.yml               ← 10 containers: nginx, next-frontend, user-service,
                                    document-service, query-service, rag-worker,
                                    nats (JetStream), qdrant, redis, langfuse :3100
                                    (PostgreSQL = AWS RDS external, không có container)

src/user-service/Dockerfile
src/document-service/Dockerfile
src/query-service/Dockerfile
src/rag-worker/Dockerfile
src/frontend/Dockerfile

nginx/
├── nginx.conf                   ← Route /api/user/*       → user-service:8000
│                                   Route /api/documents/* → document-service:8002
│                                   Route /api/query/*     → query-service:8001
│                                   Route /                → next-frontend:3000
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
- **NATS JetStream**: enable persist message cho `doc.ingest` / `doc.status`.
- **CloudWatch alarm**: ngưỡng phải đồng bộ với Circuit Breaker (`fail_max`, `reset_timeout`) của `nats_rag_client.py`.

**Không được đụng:** bất kỳ file Python `.py` logic nào.

---

## Thứ tự bắt đầu

```
Ngày 1–2:
  SA        → domain entities + repositories + API schemas → commit → tag team
  DevOps    → Dockerfile + docker-compose.yml cơ bản + CI pipeline skeleton

Ngày 3+ (song song):
  Frontend  → mock API bằng schemas, build UI
  Backend Dev       → user-service (auth, DB, JWT, quản lý user) + document-service (upload, S3, NATS doc.ingest/doc.status)
  RAG Engineer      → rag-worker: ingestion pipeline (Parent-Child chunking, Gemini OCR) + retrieval
  AI/Agent Engineer → query-service: FunctionCallingAgent + rerank + langfuse trace + streaming + conversation history
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
[AI/Agent Engineer]   FunctionCallingAgent: LLM quyết định gọi tool nào
     ├── rag_search_tool → nats_rag_client.py: NATS request-reply rag.search { query, top_k=5, document_ids }
     │        ↓  NATS
     │   [RAG Engineer] retrieval.py: embed → hybrid search → Top-5 → SearchResult[]
     │        ↓
     │   [AI/Agent Engineer] BGE-Reranker-v2-m3 (trong query-service): Top-5 → Top-3
     │
     └── hr_query_tool → query query_db.hr_mock.* tables WHERE user_id = current_user
     ↓
[AI/Agent Engineer]   build prompt → OpenAI GPT-4o mini streaming → SSE về FE
```

**Ranh giới dữ liệu:**
- RAG Engineer: (1) embed query, (2) hybrid search Top-5 — trả về `List[SearchResult]` (Top-5) qua NATS reply. **Không rerank.**
- AI/Agent Engineer: (1) quyết định document_ids nào được search, (2) **rerank Top-5 → Top-3** (BGE-Reranker trong query-service), (3) build prompt, (4) stream về FE
- RAG Engineer không biết ACL logic, không biết user là ai — chỉ nhận `document_ids` như filter thông thường

---

## Workload theo Phase

| Role | Phase 1 (3 tuần) | Phase 2+ |
|------|-----------------|----------|
| SA | Nặng tuần 1 → nhẹ dần (review PR) | Review, không code |
| Frontend Dev | Trung bình — UI chat + admin cơ bản | Trung bình — dashboard analytics |
| Backend Dev | **Nặng hơn trước** — user-service (auth + user CRUD) + document-service (upload, S3, NATS doc.ingest/doc.status, delete) | Nhẹ — ít thay đổi |
| RAG Engineer | **Nặng** — ingestion (Parent-Child chunking, Gemini OCR) + retrieval (hybrid search Top-5; rerank do query-service làm) | Tune chất lượng, chunk config |
| AI/Agent Engineer | **Nặng** — LlamaIndex FunctionCallingAgent + rerank + prompt + stream + history | Teams Bot, dashboard analytics |
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
  feat/huy/docker-setup
  feat/hai/chat-ui
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
| `RerankService` ABC | SA define, AI/Agent Engineer implement (`bge_reranker_client.py`) | Sửa → báo SA |
| API schemas (Pydantic) | SA define, Backend Dev + AI/Agent Engineer implement, Frontend Dev consume | Sửa → báo SA |
| `requirements.txt` | Tất cả | Thêm package → mở PR, không tự pip install rồi push |
| `docker-compose.yml` | DevOps owns | Thêm env var mới → báo DevOps |
| `openai_client.py` (query-service) | AI/Agent Engineer owns | RAG Engineer không dùng, không đụng |
| `openai_embedding_client.py` (rag-worker) | RAG Engineer owns | AI/Agent Engineer không dùng, không đụng |
| `nats_rag_client.py` (query-service) | AI/Agent Engineer owns | Circuit Breaker state (fail_max, reset_timeout) cần đồng bộ với CloudWatch alarm threshold |
| `langfuse_client.py` (rag-worker) | RAG Engineer owns | Bắt buộc fail silently — không throw exception ra ngoài, không ảnh hưởng request |
| `langfuse_client.py` (query-service) | AI/Agent Engineer owns | File riêng, độc lập với client rag-worker. Bắt buộc fail silently |
| Langfuse trace schema/convention | AI/Agent Engineer define, RAG Engineer + AI/Agent Engineer tuân theo | Đổi tên trace/span hoặc field → báo AI/Agent Engineer để 2 service đồng bộ |
| Langfuse server (container :3100, keys) | DevOps owns | Đổi endpoint/key → báo cả 2 service owner |
| `bge_reranker_client.py` (query-service) | AI/Agent Engineer owns — implement `RerankService` | Đã chuyển từ rag-worker sang; RAG Worker chỉ trả Top-5 qua NATS, rerank ở query-service |
