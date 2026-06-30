# System Benchmark — số liệu thực đo

> Kết quả đo trên prod `https://vsfchat.cloud` (1 GCP VM, docker-compose). Đo lần đầu **2026-06-29**.
> Phương pháp: xem [testdesign.md](testdesign.md). Mọi số dưới đây là **đo thật**, không nội suy trừ
> khi ghi rõ "(nội suy)".

---

## 1. Sức chịu tải — chat + ingest đồng thời (giờ cao điểm)

**Kịch bản**: 450 câu / 60s (≈7.5 q/s, 3 burst ~14 q/s, 21 account round-robin) — nặng gấp ~2× nhịp
1200-user thật — đồng thời ingest 40 tài liệu docx/pdf / 60s. Bộ 450 câu: simple_rag 249, multiagent
120, hr_intent 45, non_rag 36.

### Chat end-to-end
| Metric | Giá trị |
|---|---|
| Hoàn tất / lỗi | **450/450 · 0 lỗi** (không 429 / 5xx / timeout) |
| TTFT | p50 = 19.7s · p95 = 46.4s |
| Latency e2e | p50 = 25.3s · p95 = 57.9s · p99 = 98.9s · max = 321.9s |
| Outcome | SUCCESS **85%** · OFF_TOPIC 37 · CLARIFY 20 · NO_INFO 10 |
| Per-type SUCCESS | simple **97%** (p95 45s) · multiagent **71%** (p95 74s) · hr **84%** (p95 52s) |

### Agent per-node (Langfuse, dưới peak)
| Node | n | p50 | p95 | ghi chú |
|---|---|---|---|---|
| **planner** | 234 | 10s | **35s** | nặng nhất (~2× baseline) — **nghẽn gốc** |
| verify·answer | 405 | 7s | 24s | prompt nặng (~5.5k token) |
| embed (ingest) | 40 | 18s | 28s | |
| hr_lookup / leave_action | 30 | 3–8s | 5–21s | nhẹ |

### Ingest (chạy đồng thời lúc chat peak)
40/40 indexed · 0 fail · accept p50 = 1.3s (nhận job nhanh) · **e2e p50 = 60s** / p95 = 70s · 3330 chunk.
rag-worker single-instance xử lý OCR+embed+index tuần tự ⇒ e2e/doc cao.

### Sức chứa (Little's Law: in-flight = QPS × latency)
| Kịch bản | QPS | latency | in-flight | Kết quả |
|---|---|---|---|---|
| **1200 user thật** (1 câu/4 phút) | 5 q/s | ~18s | ~90 pipeline | **(nội suy)** 0 mất, TTFT ~12–15s |
| **Test thực đo** | 7.5 q/s | ~25s | ~188 pipeline | **0/450 mất**, TTFT 19.7s |

**Verdict**
- ✅ Thừa sức **800–1200 user active** ở nhịp thật — đã đo gấp đôi (~1800-user-equiv) vẫn 0 mất request.
- ⚠️ Giới hạn thực là **latency, không phải số user**: 1200 user → TTFT ~12–15s (dùng được, chậm).
- ❌ Không có tier "mượt <5s": sàn kiến trúc ~7s/câu (luôn chạy plan + answer LLM) kể cả lúc rảnh.
- Trần SỤP thật chưa chạm; ở 7.5 q/s tail đã p99 = 99s → cần ramp 10→20 q/s để xác định.

### Nghẽn & đòn bẩy (theo tác động)
Nghẽn = **tầng agent reasoning xếp hàng** (planner p95 35s + answer p95 24s), **KHÔNG phải**
rate-limit / gate / HTTP (0 lỗi).
1. Scale tầng reasoning (replica query-service / planner model nhanh hơn) — cắt p95 trực tiếp.
2. Bỏ/cache plan cho simple_rag (triage thẳng RAG) — không cần planner đầy đủ.
3. Soi multiagent 71% SUCCESS dưới tải (verify timeout / worker partial) — sửa accuracy.
4. Scale rag-worker ingest (đa instance / tách OCR-vision) — hạ e2e 60s/doc.

> Caveat: số 1200-user là nội suy từ mức đo 7.5 q/s. Qdrant lúc đo có residue (≥262 doc) → trọng tâm
> là latency/throughput/độ bền + outcome, **không phải recall@k** (recall đo riêng, mục 2).

---

## 2. Chất lượng truy hồi (recall) — corpus sạch

**Corpus**: 120 tài liệu HR-VN (full team dataset), 480 câu gold (4/doc), đo qua `rag-worker
/api/search` raw (shard-read merge cho multi). Ingest 45.7 doc/phút, 0 fail.

### Quyết định kiến trúc: single qwen8b vs multi-collection shard (2026-06-29)
| | Multi-collection shard (4 model) | **Single qwen3-embedding-8b** |
|---|---|---|
| recall@1 | 0.53 | **0.73** (+0.20) |
| recall@3 / @10 | 0.78 / 0.90 | 0.86 / 0.91 |
| MRR | 0.67 | **0.80** (+0.13) |
| latency p50 / p95 | 1.1s / 4.3s | 1.4s / 8.4s |
| ingest throughput | 45 doc/phút | ~tương đương |

### Per-model (recall trên doc shard của riêng model đó)
| model | n | @1 | @3 | @10 | |
|---|---|---|---|---|---|
| **qwen3-embedding-8b** | 104 | **0.73** | 0.91 | **0.99** | 🥇 áp đảo |
| baai/bge-m3 | 132 | 0.58 | 0.77 | 0.89 | 🥈 khá |
| openai/text-embedding-3-small | 132 | 0.42 | 0.70 | 0.88 | 🥉 yếu |
| perplexity/pplx-embed-0.6b | 112 | 0.41 | 0.76 | 0.84 | ❌ tệ nhất |

**KẾT LUẬN (bằng DATA)**: shard ĐANG HẠI recall — qwen8b trên shard của nó 0.73@1 nhưng tổng shard chỉ
0.53@1 vì pplx/te3s yếu (0.41–0.42) kéo xuống (3/4 doc rơi vào model yếu hơn). shard cho throughput
nhưng mất ~0.20 recall@1.
→ **PRODUCTION = single qwen8b** (`MULTI_EMBED_ENABLED=0`). Hạ tầng multi-collection GIỮ lại, bật khi
có model phụ mạnh ≥ qwen8b.

---

## 3. Tối ưu pipeline có đo regression

| Thay đổi | Kết quả |
|---|---|
| Bỏ per-worker distill LLM, gộp trích xuất vào `verify_answer` per-direction (`WORKER_DISTILL_MULTISTEP=0`) | latency câu nặng **−53%**, accuracy giữ ~75% |
| Embed migration qwen3-4b → 8b @4096 (3 provider) | hết `engine_overloaded`, recall@1 single = 0.73 |

---

## 4. Lề / điều kiện tái lập

- Đo trên 1 VM (mọi tầng single-instance trừ query-service ×8 + rag-ingest-worker ×8).
- Quality (recall) đo trên corpus sạch 120 doc; performance đo trên prod có residue — **không trộn**.
- Cần đo tiếp để chốt: ramp 10→20 q/s tìm trần sụp; recall single-qwen8b replicate trên full corpus;
  multiagent accuracy dưới tải.
