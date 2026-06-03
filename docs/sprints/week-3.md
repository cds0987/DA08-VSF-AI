# Tuần 3 — Sprint 2 · Tuần 2/2 · Hoàn thiện Phase 1 + Deploy + Eval

> **Sprint:** 2 / 3 · **Phase:** 1 → 1.5 · ⬅️ [Tuần 2](week-2.md) · ➡️ [Tuần 4](week-4.md)

## 🎯 Mục tiêu tuần
Đóng nốt các tính năng Phase 1 (notification, analytics, document viewer, guardrails), **deploy lên AWS chạy thật**, rồi **cuối tuần chạy Phase 1.5 Evaluation** (RAGAS + load test) làm checkpoint quyết định đi tiếp Phase 2.

---

## 📋 Task theo role

| Role | Người | Task tuần này | Phụ thuộc |
|------|-------|---------------|-----------|
| **Frontend Dev** | Đặng Hồ Hải | **Notification Center** (badge/dropdown/mark-read), **Analytics Dashboard** (`analytics.vue` + charts), **Document Viewer** (PDF.js: nhảy trang + highlight citation), **Conversation history UI**. | endpoint từ AI Eng + Backend Dev |
| **AI/Agent Engineer** | Phạm Quốc Dũng | `notify_subscriber` (sub `notify.doc_new` → SSE `/notifications`) + endpoint `/notifications/history`,`/unread-count`,`/{id}/read`; `GET /admin/metrics`; **Guardrails** (prompt injection, off-topic, PII redact); `POST /feedback`. | projection ACL (T2) |
| **Backend Dev** | Vũ Quang Dũng | `GET /documents/{id}/file` (presigned S3 URL, check ACL); delete flow + publish `doc.access{deleted}`; ghi `audit_logs` (document events); publish `notify.doc_new` khi indexed. | — |
| **RAG Engineer** | Trần Thanh Nguyên | Hoàn thiện failure handling (Langfuse fail-silently, OpenAI/Gemini fail → status `failed`); tune chunk size/overlap; chuẩn bị **bộ data eval** cùng AI Eng. | — |
| **DevOps** | Trần Hữu Gia Huy | Deploy AWS EC2 (docker compose), **HTTPS Nginx + Let's Encrypt**, **CloudWatch alarm**, S3/RDS production, Qdrant persistent volume, `smoke-test.sh` (10 câu). | image các service |
| **SA** | Lê Hữu Hưng | Review PR cuối Phase 1; xác nhận DoD đầy đủ trước khi tuyên bố production-ready. | — |

### 🧪 Cuối tuần — Phase 1.5 Evaluation (checkpoint)
| Nhóm | Ai | Nội dung |
|------|-----|----------|
| **RAG Quality (RAGAS)** | AI Eng + RAG Eng | Bộ 20–30 câu hỏi + đáp án mẫu; đo Faithfulness ≥0.90, Answer Relevance ≥0.85, Context Precision/Recall ≥0.80, Answer Correctness ≥0.80 |
| **Performance** | DevOps | Load test Locust/k6: first-token < 2s, P95 < 8s, ≥50 concurrent users |
| **Safety & Reliability** | AI Eng | Hallucination < 5%, graceful rejection ≥95%, **Access control accuracy = 100%** |

---

## 🔗 Phụ thuộc / điểm chặn
- FE cần `GET /documents/{id}/file` (Backend Dev) cho Document Viewer + các endpoint notification/metrics (AI Eng) → coordinate sớm đầu tuần.
- Deploy AWS (DevOps) cần image ổn định → các service nên freeze tính năng giữa tuần để DevOps deploy + smoke test.
- Eval cuối tuần cần data thật đã index trên môi trường deploy.

## ✅ Definition of Done cuối tuần
- [ ] **Toàn bộ DoD Phase 1** đóng (auth + SSO, upload/ingestion, Q&A streaming + nguồn, classification enforce, Notification Center, Analytics Dashboard, Document Viewer, conversation history, guardrails, feedback).
- [ ] Stack chạy ổn định trên **AWS** (11 containers + RDS), HTTPS hoạt động, smoke test 10 câu pass.
- [ ] **RAGAS** có đủ số liệu 5 chỉ số + load test có số liệu → **đạt ngưỡng**.
- [ ] Quyết định rõ: tiếp Phase 2 hay tune thêm (theo nhánh quyết định ở [roadmap.md](../roadmap.md)).

## 🔄 Ceremonies
- **Daily standup** — 15'/ngày.
- **Sprint 2 Review** — cuối Tuần 3: demo **Phase 1 hoàn chỉnh trên AWS** + trình bày báo cáo Evaluation.
- **Retrospective** — chốt bài học trước khi sang Phase 2.
