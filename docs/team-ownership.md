# Team Ownership — RAG Chatbot

## Tổng quan phân công

| Role | Người phụ trách | Phụ trách chính | Service / Folder | Bắt đầu sau |
|------|----------------|----------------|-----------------|-------------|
| **SA** | Lê Hữu Hưng | Domain design, contracts, API schemas, code review | `app/domain/` (cả 3 services) | Ngay — làm đầu tiên |
| **Frontend Dev** | Đặng Hồ Hải | Web UI chat, admin dashboard, streaming | `src/frontend/` (Next.js) | Sau khi SA freeze schemas |
| **Backend Dev** | Vũ Quang Dũng | User Service: auth, JWT, user management, DB | `src/user-service/app/` | Sau khi SA freeze domain |
| **RAG Engineer** | Trần Thanh Nguyên | Ingestion pipeline + Retrieval pipeline toàn bộ | `src/rag-service/app/` | Sau khi SA freeze domain |
| **AI/Agent Engineer** | Phạm Quốc Dũng | Chat Service: LLM orchestration, streaming, memory | `src/chat-service/app/` | Sau khi SA freeze domain |
| **DevOps** | Trần Hữu Gia Huy | Docker, AWS, CI/CD, Nginx, monitoring | `infra/`, `docker-compose.yml` | Ngay — song song với SA |

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

**Files SA tạo — chat-service:**
```
src/chat-service/app/domain/
├── entities/
│   └── conversation.py          ← Message, ConversationContext, Conversation dataclass
└── repositories/
    └── conversation_repository.py  ← ConversationRepository ABC (get_context, save_message, ...)
```

**Files SA tạo — chat-service (thêm mới):**
```
src/chat-service/app/domain/
└── repositories/
    ├── rerank_service.py              ← RerankService ABC (rerank)
    └── document_access_repository.py ← DocumentAccessRepository ABC (get_allowed_doc_ids)
```

**Files SA tạo — rag-service:**
```
src/rag-service/app/domain/
├── entities/
│   └── document.py              ← Document, Section dataclass, DocumentStatus enum
└── repositories/
    ├── vector_repository.py     ← SearchResult dataclass, VectorRepository ABC (document_ids filter)
    ├── document_repository.py   ← DocumentRepository ABC
    └── embedding_service.py     ← EmbeddingService ABC (embed, embed_batch)
```

**SA cũng define schemas (Pydantic) — nằm trong interfaces/api nhưng SA viết:**
```
src/chat-service/app/interfaces/api/schemas/
├── query.py       ← QueryRequest, QueryResponse, Source
└── document.py    ← UploadResponse

src/user-service/app/interfaces/api/schemas/
└── auth.py        ← LoginRequest, TokenResponse
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
│   │   ├── chat/page.tsx        ← Giao diện chat chính, SSE streaming consumer
│   │   ├── documents/page.tsx   ← Upload file + danh sách tài liệu của user
│   │   └── admin/
│   │       ├── documents/page.tsx  ← Pending queue: approve/reject
│   │       └── users/page.tsx      ← Danh sách user, deactivate/reactivate
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

**Phụ trách User Service toàn bộ. Bắt đầu Ngày 3.**

**Files Backend Dev tạo:**
```
src/user-service/app/
├── application/
│   └── use_cases/
│       └── auth/
│           ├── login_use_case.py          ← Verify email+password, issue JWT (HS256)
│           └── verify_token_use_case.py   ← Decode + validate JWT, trả về User
│
├── infrastructure/
│   └── db/
│       ├── models.py                      ← SQLAlchemy ORM model cho bảng users
│       └── postgres_user_repository.py    ← Implement UserRepository (async SQLAlchemy)
│
└── interfaces/
    └── api/
        ├── main.py                        ← FastAPI app init, include router
        ├── dependencies.py                ← get_login_use_case(), get_current_user()
        └── routers/
            └── auth.py                    ← POST /auth/login, GET /auth/me
```

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong chat-service hoặc rag-service.

**Key logic cần implement:**
- `login_use_case.py`: bcrypt verify password → tạo JWT payload `{sub, role, department, jti}` → sign HS256
- `postgres_user_repository.py`: implement `get_by_email`, `get_by_id`, `create` từ `UserRepository` ABC
- `dependencies.py`: `get_current_user()` — decode JWT bằng shared secret, trả về `User` object

---

### RAG Engineer — Trần Thanh Nguyên

**Phụ trách rag-service toàn bộ. Bắt đầu Ngày 3. Workload nặng nhất Phase 1.**

**Files RAG Engineer tạo:**
```
src/rag-service/app/
├── application/
│   └── use_cases/
│       ├── ingestion/
│       │   └── ingest_document_use_case.py   ← Nhận document_id → parse → section → caption → embed → upsert Qdrant
│       └── query/
│           └── retrieval.py                  ← Nhận query + document_ids → embed → hybrid search → filter score → SearchResult[]
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                         ← SQLAlchemy model cho bảng documents, audit_logs
│   │   └── postgres_document_repository.py   ← Implement DocumentRepository
│   ├── vector/
│   │   └── qdrant_vector_repository.py       ← Implement VectorRepository (hybrid_search với document_ids filter, upsert, delete)
│   └── external/
│       ├── bge_m3_client.py                  ← Implement EmbeddingService — gọi BGE-M3 HTTP API
│       ├── azure_doc_intel_client.py         ← Gọi Azure Document Intelligence — OCR PDF scan
│       └── langfuse_client.py                ← Ghi trace ingestion + retrieval vào Langfuse
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                   ← get_retrieval_use_case(), get_ingest_use_case()
        └── routers/
            ├── ingest.py                     ← POST /ingest (nhận từ Chat Service sau khi Admin approve)
            ├── scan.py                       ← POST /scan (operational — trigger scan S3 bucket)
            ├── status.py                     ← GET /status/{doc_id}
            ├── health.py                     ← GET /health
            └── search.py                     ← POST /search (nhận từ Chat Service, có document_ids filter)
```

**Key logic cần implement:**

*Ingestion pipeline (`ingest_document_use_case.py`):*
1. Tải file từ S3 → detect loại: PDF scan / PDF text / DOCX / TXT / XLSX / ...
2. OCR (nếu PDF scan): gọi `azure_doc_intel_client.py`
3. Parse text: PyMuPDF (PDF text layer), python-docx (DOCX), openpyxl (XLSX)
4. Section-based Chunking theo heading hierarchy — mỗi section là một đơn vị độc lập
5. Generate caption: thử LLM → fallback về heuristic từ heading đầu của section
6. Embed từng section: gọi `bge_m3_client.embed_batch()`
7. Upsert Qdrant: `vector_repo.upsert()` với payload gồm `section_id`, `document_id`, `caption`, `heading_path`, `source_s3_uri`, `markdown_s3_uri`, `classification`
8. Update `document_repo.update_status()` → INDEXED

*Retrieval pipeline (`retrieval.py`):*
1. Embed query: gọi `embedding_svc.embed(query_text)`
2. Hybrid search: `vector_repo.hybrid_search(vector, query_text, top_k=20, document_ids=document_ids)`
   - `document_ids` được Chat Service truyền vào — RAG Service không biết ACL logic
   - `None` → chỉ search public docs (fail-secure)
3. Score threshold filter: loại candidates dưới ngưỡng 0.5
4. Trả về `List[SearchResult]` — không rerank (Chat Service tự rerank)

*Failure Handling (`langfuse_client.py`, `bge_m3_client.py`, `azure_doc_intel_client.py`):*
- **Langfuse**: Fail silently — tất cả trace call bọc trong try/except, lỗi chỉ log console, không làm gián đoạn request
- **BGE-M3 Embedding**: Nếu unreachable → ingestion fail, cập nhật status `failed` kèm error message, Admin retry thủ công
- **Azure Document Intelligence**: Tương tự BGE-M3 — fail ingestion, không ảnh hưởng query flow

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service hoặc chat-service.

---

### AI/Agent Engineer — Phạm Quốc Dũng

**Phụ trách chat-service toàn bộ. Bắt đầu Ngày 3. Phase 1 nhẹ, Phase 2 nặng.**

**Files AI/Agent Engineer tạo:**
```
src/chat-service/app/
├── application/
│   └── use_cases/
│       └── query/
│           └── orchestration.py              ← Nhận câu hỏi → pre-filter ACL → gọi RAG → rerank → build prompt → stream Azure OpenAI
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                         ← SQLAlchemy model cho conversations, messages
│   │   ├── postgres_conversation_repo.py     ← Implement ConversationRepository
│   │   └── postgres_document_access_repo.py  ← Implement DocumentAccessRepository (query rag_svc.documents)
│   ├── cache/
│   │   └── redis_access_cache.py             ← Cache allowed_doc_ids theo user_id, TTL ~60s
│   ├── external/
│   │   ├── openai_client.py                  ← Azure OpenAI Chat Completion + SSE streaming. Timeout 30s, không retry.
│   │   ├── rag_service_client.py             ← HTTP client gọi POST /search và POST /ingest, forward X-Request-ID.
│   │   │                                        Bọc bằng Circuit Breaker (pybreaker, fail_max=5, reset_timeout=30s).
│   │   │                                        Circuit Open → trả 503 ngay, không chờ timeout.
│   │   └── bge_reranker_client.py            ← Implement RerankService — gọi BGE-Reranker-v2-m3 HTTP API
│   └── memory/                               ← Phase 2: Redis short-term memory
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                   ← get_orchestration_use_case()
        └── routers/
            ├── query.py                      ← POST /query (streaming SSE)
            ├── documents.py                  ← POST /documents/upload, GET /documents, approve/reject/delete
            ├── conversations.py              ← GET /conversations, DELETE /conversations
            └── feedback.py                   ← POST /feedback
```

**Key logic cần implement:**

*Orchestration (`orchestration.py`):*
1. Lấy conversation context: `conv_repo.get_context(user_id, recent_k=5)` → summary + 5 turns gần nhất
2. **ACL pre-filter:** `doc_access_repo.get_allowed_doc_ids(user_id, role, department)` → `allowed_doc_ids` (cache Redis TTL ~60s)
3. Gọi RAG: `rag_client.search(query, top_k=20, document_ids=allowed_doc_ids)` → `List[SearchResult]`
4. Nếu kết quả rỗng (score thấp) → stream câu trả lời "Không tìm thấy thông tin liên quan"
5. **Rerank:** `rerank_svc.rerank(query, results, top_n=3)` → Top-3 sections
6. Build prompt: system prompt + summary + recent messages + `section_content` của Top-3 sections + câu hỏi user
7. Gọi Azure OpenAI streaming: yield từng token → SSE event `data: {"token": "..."}`
8. Lưu message: `conv_repo.save_message(user_id, "user", question)` + `save_message(user_id, "assistant", full_answer)`
9. Summary buffer: nếu conversation > 10 turns → gọi LLM compress → `conv_repo.update_summary()`

*Document flow (`documents.py` router):*
- Upload file → lưu S3 → tạo record DB (status=pending/queued) → gọi `rag_client.ingest()` nếu Admin

*Failure Handling (`rag_service_client.py`, `openai_client.py`, `redis_access_cache.py`):*
- **RAG Service**: Circuit Breaker (`pybreaker`, fail_max=5, reset_timeout=30s) trong `rag_service_client.py`
- **Azure OpenAI**: Timeout 30s, không retry — trả 503 ngay, log token count vào Langfuse trước khi fail
- **Redis**: Fail-open — nếu Redis unreachable, `redis_access_cache.py` fallback về query PostgreSQL trực tiếp (rate limit tắt, log warning CloudWatch)

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service hoặc rag-service.

---

### DevOps — Trần Hữu Gia Huy

**Bắt đầu ngay Ngày 1, song song với SA.**

**Files DevOps tạo:**
```
docker-compose.yml               ← 9 containers: nginx, next-frontend, user-service,
                                    chat-service, rag-service, qdrant, redis, langfuse, postgres

src/user-service/Dockerfile
src/chat-service/Dockerfile
src/rag-service/Dockerfile
src/frontend/Dockerfile

nginx/
├── nginx.conf                   ← Route /api/user/* → user-service:8000
│                                   Route /api/chat/* → chat-service:8001
│                                   Route / → next-frontend:3000
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

**Không được đụng:** bất kỳ file Python `.py` logic nào.

---

## Thứ tự bắt đầu

```
Ngày 1–2:
  SA        → domain entities + repositories + API schemas → commit → tag team
  DevOps    → Dockerfile + docker-compose.yml cơ bản + CI pipeline skeleton

Ngày 3+ (song song):
  Frontend  → mock API bằng schemas, build UI
  Backend Dev       → user-service: auth, DB, JWT
  RAG Engineer      → ingestion pipeline + retrieval pipeline
  AI/Agent Engineer → orchestration + streaming + conversation history
  DevOps            → AWS EC2 setup + CI/CD hoàn chỉnh
```

---

## Ranh giới RAG Engineer ↔ AI/Agent Engineer

```
Câu hỏi user
     ↓
[AI/Agent Engineer]   orchestration.py: lấy conversation context từ DB
     ↓
[AI/Agent Engineer]   doc_access_repo: query PostgreSQL → allowed_doc_ids (cache Redis ~60s)
     ↓
[AI/Agent Engineer]   rag_service_client.py: gọi POST /search { query, top_k, document_ids }
     ↓  HTTP
[RAG Engineer]        retrieval.py: embed → hybrid search (document_ids filter) → filter score threshold
     ↓
[AI/Agent Engineer]   nhận List[SearchResult] (Top-20)
     ↓
[AI/Agent Engineer]   bge_reranker_client.py: rerank Top-20 → Top-3
     ↓
[AI/Agent Engineer]   build prompt (section_content) → gọi Azure OpenAI → stream về FE
```

**Ranh giới dữ liệu:**
- RAG Engineer trả về `List[SearchResult]` (section_content + score + metadata) — không rerank
- AI/Agent Engineer: (1) quyết định document_ids nào được search, (2) rerank kết quả, (3) build prompt
- RAG Engineer không biết ACL logic, không biết user là ai — chỉ nhận `document_ids` như một filter thông thường

---

## Workload theo Phase

| Role | Phase 1 (3 tuần) | Phase 2+ |
|------|-----------------|----------|
| SA | Nặng tuần 1 → nhẹ dần (review PR) | Review, không code |
| Frontend Dev | Trung bình — UI chat + admin cơ bản | Trung bình — dashboard analytics |
| Backend Dev | Trung bình — auth + user CRUD | Nhẹ — ít thay đổi |
| RAG Engineer | **Nặng** — ingestion (section chunking, caption) + retrieval (hybrid search, document_ids filter) | Tune chất lượng, query rewriting |
| AI/Agent Engineer | Trung bình — ACL pre-filter + rerank + prompt + stream + history | **Nặng** — LangGraph Agent, Redis, Teams Bot |
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
- `src/chat-service/.../openai_client.py`: AI/Agent Engineer owns — Azure OpenAI Chat + streaming
- `src/rag-service/.../bge_m3_client.py`: RAG Engineer owns — BGE-M3 Embedding client
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
| `openai_client.py` (chat-service) | AI/Agent Engineer owns | RAG Engineer không dùng, không đụng |
| `bge_m3_client.py` (rag-service) | RAG Engineer owns | AI/Agent Engineer không dùng, không đụng |
| `rag_service_client.py` (chat-service) | AI/Agent Engineer owns | Circuit Breaker state (fail_max, reset_timeout) cần đồng bộ với CloudWatch alarm threshold |
| `langfuse_client.py` (rag-service) | RAG Engineer owns | Bắt buộc fail silently — không throw exception ra ngoài, không ảnh hưởng request |
