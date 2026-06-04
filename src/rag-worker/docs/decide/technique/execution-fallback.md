# Execution placement & fallback policy technique

> Cách đẩy task nặng sang stateless helper, và fallback khi helper sập — **không tái tạo lỗi v1**.
> Grounded trong [../../handoff/](../../handoff/). **Không ★** = bắt buộc; **★** = quyết định v2 → [../NEW_REPO_DECISIONS.md](../NEW_REPO_DECISIONS.md).

## 0. Phân biệt 2 loại fallback (cốt lõi)

| Loại | Ví dụ | Handoff |
|---|---|---|
| **Correctness-degrading** | backend chính chết → mock/in-memory/file rồi báo ok | 🔴 **CẤM** (im lặng) — fail-closed |
| **Locality/capacity** | remote helper chết → chạy **cùng job** trên main | ✅ **Được phép** — kết quả giống hệt, chỉ khác nơi chạy |

Fallback ở đây thuộc loại 2 (correctness-safe). Handoff còn khuyến khích: *"policy per-dependency (cái nào degrade được, cái nào fail-closed)"* ([CONSTRAINTS §2](../../handoff/CONSTRAINTS.md)).

## 1. Cái bẫy: fallback compute nặng về main = tái tạo lỗi v1

Cả lý do tách helper là gỡ CPU-heavy/rate-limited khỏi main. Helper sập (thường vì tải cao) → đổ việc về main → **main tự bóp nghẹt serving/claim** = đúng threadpool saturation v1, vào lúc tệ nhất → cascade.

→ Fallback **không mặc định là "chạy trên main"**. Phân theo đường:

| Đường | Fallback đúng |
|---|---|
| **Ingest** (parse/caption/ingest-embed) — async, qua durable queue + claim | **KHÔNG đổ về main.** Task **ở yên trong queue**, retry, autoscale helper, health degraded. *Backpressure là fallback.* |
| **Search query-embed** — latency-sensitive, user đang chờ | **Local fallback CÓ giới hạn** để search không chết — bounded + visible |

Idempotency (id deterministic + atomic claim + atomic-safe replace) làm retry remote/local an toàn — đây là nền tảng cho toàn bộ sự linh hoạt.

## 2. Khung thiết kế (hexagonal)

```
Contract:          Parser / Embedder / Captioner
Adapters:          RemoteAdapter (helper pool)  +  LocalAdapter (in-process, bounded)
Composition root:  wire theo env
Router/policy:     prefer Remote → circuit-breaker → fallback policy (per capability + path)
```

## 3. Sáu quy tắc bắt buộc (để fallback không thành "magic che lỗi")

1. **Circuit breaker per capability** — remote lỗi/timeout vượt ngưỡng → mở circuit → áp policy fallback; probe định kỳ đóng lại. Không retry-mù mỗi request.
2. **Circuit OPEN → PAUSE claim, KHÔNG hot-requeue loop.** Phân biệt 2 trạng thái:
   - *task chưa claim*: circuit open ⇒ **ngừng claim** queue tương ứng (Q1 cho parse, Q2 cho ingest-embed); task **ở yên pending**, health = `queued-degraded`. Tránh vòng lặp nóng claim→fail→requeue→claim.
   - *task đã claim rồi remote mới lỗi*: **release + requeue với backoff/delay** (không trả ngay).
3. **Visible, không im lặng** — health lộ mode: `remote` / `local-fallback` / `queued-degraded` + lý do. Đúng-kết-quả KHÔNG có nghĩa được giấu (handoff: degraded phải thấy).
4. **Bounded executor cho local fallback** — cap concurrency rất thấp (1–2), executor **riêng**; thà chậm còn hơn cascade. **Local search-embed chỉ hợp lệ khi vector-compatible** (cùng model/dimension/space với collection Qdrant — nếu không, query vào sai không gian = kết quả rác; xem [embedding.md](./embedding.md) §4).
5. **Policy là config tường minh** — per-capability + per-path: cái nào local-fallback, cái nào pause-claim, cái nào fail-closed. Không hardcode, không auto-heal ngầm ("giảm magic").
6. **Uniform dispatch, specialized pools** — main có giao diện dispatch task thống nhất, sau lưng là **pool chuyên biệt** (CPU box parse, network box embed). Đừng làm 1 helper "làm mọi thứ".

## 4. Bảng policy mẫu (★ điều chỉnh theo nhu cầu)

| Capability | Path | Prefer | Circuit OPEN → |
|---|---|---|---|
| Parse | ingest (async) | Remote pool | **pause claim Q1** + autoscale + `queued-degraded` (KHÔNG local-parse) |
| Caption | ingest (async) | Remote/Gateway | **pause claim Q2** + `queued-degraded` |
| Embed | ingest (async) | Remote/Gateway | **pause claim Q2** + `queued-degraded` |
| Embed | search (sync) | Remote/Gateway (fast-path) | **bounded local fallback** *nếu vector-compatible* + degraded |

> *task đã claim mà remote lỗi giữa chừng* → release + requeue **với backoff**, không trả tức thì.

## 4b. Backend abstraction + execution modes (MVP-first, không rewrite core)

**Làm NGAY (rẻ, high-value):** capability interface từ ngày 1 — orchestrator gọi qua `Backend`, KHÔNG hardcode SDK trong main.

```
class ParserBackend:  async def parse(object_key, options) -> ParseResult
  LocalParserBackend  (process pool in-node)
  RemoteParserBackend (HTTP/gRPC → parser server)
orchestrator: backend = router.pick("parse_pdf"); await backend.parse(...)
```

**Mode tường minh (explicit, không thừa kế ngầm):**

| Mode | Backend | Fallback | Dùng cho |
|---|---|---|---|
| `single-node` | local, concurrency thấp (chừa CPU cho API/queue/DB) | local bounded | MVP / dev / small tenant |
| `hybrid` | prefer remote | local **rất hạn chế** (vd parse=1) | chuyển tiếp |
| `distributed` | chỉ remote pool (box riêng có thể bão hòa CPU) | **pause claim / requeue**, KHÔNG đổ về main | production scale |

## 4c. Phân phối task qua nhiều server — đừng mặc định tự viết scheduler

Cần "tận dụng tổng cores nhiều server" → 3 cách, nhẹ → nặng:

| Cách | Khi nào | Hạ tầng |
|---|---|---|
| **(a) LB / K8s Service** trước Deployment parser **đồng nhất** | server giống capability | gọi 1 URL, K8s autoscale CPU/queue — **zero registry tự viết** ← default |
| **(b) Pull model** (worker pull từ parse-queue) | muốn backpressure tự nhiên | queue lo phân phối |
| **(c) Capability registry + capacity scheduler + heartbeat** | server **heterogeneous capability** (máy A có OCR, B không) → route capability-aware | nhiều shared state phải giữ đúng |

→ **(c) chỉ đáng khi server khác capability.** Đồng nhất thì (a)/(b) cho cùng kết quả mà không phải viết scheduler (tránh đẻ lại lớp bug claim-race/staleness). "Đừng build scheduler trước khi có gì để schedule."

🔴 **Heartbeat = hiệu quả routing, KHÔNG phải correctness.** Heartbeat có thể stale/split-brain (server sống nhưng heartbeat trễ → mark dead → task chạy 2 lần). Correctness vẫn ở **atomic claim + id deterministic + idempotent**; heartbeat chỉ để chọn server còn rảnh.

## 5. ★ cần ratify → [../NEW_REPO_DECISIONS.md](../NEW_REPO_DECISIONS.md)
- Pluggable execution (remote/local adapter + router) + bảng fallback policy per-capability
- Circuit-breaker + health-mode contract

## Truy vết handoff
[CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §2 (fallback per-dependency, degraded visible) · [MINDSET.md](../../handoff/MINDSET.md) §1,4 · [LESSONS.md](../../handoff/LESSONS.md) §2 · [concise.md](../concise.md) §6,7
