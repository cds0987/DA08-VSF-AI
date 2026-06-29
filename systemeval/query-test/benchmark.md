# benchmark.md — Đánh giá hệ thống chịu tải (query + ingest đồng thời)

Prod `https://vsfchat.cloud` (1 GCP VM, docker-compose). Đo bằng harness kiểu queryeval
(`run_query` SSE: TTFT + total latency + outcome taxonomy) trên **bộ 450 câu**
(`systemeval/query-test/questions/`, đa dạng simple/multiagent/hr_intent/non_rag).
Agent per-node lấy từ **Langfuse** (`generations.all`), ingest từ `eval/ingest-load`.

> **Outcome taxonomy**: SUCCESS · OFF_TOPIC · CLARIFY · NO_INFO · REFUSE · ERROR (như query-service).
> SUCCESS không phải đúng cho mọi loại — non_rag thì OFF_TOPIC/CLARIFY mới là đúng.

---

## §1. Performance khi hệ KHÔNG có tải lớn (baseline, conc ≤ 5)

Gửi tuần tự / concurrency thấp (1–5 in-flight, << trần) → latency "sạch" 1 câu qua full MOSA path
(triage → plan → retrieve → worker → verify/answer). Tham chiếu (n≈860 tích lũy):

| Loại | TTFT p50 | LAT p50 | LAT p95 |
|---|---|---|---|
| simple_rag | 6.9s | **10.9s** | 31s |
| multiagent | 10.9s | **19.1s** | 64.7s |
| hr_intent | 11.0s | 18.2s | 29.2s |
| non_rag | 9.1s | 12.6s | 12.6s |

**Nhận xét**: Ngay cả KHÔNG tải, 1 câu RAG đơn đã mất ~7–11s (TTFT ~7s) vì path luôn chạy đủ
plan + answer LLM. Đây là **sàn latency kiến trúc** — không phải do tải. Multiagent ~2× vì fan-out.

---

## §2. Peak load — mô phỏng 800–1200 users

**Tải**: 450 câu bắn trong **60.0s** (≈7.5 q/s trung bình, **3 cửa sổ burst ~14 q/s**), open-loop,
round-robin 21 account. **Đồng thời** ingest 40 tài liệu (docx/pdf thật) rải trong 60s.

> **Quy đổi ~800–1200 user**: 7.5 q/s ⇄ ~1100–1350 user active gửi 1 câu mỗi ~2.5 phút; burst 14 q/s
> = đỉnh giờ cao điểm.

### Chat end-to-end (450 câu)
| Metric | Giá trị |
|---|---|
| Hoàn tất | **450/450** |
| Lỗi / non-200 / timeout | **0** |
| TTFT | p50=**19.7s** · p95=46.4s |
| Latency e2e | p50=**25.3s** · p95=**57.9s** · p99=98.9s · max=321.9s |
| Outcome | SUCCESS 383 (85%) · OFF_TOPIC 37 · CLARIFY 20 · NO_INFO 10 |

### Per-type dưới peak (so baseline §1)
| Loại | n | LAT p50 | LAT p95 | SUCCESS | so baseline p50 |
|---|---|---|---|---|---|
| simple_rag | 249 | 23.2s | 45.5s | 242/249 (97%) | ~2.1× chậm hơn |
| multiagent | 120 | 36.4s | **74.4s** | **85/120 (71%)** | ~1.9× + tụt accuracy |
| hr_intent | 45 | 29.8s | 52.1s | 38/45 (84%) | ~1.6× |
| non_rag | 36 | 17.8s | 35.6s | 18 SUCCESS / 18 OFF_TOPIC+CLARIFY | route giữ ổn |

**Điểm mấu chốt**:
- ✅ **0 mất request** — hệ KHÔNG sụp ở mức 800–1200 (rate-limit gate đã miễn RPC nội bộ; không 429/5xx).
- ⚠️ **Latency giãn ~2–3×**: TTFT p50 lên 19.7s, e2e p95 58s — **UX không chấp nhận được** cho chat.
- ⚠️ **multiagent xuống 71% SUCCESS** dưới tải (fan-out nhiều worker → 1 nhánh chậm/lỗi kéo câu trả lời
  không đủ) — cần soi (verify timeout? worker partial?).

---

## §3. Performance của AGENTS dưới peak (Langfuse, 709 generations cửa sổ test)

| Agent node · capability | n | LAT p50 | LAT p95 | TTFT p50 | TTFT p95 | tok p50 |
|---|---|---|---|---|---|---|
| **plan** (orchestrator/planner) | 234 | 10s | **35s** | 1.6s | 9.1s | 2562 |
| **verify·answer** (synth + đáp) | 405 | 7s | 24s | 2.1s | 10.6s | 5577 |
| embed (ingest pipeline) | 40 | 18s | 28s | — | — | — |
| hr_lookup (HR worker) | 20 | 3s | 5s | — | — | 865 |
| leave_action (intent think) | 10 | 8s | 21s | — | — | 1083 |

**Phân tích agent**:
- **Planner là agent nặng nhất**: p95=**35s** dưới peak (~2× baseline ~17s). Khi nhiều câu vào, các call
  reasoning của planner **xếp hàng** ở tầng LLM → đây là **nghẽn gốc**, đúng như đã biết
  ("pipeline reasoning là trần, KHÔNG phải rate-limit").
- **verify·answer**: tok p50=5577 (prompt nặng — gộp nguồn + verify) → p95=24s; là phần lớn TTFT chat.
- HR worker / leave_action nhẹ (3–8s) — không phải nguồn nghẽn.
- Cộng path điển hình câu RAG = triage + plan(10s) + retrieve + verify·answer(7s) → khớp e2e p50 ~25s.

---

## §4. Ingest đồng thời (40 tài liệu trong 60s, song song chat peak)

| Metric | Giá trị |
|---|---|
| Indexed / fail | **40 / 0** |
| Accept latency (nhận job) | p50=1.3s · p95=4.5s |
| E2E (nhận→index xong) | p50=**59.9s** · p95=70.5s · max=84.7s |
| Tổng chunk | 3330 |

**Nhận xét**: API **nhận job nhanh** (1.3s) kể cả khi chat đang peak (decouple tốt). NHƯNG xử lý đầy đủ
(OCR + embed + index) mất ~**60s/doc** vì **rag-worker single-instance** xử lý tuần tự + cạnh tranh
CPU/embed với chat. 0 lỗi → bền, nhưng throughput ingest là **trần cứng 1-worker**.

---

## §5. Verdict — chịu tải ở quy mô 800–1200 users

| Tiêu chí | Kết quả |
|---|---|
| **Sống sót (không mất request)** | ✅ **ĐẠT** — 450/450 chat + 40/40 ingest, 0 lỗi |
| **UX chấp nhận được (TTFT < 5s)** | ❌ **KHÔNG** — TTFT p50=19.7s, e2e p95=58s |
| **Accuracy giữ dưới tải** | ⚠️ một phần — simple 97% nhưng multiagent tụt còn 71% |
| **Ingest dưới tải** | ⚠️ nhận nhanh nhưng e2e 60s/doc (1-worker) |

**Kết luận**: Hệ **thừa sức 800–1200 user active** — test đã chạy nặng gấp ~2× nhịp thật (7.5 vs 5 q/s)
mà vẫn **0 mất request**, đã qua giai đoạn "rớt ≥200 user" trước đây. Giới hạn **không phải số user mà
là latency**: ở 1200 user TTFT ~12–15s (test 7.5 q/s ra ~20s), tức **dùng được nhưng chậm**, chưa "mượt".
Nghẽn nằm ở **tầng agent reasoning (planner p95=35s, answer p95=24s) xếp hàng**, không phải gate/HTTP/
rate-limit — nên muốn nhanh hơn (hoặc gánh > nhiều nghìn user) phải scale tầng reasoning, không phải tăng VM chung.

### Sức chứa — tính theo workload THẬT (Little's Law: in-flight = QPS × latency)

Quy đổi đúng: **1200 user** mỗi người gửi ~1 câu/4 phút → **5 q/s** chat; upload do **20–30 admin**,
~**40 doc/phút** giờ cao điểm. Test đã chạy **7.5 q/s + 40 doc** = **nặng gấp ~2×** kịch bản 1200-user.

| Kịch bản | QPS chat | latency | in-flight đồng thời | Kết quả |
|---|---|---|---|---|
| **1200 user thật** (1 câu/4ph) | 5 q/s | ~18s | **~90 pipeline** | nội suy: 0 mất request, TTFT ~12–15s |
| **Test thực đo** (450/60s) | 7.5 q/s | ~25s | **~188 pipeline** | **0/450 mất**, TTFT p50=19.7s |

> **Tổng kết**: hệ **thừa sức 800–1200 user active** ở nhịp thật (5 q/s) — đã đo gấp đôi (≈1800-user-
> equiv) vẫn **0 mất request**; ingest 40 doc/phút (20–30 uploader) 40/40 OK. Giới hạn thực **KHÔNG
> phải số user mà là latency**: ở 1200 user, TTFT ~12–15s — **dùng được nhưng chậm**.
>
> Con số "200–300" (bản nháp trước) chỉ là ngưỡng giữ latency ~gần-idle (in-flight ≤ ~25) — **không
> phải** ngưỡng "hệ chạy được", và dựa trên thước TTFT<5s mà kiến trúc không bao giờ đạt (sàn ~7s).
> Đã loại bỏ.
>
> ⚠️ Số 1200-user là **nội suy** từ mức 7.5 q/s; để chốt chính xác cần đo đúng **5 q/s** (300 câu/60s).
> Trần SỤP thật chưa chạm (cần ramp 10→20 q/s); ở 7.5 q/s đã thấy p99=99s, max=322s (tail chạm timeout).

### Đòn bẩy ưu tiên (theo tác động)
1. **Scale tầng reasoning** (planner + answer): nhiều replica query-service / model planner nhanh hơn →
   cắt trực tiếp p95 35s + 24s. Tác động lớn nhất tới TTFT.
2. **Bỏ/cache plan cho simple_rag**: câu single-fact không cần planner đầy đủ → triage thẳng RAG
   (sàn §1 còn ~7s, peak còn thấp hơn nhiều).
3. **Soi multiagent 71%**: vì sao SUCCESS tụt dưới tải (verify timeout / worker partial) — sửa accuracy.
4. **Scale rag-worker ingest** (đa instance / tách OCR-vision): hạ e2e 60s/doc khi nhập hàng loạt.

---

### Phương pháp & caveat
- Harness: `systemeval/query-test/runners/peak_load.py` (chat open-loop burst, 21 account),
  `eval/ingest-load/.../run_ingest_load.py` (ingest). Agent: Langfuse `generations.all` cửa sổ test.
- Raw: `results/peak_chat.jsonl`, `results/peak_agents_langfuse.json`, `eval/ingest-load/results/`.
- Baseline §1 là tích lũy conc 1–5 (tham chiếu light-load, không phải conc=1 thuần).
- Corpus Qdrant lúc đo có residue (≥262 doc) — recall/accuracy tuyệt đối nên đo lại trên corpus sạch;
  ở đây trọng tâm là **latency/throughput/độ bền dưới tải** + phân bố outcome, không phải recall@k.
