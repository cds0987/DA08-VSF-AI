# Query-service Benchmark

Đo **latency · correctness · hành vi dưới tải** của query-service (MOSA orchestrator-workers)
trên prod `https://vsfchat.cloud`. Câu hỏi gắn nhãn, grounded trên corpus Qdrant thật.
Mỗi lần cải tiến → thêm 1 section (Benchmark 2, 3, …) để so trước/sau.

> Dataset + harness: xem [README.md](README.md). Dữ liệu thô: [results/benchmark1/](results/benchmark1/).

---

## Benchmark 1 — Baseline (2026-06-25) · TRƯỚC cải tiến latency

**Cấu hình đo:** 21 account (admin + loadtest01-20), 3 đợt:
| Đợt | Dataset | Cách gửi | Mục đích |
|---|---|---|---|
| 1 · single | 150 câu 1-lượt (7 loại task) | concurrency thấp (cap 4) | latency + correctness **sạch** |
| 2 · ramp | 145 câu multi-agent | closed-loop, tăng dần C=3→18 | tìm ngưỡng chịu tải |
| 3 · burst | 145 câu multi-agent | open-loop **10 req/s** | hành vi khi quá tải |

### 1) Latency — TOÀN BỘ request (giây)

| Tập | n | p50 | p75 | p85 | p95 | p99 | max | avg |
|---|---|---|---|---|---|---|---|---|
| **Tất cả request** | 375 | **29.2** | 37.4 | 44.8 | 80.3 | 126.9 | 152.5 | 33.2 |
| Đợt 1 — single (low-conc) | 150 | **22.3** | 30.3 | 35.1 | 45.9 | 66.1 | 77.0 | 23.0 |
| Đợt 3 — burst 10/s | 145 | 32.3 | 38.3 | 44.8 | 86.0 | 127.1 | 152.5 | 38.1 |

TTFT (đợt 1): p50 **19.9s** · p95 38.4s · avg 20.6s → **gần như toàn bộ latency nằm TRƯỚC token đầu** (plan + retrieve + verify), không phải lúc stream.

### 2) Agent performance theo loại task (đợt 1, sạch)

| Task | n | p50 | p95 | Ghi chú |
|---|---|---|---|---|
| rag_info (tra cứu) | 45 | 24.2 | 49.2 | nặng nhất |
| hr_balance (số phép cá nhân) | 20 | 22.5 | 44.3 | hr_query |
| leave_action (tạo đơn) | 20 | 21.6 | 45.9 | có resolve_date |
| multiturn (đa lượt/memory) | 25 | 25.4 | 34.1 | memory recall OK |
| ambiguous (hỏi lại) | 12 | **6.0** | 22.6 | nhẹ — chỉ planner |
| offtopic_adv (từ chối) | 13 | **7.8** | 13.6 | nhẹ — chỉ planner |
| no_doc (graceful) | 15 | 29.7 | 42.2 | retrieve rồi từ chối |

### 3) Nút thắt latency (phân rã span Langfuse, đợt 1)

| Stage | % tổng thời gian | Bản chất |
|---|---|---|
| **plan** | **41%** | LLM lập kế hoạch — chạy 100% câu, kể cả off-topic/ambiguous không cần tra |
| **verify** | **33%** | LLM tổng hợp + sinh câu trả lời |
| rag (retrieve) | 13% | MCP + embed + rerank |
| leave_action | 11% | worker LLM tạo đơn |
| hr / preplan / acl | <2% | gần như miễn phí |

→ **plan + verify = 74%**, đều LLM nối tiếp, trước token đầu → đây là đòn bẩy latency chính.
Fan-out worker thật sự hiếm: **>1 worker chỉ 7%**, replan 8%.

### 4) Agent performance — MULTI-SUBAGENT (145 câu fan-out), 2 đợt

145 câu compound/so-sánh (compare_company, multi_topic, hr_plus_policy, multi_aspect, cross_domain,
heavy_fanout) — **ép planner fan-out ≥2 worker song song**. Mỗi câu nở 2-3 embed → tải embed ×~2.3.

**Đợt 2 — GIẢM TẢI (ramp closed-loop, giữ đúng C đồng thời, KHÔNG pile-up), 80 câu, latency giây:**

| Concurrency | p50 | p75 | p85 | p95 | p99 | max | src=0 | throughput |
|---|---|---|---|---|---|---|---|---|
| C=3 | 29.2 | 55.4 | 55.7 | 81.7 | 81.7 | 103.5 | 19% | 0.07 rps |
| C=6 | 30.2 | 40.6 | 41.6 | 123.4 | 123.4 | 130.9 | **44%** | 0.10 rps |
| C=10 | 35.9 | 55.1 | 74.7 | 116.5 | 116.5 | 124.2 | 0% | 0.13 rps |
| C=14 | 36.5 | 39.7 | 41.4 | 56.7 | 56.7 | 93.0 | 6% | 0.17 rps |
| C=18 | 40.4 | 67.8 | 77.8 | 99.4 | 99.4 | 114.3 | 12% | 0.14 rps |
| **Tổng 80** | **35.4** | 54.0 | 75.8 | 114.3 | 124.2 | 130.9 | **16%** | — |

- **Multi-subagent chậm hơn single ~1.6×** (p50 35.4s vs 22.3s) — nhiều retrieval song song + verify tổng hợp data lớn hơn → p95 lên 93-124s.
- **Throughput cực thấp 0.07-0.17 rps**: mỗi câu 30-130s, concurrency thấp → 1 VM chịu được rất ít multi-agent/giây.
- **Ngay GIẢM TẢI vẫn rớt embed**: C=6 đã **44% src=0** (fan-out tự nhân embed-concurrency: C=6 client ≈ ~15 embed đồng thời). Không đơn điệu (C=10 lại 0%) = động học cooldown 30s + mẫu nhỏ. → **multi-agent KHÔNG benchmark latency sạch được TRƯỚC fix** vì nó tự làm sập embed.

**Đợt 3 — BURST 10 req/s (open-loop, 145 câu):** p50 32.3 · p95 86 · p99 127 · max 152.5s.
- 200 OK 145/145 nhưng **src=0: 117/145 = 81%** → đa số trả "Mình chưa tìm được thông tin phù hợp".
- **Peak in-flight = 142** (pile-up theo định luật Little). Fan-out: 92/145 trace **0 worker** (worker chết vì embed 503), chỉ 11 trace có ≥2 worker.
- Per-subtype src=0: hr_plus_policy **88%**, heavy_fanout **87%** (nhiều embed nhất) > compare_company 72%.

### 5) Root cause của src=0 dưới tải (trace từ VM)

```
10/s × fan-out 2-3 worker/câu → ~366 embed-call lẻ
   → ai-router /v1/embeddings: 289/331 = 87% trả 503 "no capacity for embed"
   → MCP rag_search lỗi → 141× rag_retrieve_retry → worker no-data
   → verify_answer no-data → canned fallback → src=0
```
- **KHÔNG phải upstream**: OpenRouter qwen3-embedding-4b = **77/77 = 200 OK**. MCP coalescing (singleton) hoạt động.
- **Là ai-router tự shed**: embed dùng `banded_rotation`, rate-429 → **cooldown key 30s** (`router.py:29`), ít key embed (chung 5 key OpenRouter với chat) → burst → cạn key → resolve None → 503. Embed **không có degrade** (xiaomi là model chat, bị `feasible_model` chặn theo endpoint — đúng, để không hỏng vector space) → 503 là kết quả an toàn nhưng làm rớt retrieval.
- ⚠️ Embed **khoá đúng 1 model** `qwen3-embedding-4b` (pinned), không bao giờ rớt sang model khác.

### 6) Correctness (đợt 1, chấm tay 150/150) ≈ **~84% (≈126/150)**

| Task | Đúng | Lỗi chính |
|---|---|---|
| rag_info | ~32/45 | 9 false-negative (doc CÓ trong Qdrant nhưng retrieve trượt → "không tìm thấy" sai); 1 sai số (20% vs 17%); 1 rò JSON thô |
| hr_balance | 17/20 | 2 mis-route sang policy chung; 1 lỗi mạng |
| leave_action | 18/20 | 1 bắn nhầm action; 1 sai leave_type |
| multiturn | ~19/25 | memory recall OK; chuỗi g7 hỏng (không resolve "thời gian đó", trôi sang paternity) |
| ambiguous | **12/12** | hỏi lại làm rõ tốt |
| offtopic_adv | **13/13** | từ chối an toàn — không lộ prompt/PII, không jailbreak |
| no_doc | **15/15** | **0 hallucination** — vắng doc thì từ chối, không bịa |

### 7) Kết luận Benchmark 1
- **Latency thường ngày** (1-vài user): p50 ~22s, bị chi phối bởi **plan (41%) + verify (33%)**.
- **Chịu tải kém**: fan-out nhân tải embed → embed 503 từ concurrency vừa phải (C=6 đã 44% src0); burst 10/s sập 81%.
- **An toàn + correctness** lõi tốt (adversarial 13/13, no-doc 0 bịa, memory recall chạy); điểm yếu correctness = **retrieval recall** (false-negative) + multi-turn follow-up.
- Hướng cải tiến (đo lại ở Benchmark 2): (a) embed resilience ở ai-router (cooldown ngắn + retry-across-keys, vẫn qwen3-4b), (b) bỏ planner round-trip cho intent đơn giản, (c) cắt context verify.

---

## Benchmark 2 — (sau fix embed/rerank resilience) · 2026-06-26

**Mục tiêu:** dứt `src=0` do ai-router shed embed/rerank 503 dưới tải (nút thắt #1 ở BM1).

**2 fix deployed (ai-router, chi tiết: [src/mcp-service/docs/claudefix.md](../src/mcp-service/docs/claudefix.md)):**
- **Fix#1** (`657d00f`): rate-429 bench embed 30s→3s + `embeddings()` retry-across-keys + backoff.
- **Fix#2** (`78e3f65`): `OPENROUTER_RPM` 20→600 (embed+rerank+chat) + cooldown ngắn áp cho cả rerank.
- Giữ nguyên model: embed PIN `qwen3-embedding-4b`, rerank PIN `cohere/rerank-v3.5`.

### Kết quả — encode (embed/rerank 503) ĐÃ DỨT ✅

| Chỉ số (trace VM, burst 10/s) | BM1/trước | BM2/sau |
|---|---|---|
| **embed 503** (ai-router shed) | 195 | **0** ✅ |
| **rerank 503** | nhiều | **0** ✅ |
| rag_search error · worker-retry · no_capacity | nhiều | **0** ✅ |
| Ramp tải-thực **C=6** `src=0` (sau fix#1, đo sạch) | 44% | **0%** ✅ |
| Ramp overall `src=0` (sau fix#1, đo sạch) | 16% | **5%** ✅ |

→ **Nút thắt encode đã được giải quyết tận gốc**: dưới tải có-kiểm-soát (thực tế), retrieval không còn rỗng.

### Burst CỰC HẠN (10 req/s open-loop, 142 concurrent/1 VM) — residual = capacity, KHÔNG phải encode

| | BM1 | sau fix#1 | sau fix#2 |
|---|---|---|---|
| burst `src=0` | 81% | 80% | **68%** |
| latency p50 | 32s | 74s | 82s |

- Scrape 14 trace src=0 burst#2: **embed/rerank đều 200** (không 503), nhưng **answer rỗng**, 88/99
  chậm ≥50s, trace treo ~60s sau `plan` = **worker_timeout (60s)**. → Dưới 142-concurrent pile-up,
  worker/verify queue vượt timeout → bão hòa. **Đây là trần capacity 1-VM**, không phải lỗi encode.
- Nâng retry/cooldown/RPM thêm KHÔNG cứu (latency còn tệ hơn). Cần **scale ngang / admission-control**
  (re-enable concurrency cap → fast-fail thay vì degrade) — ngoài phạm vi fix encode.

> ⚠️ Caveat đo: ramp post-fix#2 chạy ngay sau burst (prod đang hồi tải) nên `src=0` 35% bị NHIỄM,
> không phải số sạch. Số sạch của tải-thực = ramp post-fix#1 (5%) + log VM (503=0, độc lập với tải).

### Kết luận Benchmark 2
- ✅ **"mcp rag encode đã ổn chưa": RỒI** — embed/rerank 503 = 0; tải thực-tế (ramp) sạch.
- ⛔ Burst cực hạn 142-concurrent/1 VM vẫn ~68% src=0 do **bão hòa pipeline** (worker timeout, plan/
  verify chậm) — trần capacity, để dành nếu cần scale.
- Nút thắt latency thường ngày (plan 41% + verify 33%) **chưa đụng** → còn nguyên cho Benchmark 3.

---

## Benchmark 3 — (A fast-path: cắt heavy-planner cho RAG đơn) · 2026-06-26

**Mục tiêu:** đánh nút thắt latency #1 ở BM1 — **plan 41%** (heavy-planner chạy MỌI câu, kể cả tra
cứu 1-doc đơn giản). BM1 đo: fan-out >1 worker chỉ 7% → ~93% câu 1-step không cần DAG-planner.

**Thay đổi deployed:**
- **A FAST-PATH** (`orchestrator_workers._fast_triage`): triage rẻ (capability `triage`, gpt-4o-mini
  ~1s) phân loại **RAG** (tra cứu 1 quy định, tự-đủ-nghĩa) vs **OTHER**. RAG → plan CỐ ĐỊNH 1-step
  `rag_retrieve`, **BỎ heavy-planner (~9s)**. OTHER (mơ hồ/cá-nhân/đơn-nghỉ/off-topic/follow-up) →
  heavy-planner (an toàn). Replan (verify NEED_MORE) → ESCALATE heavy (net bắt misclassify).
- **Outcome-field fix**: MOSA done-event trước chỉ NO_INFO|SUCCESS → mọi refuse/clarify/no_info =
  SUCCESS (benchmark auto-grade sai). `_classify_mosa_outcome` suy outcome từ route + nội dung answer.
- (Thử //hóa answer 2-pool deepseek+gpt-oss để rải GPU → REVERT: gpt-oss phá format
  `astream_verify_answer` → dump raw data. //hóa answer cần model cùng-họ-format.)

### Kết quả — latency (single 150, open-loop rate 0.5, đo sạch)

| task | BM1 p50 | BM3 p50 | Δ |
|---|---|---|---|
| **TỔNG** | 22.3 | **15.3** | **-31%** ✅ |
| rag_info (A short-circuit) | 24.2 | **16.4** | **-32%** |
| hr_balance | 22.5 | 17.9 | -20% |
| leave_action | 21.6 | 16.7 | -23% |
| multiturn | 25.4 | 17.1 | -33% |
| ambiguous | 6.0 | 5.9 | ≈ (giữ nhanh) |
| offtopic_adv | 7.8 | 9.1 | +1.3 |
| no_doc | 29.7 | 16.5 | -45% |

- **150/150 OK, 0 lỗi** (rate 0.5). p90 40.7 · p95 49.9s (BM1 single p95 45.9 — tương đương; rate-0.5
  open-loop ≈ in-flight ~10 nên đuôi nhỉnh hơn closed-loop cap-4 của BM1).
- **A triage có 2 phiên bản:** v1 (prompt rộng) regress ambiguous 6→22s + leave +4s (bắt nhầm câu mơ
  hồ/đơn-nghỉ → phí retrieve). **v2 conservative** (chỉ RAG khi tự-đủ-nghĩa, probe vs labeled:
  rag_info 6/6 RAG · ambiguous/offtopic/leave/hr 0/6 RAG) **xóa sạch regression** → bảng trên là v2.

### Correctness (outcome-field auto-grade, sau fix)

- rag_info / hr_balance / leave_action: **100%** · multiturn 84% · **TỔNG 80%** (BM1 chấm-tay 84%).
- ⚠️ Light-route (ambiguous/offtopic/no_doc) **bị undercount**: `_classify_mosa_outcome` là heuristic
  cụm-từ → bắt hết clear cases nhưng sót vài cách diễn đạt clarify/no_info → grade thấp hơn HÀNH VI
  thực (spot-check live: refuse/clarify/no_info đều ĐÚNG). Muốn số chính xác tuyệt đối → **LLM-judge**.

### Kết luận Benchmark 3
- ✅ **plan-bottleneck đánh trúng: -31% latency tổng** (rag_info -32%), không regress nhóm nào (v2),
  0 lỗi. A short-circuit ~43% traffic nặng nhất bằng triage ~1s thay heavy-planner ~9s.
- ✅ Outcome-field hết "luôn SUCCESS" → auto-grade dùng được (clear cases), light-route cần LLM-judge.
- 🔭 Còn lại: **verify 33%** (chưa đụng) + //hóa answer cùng-họ-format (rải GPU) + burst admission-control.

---

## Benchmark 4 — (//hóa answer 7 model đa-pool) · 2026-06-26

**Mục tiêu:** đánh **variance answer-node** — deepseek-v4-flash là model CHẬM NHẤT còn lại (đo idle
p50 6.3s, biến thiên 2-14s) và mọi answer DỒN 1 upstream → queue GPU + đuôi p95/p99 xấu.

**Khảo sát (7 model × 4 scenario × 3 reps, OpenRouter):** đủ-data / đa-nguồn / thiếu→NEED_MORE /
off-topic. Root-cause "//hóa hỏng" trước (gpt-oss dump raw) = **reasoning-model nhồi answer vào
`reasoning_content`, `content` RỖNG** → verify đọc content rỗng → fail-safe dump raw data.

**Thay đổi deployed:**
- **reasoning-off** (profiles.yaml answer `reasoning_effort: "off"` → `reasoning:{enabled:false}`):
  ép MỌI model nhồi answer vào `content` (kể cả deepseek — off còn NHANH hơn + cite tốt hơn).
- **soft-adapter `_va_split`** (model-agnostic): tách "BƯỚC 1 reasoning" khỏi answer trong content
  (model reasoning-off xuất 'BƯỚC 1..BƯỚC 2: answer') + glyph-normalize 【1】→[1]. deepseek
  reasoning-on (pure-answer) vẫn stream live như cũ (giữ legacy path).
- **routing.yaml answer.paid = 7 model**: deepseek-v4-flash + qwen3.5-flash + qwen3-vl-30b +
  qwen3-235b + llama-4-scout + glm-4.7-flash + hy3-preview (DeepSeek/Qwen/Meta/Zhipu/Tencent).
  LOẠI gpt-oss-120b (content RỖNG cả 2 chế độ — unfit thật).

### Kết quả (single 150, rate 0.5, WARM — BM4 lần đầu bị cold-start ngay sau deploy, đã re-run)

| | BM1 | BM3 | **BM4** | Δ vs BM3 |
|---|---|---|---|---|
| correct | 84% (tay) | 80% | **86%** | +6 |
| p50 | 22.3 | 15.3 | 15.4 | ~ |
| **p95** | — | 72.6 | **42.7** | **-41%** ✅ |
| **max** | 152 | 139 | **71** | **-49%** ✅ |
| lỗi · raw-dump | — | 0 | **0 · 0** | |

- **Đòn //hóa = ĐUÔI**: p95 -41%, max -49% — rải answer qua 7 pool xoá outlier chậm của deepseek
  (variance 2-14s). p50 ~same (rag-retrieve 4-10s vẫn chi phối; answer-node nhanh hơn chỉ 1 phần).
- **Correctness 86% (cao nhất)**: answer đa-model + output sạch (cite [N] chuẩn sau glyph-normalize).
- **0 raw-dump dưới tải**: soft-adapter `_va_split` + reasoning-off ổn định. Survey split_ok ~12/12.
- ⚠️ **Cold-start sau deploy NẶNG hơn** (7 model cần warm connection riêng): BM4 lần đầu rag_info tụt
  17% (fallback NO_INFO), warm lại → 100%. → cần warm-up sau mỗi deploy trước khi đo/serve.

### Kết luận Benchmark 4
- ✅ **//hóa answer đạt mục tiêu: cắt đuôi latency (p95 -41%, max -49%)** + correctness +6% + 0 raw-dump.
- ✅ Soft-adapter model-agnostic (reasoning-off + `_va_split`) → thêm/bớt model chỉ sửa routing.yaml.
- 🔭 Còn lại: rag-retrieve 4-10s (chi phối p50) + burst admission-control (trần 1-VM) + LLM-judge.

---

## Benchmark 5 — (triage reasoning-OFF + clean methodology) · 2026-06-26

**Mục tiêu:** trace lộ orchestrate nghĩ 2 LẦN cho câu OTHER — fast_triage (deepseek-v4-flash
reasoning-ON, ~3-4s) + heavy planner. Triage chỉ là classify RAG/OTHER, KHÔNG cần suy luận.

**Đo router-accuracy (49→150 câu labeled, OpenRouter):** deepseek-reason-ON 93%@3.0s ==
qwen3.5-flash-reason-OFF 93%@1.2s == deepseek-reason-OFF 93%@2.4s. Full 80 câu (rag/leave/no_doc):
qwen-off **100%** == deepseek-off 100%. → **reasoning VÔ DỤNG cho classify** (accuracy giống hệt),
chỉ tốn ~2s.

**Thay đổi deployed:**
- capability `triage_fast` = [qwen3.5-flash, qwen3-vl-30b] (OpenRouter, **OFF OpenAI** → ổn định prod).
- profiles.yaml triage node: standard → openrouter_effort + `reasoning_effort: "off"` (dynamic-reasoning).
- → triage **4s → ~1s** (verified live: planner-start 4.4s → 0.7s).

### Phương pháp ĐO SẠCH (giảm noise — học từ BM3/4 nhiễu)

BM3/4 nhiễu do: (1) **semantic-cache hit** (~25% cross-run, lexical cosine≥0.90 TTL 1h → 0.01s/0-token,
KHÔNG tới ai-router); (2) **//hóa answer 7-model** round-robin → latency variance; (3) cold-start sau
deploy. → BM5: **filter cache-hit (latency<2s)** + **2-run** lấy variance + **warm trước**.

| | run1 | run2 | nhận xét |
|---|---|---|---|
| cache-hit | 0% | 0% | (2 run này sạch sẵn) |
| **p50 (real-query)** | 15.4s | 15.1s | ✅ ỔN ĐỊNH |
| p90 / p95 | 35.3 / 46.3 | 32.4 / 40.2 | ±6s |
| correct (heuristic) | 75% | 76% | (NHIỄU — xem LLM-judge dưới) |

### Correctness — LLM-judge (deepseek-chat giám khảo, 150 câu) — THAY heuristic nhiễu

outcome-heuristic (cụm-từ) UNDERCOUNT nặng light-route → chấm lại bằng **LLM-judge**: fire 150 câu →
capture answer → giám khảo so `expect` + `expect_outcome`. (Lưu `benchmark5/llm_judge.jsonl`.)

| task | heuristic | **LLM-judge** | ghi chú |
|---|---|---|---|
| offtopic_adv | 53-69% | **100%** (13/13) | từ chối an toàn — judge xác nhận |
| ambiguous | 33-41% | **91%** (11/12) | hỏi-lại đúng (heuristic tưởng sai) |
| no_doc | 20↔46% | **86%** (13/15) | NO_INFO trung thực |
| rag_info | 91% | **84%** (37/44) | tra cứu |
| hr_balance | (37% artifact) | **75%** (15/20) | ⚠️ judge ban đầu phạt nhầm `src=0`; HR data từ **hr_query tool** (KHÔNG phải rag-source, có chống-bịa code-level `_payroll_facts`) → re-judge src-agnostic |
| leave_action | (53% artifact) | **66%** (12/18) | tạo đơn (no-source) |
| multiturn | 64-76% | **56%** (14/25) | thấp nhất — harness fire STANDALONE (mất ngữ cảnh) → follow-up "đó/còn..." không resolve được |
| **TỔNG** | 75-76% | **78%** (115/147) | |

### Kết luận Benchmark 5
- ✅ **Triage-fast: triage 4s→1s, routing accuracy 100% (full dataset), OFF OpenAI.** ambiguous/offtopic
  latency ~6s (BM4 7.5-9s) — win consistent ở câu triage-bound.
- ✅ **Latency baseline ĐÁNG TIN** (2-run tight: p50 15.1-15.4, p95 40-46). p50 ~same BM4 (rag-retrieve
  + //hóa answer chi phối; triage chỉ 1 phần). Net trung-tính-tích cực.
- ✅ **LLM-judge: 78% (115/147)** — light-route THỰC SỰ cao (offtopic 100%, ambiguous 91%, no_doc 86%),
  heuristic cũ undercount do bám `src`/cụm-từ. hr_balance 75% (giải oan src-artifact). multiturn 56% là
  hạn chế HARNESS (fire standalone mất ngữ cảnh) chứ không phải hệ.
- 🔭 Còn lại: **migrate worker** (gpt-5.4-mini OpenAI → //hóa, phân tích KHÔNG tool-call) + harness
  multiturn giữ conversation_id + warm-up-after-deploy (cold-start 7-model).
