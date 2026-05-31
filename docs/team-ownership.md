# Team Ownership — RAG Chatbot

## Tổng quan phân công

| Role | Phụ trách chính | Service / Folder | Bắt đầu sau |
|------|----------------|-----------------|-------------|
| **SA** | Domain design, contracts, API schemas, code review | `app/domain/` (cả 3 services) | Ngay — làm đầu tiên |
| **Frontend Dev** | Web UI chat, admin dashboard, streaming | `src/frontend/` (Next.js) | Sau khi SA freeze schemas |
| **Backend Dev** | User Service: auth, JWT, user management, DB | `src/user-service/app/` | Sau khi SA freeze domain |
| **RAG Engineer** | Ingestion pipeline + Retrieval pipeline toàn bộ | `src/rag-service/app/` | Sau khi SA freeze domain |
| **AI/Agent Engineer** | Chat Service: LLM orchestration, streaming, memory | `src/chat-service/app/` | Sau khi SA freeze domain |
| **DevOps** | Docker, AWS, CI/CD, Nginx, monitoring | `infra/`, `docker-compose.yml` | Ngay — song song với SA |

---

## Chi tiết từng role

---

### SA (Solution Architect)

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

**Files SA tạo — rag-service:**
```
src/rag-service/app/domain/
├── entities/
│   └── document.py              ← Document, Chunk dataclass, DocumentStatus enum
└── repositories/
    ├── vector_repository.py     ← UserContext, SearchResult dataclass, VectorRepository ABC
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

### Frontend Dev

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

### Backend Dev

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

### RAG Engineer

**Phụ trách rag-service toàn bộ. Bắt đầu Ngày 3. Workload nặng nhất Phase 1.**

**Files RAG Engineer tạo:**
```
src/rag-service/app/
├── application/
│   └── use_cases/
│       ├── ingestion/
│       │   └── ingest_document_use_case.py   ← Nhận document_id → parse → chunk → embed → upsert Qdrant
│       └── query/
│           └── retrieval.py                  ← Nhận query + UserContext → embed → hybrid search → rerank → filter → SearchResult[]
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                         ← SQLAlchemy model cho bảng documents, audit_logs
│   │   └── postgres_document_repository.py   ← Implement DocumentRepository
│   ├── vector/
│   │   └── qdrant_vector_repository.py       ← Implement VectorRepository (hybrid_search, upsert, delete)
│   └── external/
│       ├── bge_m3_client.py                  ← Implement EmbeddingService — gọi BGE-M3 HTTP API
│       ├── bge_reranker_client.py            ← Gọi BGE-Reranker HTTP API, trả về rerank scores
│       ├── azure_doc_intel_client.py         ← Gọi Azure Document Intelligence — OCR PDF scan
│       └── langfuse_client.py                ← Ghi trace ingestion + retrieval vào Langfuse
│
└── interfaces/
    └── api/
        ├── main.py
        ├── dependencies.py                   ← get_retrieval_use_case(), get_ingest_use_case()
        └── routers/
            ├── ingest.py                     ← POST /ingest (nhận từ Chat Service)
            └── search.py                     ← POST /search (nhận từ Chat Service)
```

**Key logic cần implement:**

*Ingestion pipeline (`ingest_document_use_case.py`):*
1. Tải file từ S3 → detect loại: PDF scan / PDF text / DOCX / TXT / XLSX / ...
2. OCR (nếu PDF scan): gọi `azure_doc_intel_client.py`
3. Parse text: PyMuPDF (PDF text layer), python-docx (DOCX), openpyxl (XLSX)
4. Parent-Child Chunking: Child 128–256 token, Parent 512–1024 token, overlap 20–30 token
5. Embed từng child chunk: gọi `bge_m3_client.embed_batch()`
6. Upsert Qdrant: `vector_repo.upsert()` với payload gồm `classification`, `allowed_departments`, `allowed_user_ids`
7. Update `document_repo.update_status()` → COMPLETED

*Retrieval pipeline (`retrieval.py`):*
1. Embed query: gọi `embedding_svc.embed(query_text)`
2. Hybrid search: `vector_repo.hybrid_search(vector, query_text, user_context, top_k=20)`
   - Qdrant filter tự động theo `user_context.user_department` / `user_context.user_id`
3. Rerank Top-20 → Top-3: gọi `bge_reranker_client.rerank(query, chunks)`
4. Score threshold: nếu `max(rerank_score) < 0.7` → trả về rỗng (bot sẽ nói "không tìm thấy")
5. Trả về `List[SearchResult]`

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service hoặc chat-service.

---

### AI/Agent Engineer

**Phụ trách chat-service toàn bộ. Bắt đầu Ngày 3. Phase 1 nhẹ, Phase 2 nặng.**

**Files AI/Agent Engineer tạo:**
```
src/chat-service/app/
├── application/
│   └── use_cases/
│       └── query/
│           └── orchestration.py              ← Nhận câu hỏi → lấy context → gọi RAG → build prompt → stream Azure OpenAI
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py                         ← SQLAlchemy model cho conversations, messages
│   │   └── postgres_conversation_repo.py     ← Implement ConversationRepository
│   ├── external/
│   │   ├── openai_client.py                  ← Azure OpenAI Chat Completion + SSE streaming
│   │   └── rag_service_client.py             ← HTTP client gọi POST /search và POST /ingest của RAG Service
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
2. Gọi RAG: `rag_client.search(query, user_context)` → `List[SearchResult]`
3. Nếu kết quả rỗng (score thấp) → stream câu trả lời "Không tìm thấy thông tin liên quan"
4. Build prompt: system prompt + summary + recent messages + parent_text của Top-3 chunks + câu hỏi user
5. Gọi Azure OpenAI streaming: yield từng token → SSE event `data: {"token": "..."}`
6. Lưu message: `conv_repo.save_message(user_id, "user", question)` + `save_message(user_id, "assistant", full_answer)`
7. Summary buffer: nếu conversation > 10 turns → gọi LLM compress → `conv_repo.update_summary()`

*Document flow (`documents.py` router):*
- Upload file → lưu S3 → tạo record DB (status=pending/queued) → gọi `rag_client.ingest()` nếu Admin

**Không được đụng:** `app/domain/` (SA owns), bất kỳ file nào trong user-service hoặc rag-service.

---

### DevOps

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
[AI/Agent Engineer]   rag_service_client.py: gọi POST /search
     ↓  HTTP
[RAG Engineer]        retrieval.py: embed → hybrid search → rerank → filter
     ↓
[AI/Agent Engineer]   nhận List[SearchResult] → build prompt → gọi Azure OpenAI → stream về FE
```

**Ranh giới dữ liệu:**
- RAG Engineer trả về `List[SearchResult]` (chunk content + score + metadata)
- AI/Agent Engineer nhận list đó, không biết Qdrant hay BGE-M3 là gì

---

## Workload theo Phase

| Role | Phase 1 (3 tuần) | Phase 2+ |
|------|-----------------|----------|
| SA | Nặng tuần 1 → nhẹ dần (review PR) | Review, không code |
| Frontend Dev | Trung bình — UI chat + admin cơ bản | Trung bình — dashboard analytics |
| Backend Dev | Trung bình — auth + user CRUD | Nhẹ — ít thay đổi |
| RAG Engineer | **Nặng nhất** — toàn bộ ingestion + retrieval | Tune chất lượng, query rewriting |
| AI/Agent Engineer | Nhẹ — prompt + stream + lưu history | **Nặng** — LangGraph Agent, Redis, Teams Bot |
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
  feat/minh/rag-ingestion
  feat/hung/auth-jwt
  feat/linh/llm-orchestration
  feat/nam/docker-setup
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
| `SearchResult` dataclass | SA define, RAG Engineer implement, AI/Agent Engineer consume | Sửa → báo SA → SA update contracts.md → tất cả update |
| `UserContext` dataclass | SA define, AI/Agent Engineer truyền vào, RAG Engineer nhận | Như trên |
| API schemas (Pydantic) | SA define, Backend Dev + AI/Agent Engineer implement, Frontend Dev consume | Sửa → báo SA |
| `requirements.txt` | Tất cả | Thêm package → mở PR, không tự pip install rồi push |
| `docker-compose.yml` | DevOps owns | Thêm env var mới → báo DevOps |
| `openai_client.py` (chat-service) | AI/Agent Engineer owns | RAG Engineer không dùng, không đụng |
| `bge_m3_client.py` (rag-service) | RAG Engineer owns | AI/Agent Engineer không dùng, không đụng |
