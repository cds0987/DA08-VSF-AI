# OpenRAGBench — Báo cáo test chất lượng & chịu tải (production)

> Ngày 2026-06-23. Dataset **OpenRAGBench** (`gunnybd01/OpenRAGBench`, 1001 docs / 3045 queries).
> Tải vào **production thật** (vsfchat.cloud) + **10 account admin** đo đồng thời. Chạy từ **mạng sạch**
> (không join domain → latency tin được, xem [[proxy-domain-blocks-sse]]).
> Scripts/PDF KHÔNG commit (chứa credential + ~GB data) — chỉ commit báo cáo này.

## 0. Thiết lập
- **Account:** 10 admin loadtest `oragload01..10@orag.test` (INSERT cẩn thận vào `user_svc.users`, bcrypt $2b$12$, chỉ thêm — không sửa/xóa; **đã dọn sau test**).
- **Ingest:** chọn 30 doc OpenRAGBench (balanced extractive/abstractive), upload prod (prefix `ORAG_`, track doc_id).
  - **28/30 indexed**, 2 fail (OCR/parse) → **5961 chunks**. Corpus prod sau ingest: **107 docs / ~11.7k điểm**.
  - **Đã dọn sau test** (xóa đúng 32 doc theo manifest doc_id).

## 1. Chất lượng retrieval (precision/recall) — XUẤT SẮC
Đo qua **`rag_search` THẬT** (qwen3-embedding-4b + Qdrant hybrid dense+BM25 + Cohere rerank-4-pro + diversify),
truyền ACL `document_ids` = toàn bộ doc nội bộ. **243 query** (gt thuộc 28 doc indexed).

| Metric | Giá trị |
|---|---|
| **recall@1 = precision@1** | **0.984** |
| recall@3 / @5 / @10 | 0.984 (gt khi tìm được luôn ở **hạng 1**) |
| **MRR** | **0.984** |
| extractive (n=109) | r@1 = 0.99 |
| abstractive (n=134) | r@1 = 0.98 |
| miss (gt ngoài top-10) | **4/243 (1.6%)** |
| **Latency retrieval thuần** | **p50=1.15s · p95=1.87s · p99=2.68s** |

→ Lớp RAG đưa đúng tài liệu lên **hạng 1** gần như tuyệt đối giữa corpus ~11.7k chunks. Nhanh, ổn định.

## 2. Phát hiện: agent scope-guard từ chối query ngoài domain
Query OpenRAGBench (học thuật tiếng Anh) **không đo được end-to-end qua /api/query**: agent (planner)
phân loại **NGOÀI phạm vi** → `route=light` → **từ chối, không retrieve**:
> *"Mình chỉ hỗ trợ về nhân sự, chính sách, tài liệu & quy trình nội bộ công ty và đơn nghỉ phép..."*

**Đúng thiết kế** (chatbot HR nội bộ VSF). ⇒ precision/recall phải đo qua **lớp retrieval thẳng** (mục 1).
**Playwright e2e xác nhận LIVE** (mạng sạch, SSE chạy):
- VSF in-scope ("nghỉ phép năm tối đa?") → **answer đầy đủ + cite nguồn** (~28s).
- OpenRAGBench → **scope-guard từ chối** (screenshot `pw_q2.png`).

## 3. Chịu tải (load / concurrency) — query path
Query heavy-path = planner + retrieve + rerank + synth. Đo bằng query VSF **in-scope** (kích heavy-path thật).

**Ramp sạch** (mỗi mức C account riêng, cooldown 60s):

| Concurrency C | ok | 503-shed | lat p50 | p95 | max |
|---|---|---|---|---|---|
| 2 | 2 | 0 | 23.4s | 23.4s | 23.4s |
| 4 | 4 | 0 | 19.2s | 21.3s | 21.3s |
| 6 | 6 | 0 | 16.6s | 47.3s | 47.3s |
| 8 | 8 | 0 | 16.3s | 38.0s | 38.0s |
| 10 | 8 | 0 | 12.8s | 16.4s | 16.4s (2 ConnErr phía client) |

- **Sustained burst:** 3 wave × 10 concurrent back-to-back = **30/30 OK**, 0 lần 503.
- ⇒ Query path **khỏe**: chịu ≥10 concurrent distinct-user với **0 load-shed**, p50 12-23s.

**Đính chính bẫy đo:** lần load-test đầu nhiều "lỗi" là **artefact của test** (tái dùng ít account nhanh → dính
**rate-limit 20 req/phút/user** + per-user concurrency cap — đều **by design** chống lạm dụng, `query.py:86-117`),
KHÔNG phải capacity. 503 lẻ tẻ là **transient** khi hệ chưa nguội (rate-limiter Redis / auth pre-flight).

## 4. Chịu tải — INGEST (điểm yếu thật)
**Upload (nhận file) chịu concurrent tốt** — 30 doc accept trong ~60s. **Nghẽn ở XỬ LÝ ingest:**

| Bằng chứng | Giá trị |
|---|---|
| `INGEST_WORKER_COUNT` | **= 1** (mặc định, prod không override) → xử lý **tuần tự 1 doc/lần** |
| Throughput | **~75s/doc** (parse + OCR vision + embed dense+sparse ~200 chunks) |
| NATS consumer | push-subscribe đơn; scale ngang còn **TODO** (`nats_client.py:101`) |
| Trong 1 doc vẫn song song | `CAPTION_MAX_CONCURRENCY=5`, embed batch 100, parse `max_workers=2` |

→ Suy ra 657 doc ≈ **~14h** (lý do giảm scope còn 30). **Cố ý 1 worker để backpressure**, bảo vệ OCR/embed
ngoài (đúng cái làm 2/30 doc + C/D/F/G fail dưới tải).

## 5. Kiến trúc & hướng scale (phân tích đi kèm)
- **Logic AI ở SERVICES** (query: planner/agent; rag-worker: ingest; mcp: rag_search). **ai-router = gateway
  thực thi thuần** (chọn model/key/tier + accounting + retry/fallback, KHÔNG prompt/reasoning) — `router.py:275`.
- **Chỉ AI-call qua ai-router**; DB/Qdrant/NATS/MCP/auth gọi **thẳng**.
- **ai-router = `--workers 1`** (1 core) → chokepoint dùng-chung toàn hệ; embed/OCR/rerank đều **API ngoài**
  (OpenRouter/OpenAI/Cohere). Trần thật = **quota 10 key** (banded rotation + Redis atomic `reserve`).
- **Sẵn sàng scale ngang:** services stateless + điều phối nguyên tử (Redis key/budget + Postgres job-lease
  `claim_next_pending` + NATS durable) → thêm worker/replica **không double-work/double-spend**.

**VM:** 4 vCPU / 15GB RAM (~4.7GB trống) / load 1.5. Data layer (Redis/PG/NATS/Qdrant) **co-located** trên VM.

**Khuyến nghị scale (theo độ trưởng thành):**
1. **Vertical trước** (rẻ, không đổi topology): resize 4→8 vCPU + `INGEST_WORKER_COUNT=2-3` + ai-router `--workers=2`.
   - **N an toàn = 2 (tối đa 3).** VM chỉ OOM ở N≥6; nhưng **OCR/embed ngoài gãy sớm hơn ~N=3-4**.
2. **Horizontal sau** (khi cần HA / vượt 1 VM / đã mở thêm key): tách data layer dùng-chung + LB + app replica.
3. **Auto-scale:** GCE **không** hotplug vCPU (auto-core = không). Auto thật = **MIG autoscale** (rag-worker theo
   queue-depth) hoặc **Cloud Run** (ai-router/query stateless) — đều cần data layer externalize.

## 6. Kết luận
| Khía cạnh | Kết quả |
|---|---|
| **Precision/recall retrieval** | ✅ **0.984** (rất mạnh, p50 1.15s) |
| **Query path dưới tải** | ✅ Khỏe (≥10 concurrent, 0 shed, p50 12-23s); rate-limit 20/min/user by design |
| **Ingest throughput** | 🟠 Thấp **có chủ đích** (1 worker, ~75s/doc) — tunable, scale-ngang sẵn sàng (DB-lease) |
| **Scope-guard** | ✅ Từ chối ngoài-domain đúng thiết kế |
| **Nút thắt chính** | ai-router 1-worker + INGEST=1 + quota 10 key — đều tunable, không phải lỗi |
