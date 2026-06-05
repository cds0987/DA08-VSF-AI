# mcp-service — Việc cụ thể cần làm để tích hợp `rag_search`

> Tài liệu này chỉ liệt kê **phần việc của mcp-service**. Bối cảnh tích hợp tổng thể + phần
> query-service: xem [`docs/mcp-query-integration.md`](../../../docs/mcp-query-integration.md) (root repo).
>
> Quyết định đã chốt (không bàn lại trong file này):
> - Field URI = **`gcs`** (`source_gcs_uri` / `markdown_gcs_uri`) — mcp giữ nguyên.
> - **ACL không phải việc của search tool** — `document_ids` nhận nhưng KHÔNG filter.
> - Reranker prod = **LLM đánh giá lại**.
> - mcp **không** thêm `boto3`/s3 (consumer chỉ-đọc Qdrant).

Mức ưu tiên: 🔴 chặn tích hợp · 🟠 cần cho prod · 🟡 nên làm.

---

## T1. 🟠 Port LLM reranker (dùng LLM đánh giá lại)

**File:** [`app/core/rerank.py`](../app/core/rerank.py) · config [`config.yaml`](../config.yaml)

Hiện trạng: `build_reranker("llm")` đang `raise NotImplementedError`; chỉ có `NoopReranker` (`none`) và `LexicalReranker` (`lexical`).

**Cần làm:**
1. Thêm class `LlmReranker` implement Protocol `Reranker`:
   ```python
   def rerank(self, query: str, hits: List[SearchHit], top_k: int, threshold: float) -> List[SearchHit]:
   ```
   - Gửi `(query, [hit.caption + "\n" + hit.parent_text])` cho LLM chấm điểm liên quan 0..1.
   - Nên chấm **theo batch** (1 call cho N candidate) để giảm số request; parse điểm về từng hit.
   - Gán `hit.score = điểm LLM`, lọc `>= threshold`, sort giảm dần, cắt `top_k`.
2. `build_reranker("llm")` trả `LlmReranker(...)` thay vì raise.
3. **Cấu hình qua config/env** (KHÔNG hard-code key): model id, endpoint/gateway, timeout, batch size. Dùng AI provider/gateway sẵn có của service.
4. **Fallback bắt buộc** khi LLM lỗi/timeout: rớt về `NoopReranker` (giữ thứ tự vector score), **log cảnh báo**, KHÔNG để vỡ `rag_search`.
5. Cân chi phí/độ trễ: rerank chạy trên `top_k_candidates` (số lấy từ Qdrant). Đảm bảo con số này hợp lý (vd 20–50), đừng đẩy cả trăm candidate vào LLM.

**Test:**
- Unit: mock LLM trả điểm cố định → đúng thứ tự + cắt `top_k` + lọc `threshold`.
- Unit: LLM raise/timeout → fallback noop, không raise ra ngoài.
- CI/offline vẫn dùng `RERANK_PROVIDER=none|lexical` (không gọi mạng).

**Done khi:** `RERANK_PROVIDER=llm` chạy được, có fallback, có test.

---

## T2. 🟡 Dọn `document_ids` cho đúng thiết kế (KHÔNG thêm filter)

**File:** [`app/core/search.py`](../app/core/search.py) (`SearchService.rag_search`, đoạn TODO ACL)

Hiện trạng: `rag_search` nhận `document_ids` nhưng no-op, kèm comment/log *"TODO ACL — KHÔNG để lọt production"* → gây hiểu nhầm là thiếu sót.

**Cần làm:**
1. Giữ no-op (đúng thiết kế: ACL do service khác lo). **KHÔNG** thêm Qdrant filter `document_id`.
2. Sửa comment + log: bỏ "TODO ACL / không để lọt production", thay bằng ý rõ ràng:
   > `document_ids` nhận để tương thích chữ ký MCP; lọc quyền document KHÔNG thuộc search tool — do service khác đảm nhiệm.
3. Bảo đảm **không crash** với mọi input: `None`, `[]`, list rất dài, phần tử rỗng/trùng.

**Test:**
- `rag_search` với `document_ids=None | [] | [".."]*1000` đều trả bình thường, không lỗi.

**Done khi:** không còn chữ "TODO ACL" gây hiểu nhầm; input biên không crash.

---

## T3. 🟡 Xác nhận & ghi rõ endpoint MCP cho client

**File:** [`app/interfaces/mcp_server.py`](../app/interfaces/mcp_server.py), [`app/main.py`](../app/main.py)

**Cần làm:**
1. Chốt và ghi vào README/config:
   - Host/port: `MCP_HOST` / `MCP_PORT` (mặc định `0.0.0.0:8003`).
   - Transport: **Streamable HTTP**.
   - URL đầy đủ client cần gọi (vd `http://mcp-service:8003/mcp` — xác nhận path thật của FastMCP).
   - Tên tool: `rag_search`; chữ ký `(query, document_ids?, top_k=5)`.
2. Output `rag_search` = `list[dict]` đúng shape `SearchResult` với field `*_gcs_uri` ([`_hit_to_dict`](../app/interfaces/mcp_server.py)).

**Done khi:** query-service dev có đủ URL + tool name + shape để viết real MCP client mà không phải hỏi.

---

## T4. 🟡 Healthcheck / contract verify khi startup

**File:** [`app/main.py`](../app/main.py), [`app/core/search.py`](../app/core/search.py) (`verify_contract`), [`app/core/vectorstore.py`](../app/core/vectorstore.py)

Hiện trạng: đã có `verify_contract` fail-closed (check collection tồn tại + vector dim + stamp).

**Cần làm:**
1. Đảm bảo `main` **gọi `verify_contract` trước khi serve** (fail-closed): Qdrant chưa có collection (rag-worker chưa ingest) hoặc lệch dimension → log rõ + thoát/loud, không serve âm thầm.
2. (Tùy chọn) expose 1 endpoint/health nhẹ để orchestration/query-service ping được mcp-service (phục vụ `/health` của query-service báo `mcp_service=real`).

**Done khi:** startup fail rõ ràng khi contract lệch; có cách ping liveness.

---

## T5. 🟡 Cập nhật docs mcp-service cho khớp code thật

**File:** [`README.md`](../README.md), và phối hợp sửa [`docs/contracts.md`](../../../docs/contracts.md) (root)

Hiện trạng lệch:
- README ghi `rag_search / hr_query` — nhưng code **chỉ có `rag_search`**.
- `contracts.md` mô tả mcp-service theo DDD (`app/domain/...`, `RerankService` BGE, `hr_repository`) — code thật là `app/core/*`, search-only.

**Cần làm:**
1. README: bỏ `hr_query` hoặc ghi rõ **"chưa implement"**.
2. contracts.md (cần SA): cập nhật section mcp-service mô tả đúng `app/core/*`, reranker `none|lexical|llm`, đánh dấu `hr_query` = "chưa làm".

**Done khi:** docs khớp code; không còn nhắc tính năng chưa tồn tại như đã có.

---

## Ngoài phạm vi (KHÔNG làm trong đợt này)
- `hr_query` (tool HR) — tạm gác.
- Lọc ACL theo `document_ids` — không phải việc search tool.
- Thêm `boto3`/s3 client — mcp không tải file, không cần.
- Hybrid search (vector + BM25 RRF) — v1 chỉ vector + rerank.

---

## Checklist nhanh
- [ ] T1 — LLM reranker chạy + fallback + test.
- [ ] T2 — `document_ids` no-op rõ ràng, input biên không crash.
- [ ] T3 — endpoint/tool/shape đã ghi rõ cho client.
- [ ] T4 — verify_contract gọi lúc startup, có liveness.
- [ ] T5 — README + contracts.md khớp code thật.
