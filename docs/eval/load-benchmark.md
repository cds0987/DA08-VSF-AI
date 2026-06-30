# Load Benchmark — Sức chịu tải hệ thống (query + ingest)

> Báo cáo đánh giá khả năng chịu tải prod `https://vsfchat.cloud` (1 GCP VM, docker-compose) ở quy mô
> **800–1200 user**. Số liệu hợp nhất + phương pháp: `systemeval/benchmark.md` + `systemeval/testdesign.md`.
> Agent timing: Langfuse `generations.all`. Đo lần đầu **2026-06-29**.

## 1. Kịch bản đo (mô phỏng giờ cao điểm)

| Thành phần | Tải | Quy đổi |
|---|---|---|
| Chat query | 450 câu / 60s (≈7.5 q/s, 3 burst ~14 q/s), 21 account round-robin | nặng gấp ~2× nhịp 1200-user thật |
| Ingest | 40 tài liệu docx/pdf / 60s, đồng thời | đúng giờ cao điểm (20–30 admin uploader) |

Bộ câu hỏi 450 đa dạng: simple_rag 249, multiagent 120,
hr_intent 45, non_rag 36.

## 2. Kết quả

### Chat end-to-end
| Metric | Giá trị |
|---|---|
| Hoàn tất / lỗi | **450/450 · 0 lỗi** (không 429/5xx/timeout) |
| TTFT | p50=19.7s · p95=46.4s |
| Latency e2e | p50=25.3s · p95=57.9s · p99=98.9s · max=321.9s |
| Outcome | SUCCESS 85% · OFF_TOPIC 37 · CLARIFY 20 · NO_INFO 10 |
| Per-type | simple 97% SUCCESS (p95 45s) · **multiagent 71%** (p95 74s) · hr 84% (p95 52s) |

### Agent per-node (Langfuse, dưới peak)
| Agent | n | lat p50 | lat p95 | ghi chú |
|---|---|---|---|---|
| **planner** | 234 | 10s | **35s** | nặng nhất, ~2× baseline — nghẽn gốc |
| verify·answer | 405 | 7s | 24s | prompt nặng (~5.5k tok) |
| embed (ingest) | 40 | 18s | 28s | |
| hr_lookup / leave_action | 30 | 3–8s | 5–21s | nhẹ |

### Ingest (đồng thời)
40/40 indexed, 0 fail · accept p50=1.3s (nhận job nhanh dù chat đang peak) · **e2e p50=60s** p95=70s
(rag-worker single-instance xử lý tuần tự OCR+embed+index) · 3330 chunk.

## 3. Sức chứa — tính theo Little's Law (in-flight = QPS × latency)

| Kịch bản | QPS | latency | in-flight | Kết quả |
|---|---|---|---|---|
| **1200 user thật** (1 câu/4ph) | 5 q/s | ~18s | ~90 pipeline | nội suy: 0 mất, TTFT ~12–15s |
| **Test thực đo** | 7.5 q/s | ~25s | ~188 pipeline | **0/450 mất**, TTFT 19.7s |

**Verdict**:
- ✅ Hệ **thừa sức 800–1200 user active** ở nhịp thật — đã đo gấp đôi (≈1800-user-equiv) vẫn 0 mất
  request; ingest 40 doc/phút OK.
- ⚠️ Giới hạn thực **là latency, không phải số user**: 1200 user → TTFT ~12–15s (dùng được, chậm).
- ❌ Không có tier "mượt <5s" — sàn kiến trúc ~7s/câu (luôn chạy plan+answer LLM) kể cả lúc rảnh.
- Trần SỤP thật chưa chạm; ở 7.5 q/s tail đã p99=99s, max=322s → cần ramp 10→20 q/s để xác định.

## 4. Nghẽn & đòn bẩy (theo tác động)

Nghẽn = **tầng agent reasoning xếp hàng** (planner p95=35s + answer p95=24s), **KHÔNG phải** rate-limit/
gate/HTTP (0 lỗi). Muốn nhanh hơn hoặc gánh nhiều nghìn user → scale tầng reasoning, không phải VM chung.

1. **Scale tầng reasoning** (replica query-service / planner model nhanh hơn) — cắt trực tiếp p95.
2. **Bỏ/cache plan cho simple_rag** — triage thẳng RAG, không cần planner đầy đủ.
3. **Soi multiagent 71% SUCCESS** dưới tải (verify timeout / worker partial) — sửa accuracy.
4. **Scale rag-worker ingest** (đa instance / tách OCR-vision) — hạ e2e 60s/doc.

## 5. Caveat
- Số 1200-user là **nội suy** từ mức đo 7.5 q/s; đo đúng 5 q/s (300 câu/60s) để chốt.
- Qdrant lúc đo có residue (≥262 doc) → trọng tâm là latency/throughput/độ bền + outcome, **không phải
  recall@k tuyệt đối** (đo recall trên corpus sạch riêng).
- Chi tiết phương pháp + số liệu hợp nhất: `systemeval/testdesign.md` + `systemeval/benchmark.md`.
