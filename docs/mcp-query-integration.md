# Tích hợp `rag_search`: query-service ↔ mcp-service

> Phạm vi: nối **query-service (MCP client)** với **mcp-service (MCP tool server)** cho tool `rag_search`.
> `hr_query` **đã được implement** ở mcp-service dưới dạng **HTTP proxy** sang hr-service (`POST /hr/query`), mặc định TẮT (`TOOL_HR_QUERY_ENABLED=0`) — không nằm trong phạm vi tài liệu `rag_search` này. Xem `docs/contracts.md` (section hr-service) + `src/hr-service/docs/`.
> Trạng thái hiện tại: ✅ **Tích hợp đã hoàn tất hai phía.** mcp-service: LLM reranker + endpoint `/mcp` + fail-closed (commit `56489bd`/`78943f3`). query-service: **real MCP client đã wire** (`MCPStreamableHttpClient`, `MCP_MODE=real` trong prod); field URI dùng `*_gcs_uri` (giữ `*_s3_uri` chỉ làm fallback đọc). e2e CI rag-worker→mcp→query **xanh**.

---

## 1. Bối cảnh kiến trúc

```
                  document_ids (no-op ở search tool)
query-service  ─────────────────────────────────────►  mcp-service ──HTTP POST /api/search──►  rag-worker
(MCP client)   rag_search(query, document_ids, top_k)   (MCP tool :8003)   {query,document_ids,top_k}   (:8000 nội bộ)
                                                              │                                        │ embed query
   ◄──────────────────────────────────────────────────       │ rerank candidates      candidates ◄────┘ + vector search Qdrant
        List[SearchResult]  (đã rerank, top-k)                ▼                          (CHƯA rerank)
```

- **query-service**: gọi `rag_search`, có thể truyền `document_ids` xuống. Tham số nhạy cảm do client inject, **không tin LLM**.
- **mcp-service**: THIN interface — gọi **rag-worker `POST /api/search`** (rag-worker embed query + vector search Qdrant → candidates), rồi **rerank** → trả top-k. mcp KHÔNG embed/đọc Qdrant; ghép với rag-worker qua **HTTP** (field candidate map 1:1).
- **ACL / lọc theo `document_ids` KHÔNG phải việc của search tool** — đó là trách nhiệm của service khác. Search tool chỉ **nhận `document_ids` để không crash** (no-op), không filter. Xem mục 5.1.
- Giao thức: **MCP Streamable HTTP**.

---

## 2. Trạng thái hiện tại

| Thành phần | Có gì | Thiếu gì |
|-----------|-------|----------|
| query-service | ✅ `MockMCPClient` (test) **+ real `MCPStreamableHttpClient`**; `MCP_MODE=mock\|real` (prod `real`); field `*_gcs_uri` (s3 chỉ fallback đọc); orchestration (ACL→cache→search→threshold→top-3→LLM) | — |
| mcp-service | ✅ Tool `rag_search` thật; **LLM reranker + fallback**; endpoint `/mcp` công bố; fail-closed; README runtime contract; e2e CI xanh | — |
| docs | contract shape `SearchResult`; file này; README mcp-service; `contracts.md` đã khớp code | — |

### Đã khớp ✅
- Chữ ký `rag_search(query, document_ids, top_k=5)` đồng nhất ở Protocol / mock / tool thật.
- Shape `SearchResult` (trừ field URI): `chunk_id, document_id, document_name, caption, parent_text, heading_path, score, page_number`.
- Luồng query-service hoàn chỉnh + có test.
- `document_ids` là no-op trong search tool — **đúng thiết kế** (ACL do service khác lo), không phải bug.
- **rag-worker → mcp-service qua HTTP `/api/search` đã chứng minh end-to-end trên CI** (full validation corpus, mục 11).

### Blocker còn lại — ✅ ĐÃ XỬ LÝ XONG
1. ~~Field URI lệch tên~~ → query-service đọc `*_gcs_uri` (giữ `*_s3_uri` làm fallback).
2. ~~Chưa có real MCP client~~ → đã wire `MCPStreamableHttpClient`, prod `MCP_MODE=real` (mục 6.1/6.2).

---

## 3. Contract chốt (nguồn sự thật)

Tool MCP:

```python
rag_search(
    query: str,
    document_ids: Optional[List[str]] = None,   # NHẬN nhưng search tool KHÔNG filter (no-op); ACL do service khác
    top_k: int = 5,
) -> List[SearchResult]
```

`SearchResult` (shape thống nhất 2 bên — đã chốt `gcs`):

```python
chunk_id: str
document_id: str
document_name: str
caption: str
parent_text: str
heading_path: List[str]
score: float
page_number: Optional[int] = None
source_gcs_uri: str = ""        # ✅ CHỐT: dùng GCS (bỏ s3) — xem mục 4
markdown_gcs_uri: str = ""      # ✅ CHỐT: dùng GCS (bỏ s3)
```

---

## 4. ✅ Đã chốt: tên field URI = `gcs` (bỏ s3)

**Quyết định: dùng GCP, tên field là `source_gcs_uri` / `markdown_gcs_uri`** — khớp contract (`contracts.md`) + payload rag-worker + mcp-service hiện tại.

| Bên | Hiện tại | Hành động |
|-----|----------|-----------|
| mcp-service + contracts.md | `source_gcs_uri`, `markdown_gcs_uri` | ✅ giữ nguyên |
| query-service (toàn bộ) | `source_s3_uri`, `markdown_s3_uri` | 🔧 đổi `s3`→`gcs` (mục 6.3) |

> Không còn `s3` ở bất kỳ đâu trong contract search. (Lưu ý: rag-worker vẫn truy cập GCS qua giao thức S3-interop/boto3 ở tầng storage — đó là chuyện nội bộ tầng I/O, KHÔNG liên quan tên field trong `SearchResult`.) Chi tiết: mục 4b.

---

## 4b. Storage / URI: vì sao rag-worker dùng `s3` mà mcp KHÔNG cần

Chữ "s3" xuất hiện ở rag-worker là **SDK ở tầng I/O storage (boto3)**, KHÔNG phải tên field contract. Hai chuyện khác hẳn nhau — đừng nhầm.

### Vì sao rag-worker dùng `s3`
rag-worker là **producer — phải TẢI file gốc về để ingest**, dùng `boto3` ([`s3_parser.py`](../src/rag-worker/app/infrastructure/external/s3_parser.py)):
- **"S3" = giao thức/SDK, không phải dịch vụ AWS.** boto3 chỉ nói giao thức S3; một client phục vụ chung GCS/MinIO/R2/AWS. **Prod là GCS qua S3-interop**: `S3_ENDPOINT_URL=https://storage.googleapis.com` + HMAC key, cùng code đường. Giữ tên `S3_*` (không đổi `GCS_*`) là **chủ ý**: CI chạy MinIO, prod chạy GCS, không phải đổi code.
- Cần SDK này vì có lớp **guard tải an toàn** (HEAD size-check → stream xuống đĩa → đếm byte → semaphore → timeout). Chỉ producer mới cần.
- Giá trị URI lưu vào Qdrant: scheme `s3://bucket/key` (hoặc `gs://`); key payload tên trung lập `source_uri`, `artifact_uri`.

### Vì sao mcp-service KHÔNG cần `s3`
mcp-service nhận candidates từ rag-worker `/api/search` (đã có sẵn URI), **không bao giờ tải file** — và cũng KHÔNG đọc Qdrant trực tiếp nữa:
- [`search.py`](../src/mcp-service/app/core/search.py) + [`models.py`](../src/mcp-service/app/core/models.py) chỉ nhận string URI trong candidate (`source_gcs_uri`, `markdown_gcs_uri`) rồi **truyền thẳng** ra cho FE cite nguồn — KHÔNG fetch.
- `requirements.txt` của mcp-service **không có boto3** và **không cần thêm**.
- → Thêm `boto3`/S3 client vào mcp-service là **dependency thừa**. (Chỉ cân nhắc nếu sau này mcp tự tải markdown để mở rộng context — hiện không có.)

### Điểm lệch cosmetic cần biết
| | Tên | Giá trị |
|---|---|---|
| Payload Qdrant (rag-worker ghi) | `source_uri`, `artifact_uri` (trung lập) | scheme `s3://...` |
| Output mcp (đã chốt) | `source_gcs_uri`, `markdown_gcs_uri` | vẫn là chuỗi `s3://...` |

Field tên `*_gcs_uri` nhưng **value bên trong vẫn `s3://...`**. Vô hại cho cite (chỉ là con trỏ chuỗi). Nếu FE cần link click được, chọn 1:
- **(a)** Để nguyên — tên field là quy ước contract, value là lineage thô. Đơn giản nhất.
- **(b)** Chuẩn hóa scheme `s3://` → `gs://`/HTTPS GCS **ở rag-worker lúc ghi payload**, để value khớp tên `gcs`.

### Chốt
- rag-worker giữ `s3`/boto3 ở tầng I/O — **đúng, không đụng**.
- mcp-service **không thêm s3/boto3**; tên field dùng `gcs` (mục 4).
- Chuẩn hóa scheme value (a/b) là **tùy chọn**, không chặn tích hợp.

---

## 5. Việc cho **mcp-service** — ✅ ĐÃ XONG (commit `56489bd`, `78943f3`)

> Toàn bộ phần thuộc mcp-service đã hoàn thành và có test (`pytest src/mcp-service/tests` = 18 passed)
> + được CI e2e chứng minh (mục 11). Giữ lại chi tiết bên dưới làm tham chiếu.

### 5.1. ✅ `document_ids` — KHÔNG lọc trong search tool (DONE)
- **Search tool KHÔNG làm ACL** — đúng thiết kế. Đã sửa comment/log ở [`app/core/search.py`](../src/mcp-service/app/core/search.py) (bỏ "TODO ACL"), log nói rõ "ACL owned by another service". Có test edge cases `None`/`[]`/list dài không crash.
- **Không** thêm Qdrant filter `document_id`.

### 5.2. ✅ Field URI: giữ `gcs` (DONE)
- mcp-service trả `source_gcs_uri` / `markdown_gcs_uri` ([`mcp_server.py`](../src/mcp-service/app/interfaces/mcp_server.py) `_hit_to_dict`). Việc đổi `s3`→`gcs` còn lại ở query-service (mục 6.3).

### 5.3. ✅ Endpoint MCP công bố (DONE)
- Transport Streamable HTTP, path `/mcp`, `MCP_HOST`/`MCP_PORT` (mặc định `0.0.0.0:8003`). `main` log `transport=streamable-http endpoint=...`. README mcp-service ghi rõ runtime contract + tool shape.

### 5.4. ✅ Fail-closed startup (DONE)
- `verify_contract` chạy trước khi serve; lệch collection/dimension/fingerprint → thoát non-zero. Có test `test_main_fails_closed_when_contract_verify_fails`.

### 5.5. ✅ LLM reranker (DONE — chốt dùng LLM đánh giá lại)
- `LlmReranker` ở [`app/core/rerank.py`](../src/mcp-service/app/core/rerank.py): batch scoring, clamp `[0,1]`, parse JSON; `build_reranker("llm")` không còn raise; config/env hóa (`RERANK_*`).
- **Fallback** về `NoopReranker` (vector order) khi LLM lỗi/timeout + log `rerank_fallback` — **best-effort, có thể trả hit dưới threshold** (đã ghi trong README).
- `lexical`/`none` chỉ dùng CI/offline.

---

## 6. Việc cho **query-service** — ✅ ĐÃ XONG

### 6.1. ✅ Real MCP client (DONE)
- File mới: `app/infrastructure/external/mcp_client_real.py` (hoặc mở rộng [`mcp_client.py`](../src/query-service/app/infrastructure/external/mcp_client.py)).
- Implement Protocol `MCPToolClient` ([`app/application/ports.py`](../src/query-service/app/application/ports.py)):
  - Kết nối MCP Streamable HTTP tới URL mcp-service (mục 5.3).
  - `rag_search(query, document_ids, top_k)` → gọi tool MCP, map kết quả về `SearchResult`.
  - `list_tools()` → liệt kê tool từ server.
  - (Bỏ qua `hr_query` lúc này — có thể raise `NotImplementedError` hoặc tách Protocol.)
- Xử lý lỗi: timeout, mcp-service down → fallback rõ ràng (không làm vỡ luồng chat).

### 6.2. ✅ `MCP_MODE` switch (mock ↔ real) (DONE)
- [`config.py`](../src/query-service/app/infrastructure/config.py) `mcp_mode` (default `mock`) + [`dependencies.py`](../src/query-service/app/interfaces/api/dependencies.py) `get_mcp_client` trả `MCPStreamableHttpClient` khi `MCP_MODE in {real, mcp}`. **Prod: `MCP_MODE=real`.**
- `/health` báo `mcp_service` + ping mcp-service.

### 6.3. ✅ Field URI `gcs` (DONE)
- query-service đọc `source_gcs_uri`/`markdown_gcs_uri` (giữ `*_s3_uri` làm fallback đọc) ở:
  - [`app/application/ports.py`](../src/query-service/app/application/ports.py) (`SearchResultLike`)
  - [`app/infrastructure/external/mcp_client.py`](../src/query-service/app/infrastructure/external/mcp_client.py) (`SearchResult`, mock)
  - [`app/application/use_cases/query/orchestration.py`](../src/query-service/app/application/use_cases/query/orchestration.py) (`_source_payload`)
  - [`app/interfaces/api/schemas/query.py`](../src/query-service/app/interfaces/api/schemas/query.py) (`Source`)
  - mock data + test liên quan.

### 6.4. 🟡 Rà điểm contract nhỏ
- query-service tự cắt `top_results[:3]` ([orchestration.py:100](../src/query-service/app/application/use_cases/query/orchestration.py#L100)) trong khi gọi `top_k=5`. Chốt: rerank top-k do mcp-service quyết hay query-service cắt — tránh cắt 2 lần.
- `rag_score_threshold` lọc ở query-service vs `rerank_threshold` ở mcp-service — chốt ngưỡng nằm ở đâu để không lọc trùng/sai.

---

## 7. Thứ tự thực hiện — ✅ HOÀN TẤT

1. ✅ Field URI chốt `gcs` + mcp-service (LLM reranker, document_ids, endpoint, fail-closed).
2. ✅ query-service đọc field `gcs` (s3 fallback).
3. ✅ query-service real MCP client (6.1) + `MCP_MODE=real` (6.2) → gọi `/mcp` :8003.
4. ✅ Cập nhật `/health` + rà contract (6.4).
5. ✅ `contracts.md` khớp code mcp thật (mục 8).

---

## 8. Docs cần cập nhật theo

- [`docs/contracts.md`](contracts.md) — ✅ **đã sửa khớp code** (đồng bộ 7 intent hr_query: leave_balance/leave_requests/attendance/onboarding/payroll/benefits/performance): section `mcp-service` mô tả search-only (`SearchHit` ở `app/core/vectorstore.py`, reranker Protocol `none|lexical|llm` ở `app/core/rerank.py`, `tool_io.py` chỉ còn `RagSearchInput`); section `hr-service` đủ DTO HR (gồm `BenefitsDTO`/`PerformanceReviewDTO`) + `HrRepository` (gồm `get_benefits`/`get_performance`) + contract `POST /hr/query`; `hr_query` ở mcp-service là HTTP proxy.
- [`src/mcp-service/README.md`](../src/mcp-service/README.md) — ✅ đã cập nhật: runtime contract, tool shape, `hr_query chua implement`.
- File này — ✅ đã cập nhật field `gcs` (mục 3/4) + trạng thái mcp xong + CI e2e (mục 11).

---

## 9. Definition of Done

- [x] mcp-service trả field `*_gcs_uri`; query-service đọc `gcs` (s3 fallback).
- [x] `rag_search` nhận `document_ids` (`None`/`[]`/list dài) không crash; comment/log nói rõ ACL ngoài phạm vi.
- [x] query-service có real MCP client + `MCP_MODE=real` gọi được :8003.
- [x] `/health` query-service báo `mcp_service` và ping OK.
- [x] E2E rag-worker→mcp qua `/api/search` (full corpus) xanh trên CI — mục 11.
- [x] `contracts.md` khớp code thật (README mcp ✅ xong).
- [x] LLM reranker hoạt động (`RERANK_PROVIDER=llm` không còn raise), có fallback khi LLM lỗi.

---

## 10. Ngoài phạm vi (ghi để khỏi quên)

- `hr_query` (tool HR, 7 intent: leave_balance / leave_requests / attendance / onboarding / payroll / benefits / performance) — **đã implement** ở mcp-service như HTTP proxy sang hr-service, mặc định TẮT. Tích hợp phía query-service (real client cho `hr_query`) nằm ngoài tài liệu `rag_search` này.
- Hybrid search (vector + BM25 sparse) — **đã bật ở rag-worker** (`VECTOR_HYBRID=true`, cả khi ghi lẫn khi search `/api/search`); mcp chỉ rerank candidates trả về.

> **Reranker**: chốt dùng **LLM đánh giá lại** (mục 5.5) — đây là việc IN-SCOPE, không phải để sau.
> `lexical`/`none` chỉ dùng cho CI/offline.

---

## 11. E2E CI: rag-worker → mcp-service qua `/api/search` (đã xanh)

Workflow [`.github/workflows/rag-service-ci.yml`](../.github/workflows/rag-service-ci.yml) — job **`search-semantic`** dựng hạ tầng THẬT (NATS + MinIO + Qdrant docker) và chạy luồng 2 service:

```
document-service (GIẢ LẬP)  ──upload MinIO + publish doc.ingest (NATS)──►  rag-worker (THẬT)
   scripts/seed_validation_corpus_e2e.py                                     ingest cả validation corpus
                                                                              -> Qdrant + contract stamp
query-service (GIẢ LẬP)  ──rag_search từng golden query──►  mcp-service (THẬT)
   scripts/e2e_search_validation.py                          verify_contract + search trên CÙNG Qdrant
```

- Service ở giữa **mock bằng message/script**; hạ tầng (Qdrant, MinIO, NATS) **thật**. Ranh giới runtime giữa 2 service là **rag-worker `/api/search` (HTTP)** — mcp gọi vào đó (rag-worker mới là bên embed + đọc Qdrant).
- Phủ **toàn bộ corpus** `src/rag-worker/eval/validation/manifest.json` (7 doc, đủ định dạng txt/md/html/docx/pdf/pptx/xlsx).
- Kết quả CI (commit `adc502e`): seed 7 doc → mcp `SEARCH_OK 7/7` (mỗi query ra đúng doc ở top-1) + **drift fail-closed** pass.
- Offline embedding (CI không có key) → kiểm **plumbing xuyên 2 service** + routing bằng lexical rerank; chất lượng ngữ nghĩa thật cần provider (`RAG_EVAL_REAL_PROVIDER=1`).
- Guard kèm: job `contract` (parity fingerprint rag-worker↔mcp) chặn lệch embed model/collection contract ngay ở PR.
