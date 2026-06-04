# Search technique — luồng ĐỌC

> Mô tả kỹ thuật cụ thể cho [../diagram/search.mermaid](../diagram/search.mermaid).
> Grounded trong [../../handoff/](../../handoff/). Ký hiệu: **không ★** = bắt buộc theo handoff; **★** = quyết định v2 ngoài/để-ngỏ trong handoff → ghi `PROPOSED` vào `NEW_REPO_DECISIONS.md` trước khi chốt.

## 0. Mục tiêu

Trả về *đơn vị tri thức hoàn chỉnh* khớp theo **ý định** (semantic), kèm lineage để tầng trên grounding mà không bịa. Rủi ro lớn nhất không phải "chết" mà là *"trả kết quả sai mà caller tưởng đúng"* → degraded phải nhìn thấy được.

---

## 1. Pipeline đọc (stages)

```
Query (+correlation id)
  → Embed query (CÙNG embedder/coalescer với ingest)
  → Vector search semantic (Qdrant)
  → ★ Hybrid + Rerank (Open Q — bù caption-only)
  → ★ Resolve content_ref → full content (chỉ khi payload là ref)
  → Result (full content + lineage + score + correlation id)
  → Consumer (access control ở caller)
```

---

## 2. Embed query

Dùng **đúng cùng embedder + cùng model/dimension** với ingest. Khác model/dimension giữa ingest và search ⇒ lệch không gian vector ⇒ recall vô nghĩa. Đi qua cùng coalescer để tận dụng cache + rate-limit policy; chú ý áp lực embed của search cần được lộ qua health.

---

## 3. Vector search

- khớp **ý định** (semantic), không khớp từ khoá
- ngưỡng `score` tối thiểu; nếu không đủ context → **no-answer policy** (trả rỗng/he-thong-bao thiếu grounding, KHÔNG bịa)
- trả về theo `section` (đơn vị nghĩa), không trả mảnh token

---

## 4. ★ Hybrid + Rerank (Open Question — bù rủi ro caption-only)

Vì vector = embedding(*caption*), section dài nhiều ý có thể bị caption nuốt mất chi tiết quan trọng. Ví dụ section nói về `pricing, auth, retry, rate limit, timeout` mà caption chỉ tóm "API operational constraints" → query "timeout 30s" dễ miss.

Cách bù (production nên có ít nhất một):
- **hybrid**: BM25/full-text trên *full content* song song với vector → hợp nhất kết quả
- **rerank**: lấy top-K theo vector rồi rerank bằng *full content* (cross-encoder)
- (tùy chọn) embed thêm key facts/keywords bên cạnh caption

Đây là Open Question caption-only vs hybrid trong [../concise.md](../concise.md) §11; handoff cho phép xem lại khi đo được caption làm mất recall ([../../handoff/MINDSET.md](../../handoff/MINDSET.md) §3). Mọi thay đổi rerank/policy phải qua eval gate (§6).

---

## 5. ★ Resolve content_ref → full content

Chỉ áp dụng nếu chọn lưu `content_ref` cho section lớn (xem [ingestion.md](./ingestion.md) §8). Khi đó:
- payload Qdrant chứa `content_ref` (vd `artifact://document_id#section_id`) + preview + `content_hash`
- search **bắt buộc** fetch full content từ canonical artifact trước khi trả

> 🔴 **Ràng buộc cứng:** response phải chứa *nội dung đầy đủ* + *cả hai lineage URI* ([../../handoff/CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §2). content_ref chỉ là tối ưu lưu trữ; nếu trả ref thay full content cho consumer là **vỡ contract**. Vì vậy đây là ★ phải cân nhắc thêm read-dependency vào artifact store.

---

## 6. Result — response schema là CONTRACT

Mỗi kết quả trả về phải đủ (không bỏ field, không đổi tên; breaking ⇒ version hóa + báo consumer):

| Field | Mô tả |
|---|---|
| `correlation_id` | ID duy nhất cho **request** — trace log xuyên suốt các service (echo trong mỗi result) |
| `unit_id` | Định danh đơn vị (section) — deterministic theo `document_id` + `section_order` |
| `document_id` | Định danh document — deterministic theo địa chỉ nguồn |
| `display_name` | Tên hiển thị của section |
| `caption` | Tóm tắt nén — thứ đã được embed để search |
| `content` | Nội dung đầy đủ của section — AI Team dùng làm grounding context |
| `heading_path` | Đường dẫn phân cấp (breadcrumb) |
| `lineage.artifact_uri` | URI canonical artifact đã xử lý |
| `lineage.source_uri` | URI file gốc — dùng để tạo citation |
| `score` | Điểm similarity |

> Tên field cụ thể là lựa chọn của repo v2; *tập field* trên là contract cứng theo [../../handoff/CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §2.
> - `correlation_id` là **per-request** (echo trong từng result để consumer trace dễ).
> - `content` phải là **nội dung đầy đủ** kể cả khi payload dùng `content_ref` (§5 resolve trước khi trả) — trả preview/ref là vỡ contract.
> - ★ Nếu bật rerank (§4), có thể bổ sung `rerank_score` bên cạnh `score` (vector similarity) — optional, không thuộc contract cứng.

**Access control / filtering** là việc của **caller tầng trên**. Retrieval layer trả raw unit + lineage, *để sẵn* field `scope`/`tags` nhưng **KHÔNG enforce** (giữ ranh giới trách nhiệm — [../../handoff/LESSONS.md](../../handoff/LESSONS.md) §1 discovery).

---

## 7. Cross-cutting

**Health/readiness (search)** — fail-closed: vector backend lỗi ⇒ unhealthy + lý do; lộ áp lực embed của search. Không báo ok khi degraded.

**Eval gate** — kiến trúc đúng chưa đủ; phải đo chất lượng:
- golden queries + expected source lineage cho từng câu
- tiêu chí recall / precision / no-answer / source correctness
- latency p50/p95 cho search
- phát hiện hallucination / câu trả lời thiếu grounding
- chặn merge mọi thay đổi parser/caption/model/index/search policy/**rerank**
- có owner + tần suất chạy lại

---

## 8. Đặc tính vận hành

- **Latency budget**: embed query + vector search + (★rerank) + (★resolve); rerank và resolve thêm độ trễ → đo p95.
- **Backpressure**: search chia sẻ embedder với ingest → cần limit/áp lực riêng để ingest nặng không làm search timeout (bài học async nửa vời).
- **No-answer** đúng nghĩa quan trọng hơn cố trả một kết quả yếu.

---

## 9. Config keys (đề xuất)

```
SEARCH_TOP_K
SEARCH_SCORE_THRESHOLD
NOANSWER_POLICY
RERANK_ENABLED / RERANK_MODEL        # ★
HYBRID_BM25_ENABLED                  # ★
RESOLVE_CONTENT_REF                  # ★
EMBED_MODEL / EMBED_DIMENSION         # phải khớp ingest
```

---

## 10. ★ cần ratify (đưa vào NEW_REPO_DECISIONS.md)

- Caption-only vs hybrid/rerank (và model rerank)
- content_ref resolve + ngưỡng kích thước section
- no-answer policy + ngưỡng score cụ thể theo corpus

## Truy vết handoff
[CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §2 (response schema, eval gate) · [MINDSET.md](../../handoff/MINDSET.md) §1–3 · [DAY0_CHECKLIST.md](../../handoff/DAY0_CHECKLIST.md) §13 · tổng hợp [../concise.md](../concise.md)
