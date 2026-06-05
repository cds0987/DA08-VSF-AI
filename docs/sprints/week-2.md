# Tuần 2 — Sprint 2 · Tuần 1/2 · Core happy-path

> **Sprint:** 2 / 3 · **Phase:** 1 · ⬅️ [Tuần 1](week-1.md) · ➡️ [Tuần 3](week-3.md)

## 🎯 Mục tiêu tuần
Nối **luồng chính chạy thông** (local): Admin upload tài liệu → ingestion index vào Qdrant → End User hỏi → bot trả lời **streaming + nguồn**. Mỗi service ráp logic nghiệp vụ vào scaffold tuần 1.

---

## 📋 Task theo role

| Role | Người | Task tuần này | Phụ thuộc |
|------|-------|---------------|-----------|
| **Backend Dev** | Vũ Quang Dũng | document-service: `upload_document_use_case` (validate → GCS → record `queued` → publish `doc.ingest` + `doc.access`); `nats_subscriber` (sub `doc.status` → update status + chunk_count); user CRUD admin (`list`, deactivate/reactivate). | NATS contract (T1) |
| **RAG Engineer** | Trần Thanh Nguyên | rag-worker: ingestion đầy đủ (Gemini OCR → Parent-Child chunking → embed 1536d → upsert Qdrant) + `retrieval.py` Top-5; mcp-service: tool `rag_search` (NATS rag.search → rerank BGE Top-3) + `hr_query`. | `doc.ingest` từ Backend Dev |
| **AI/Agent Engineer** | Phạm Quốc Dũng | query-service: `orchestration.py` (FunctionCallingAgent = MCP client → gọi `rag_search`/`hr_query`); SSE streaming token/done; `doc_access_subscriber` (sub `doc.access` → projection `document_access`); semantic cache Redis. | mcp-service tools (RAG Eng) |
| **Frontend Dev** | Đặng Hồ Hải | **frontend/chat**: chat SSE chạy thật (`StreamingText.vue` đọc token từ `POST /query`) + `useChat`. **frontend/admin**: `documents.vue` (`FileUpload` + bảng status). `useApi`/`useAuth` ở base layer. | SSE `/query` (AI Eng) |
| **DevOps** | Trần Hữu Gia Huy | `docker-compose up` full **12 containers** chạy local; dựng **Langfuse server** (:3100) + cấp API key qua Secret Manager. | Dockerfile các service (T1) |
| **SA** | Lê Hữu Hưng | Review PR; cập nhật `contracts.md`/`data-schema.md` nếu phát sinh đổi contract trong lúc ráp. | — |

---

## 🔗 Phụ thuộc / điểm chặn
- Chuỗi chính: **Backend Dev (`doc.ingest`) → RAG Eng (ingestion + tool) → AI Eng (orchestration) → FE (chat UI)**. Khuyến nghị RAG Eng ưu tiên `rag_search` sớm để AI Eng ráp MCP client.
- FE mock được phần chưa có backend → không bị chặn cứng.

## ✅ Definition of Done cuối tuần
- [ ] Admin upload file → ingestion tự chạy → status `indexed` + `chunk_count` (không cần duyệt).
- [ ] Hỏi câu hỏi → bot trả lời **streaming qua SSE** (`POST /query`) kèm nguồn (tên tài liệu + đoạn trích).
- [ ] **Semantic Cache** hoạt động — câu hỏi tương tự (cosine > 0.95) trả từ cache, không gọi OpenAI.
- [ ] **HR Q&A**: `hr_query` trả đúng dữ liệu mock theo `user_id`, không xem được của người khác.
- [ ] mcp-service chạy như MCP server (:8003) — Query Service là MCP client gọi `rag_search`/`hr_query`.

## 🔄 Ceremonies
- **Sprint 2 Planning** — đầu Tuần 2: chọn scope core Phase 1 cho 2 tuần (T2–T3).
- **Daily standup** — 15'/ngày.
- **Mốc nội bộ giữa sprint** (cuối T2): demo happy-path E2E local (chưa phải Sprint Review — review ở cuối T3).
