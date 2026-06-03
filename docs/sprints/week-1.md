# Tuần 1 — Sprint 1 (1 tuần) · Nền tảng

> **Sprint:** 1 / 3 · **Phase:** 1 (nền) · ⬅️ [README](README.md) · ➡️ [Tuần 2](week-2.md)

## 🎯 Mục tiêu tuần
SA **freeze** domain + contracts + API schemas để cả team có "bản hợp đồng" code theo. DevOps dựng hạ tầng cơ bản. Cuối tuần mọi service đã **scaffold chạy được** (chưa có logic nghiệp vụ).

> Cách làm: **Ngày 1–2** chỉ SA + DevOps chạy (team chờ). **Ngày 3+** cả team checkout bản freeze của SA và bắt đầu scaffold song song.

---

## 📋 Task theo role

| Role | Người | Task tuần này | Phụ thuộc |
|------|-------|---------------|-----------|
| **SA** | Lê Hữu Hưng | (Ngày 1–2) Viết domain entities + repositories ABC cho cả **5 service** + Pydantic schemas (`query.py`, `auth.py`, `user.py`, `document.py`, `tool_io.py`…) → commit `develop` → **tag team**. (Ngày 3+) review PR. | — (làm đầu tiên) |
| **DevOps** | Trần Hữu Gia Huy | (Ngày 1–2, song song SA) Dockerfile mỗi service + `docker-compose.yml` skeleton + CI pipeline skeleton. Provision **RDS** (5 db: user/doc/query/mcp/langfuse), **S3**, container **NATS/Qdrant/Redis**. | — |
| **Backend Dev** | Vũ Quang Dũng | (Ngày 3) **Chốt NATS subject contract** `infra/nats/subjects.md` (doc.ingest/doc.status/doc.access/notify.doc_new) — ưu tiên làm sớm vì RAG/AI Eng chờ. user-service: login JWT HS256, `verify_token`, `GET /auth/me`, `models.py` (users/refresh_tokens/audit_logs). | Chờ SA freeze |
| **RAG Engineer** | Trần Thanh Nguyên | (Ngày 3) Scaffold rag-worker (`main.py` NATS subscriber + subscribe `doc.ingest`); khung `openai_embedding_client.py`, `qdrant_vector_repository.py`. Scaffold mcp-service (`mcp_server.py`). | Chờ SA freeze + NATS contract |
| **AI/Agent Engineer** | Phạm Quốc Dũng | (Ngày 3) Scaffold query-service; khung `mcp_client.py`; SSE `POST /query` (khung, chưa gọi LLM); `conversation_repo` + `models.py`. | Chờ SA freeze + NATS contract |
| **Frontend Dev** | Đặng Hồ Hải | (Ngày 3) Nuxt 4 setup (`nuxt.config.ts`, `app/app.vue`, `middleware/auth.ts`); `pages/login.vue`, `pages/chat.vue` (shell) — mock API bằng schemas SA, không chờ backend. | Chờ SA freeze (schemas) |

---

## 🔗 Phụ thuộc / điểm chặn
- **Cả team chờ SA freeze** (Ngày 1–2) mới bắt đầu code → SA là đường găng tuần này.
- **NATS subject contract** (Backend Dev) phải chốt sớm Ngày 3 → RAG Eng + AI Eng cần nó để code NATS client.
- DevOps cần xong NATS/Qdrant/Redis container để team test scaffold local.

## ✅ Definition of Done cuối tuần
- [ ] SA commit domain + repositories ABC + schemas lên `develop`, team đã checkout.
- [ ] NATS subject contract (`infra/nats/subjects.md`) đã chốt.
- [ ] Đăng nhập email/password (JWT) chạy được local (user-service).
- [ ] Mọi service `uvicorn`/`nuxi dev` khởi động được (scaffold, chưa cần logic đầy đủ).
- [ ] `docker-compose up` skeleton chạy được (DevOps), kết nối NATS/Qdrant/Redis OK.

## 🔄 Ceremonies
- **Sprint 1 Planning** — đầu Tuần 1: chốt scope nền tảng (freeze + scaffold).
- **Daily standup** — 15'/ngày.
- **Sprint 1 Review + Retro** — cuối Tuần 1: nghiệm thu "SA freeze xong, NATS contract chốt, scaffold lên"; rút kinh nghiệm trước khi vào Sprint 2.
