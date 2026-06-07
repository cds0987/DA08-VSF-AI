# rag-worker = INGEST-ONLY — Inventory dọn code search-side dư thừa

> Trạng thái: **ĐÃ THỰC THI XONG** (2026-06-07). Toàn bộ search/rerank đã được gỡ:
> `rerank/`, `RetrievalUseCase`, `engine.search()` (gỡ trước đó); và lớp vectorstore
> `search()`/`hybrid_search()` + `SearchResult`/`SearchLineage` + helper `_to_result`/
> `_assemble`/`_search_kwargs` ở store/provider/3 backend (qdrant·chromadb·milvus)
> (gỡ ở đợt này). Contract & selftest đã viết lại nghiệm thu qua
> `list_chunk_ids_by_document`. rag-worker giờ thuần producer ingest.
>
> Tài liệu giữ lại làm hồ sơ inventory gốc bên dưới.

## Bối cảnh

rag-worker từng là RAG engine đầy đủ (ingest **và** search). Sau khi search được
tách hẳn sang **mcp-service** (xem [search-split-vectorstore-contract.md](./search-split-vectorstore-contract.md)),
rag-worker chỉ còn vai trò **producer / ingest-only**, nhưng nửa search chưa được
dọn — vẫn nằm trong `core_engine` và được giữ sống chủ yếu bởi test e2e.

Bằng chứng codebase đã coi đây là ingest-only:

- [config.yaml:24](../config.yaml) — `NOTE: rag-worker = INGEST-ONLY. KHÔNG có reranker/retrieval (việc của mcp-service).`
- [app/interfaces/api/runtime.py:550](../app/interfaces/api/runtime.py) — `rag-worker = INGEST-ONLY: ép reranker = noop ... Rerank là việc của mcp-service.`
- `HaystackRagEngine.search()` và `RetrievalUseCase` **chỉ** được gọi trong
  test / e2e / selftest / demo / benchmark — không một interface production nào
  (HTTP router & NATS consumer chỉ làm ingest).

Lưu ý mâu thuẫn còn lại: dù `config.yaml` đã bỏ section `reranker`/`retrieval`,
`config_schema` vẫn mặc định `RerankerConfig(impl="llm")` và `mapping` vẫn wire —
nên code vẫn cõng theo, chỉ YAML là sạch.

## Phạm vi nhiệm vụ ingest thật

`NATS job → parse (S3/markitdown) → chunk → caption → embed → ghi Qdrant + đóng
dấu niêm (contract stamp) → ghi Postgres`. Mọi thứ ngoài chuỗi này là ứng viên xóa.

---

## A. Xóa hẳn (search-only, prod không bao giờ chạy)

| Mục | Vị trí | Ghi chú |
|---|---|---|
| `RetrievalUseCase` + package | `app/application/use_cases/query/` (`retrieval.py`, `__init__.py`) | Chỉ `test_retrieval.py` dùng |
| `LLMReranker` | `core_engine/rerank/llm.py` | Trùng bản của mcp-service |
| `LexicalRerankerService` | `core_engine/rerank/lexical.py` | nt |
| `NoopRerankerService` | `core_engine/rerank/noop.py` | Chỉ tồn tại để override `search()` |
| `Reranker` protocol + package | `core_engine/rerank/base.py` + `__init__.py` | Xóa cả thư mục `rerank/` sau khi gỡ tham chiếu |
| `HaystackRagEngine.search()` | `core_engine/engine.py:153-215` | Toàn bộ method |

## B. Sửa — bóc phần search khỏi file dùng chung

| File | Bỏ | Giữ |
|---|---|---|
| `core_engine/engine.py` | tham số `reranker` (36, 43), import `Reranker` (14) + `SearchResult` (15), method `search()` | `IngestInput`, `ingest()`, embedder/vectors/captioner/chunker |
| `core_engine/config_schema.py` | `RerankerConfig` (78-87), `RetrievalConfig` (141-156), field `reranker` (169-170) & `retrieval` (190) | parser/chunker/embedder/captioner/vectorstore |
| `core_engine/mapping.py` | import rerank (20-24), `rerank` CapabilityConfig (91-94, 109), `rerank_top_k/threshold` (129-130), block resolve reranker (185-194), 3 dòng `register("reranker",...)` (211-213) | phần còn lại của `build_engine_from_config` |
| `core_engine/config.py` | `top_k_candidates`, `rerank_top_k`, `rerank_threshold` (27-29, 57-59) | parent/child words, embed_dimension |
| `app/interfaces/api/runtime.py` | import `NoopRerankerService` (35), `reranker_override`/`reranker=` (556, 563), validate rerank (127-131), `rerank_top_k/threshold` (508-509) | toàn bộ wiring ingest |
| `core_engine/types.py` | `SearchResult` (15), `rerank_score` (28); trên `VectorRepository`: `search()`, `hybrid_search()` | `VectorRecord`, `EmbeddingService`, `upsert_many`, `list_chunk_ids_by_document`, `delete_many` |
| `core_engine/vectorstore/store.py` | `search()` (36), `hybrid_search()` (44) | `upsert/upsert_many/list_chunk_ids/delete*` |

Sau khi bóc khỏi `store.py`/`types.py`: có thể gỡ luôn impl `search`/`hybrid_search`
trong từng provider (`core_engine/vectorstore/providers/{qdrant,chromadb,milvus}/`).

## C. Giữ nguyên (ingest cần)

embedder · captioner · chunking · parser (local/s3) · OCR · contract +
`write_contract_stamp` · vector `upsert/list/delete` · Postgres doc repo ·
NATS consumer · `engine.ingest()`.

## D. Test bị ảnh hưởng — ĐỌC TRƯỚC KHI XÓA

**Xóa thẳng** (thuần search): `tests/application/query/test_retrieval.py`,
`tests/core_engine/test_search_contract.py`, `tests/core_engine/test_rerank_contract.py`.

**Phải viết lại — điểm mấu chốt:** các e2e đang dùng *chính search của rag-worker*
để tự nghiệm thu ingest:

- `tests/e2e/test_inmemory_ingest_search.py`
- `tests/e2e/test_r2_source_ingest_search.py`
- `tests/e2e/test_validation_corpus_ingest_search.py`
- `tests/e2e/test_validation_ocr_corpus.py`
- `tests/eval/test_golden_queries.py`

Sau khi bỏ `search()`, đổi cách verify sang một trong hai:

- **(a)** đọc thẳng vector/payload từ Qdrant rồi assert (nhẹ, nội bộ rag-worker);
- **(b)** verify qua mcp-service — đúng ranh giới thật. CI
  [deploy CI / rag-service-ci.yml](../../../.github/workflows/rag-service-ci.yml)
  đã có luồng 2-service thật rag→mcp nên (b) khả thi nhưng nặng tay hơn.

**Sửa nhẹ** (gỡ assertion rerank/retrieval): `test_factory_config.py`,
`test_mapping.py`, `test_config_loader.py`, `test_logging.py`, `test_qdrant_contract.py`.

## E. Ngoài phạm vi search nhưng cũng "thừa" nếu đích chỉ Qdrant

`core_engine/vectorstore/providers/chromadb/` và `.../milvus/` (mỗi cái 3 file
base/inprocess/remote). Production chỉ dùng `qdrant/` (`VECTOR_DB_PROVIDER:-qdrant`).
Quyết định riêng, không gắn với việc bóc search.

---

## Thứ tự thực thi an toàn

1. Xóa `app/application/use_cases/query/` + 3 test thuần search (mục D).
2. Bóc `search()` khỏi `engine.py` / `store.py` / `types.py`.
3. Gỡ rerank khỏi `config_schema.py` / `mapping.py` / `config.py` / `runtime.py`.
4. Xóa package `core_engine/rerank/`.
5. Xử lý nhóm e2e — chọn cách verify (a) hoặc (b).
6. (Tùy chọn) dọn provider chromadb/milvus.

Mỗi bước chạy lại test rag-worker (`pytest`) trước khi sang bước kế.
