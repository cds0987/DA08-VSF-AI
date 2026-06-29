---
service: rag-worker
path: src/rag-worker
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/rag-worker/app/interfaces/api/main.py
  - src/rag-worker/app/interfaces/api/runtime.py
  - src/rag-worker/app/interfaces/api/routers/search.py
  - src/rag-worker/app/interfaces/api/routers/ingest.py
  - src/rag-worker/app/interfaces/nats/ingest_consumer.py
  - src/rag-worker/app/application/use_cases/ingestion/ingest_document_use_case.py
  - src/rag-worker/app/application/use_cases/search/search_use_case.py
  - src/rag-worker/core_engine/embedding/service.py
  - src/rag-worker/core_engine/concurrency/adaptive_limiter.py
  - src/rag-worker/core_engine/ocr/extractor.py
  - src/rag-worker/embeddings.yaml
  - src/rag-worker/config.yaml
  - deploy/env/common.env
  - docker-compose.yml
---
# RAG Worker

## Trách nhiệm
Service GHI + ĐỌC vector cho RAG. Hai vai, cùng image, tách qua `INGEST_ENABLED`:
- **Ingest**: nhận sự kiện `doc.ingest` (NATS) → enqueue job-queue trong Postgres → worker parse/OCR/chunk/embed/upsert vào Qdrant → publish `doc.status`.
- **Search**: phục vụ RPC nội bộ `POST /api/search` (mcp-service gọi) — embed query + retrieve ứng viên (CHƯA rerank). Query-side retrieval đã chuyển TỪ mcp VỀ đây để embedder/vectorstore đối xứng với ingest (cùng provider/model/dim/sparse).
- Xóa vector qua `doc.access{deleted:true}` (document-service KHÔNG gửi `doc.delete`).

## API / giao diện
HTTP (`app/interfaces/api/main.py`, prefix `/api`):
- `POST /api/search` → ứng viên retrieval (chunk_id, document_id, child/parent_text, caption, heading_path, score, page_number, source/markdown_gcs_uri). ACL = `document_ids` rỗng/None → kết quả RỖNG.
- `GET /api/ingest/{document_id}`, `GET /api/ingest`, `GET /api/ingest/jobs/{job_id}` → đọc trạng thái doc/job.
- `DELETE /api/ingest/{document_id}` (yêu cầu delete API key).
- Health/ops: `GET /livez`, `/readyz`, `/health`, `/healthz`, `/metrics` (Prometheus text).
- **KHÔNG còn `POST /ingest`** — tạo ingest chỉ qua NATS.
- Middleware edge-guard: rate-limit per-IP (default 60/60s) MIỄN cho `/api/search` + `/api/ingest` (RPC nội bộ); body-size guard (413) cho mọi path.

NATS JetStream (`app/interfaces/nats/`, stream mặc định `DOC_EVENTS`):
- Subscribe `doc.ingest` (durable `rag-worker-ingest`) → enqueue. Payload hỏng → `term` (poison); lỗi tạm → `nak`.
- Subscribe `doc.access` (durable `rag-worker-access`) → nếu `deleted=true` xóa vector; `nak(delay=5)` chống NAK-storm.
- Publish `doc.status` (`indexed`/`failed` + chunk_count) sau khi worker xử lý job.

## Pipeline ingest
`enqueue` (dedup redelivery qua `find_active_job`; skip doc đã COMPLETED trừ `force`) → `process_next_job` claim job (claim-lease DB + heartbeat `_maintain_claim_lease`, stale reaper) → các bước trong `core_engine` engine:
1. **parse** (`_prepare_markdown`): parser local hoặc s3 tải `source_uri` (s3://|gs://) → markdown; ghi artifact markdown (GCS/local).
2. **OCR/vision**: qua AI gateway (`ProviderImageTextExtractor`); giới hạn `MAX_OCR_PAGES`, concurrency AIMD `AdaptiveConcurrencyLimiter` (`OCR_MAX_CONCURRENCY` default 4, min 2).
3. **chunk**: `heading_sections` (parent ~220 từ, child ~90, overlap 15).
4. **caption** (tùy `CAPTION_ENABLED`) → text embed = caption+raw theo `EMBED_TARGET` (default `caption_raw`).
5. **embed**: `ProviderEmbeddingService.embed_batch` chia sub-batch (`EMBED_BATCH_SIZE` default 100), gather SONG SONG qua AIMD limiter (`EMBED_BATCH_MAX_CONCURRENCY` default 24; prod ingest-worker đặt 16), tự co khi 429.
6. **index**: upsert Qdrant (`UPSERT_BATCH_SIZE` default 256), prune stale chunk.
Timeout job `INGEST_JOB_TIMEOUT_SECONDS` (600); 0 chunk → `EmptyIngestResultError` (transient → store-reconciler retry, cap 3). Lỗi phân loại transient/permanent (`classify_ingest_error`): mạng/timeout/Qdrant-missing/empty = transient.

## Search / retrieval
`SearchUseCase` (`read_targets`): embed query → `vectors.search(dense [+sparse hybrid], top_k, document_ids)` → map `SearchHit`→candidate. Caller (mcp) rerank.
**Multi-collection shard** (`embeddings.yaml`, mode=`shard`): mỗi doc embed vào CHỈ 1 trong N collection round-robin theo `hash(document_id)`; collection = `{VECTOR_COLLECTION}__{model_tag}__d{dim}`. READ phải query MỌI collection + merge/dedup theo chunk_id (giữ score cao). Pool hiện 4 model: qwen3-embedding-8b (primary), bge-m3, openai text-embedding-3-small, pplx-embed-v1. Bật bằng `MULTI_EMBED_ENABLED=1`; shard-read tắt bằng `MULTI_EMBED_SHARD_READ=0`.
**Prod hiện chạy single `qwen/qwen3-embedding-8b` @ dim 4096, `MULTI_EMBED_ENABLED=0`** (docker-compose.yml rag-worker/rag-ingest-worker; common.env). Multi-embed là augment, chưa bật.

## Config / ENV (verify trong code/compose)
- Embed: `EMBED_MODEL` (prod qwen/qwen3-embedding-8b), `EMBED_DIMENSION` (4096), `EMBED_BASE_URL` (ai-router `http://ai-router:8010/v1`), `EMBED_BATCH_SIZE`, `EMBED_BATCH_{MAX,MIN,INITIAL}_CONCURRENCY`, `EMBED_TARGET`.
- Multi-embed: `MULTI_EMBED_ENABLED` (default 0), `MULTI_EMBED_MODE`, `MULTI_EMBED_SHARD_READ`.
- Vector: `VECTOR_DB_PROVIDER` (qdrant), `VECTOR_DB_URL`, `VECTOR_DB_API_KEY`, `VECTOR_COLLECTION` (rag_chatbot), `VECTOR_HYBRID`.
- OCR/parse: `PARSER_IMPL` (local|s3), `PARSER_MAX_WORKERS`, `MAX_OCR_PAGES`, `PDF_OCR_SCALE`, `OCR_{MAX,MIN,INITIAL}_CONCURRENCY`, `S3_SOURCE_BUCKET`, `S3_*`/`R2_*`.
- Worker: `INGEST_ENABLED` (search-only=false; ingest-worker=true), `INGEST_WORKER_COUNT`, `INGEST_JOB_TIMEOUT_SECONDS`, `CLAIM_*` (lease), `UPSERT_BATCH_SIZE`, `MAX_CHUNKS_PER_DOC`.
- Hạ tầng: `DATABASE_URL` (postgresql+psycopg://, bắt buộc ở prod), `NATS_URL`, `NATS_STREAM` (DOC_EVENTS), `NATS_*_SUBJECT`/`*_DURABLE`, `APP_ENV` (prod fail-closed nếu provider offline / vector in-process / metadata không Postgres).
- Edge: `RATE_LIMIT_REQUESTS/WINDOW`, `MAX_REQUEST_BODY_BYTES`.

## Phụ thuộc
- **Qdrant** (vector store) — `core_engine/vectorstore/providers/qdrant`.
- **AI Router** (embed + caption + OCR/vision gateway) — base_url `ai-router:8010/v1`, 1 token nội bộ.
- **Postgres** — metadata doc + job-queue + job-log (alembic `migrations/`).
- **NATS JetStream** — `doc.ingest`/`doc.status`/`doc.access`.
- **GCS/S3** (boto3, qua endpoint S3-interop) — tải source + ghi artifact markdown.

## Code map
- API app + edge-guard: [main.py](src/rag-worker/app/interfaces/api/main.py)
- Bootstrap/lifespan/worker loop/NATS wiring: [runtime.py](src/rag-worker/app/interfaces/api/runtime.py)
- Search router/use-case: [search.py](src/rag-worker/app/interfaces/api/routers/search.py), [search_use_case.py](src/rag-worker/app/application/use_cases/search/search_use_case.py)
- Ingest router (đọc/delete): [ingest.py](src/rag-worker/app/interfaces/api/routers/ingest.py)
- NATS consumer/publisher: [ingest_consumer.py](src/rag-worker/app/interfaces/nats/ingest_consumer.py)
- Ingest use-case (job lifecycle): [ingest_document_use_case.py](src/rag-worker/app/application/use_cases/ingestion/ingest_document_use_case.py)
- Embed service (AIMD batch): [service.py](src/rag-worker/core_engine/embedding/service.py)
- AIMD limiter: [adaptive_limiter.py](src/rag-worker/core_engine/concurrency/adaptive_limiter.py)
- Multi-collection: [embeddings.yaml](src/rag-worker/embeddings.yaml), [multi_embed.py](src/rag-worker/core_engine/multi_embed.py)
- Pipeline config: [config.yaml](src/rag-worker/config.yaml)
