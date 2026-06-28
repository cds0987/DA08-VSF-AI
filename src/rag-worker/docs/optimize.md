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

**Result (bm2 vs bm1)** — commit 9f6975a:
| | bm0 | bm1 | bm2 |
|---|---|---|---|
| Drain 96 doc (throughput) | ~37′ | ~25.5′ | **~24.5′** |
| Tăng so bm1 | — | — | **~1.04× (≈ bằng)** |
| **embed_ms / doc 450-575chunk** | 92s | 92s | **15-48s (~2-3×)** |
| embed_concurrency grow/shrink | — | — | grow→24, **0 shrink** |
| ai-router engine_overloaded | — | 0 | **0** |
| indexed / fail | 84/12 | 84/12 | **80/16** (12 oversized + **4 ResponseHandlingException MỚI**) |
| **Recall @1 / @3 / MRR** (quality) | 0.944/1.0/0.972 | (bất biến) | **0.957/1.0/0.978 ✓ GIỮ** |

**Conclusion**:
- ✅ **Per-doc embed ~2-3×** (92s→15-48s) — A1 hoạt động đúng; gather sub-batch + limiter nở→24, 0 shrink/0 shed = router thừa trần.
- ✅ **Recall GIỮ** (0.957@1 ≥ 0.944, @3=1.0) — order-preserve đúng, KHÔNG xáo trộn embedding.
- ❌ **System throughput KHÔNG tăng** (~24.5′ ≈ bm1): nghẽn đã dời sang **CPU 1-core 100%** (rag-worker
  single event-loop: decode base64 embedding + rasterize serial trên 1 core). Embed nhanh hơn nhưng
  CPU không kịp xử lý kết quả → throughput trần ~4 doc/phút.
- ⚠️ **+4 fail transient** (ResponseHandlingException): embed conc=24 stress thêm response-handling
  (httpx/qdrant). Cân nhắc hạ EMBED_BATCH_MAX_CONCURRENCY 24→16 hoặc điều tra; recall không ảnh hưởng
  (fail transient, re-ingest phục hồi).

**Giá trị A1**: thắng per-doc (1 doc upload index nhanh ~2-3×, giảm tail-latency) + recall-safe → GIỮ.
Nhưng **muốn vượt ~4 doc/phút phải A2 (scale rag-worker ngang nhiều process/replica)** — CPU 1-core
là trần thật, không phải embed/OCR concurrency.

→ **bm3 (đề xuất tiếp)**: A2 scale rag-worker 1→N replica (claim-lease DB-safe) — dùng 15 core rảnh.

---

## bm3 — A2: tách + scale rag-ingest-worker (đã làm)

**What**: tách service `rag-ingest-worker` (INGEST_ENABLED=true) khỏi `rag-worker` search; scale
`deploy.replicas` + `INGEST_WORKER_COUNT` (claim-lease DB-safe, nhiều process/core). Search giữ
riêng (INGEST_ENABLED=false) → ingest KHÔNG bóp chat-search-latency.

**Why**: bm2 chứng minh trần là **CPU 1-core** (single event-loop decode/rasterize serial), không
phải embed/OCR concurrency. Vượt = scale ngang nhiều process → dùng 15 core rảnh.

**Result**: throughput vượt trần ~4 doc/phút của bm2. Đo full corpus HR-VN (120 doc nhỏ):
**45 doc/phút, 0 fail**. PDF academic NẶNG (openragbench, 449-1025 chunk/file, vision-OCR):
**8.5 pdf/phút** (≈ baseline cũ 7-9) — bottleneck giờ là **parse + vision-OCR PDF khổng lồ**, không
phải số process. Combined-test (chat + ingest đồng thời): chat 0-err coexist, ai-router gỡ maxout.

**Conclusion**: A2 thắng throughput cho corpus thường; PDF siêu-nặng thì OCR-vision là trần kế tiếp
(`OCR_MAX_CONCURRENCY=4`/worker — nâng nếu cần, ai-router AIMD còn headroom: no_capacity ocr=0).

---

## bm4 — Multi-collection (shard N embed model) — "phá BẪY embedding"

**What**: mỗi embed model → 1 Qdrant collection riêng (qwen8b@4096 · bge-m3@1024 · te3s@1536 ·
pplx@1024). `embeddings.yaml mode: shard` → mỗi doc embed vào CHỈ 1 collection (hash document_id %
N) → corpus chia đều ~N/N; READ query N collection song song + merge + rerank. e5large GỠ (ctx 512
quá nhỏ = mắt xích yếu). `index_id` fingerprint = collection+model+dim.

**Why / Motivation**: single qwen8b = 1 vector-space PIN cố định (**BẪY embedding**, PLAN §4b) — phụ
thuộc 1 model/provider; kém resilience + không đa dạng ngữ nghĩa. Kỳ vọng (a) embed throughput cao
(shard = 1 embed/doc thay vì replicate N), (b) đa dạng model bắt được nhiều ngữ nghĩa hơn.

---

## bm5 — 🚨 BUG NGẦM: router ÉP mọi embed về qwen8b (multi-collection GIẢ)

**Phát hiện**: multi-collection chạy "thành công" 0 lỗi, NHƯNG forensic **cosine** lộ sự thật:
`cos(stored e5large, qwen8b-tươi) = 0.96` (model THẬT phải ≈ 0); gửi `model=e5large` vs `model=qwen8b`
→ kết quả Y HỆT. → mọi collection phụ lưu **vector qwen8b cắt chiều**, KHÔNG phải model riêng.

**Gốc**: `router.embeddings()` **hardcode `resolve('embed')`** → bỏ qua `body['model']` → MỌI request
embed phục vụ qwen8b. routing.yaml ĐÃ khai capability `embed_e5large/bgem3/...` + rag-worker ĐÃ gửi
model thật, nhưng router **chưa bao giờ route tới** = migration single→multi-collection **DỞ DANG**
(foundation còn giả định 1-model). Cùng gốc bệnh với "primary/anchor thừa thãi trong shard".

**Vì sao IM LẶNG tuyệt đối**: (1) router passthrough param `dimensions`; (2) qwen8b là **Matryoshka
(MRL)** → TUÂN `dimensions` → trả ĐÚNG dim mỗi collection mong đợi (1024/1536) → upsert vừa khít →
**0 lỗi, 0 cảnh báo**. Nếu thiếu BẤT KỲ điều kiện nào (qwen8b non-MRL HOẶC router không-passthrough)
→ dim-mismatch CRASH = lộ ngay. Cả 2 trùng → bug sống ẩn. Chỉ phát hiện bằng forensic cosine.

---

## bm6 — 6 fix gốc + gate CI chống tái phát (đã deploy)

1. **router.embeddings() route theo `body['model']`** → capability THẬT (qwen8b→embed,
   e5large→embed_e5large, te3s→embed_te3s/OpenAI, bge-m3/pplx→embed_*). Primary qwen8b KHÔNG đổi.
2. **embed est = MAX per-text** (KHÔNG sum batch): est cũ = sum(100 chunk)~8300 tok > ctx bge-m3 8192
   → `feasible_model` loại OAN → 503 no_capacity → 7/14 doc mất. context_length là PER-TEXT → phải
   MAX (~200 tok) < mọi ctx.
3. **`no_inflight_cap` cho embed** (LLM-router pattern, LiteLLM/OpenRouter): bỏ AIMD inflight-cap
   client-side (gây tự-503 "no capacity" dù key CÒN tiền) → đẩy thoải mái + round-robin key +
   failover-on-429 + cooldown. AIMD GIỮ cho chat (đúng chỗ nó cần).
4. **Dẹp hardcode**: `test_multi_embed` DERIVE từ `load_active_embed_models()` (bỏ hardcode list);
   reframe "primary" → "anchor" (KHÔNG privileged trong shard; mọi model peer ngang nhau).
5. **`infra/ci/embed_model_lint.py` + CI gate XUYÊN-SERVICE**: embeddings.yaml(active) ⊆
   contract.EMBED_MODELS/MODEL_TAGS ⊆ routing.yaml(alias/capability/pinned/tier) ⊆ catalog →
   thiếu/lệch chỗ nào = **CI ĐỎ trước prod** (bắt đúng class bug qwen8b). Cũng fix drift
   `_EXPECTED_CAPABILITIES` query-service.
6. **Gỡ e5large** (ctx 512 = mắt xích yếu).

**Verify**: secondary collection giờ là model THẬT — `cos(stored, qwen8b) ≈ 0` (-0.04 bge-m3 /
-0.01 te3s / 0.09 pplx) vs 0.96 thời-bug; OpenRouter serve thật (e5large=intfloat, bge-m3=parasail,
pplx); shard-read merge phủ **4/4 collection**.

---

## bm7 — Recall multi-collection THẬT (120 doc HR-VN, 480 câu gold)

**Corpus**: 120 doc HR-VN (full team dataset, ingest 45 doc/phút 0 fail). Gold 480 câu (4/doc,
gt=doc, có ref_answer). **Phương pháp ĐÚNG cho multi-collection**: recall qua **shard-read merge**
`/api/search` (embed query bằng CẢ N model → search N collection → merge → rerank). Per-collection
cũ (single-model) VÔ NGHĨA vì shard (mỗi collection chỉ ~1/N doc). Domain phải đúng (HR-VN, KHÔNG
openragbench academic — chỉ hợp đo throughput).

**Result**:
| | giá trị |
|---|---|
| Recall shard-merge | @1=0.53 @3=0.78 @5=0.85 @10=0.90 MRR=0.67 · latency p50=1.1s |
| **Per-model** (recall trên shard của model đó) | **qwen8b 0.73@1 (TỐT NHẤT)** · bge-m3 0.58 · te3s 0.42 · **pplx 0.41 (TỆ)** |
| Chấm tay (Claude judge relevance, 110 câu) | 75% answered@3 · khớp gt-match |

**Conclusion**: **shard ĐANG HẠI recall** — qwen8b trên shard của nó = 0.73@1 nhưng TỔNG chỉ 0.53@1
vì 3/4 doc rơi vào model yếu hơn (pplx/te3s 0.41). "Đa dạng model" KHÔNG giúp khi model phụ yếu.

---

## bm8 — Single qwen8b vs Multi → 🏁 QUYẾT KIẾN TRÚC

**What**: `MULTI_EMBED_ENABLED=0` = single qwen8b (mọi doc → 1 collection qwen8b@4096). Re-ingest
120 doc → đo recall + latency CÙNG 480 câu, so trực tiếp multi.

**Result** (cùng corpus + gold):
| | Multi-collection shard (4 model) | **Single qwen8b** |
|---|---|---|
| **recall@1** | 0.53 | **0.73** (+0.20) |
| recall@3 / @10 | 0.78 / 0.90 | 0.86 / 0.91 |
| **MRR** | 0.67 | **0.80** (+0.13) |
| latency p50 / p95 | 1.1s / 4.3s | 1.4s / 8.4s (~tương đương; qwen8b-tail) |
| ingest throughput | 45 doc/phút | ~tương đương (shard cũng 1 embed/doc) |

**Conclusion — QUYẾT ĐỊNH (data-driven)**: **SINGLE QWEN8B THẮNG ÁP ĐẢO** — recall@1 **+0.20**, MRR
+0.13; latency/throughput tương đương. **Multi-collection shard = LỖ RÒNG**: model phụ yếu kéo recall
xuống mà KHÔNG đổi lại được throughput (shard = 1 embed/doc = BẰNG single, KHÔNG phải ×N — ×N chỉ
đúng so với replicate) hay latency.

→ **PRODUCTION = single qwen8b** (`MULTI_EMBED_ENABLED=0`, đã deploy 2026-06-29). "Hybrid" hiện hữu =
**dense(qwen8b) + sparse(BM25)** mỗi collection (`__s2`) — đủ; hybrid đa-MODEL data nói KHÔNG đáng.
Hạ tầng multi-collection + gate CI **GIỮ** (sẵn bật lại) — chỉ có nghĩa NẾU sau này có model phụ
MẠNH ≥ qwen8b. Embeddings.yaml vẫn khai 4 model (cho shard) nhưng MULTI_EMBED_ENABLED=0 → chạy single.

**Bài học**:
1. **Đo recall ĐÚNG** (đúng domain HR-VN + đúng path shard-merge, không gt-match per-collection) mới ra
   sự thật — "multi-model giả" + "shard hại recall" đều chỉ lộ khi đo nghiêm.
2. **Bug correctness có thể IM LẶNG TUYỆT ĐỐI** (qwen8b-MRL + router passthrough che lấp) → cần forensic
   (cosine) + **gate CI xuyên-service** để không tái phát.
3. **"Đa dạng model" chỉ giúp NẾU model phụ đủ mạnh** — pplx 0.6B / te3s nhỏ << qwen8b 8B → đa dạng =
   pha loãng chất lượng. Một model MẠNH > nhiều model yếu.

