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
