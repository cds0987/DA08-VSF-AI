# Claude Fix Log — RAG embed/rerank 503 → `src=0` dưới tải

Nhật ký fix→test lặp cho sự cố **retrieval rỗng (`src=0`) khi đồng thời cao**. Mỗi vòng:
hypothesis → change → deploy → test (queryeval) → verdict. Fix tới khi burst cực hạn ổn.

> Benchmark/data: [queryeval/benchmark.md](../../../queryeval/benchmark.md). Test = re-run đúng
> bộ 145 câu multi-subagent (ramp closed-loop + burst 10 req/s open-loop).

## Vấn đề gốc
Burst 10 req/s câu multi-subagent (fan-out 2-3 worker/câu) → **81% `src=0`** ("Mình chưa tìm được
thông tin phù hợp"). Trace VM: `embed`/`rerank` qua ai-router trả **503 "no capacity"** → MCP
`rag_search` lỗi → `verify_answer` no-data → canned fallback. **KHÔNG phải upstream** (OpenRouter
embed 200/200) — ai-router **tự shed**. Ràng buộc: embed PIN `qwen3-4b`, rerank PIN
`cohere/rerank-v3.5` — KHÔNG được đổi model (hỏng vector space).

---

## Iterations

### Fix #1 — cooldown ngắn + retry embed · commit `657d00f` · 2026-06-26
- **Hypothesis:** rate-429 bench key **30s** làm cạn pool embed (pool nhỏ, không degrade) dưới tải.
- **Change (ai-router):** `EMBED_RATE_COOLDOWN_SECONDS=3` (chat giữ 30s); `embeddings()`
  retry-across-keys + backoff (MAX_ATTEMPTS, `_embed_backoff` 0.5/1/2s).
- **Deploy:** ✅ CD develop (ai-router image 16:46Z).
- **Test:**
  - Ramp controlled: **C=6 `src=0` 44%→0%** ✅; overall 16%→5%.
  - Burst 10/s: **80% `src=0`** ❌; latency p50 32→**74s tệ hơn** (retry quay vòng).
- **Verdict:** Cứu tải-có-kiểm-soát; **KHÔNG** cứu burst → còn nghẽn khác.

### Fix #2 — nâng RPM 20→600 + rerank parity · commit `78e3f65` · 2026-06-26
- **Hypothesis:** burst nghẽn ở **RPM reserve** của ai-router, KHÔNG phải cooldown. VM: embed
  503=195 nhưng **key_429=0** → không có 429 upstream → nghẽn ở `reserve()`. embed(`embed_or`) +
  rerank(`paid`) + chat dùng CHUNG 5 key OpenRouter, mỗi key **RPM=20** → 5×20=1.7/s « burst ~40/s.
- **Change (ai-router):** `OPENROUTER_RPM` 20→**600** (env `AIROUTER_OPENROUTER_RPM`); đổi tên
  `RAG_RATE_COOLDOWN_SECONDS` áp cho **cả `embed` và `rerank_api`** (rerank cũng pool nhỏ no-degrade;
  `rerank()` đã có retry sẵn).
- **Deploy:** ✅ CD develop (ai-router image 17:24Z).
- **Test (burst 10/s):**
  - **embed 503: 195→0, rerank 503: 0** ✅ — RPM fix DỨT 503 encode. VM: 0 rag error, 0 worker-retry.
  - burst `src=0`: 80%→**68%** (giảm nhưng còn cao); latency p50 74→82s.
- **Diagnosis residual (scrape 14 trace src=0):** KHÔNG còn do embed/rerank. 99/99 src=0 có **answer
  RỖNG**, 88/99 chậm ≥50s; trace chỉ có `preplan + plan` rồi treo (vd plan 6s nhưng total 67s = treo
  ~60s = **worker_timeout**). → Dưới **142 concurrent** (open-loop pile-up), worker/verify queue quá
  `worker_timeout=60s` → no-data → answer rỗng. Đây là **bão hòa capacity 1-VM**, KHÔNG phải lỗi encode.
- **Verdict:** ✅ **Encode (embed/rerank 503) ĐÃ FIX**. Residual burst = capacity ceiling (1 VM, 5 key,
  deepseek plan/verify chậm dưới burst) — cần SCALE/admission-control, KHÔNG phải cooldown/RPM tuning.

### Kết luận
- **Câu hỏi gốc "mcp rag encode đã ổn chưa": RỒI** — embed/rerank 503 = 0 sau fix#1+#2; tải-thực
  (ramp) sạch (C=6 `src=0` 44%→0%).
- **Burst cực hạn 10/s (142 concurrent/1 VM)** vẫn ~68% src=0 do **bão hòa pipeline** (worker timeout,
  plan/verify chậm) — đây là trần capacity, vượt phạm vi fix encode. Hướng nếu cần: scale ngang
  ai-router/mcp, thêm OpenRouter key, hoặc admission-control (re-enable concurrency cap → fast-fail
  thay vì degrade cả loạt). KHÔNG nên tiếp tục nâng retry/cooldown (làm latency tệ hơn).

<!-- Fix #3+ thêm bên dưới khi cần -->
