# E2E — 1 stack mô phỏng production

Thư mục này chứa **bài test e2e DUY NHẤT** thay cho mớ job tích hợp rời rạc cũ
(`rag-test`, `search-semantic`, `e2e-cloud`, `hr-integration`, `langfuse-test`, …).

## Triết lý: 2 tầng test

| Tầng | Chạy gì | Bắt lỗi gì |
|------|---------|-----------|
| **Phase 1 — per-service** (CI job `unit`) | `pytest` từng service, infra off + contract parity | behavior + contract sai của **1 service** |
| **Phase 2 — e2e** (CI job `e2e`) | `docker-compose.e2e.yml` + `run_e2e.py` | lỗi **tích hợp / orchestration** (vd nats-bootstrap), thứ per-service test không thấy |

E2e **giữ nguyên chuỗi `depends_on` của prod** (`docker-compose.yml`):
`nats-bootstrap` (provision DOC_EVENTS, verify-only) → `*-migrate` → service. Nên
bootstrap/migrate hỏng = `compose up` fail = test fail — đúng lớp lỗi đã làm prod sập.

## Khác prod

- Build từ source (không pull Docker Hub).
- Postgres / NATS / Redis = container; **GCS + Qdrant = CLOUD THẬT**.
- Thêm seed one-shot (`seed-user`, `seed-doc`) vì prod seed Cloud SQL tay 1 lần.
- Langfuse **v2** self-host (khớp prod) + **bật trace** query-service lẫn rag-worker.

## Chạy local

```bash
# .env (gitignored) ở repo root cần:
#   OPENAI_API_KEY=...
#   QDRANT_URL=https://...:6333
#   QDRANT_API_KEY=...
#   GCS_HMAC_KEY=...        GCS_HMAC_SECRET=...
#   GCS_BUCKET=vsf-rag-chatbot-docs-dev   (tùy chọn)

docker compose -f docker-compose.e2e.yml up -d --build
python infra/e2e/run_e2e.py            # 1 flow xuyên suốt; exit !=0 = fail
docker compose -f docker-compose.e2e.yml down -v
```

⚠ E2e dùng Qdrant Cloud + GCS THẬT → `run_e2e.py` tự dọn object + collection đã tạo
ở bước cleanup. Chạy `--no-cleanup` để giữ lại debug.

## Files

- `init-db.sql` — tạo các database (user/doc/query/rag/hr).
- `seed_user.py` — create_all + seed admin cho user-service (chạy trong image user-service).
- `seed_doc.sql` — schema `doc_svc` cho document-service.
- `run_e2e.py` — orchestrator 1 flow: login → upload → ingest → trace → query RAG/HR → trace → cleanup.
