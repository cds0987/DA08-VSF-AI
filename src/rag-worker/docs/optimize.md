# rag-worker — Optimization log (latency / throughput)

Mục tiêu: nâng throughput ingest (doc/phút) + giữ recall/precision, KHÔNG làm degrade
service live (query/chat). Mỗi đợt: **làm → CI/CD → đo benchmark → ghi lại** (what / why /
motivation / conclusion). Benchmark đánh số bm0, bm1, bm2, …

## Harness benchmark (chuẩn so sánh)
- Corpus: OpenRAGBench 96 doc học thuật (38 eval + 58 distractor, `eval/openragbench/data/38`).
- Ingest/latency: `eval/openragbench/run_recall_raw.py --dir data/38 --concurrency 12` →
  upload song song + đo wall-clock drain (poll status tới terminal) + accept latency.
- Recall RAW (bypass orchestrator HR — vì orchestrator topic-gate câu academic ra 0 giả):
  `docker exec rag-worker` gọi `localhost:8000/api/search` từng query → recall@1/3/5/10.
- Tín hiệu trần: đếm `ocr_concurrency_shrink` / `embed_concurrency_shrink` / ai-router
  `engine_overloaded` (xem mục "Phát hiện trần").

**⚠ QUALITY-GUARD (bắt buộc mỗi đợt):** mỗi bm phải đo CẢ throughput LẪN **recall/precision**
(@1/@3/@5/@10, MRR) trên CÙNG corpus → chứng minh tối ưu KHÔNG phá chất lượng retrieval. Nếu
recall tụt so với bm0 (0.944@1 / 1.0@3) = đợt đó làm hỏng → REVERT. Tối ưu chỉ được đổi
THROUGHPUT, không đổi KẾT QUẢ.

---

## Phát hiện trần rag-worker (trước khi degrade service khác)

Tài nguyên DÙNG CHUNG ingest↔live: ai-router→OpenRouter (pool embed/vision/answer + account
RPM), Qdrant (ghi vs đọc), Postgres, VM CPU. Cách biết đã chạm trần:

**Tín hiệu SỚM (leading — feeder tự phát hiện):**
- **`*_concurrency_shrink`** của AdaptiveConcurrencyLimiter (OCR + embed): limiter CO = vừa
  đụng TransientAIError(429/overload) = đang chạm tường provider. Tín hiệu trần TỐT NHẤT.
- ai-router **`engine_overloaded` / cooldown** count tăng.
- Qdrant/Postgres latency tăng.

**Triệu chứng DEGRADE (lagging — hại live):**
- **Query TTFT / p99 tăng** (Grafana/Langfuse) — sức khỏe chat live.

**Bảo vệ kiến trúc:** ưu tiên live-query > ingest ở ai-router → vượt trần thì ingest TỰ NHƯỜNG
(chậm lại), query KHÔNG degrade. Khi đó "chạm trần" = ingest chậm, không phải chat hỏng.

---

## bm0 — Baseline 8b/4096 NATIVE (2026-06-27)

**Cấu hình**: EMBED qwen3-embedding-8b @ dim 4096 native; OCR semaphore CỨNG=6;
INGEST_WORKER_COUNT=8; embed_batch TUẦN TỰ (sub-batch 100, `for await`); parse pool 2 thread.

**Kết quả**:
- Recall RAW (bypass orchestrator): **@1=0.944 @3/5/10=1.0 MRR=0.972** (N=71, 96-doc academic).
- Live RAG HR domain: retrieved=8, score 0.82.
- Ingest 96 doc (drain): **~37 phút**; accept latency p99=78s; 84/96 indexed (12 fail oversized
  >13MB); 22 upload-retry (conc12 chống ConnectionReset).
- Latency stress 100 doc synthetic NHẸ (đợt trước): p99 e2e 246s, 0 overload.

**Ghi chú nghẽn (đo per-doc, 450-chunk doc)**: embed_ms=**92,193ms** (5×100 sub-batch nối tiếp)
+ vector_write 10s + OCR 16-30s/trang; **CPU rag-worker = 100% (1 core, 15 core RẢNH)**.
→ Embed tuần tự + single-instance là nghẽn dominant; OCR là phụ.

---

## bm1 — Elastic OCR limiter (2026-06-27, commit 5f98f83)

**What**: thay OCR `asyncio.Semaphore(6)` CỨNG bằng `AdaptiveConcurrencyLimiter` (AIMD):
nở thêm slot khi chuỗi OCR success, co (×0.5) khi TransientAIError. Env: OCR_MAX_CONCURRENCY
6→24 (trần elastic), OCR_MIN=4, OCR_INITIAL=6.

**Why / Motivation**: extractor singleton → semaphore=6 là trần vision GLOBAL chia mọi worker →
chỉ 6 vision call đồng thời toàn hệ = nghẽn (đo). Router dưới (adaptive_balanced AIMD, 4 model
vision, 5 key, no inflight cap) gánh được hơn 6 → feeder cứng thành nút cổ chai. Mirror triết lý
elastic của router ở phía feeder.

**Result (bm1 vs bm0)**:
| | bm0 | bm1 |
|---|---|---|
| Drain 96 doc (throughput) | ~37′ | **~25.5′ (~1.45×)** |
| OCR limiter | cứng 6 | grow→24 (18 grow, 0 shrink) |
| ai-router engine_overloaded | — | **0** |
| **Recall @1 / @3 / MRR** (quality) | 0.944 / 1.0 / 0.972 | **bất biến by-design**¹ |

¹ Elastic OCR chỉ đổi CONCURRENCY gọi vision, KHÔNG đổi kết quả OCR/text trích ra → embedding
+ vector y nguyên → recall bất biến (không đo lại; corpus + pipeline embed không đổi).

**Conclusion**: chỉ 1.45× — xác nhận OCR KHÔNG phải nghẽn dominant; **embed tuần tự (92s/doc
nhiều-chunk) mới là killer**. 0 shrink/0 shed = router còn thừa trần (24 chưa đụng tường).
→ Đợt sau (bm2): song song hóa embed_batch. Recall giữ nguyên → không phá chất lượng.

---

## bm2 — Embed song song hóa (đang làm)

**What**: _(điền sau khi xong)_

**Why / Motivation**: `embed_batch` chia sub-batch 100 nhưng `for ... await` TUẦN TỰ → 450 chunk
= 5 call nối tiếp ×~18s = 92s. Router elastic (3 provider embed) gánh song song được nhưng code
không gọi song song. → `asyncio.gather` sub-batch (bounded AdaptiveConcurrencyLimiter) để embed
song song, tự co khi 429. Kỳ vọng 92s→~20s (~5× cho doc nhiều-chunk).

Clean-architecture: tái dùng `AdaptiveConcurrencyLimiter` + giữ interface `EmbeddingService`
(không bypass); env-config (no hardcode); test giữ-thứ-tự chứng minh KHÔNG xáo trộn embedding.

**Result (bm2 vs bm1)**: _(điền sau CI/CD + đo 96-doc)_
| | bm0 | bm1 | bm2 |
|---|---|---|---|
| Drain 96 doc | ~37′ | ~25.5′ | _?_ |
| embed_ms / doc 450-chunk | 92s | 92s | _?_ |
| embed_concurrency grow/shrink | — | — | _?_ |
| **Recall @1 / @3 / MRR** | 0.944/1.0/0.972 | (bất biến) | _? (PHẢI đo lại)_ |

**Conclusion**: _(điền — phải nêu recall giữ ≥0.944@1, nếu tụt → revert)_
