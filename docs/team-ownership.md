# Team Ownership — RAG Chatbot

## Phân chia công việc

| Role | Phụ trách chính | Folder sở hữu | Phụ thuộc vào |
|------|----------------|---------------|---------------|
| **SA** | Architecture, domain design, contracts, code review | `app/domain/` | — (viết trước) |
| **Frontend Dev** | Web UI chat, admin dashboard, streaming display | `frontend/` (Next.js) | API Schemas từ SA |
| **Backend Dev** | User Service: FastAPI setup, Auth JWT, user management, DB setup | `user-service/app/interfaces/api/`, `user-service/app/infrastructure/db/`, `user-service/app/application/use_cases/auth/` | Domain entities từ SA |
| **RAG Engineer** | Toàn bộ RAG pipeline: ingestion (parse → chunk → embed → store) + query retrieval (embed → search → rank → filter) | `rag-service/app/application/use_cases/ingestion/`, `rag-service/app/application/use_cases/query/retrieval.py`, `rag-service/app/infrastructure/vector/`, `rag-service/app/infrastructure/external/gemini_client.py` | VectorRepository, DocumentRepository interface |
| **AI/Agent Engineer** | Chat Service toàn bộ: LLM orchestration, prompt building, streaming response, conversation memory, API routing. Phase 2+: LangGraph Agent, Redis, tools | `chat-service/app/` | ConversationRepository interface, SearchResult từ RAG Engineer |
| **DevOps** | Docker, AWS ECS, CI/CD, Langfuse setup, monitoring | `infra/`, `docker-compose.yml`, `.github/workflows/` | Không phụ thuộc code logic |

---

## Ranh giới RAG Engineer ↔ AI/Agent Engineer

```
Câu hỏi user
     ↓
[AI/Agent Engineer]  Nhận câu hỏi + lấy lịch sử hội thoại từ DB
     ↓
[RAG Engineer]       Embed câu hỏi → tìm Qdrant → rerank → filter threshold
     ↓               Trả về: List[SearchResult]
[AI/Agent Engineer]  Nhận List[SearchResult] → build prompt → gọi OpenAI Chat → stream về FE
```

**Ranh giới dữ liệu:**
- RAG Engineer trả về `List[SearchResult]` (chunk content + score + metadata)
- AI/Agent Engineer nhận list đó, không cần biết bên trong Qdrant làm gì

---

## Thứ tự bắt đầu

```
Ngày 1-2 (SA làm trước):
  SA viết app/domain/entities/
  SA viết app/domain/repositories/ (interfaces)
  SA viết app/interfaces/api/schemas/ (API contracts)
  → Freeze → team bắt đầu

Ngày 3+ (song song):
  Frontend Dev      → mock API bằng schemas SA viết
  Backend Dev       → implement Auth + API routing + DB
  RAG Engineer      → implement Ingestion pipeline + Qdrant retrieval
  AI/Agent Engineer → implement orchestration + OpenAI streaming + memory
  DevOps            → setup Docker + AWS + CI/CD
```

---

## Workload theo Phase

| Role | Phase 1 (MVP – 2 tuần) | Phase 2+ |
|------|------------------------|----------|
| RAG Engineer | **Nặng** — ingestion pipeline (OCR, chunking, embedding) + retrieval | Tune chất lượng, reranking |
| AI/Agent Engineer | **Nhẹ** — prompt template + stream + lưu conversation history vào PostgreSQL | **Nặng** — LangGraph Agent, Redis memory, tools |

**Gợi ý:** AI/Agent Engineer Phase 1 có thể hỗ trợ thêm Backend Dev (auth endpoints) hoặc DevOps để cân bằng sprint.

---

## Quy tắc không đụng nhau

### 1. Chỉ sửa folder mình owns
Mỗi người chỉ tạo/sửa file trong folder của mình. Muốn sửa file người khác:
- Mở PR → tag người đó review
- Chờ approve mới merge

### 2. Không import chéo giữa use cases
```python
# BAD — orchestration không được gọi thẳng vào ingestion
from app.application.use_cases.ingestion import IngestDocumentUseCase  # ❌

# OK — cả 2 dùng chung domain entity
from app.domain.entities.document import Document  # ✅
```

### 3. Thay đổi contract → báo SA
Bất kỳ thay đổi nào trong `app/domain/` phải được SA approve trước.

### 4. `openai_client.py` — mỗi service có file riêng, độc lập
- `chat-service/.../openai_client.py`: AI/Agent Engineer owns — Chat Completion + streaming.
- `rag-service/.../openai_client.py`: RAG Engineer owns — Embedding only.

2 file hoàn toàn độc lập, không dùng chung. RAG Engineer không cần tag AI/Agent Engineer khi thêm embedding method.

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
- [ ] Không break code của người khác
- [ ] Đã test tính năng chính
- [ ] 1 teammate review + approve

---

## Touch Points — Nơi dễ conflict

| Touch point | Người liên quan | Cách xử lý |
|-------------|----------------|------------|
| Domain entities | SA + tất cả | SA freeze trước khi team code |
| API schemas | Backend Dev (User Service) + AI/Agent Engineer (Chat Service) + Frontend Dev | SA định nghĩa schema trong contracts.md, các bên code song song |
| `SearchResult` dataclass | SA define, RAG Engineer dùng, AI Engineer nhận | SA define trong `domain/`, không ai được tự sửa |
| DB models | Backend Dev + RAG + AI Engineer | Mỗi service owns `infrastructure/db/` của mình: Backend Dev → `user-service/`, AI/Agent Engineer → `chat-service/`, RAG Engineer → `rag-service/`. Không cross-service. |
| `openai_client.py` | AI/Agent Engineer owns, RAG Engineer dùng | AI Engineer owns, RAG Engineer mở issue nếu cần thêm method |
| `requirements.txt` | Tất cả | Thêm package → mở PR, không tự pip install rồi push |
