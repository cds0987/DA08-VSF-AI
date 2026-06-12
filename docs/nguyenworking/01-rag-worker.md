# RAG Worker — Tiến độ & việc cần làm

**Trạng thái:** 🟢 Production, verified E2E · **Mức hoàn thiện:** ~93% · **Cập nhật:** 2026-06-12
**Vai trò:** Subscriber NATS — ingest (OCR → chunk → caption → embed) → ghi Qdrant. Không HTTP serving nghiệp vụ, không DB nghiệp vụ.

> **Mới hoàn thành (2026-06-11, đã deploy develop):** Langfuse tracing cho luồng ingest + CI siết failure-path. Pipeline `develop` PASS full (validate→build→deploy production). Chi tiết: [rag-worker-langfuse.md](rag-worker-langfuse.md).

## Đã ổn định (căn bản XONG)
- ✅ **Pipeline ingest đầy đủ:** OCR → chunking → caption → embedding (`text-embedding-3-small`) → Qdrant collection `rag_chatbot__te3s__d1536`. Verified 68 chunk thật.
- ✅ **Clean Architecture 4 lớp** (`app/`: domain / application / infrastructure / interfaces) + `core_engine/` là RAG engine tự cuốn tay (đổi tên từ `haystack_interface`). `haystack/` chỉ clone tham khảo — **KHÔNG dùng runtime**.
- ✅ **Qdrant remote hardening:** centralize url/timeout qua `remote_client_kwargs()` (port 443 + timeout) → hết Cloud Run ConnectTimeout; hỗ trợ Qdrant sau nginx HTTP Basic Auth; recover sau mất collection; timeout config-driven (`config.yaml`).
- ✅ **CSV parser:** CSV → markdown, fixture trong validation corpus, parity whitelist với config.
- ✅ **Artifact store:** S3 + GCS, `artifact_uri` derive scheme theo endpoint (`gs://` cho GCS, không hardcode `s3://`) — commit `78833cf`.
- ✅ **Observability:** New Relic APM (APM/infra) + **Langfuse tracing luồng ingest** (debug nội dung AI + thấy stage crash) — best-effort, OFF mặc định, sampling, flush `to_thread`. Span phủ parse→chunk→caption→embed→qdrant-write; caption/embed là generation.
- ✅ **Test:** 36+ file test — coverage tốt nhất trong 3 service. Thêm **failure-matrix** (mỗi stage lỗi → span_error đúng stage, chạy trong `rag-test`) + job CI **`rag-langfuse`** (integration thật với Langfuse: doc tốt→SUCCESS, 2 doc lỗi→FAILED + span ERROR đúng stage). Đã verify trên CI + Python 3.13.

## Việc cần làm để vào Production thật

### 🔴 Cao
- [ ] **Fix structured log INFO không ra docker stdout** — root logger ở WARNING nên log INFO bị nuốt. ⚠️ Đã **giảm nhẹ** nhờ Langfuse tracing (debug được qua trace), nhưng vẫn nên fix để có log thường ngày rẻ; hạ ưu tiên xuống 🟡 sau khi có Langfuse.

### ✅ Đã xong
- [x] **Hardening Qdrant `_ensure` / recreate reliability** (gap `gap-qdrant-ensure-recreate` → RESOLVED): provider **tự tạo lại collection + retry** khi gặp 404 collection-missing (`_retry_on_missing_collection`, commit `409a38a`); lỗi này classify `transient` để job retry thay vì FAILED-cứng. 4 test phủ recreate + chống loop vô hạn. **Hết cảnh phải restart tay.**

### 🟢 Thấp (polish chất lượng — việc RAG còn lại DUY NHẤT)
- [ ] **Tuning chất lượng chunk/caption** (gap6–gap9) — cải thiện độ chính xác retrieval. Không chặn production.

## Lưu ý vận hành / bẫy đã biết
- Env phải trỏ **Qdrant nội bộ `qdrant:6333`**, KHÔNG trỏ cloud (cloud → 404 crash).
- Mọi remote Qdrant client phải qua `VectorStoreConfig.remote_client_kwargs()`, nếu không → Cloud Run ConnectTimeout.
- Thêm key top-level vào `config.yaml` → **phải thêm field vào `config_schema.py` cùng lượt**, nếu không CI parity fail `extra_forbidden`.
- GCS qua boto3 S3-interop: tắt checksum botocore, set default project cho user-HMAC, PUT cần billing active.
- Quy trình wipe Qdrant + re-ingest staging qua NATS `doc.ingest`; `rag_db` nội bộ tách `doc_db`.
- ✅ Xóa nguyên collection Qdrant giờ **KHÔNG còn làm ingest 404 vĩnh viễn** — provider tự tạo lại + retry (không cần restart tay nữa). Vẫn nên restart nếu nghi cache lệch khác.

## Liên kết
- Roadmap tổng: [00-roadmap.md](00-roadmap.md)
- Docs gap kỹ thuật: [../../src/rag-worker/docs/gap](../../src/rag-worker/docs/gap)
