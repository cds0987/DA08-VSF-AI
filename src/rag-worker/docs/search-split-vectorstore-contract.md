# Tách Search khỏi RAG Worker + Cơ chế chống lệch Vector Store

> **Trạng thái:** Đề xuất đã chốt phương án (chờ implement)
> **Phạm vi:** `rag-worker` (producer) ↔ `mcp-service` (consumer) qua Qdrant
> **Người chủ:** RAG Engineer (sở hữu cả `rag-worker` và `mcp-service`)
> **Đối tượng đọc:** toàn đội dev — đọc kỹ trước khi đụng vào ingest/search/vectorstore
> **Mục tiêu tài liệu:** mô tả TOÀN BỘ quá trình thật chi tiết để không ai làm lệch chuẩn.

---

## 0. TL;DR — các quyết định đã chốt (phương án tối ưu cho production)

| # | Vấn đề | Phương án CHỌN (production) | Vì sao |
|---|--------|----------------------------|--------|
| 1 | Search nằm ở đâu | **`rag-worker` chỉ ingest. Search (embed query + hybrid + rerank) chuyển hẳn sang `mcp-service`** | Single-responsibility; rerank vốn đã nằm trong engine; bỏ được transport rag.search |
| 2 | Hai service nói chuyện qua gì | **Chỉ qua Qdrant** (writer/reader). KHÔNG HTTP/NATS giữa rag-worker ↔ mcp-service | Decouple runtime, ít điểm hỏng, ít độ trễ |
| 3 | Chống lệch code embed/vectorstore | **Mỗi service tự dựng module RIÊNG** (mcp-service KHÔNG import `core_engine`). Giữ giá trị contract khớp tay; drift bắt bằng 2 guard (CI fingerprint + dấu niêm Qdrant) | Chủ dự án muốn microservice tách bạch thật; chấp nhận duplication, đổi lấy độc lập deploy. Guard làm duplication an toàn |
| 4 | `dimension` trong config | **Derive tự động từ model** (registry). Chỉ override cho model Matryoshka, có validate | Đổi model lúc test chỉ sửa 1 biến; bỏ nguồn drift gõ tay |
| 5 | Tên collection | **Encode cả model + dim**: `{collection}__{model_tag}__d{dim}` | Đổi model = collection riêng → test song song an toàn, không đè vector |
| 6 | `document_ids` (ACL) | **Truyền xuyên suốt nhưng no-op** (chưa lọc). Đánh dấu `TODO(ACL)`, fail-OPEN | Giữ flow không gãy giữa các service; ACL làm sau |
| 7 | Bảo vệ chắc chắn | **3 lớp guard fail-closed**: (a) CI so fingerprint 2 config, (b) registry model↔dim, (c) **dấu niêm trong Qdrant** mcp verify lúc startup | Phòng thủ nhiều lớp: bắt cả lệch file lẫn lệch env lúc deploy |
| 8 | Vector store in-memory | **Chỉ dùng trong test của `rag-worker`**. Flow thật = Qdrant remote cho cả 2 | In-process không share được giữa 2 process |

> Nguyên tắc xương sống: **hai service ĐỘC LẬP, runtime chỉ ghép ở Qdrant; mỗi bên tự dựng module riêng nhưng giữ contract khớp; và mọi sai lệch phải làm CRASH ngay, không bao giờ trả kết quả rác.**
>
> ⚠️ **Cập nhật 2026-06-05:** quyết định #3 đã đổi từ "dùng chung core_engine" sang "mỗi service tự dựng module riêng" (xem §4). mcp-service nay là service độc lập, KHÔNG import `core_engine` của rag-worker.

---

## 1. Bối cảnh & vì sao phải làm

Hiện tại `rag-worker` ôm cả hai việc:
- **Ingest**: NATS `doc.ingest` → parse → chunk → embed → upsert Qdrant.
- **Search**: HTTP `POST /api/search` → `core_engine.engine.HaystackRagEngine.search()` (embed query → hybrid_search → rerank).

Vấn đề:
1. Search và rerank đáng lẽ thuộc `mcp-service` (phân tách trách nhiệm). rag-worker đang làm thừa.
2. Có hai đường transport mâu thuẫn (contract ghi NATS `rag.search`, code lại là HTTP) → nợ kỹ thuật.
3. **Rủi ro lớn nhất:** khi search ở một service và ingest ở service khác, nếu hai bên lệch **embedding model / dimension / collection / payload schema** thì retrieval trả kết quả rác mà **không có lỗi nào nổ ra**. Đây là loại bug nguy hiểm nhất vì im lặng.

Tài liệu này định nghĩa kiến trúc đích + cơ chế khiến mọi sai lệch đều **crash ngay**.

---

## 2. Kiến trúc đích

```
                ┌─────────────────────────────┐
   doc.ingest   │        rag-worker           │
   doc.delete ─▶│  (CHỈ INGEST — producer)    │
   doc.access   │  parse→chunk→embed→upsert   │
                │  + ghi DẤU NIÊM contract     │
                └──────────────┬──────────────┘
                               │ ghi vector + stamp
                               ▼
                        ┌────────────┐
                        │   Qdrant   │  ◀── RANH GIỚI DUY NHẤT giữa 2 service
                        │  (remote)  │
                        └────────────┘
                               ▲
                               │ đọc vector + verify stamp (startup)
                ┌──────────────┴──────────────┐
   MCP tool     │        mcp-service          │
   rag_search ─▶│  (CHỈ SEARCH — consumer)    │
   (query-svc)  │  embed→hybrid→rerank→top-3  │
                └─────────────────────────────┘

       core_engine (KERNEL DÙNG CHUNG, import bởi cả 2):
       embedding · vectorstore(qdrant+index_id) · contract · payload schema · domain types
```

- **Không** có RPC trực tiếp giữa rag-worker và mcp-service.
- `query-service` không đổi gì: vẫn gọi MCP tool `rag_search` ở mcp-service.

---

## 3. `rag-worker` sau refactor — CHỈ ingest

### 3.1 GỠ khỏi rag-worker
| Bỏ | File |
|----|------|
| Router search | `app/interfaces/api/routers/search.py` |
| Schema search | `app/interfaces/api/schemas/search.py` |
| Use case retrieval | `app/application/use_cases/query/retrieval.py` |
| Wiring retrieval | `RetrievalUseCase`, `get_retrieval_use_case` trong `runtime.py`/`dependencies.py` |
| Include router search | trong `app/interfaces/api/main.py` |

> Engine build cho rag-worker dùng **reranker = `noop`** (vì không search nữa). Hoặc tách `build_ingest_engine()` chỉ cần `chunker + captioner + embedder + vectors`.

### 3.2 GIỮ ở rag-worker
- NATS consumers: `doc.ingest`, `doc.delete`, `doc.access` (nguyên trạng).
- Ingest pipeline trong `core_engine.engine.HaystackRagEngine.ingest()`.
- HTTP còn lại: **chỉ health** (`/livez`, `/readyz`, `/health`). Còn lại không expose.
- **MỚI:** ghi dấu niêm contract vào Qdrant (xem §7.3).

### 3.3 HTTP của rag-worker
Sau refactor rag-worker gần như "không expose HTTP nghiệp vụ" — chỉ health. Đúng tinh thần `api-spec.md` ("RAG Worker không expose HTTP").

---

## 4. Hai service ĐỘC LẬP — mỗi bên tự dựng module riêng

> **Quyết định (2026-06-05):** mcp-service KHÔNG import `core_engine` của rag-worker.
> Nó là service độc lập, tự dựng module **mô phỏng ý tưởng** của `core_engine` trong
> `src/mcp-service/app/core/`. Chấp nhận duplication để được tách bạch deploy.

### 4.1 Mỗi service giữ bản riêng của những gì cần
| rag-worker (producer) | mcp-service (consumer) |
|-----------------------|------------------------|
| `core_engine/contract.py` | `app/core/contract.py` (BẢN RIÊNG, giá trị y hệt) |
| `core_engine/embedding/`, `ai/offline_provider`, `text_utils` | `app/core/embedding.py` + `app/core/text_utils.py` |
| `core_engine/vectorstore/` (ghi) + `qdrant_contract.write_contract_stamp` | `app/core/vectorstore.py` (chỉ ĐỌC + verify stamp) |
| `core_engine/rerank/` | `app/core/rerank.py` (noop/lexical; llm = TODO) |
| ingest: `chunking/caption/parser/ocr` | (không có — search-only) |

### 4.2 "Hợp đồng ngầm" phải giữ khớp TAY giữa 2 bản
Vì không share code, 4 thứ sau lệch là hỏng IM LẶNG — sửa 1 bên phải sửa bên kia:
- **embedding model + dimension** (quyết định KHÔNG GIAN vector). ⚠️ Offline provider
  là hash CỤC BỘ → `hash_embed` 2 bản phải **byte-identical** (mcp copy nguyên từ
  rag-worker `text_utils`). Model thật (openai) cùng API nên tự khớp.
- **cách tính `index_id`** (`{collection}__{model_tag}__d{dim}`) + `point_id` (uuid5).
- **tên field payload** (`child_text`, `parent_text`, `source_uri`, `artifact_uri`,
  `heading_path`, `document_id`...) — mcp đọc đúng key rag-worker ghi.
- **thuật toán fingerprint** (canonical JSON + sha256[:16]) + `PAYLOAD_SCHEMA_VERSION`.

### 4.3 Hai guard làm duplication AN TOÀN (xem §7)
- **CI fingerprint parity**: so giá trị contract của 2 config.
- **Dấu niêm Qdrant**: mcp tự tính fingerprint **bằng code của chính nó** rồi so với
  stamp producer ghi → bắt được nếu logic 2 bản lệch tay. Đây là cái chốt khiến
  "copy code" không còn nguy hiểm.

> ⚠️ Hạn chế còn lại guard KHÔNG bắt: offline `hash_embed` lệch thuật toán nhưng vẫn
> cùng tên "offline"/dim 256 → fingerprint vẫn khớp, search ra rác. Vì vậy `text_utils`
> 2 bên phải copy nguyên văn (e2e CI offline sẽ lộ ra nếu lệch: search ra 0 hit).

### 4.4 Vệ sinh dependency (vẫn áp dụng cho rag-worker)
`core_engine` của rag-worker: import read-path (`contract/embedding/vectorstore/rerank`)
KHÔNG được kéo `ocr` (đã fix: `mapping.py` lazy-import ocr). mcp-service vốn không có
ocr nên sạch sẵn.

---

## 5. Vector Store Contract — tập bất biến

Chỉ 5 field, lệch cái nào cũng vỡ ngầm:

| Field | Nguồn | Ghi chú |
|-------|-------|---------|
| `provider` | `vector_store.impl` | qdrant |
| `collection` | `vector_store.params.collection` | tên cơ sở |
| `embed_model` | `embedder.model` | quyết định không gian vector |
| `dimension` | **derive từ model** (xem §6) | số chiều vector |
| `payload_schema_version` | hằng số trong `core_engine.contract` | bump khi đổi key payload |

Mọi guard bên dưới đều xoay quanh đúng 5 field này.

---

## 6. `dimension` derive từ model (tiện đổi model khi test & vận hành)

### 6.1 Nguyên tắc
- **KHÔNG gõ tay `dimension`.** Mặc định để TRỐNG → suy ra từ model qua registry.
- Chỉ set `EMBED_DIMENSION` khi **cố ý override** cho model Matryoshka (cắt chiều), và phải hợp lệ.

### 6.2 Registry (đặt trong `core_engine/contract.py`)
```python
# native = số chiều mặc định; allowed = các chiều hợp lệ (Matryoshka cắt được)
EMBED_MODELS = {
    "text-embedding-3-small": {"native": 1536, "allowed": "256..1536"},
    "text-embedding-3-large": {"native": 3072, "allowed": "256..3072"},
    "bge-m3":                 {"native": 1024, "allowed": {1024}},
    "offline":                {"native": 256,  "allowed": {256}},
}

def resolve_dimension(model: str, override: int | None = None) -> int:
    spec = EMBED_MODELS.get(model.strip().lower())
    if spec is None:                      # model lạ → KHÔNG đoán, bắt khai tay
        if override is None:
            raise ValueError(f"model {model!r} chưa có trong EMBED_MODELS, phải set EMBED_DIMENSION rõ ràng")
        return int(override)
    if override is None:
        return spec["native"]
    if not _is_allowed(override, spec["allowed"]):
        raise ValueError(f"model {model!r} không cho dimension={override} (allowed={spec['allowed']})")
    return int(override)
```

### 6.3 Đổi model = MIGRATION, không phải tweak
Dù derive tự động, **đổi embed model bắt buộc re-ingest** — vector model cũ nằm ở không gian khác, không search bằng model mới được. Cơ chế không giấu điều này; nó chỉ làm việc đó AN TOÀN nhờ:
- collection encode model (§6.4) → không đè vector cũ,
- fingerprint + stamp → không lệch ngầm.

Dùng `profiles:` trong `config.yaml` cho mỗi model test:
```yaml
profiles:
  bge:  { extends: baseline, embedder: { model: bge-m3 } }  # dim auto 1024
  te3l: { extends: baseline, embedder: { model: text-embedding-3-large } }
```
Đổi model test = đổi `PIPELINE_PROFILE`, không đụng dim, không đè collection.

### 6.4 `index_id` encode model + dim
```python
def model_tag(model: str) -> str:
    return {                       # tag ngắn, ổn định
        "text-embedding-3-small": "te3s",
        "text-embedding-3-large": "te3l",
        "bge-m3": "bgem3",
        "offline": "offline",
    }.get(model.strip().lower(), _slug(model))  # model lạ → slug hoá tên

def index_id(collection: str, model: str, dimension: int) -> str:
    return f"{collection}__{model_tag(model)}__d{dimension}"
    # vd: rag_chatbot__te3s__d1536
```
> ⚠️ Đây là **đổi schema tên collection** (hiện chỉ `__d{dim}`). Collection cũ phải re-ingest. Đang ở giai đoạn pre-prod nên chấp nhận — ghi rõ trong changelog.

Lợi ích trực tiếp: 2 model khác nhau **cùng dim** không còn đè/đọc lẫn nhau (vd `bge-m3` vs model 1024 khác → tag khác → collection khác).

---

## 7. Ba lớp guard fail-closed

### 7.1 Fingerprint (hàm dùng chung)
```python
# core_engine/contract.py
import hashlib, json
PAYLOAD_SCHEMA_VERSION = 1   # bump khi đổi tên/khóa payload Qdrant

def vectorstore_fingerprint(*, provider, collection, embed_model, dimension, schema_version) -> str:
    # validate cặp model↔dim ngay tại đây (lớp guard 7.2)
    resolved = resolve_dimension(embed_model, dimension)
    payload = json.dumps({
        "provider": provider.strip().lower(),
        "collection": collection.strip(),
        "embed_model": embed_model.strip().lower(),
        "dimension": int(resolved),
        "schema_version": int(schema_version),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
```

### 7.2 Lớp A — CI guard (bất kể deploy lên đâu)
Mục tiêu: chặn lệch **trước khi merge/deploy**, không cần Qdrant chạy.

`scripts/check_vectorstore_contract.py`:
1. Load `src/rag-worker/config.yaml` và `src/mcp-service/config.yaml`.
2. Resolve block `vectorstore_contract` theo **default** (không đọc env runtime — so chuẩn tĩnh).
3. Tính fingerprint mỗi bên (đã gồm validate model↔dim).
4. Lệch → in diff rõ ràng + `sys.exit(1)`.

Cắm vào `.github/workflows/rag-service-ci.yml` thành job **luôn chạy với mọi PR/branch**:
```yaml
  vectorstore-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pyyaml
      - run: python scripts/check_vectorstore_contract.py
```
> Job này KHÔNG phụ thuộc môi trường deploy → "bất kể deploy lên đâu" vẫn bị chặn ở CI.

### 7.3 Lớp B — DẤU NIÊM trong Qdrant (cơ chế "chắc chắn" trong mcp-service)
CI chỉ so file. Nếu lúc deploy ai đó override env (vd `EMBED_MODEL`/`EMBED_DIMENSION` khác cho mcp) thì file vẫn khớp nhưng thực tế lệch. Lớp này kiểm **cái đã THỰC SỰ ingest**.

**rag-worker (producer) — ghi dấu niêm:**
- Tại lần ingest đầu (hoặc lúc startup), upsert một điểm vào **collection metadata riêng** `{collection}__meta` (dim=1, không lẫn vào không gian search):
```python
stamp = {
    "kind": "__contract__",
    "index_id": index_id(collection, model, dim),   # collection dữ liệu tương ứng
    "fingerprint": fp,
    "provider": provider, "collection": collection,
    "embed_model": model, "dimension": dim,
    "schema_version": PAYLOAD_SCHEMA_VERSION,
    "written_by": "rag-worker", "written_at": "<iso8601>",
}
```
> Dùng collection `__meta` riêng để **không** làm bẩn kết quả search bằng vector giả.

**mcp-service (consumer) — verify lúc startup, FAIL-CLOSED:**
```
1. resolve config → model, dim=resolve_dimension(model, override), idx=index_id(...), fp_self=fingerprint(...)
2. Qdrant.get_collection(idx)  → phải tồn tại & vectors.size == dim   (bắt lệch dim / chưa ingest)
3. đọc stamp(index=idx) ở {collection}__meta
       → phải tồn tại & stamp.fingerprint == fp_self                  (bắt lệch model/schema/env)
4. bất kỳ điều kiện nào sai → raise RuntimeError → tiến trình thoát ≠ 0, KHÔNG phục vụ search
```

Vì sao mạnh: env override lúc deploy → collection mong đợi không tồn tại HOẶC stamp lệch → mcp **crash ngay** thay vì trả kết quả rác.

### 7.4 Bảng tổng kết phòng thủ
| Lớp | Bắt được | Chạy ở đâu | Hệ quả khi lệch |
|-----|----------|-----------|------------------|
| Registry model↔dim (7.1/6.2) | config tự mâu thuẫn (vd bug 1024 vs te3s=1536) | CI + startup cả 2 service | raise ngay khi tính fingerprint |
| CI fingerprint (7.2) | lệch giữa 2 file config | GitHub Actions, mọi PR | fail build |
| Qdrant stamp (7.3) | env override khi deploy + ingest thật lệch | mcp startup | crash, fail-closed |

---

## 8. `document_ids` — pass-through no-op (giai đoạn này)

- Tool `rag_search(query, document_ids, top_k)` **vẫn nhận** `document_ids` để giữ chữ ký hợp đồng với query-service.
- **Chưa lọc theo `document_ids`** (chưa thread xuống `hybrid_search`). Đánh dấu rõ:
```python
# TODO(ACL): hiện CHƯA lọc theo document_ids → FAIL-OPEN (trả cả doc ngoài quyền).
# KHÔNG được bật cho production thật. Theo dõi ở <issue/ticket>.
```
- ⚠️ Đây là fail-OPEN. Trước khi lên production phục vụ user thật, **bắt buộc** implement lọc ACL ở `hybrid_search` (fail-secure: `None` → chỉ public/rỗng). Hiện `core_engine/engine.py` cũng đang no-op nên không regress.

---

## 9. Trạng thái triển khai (cập nhật 2026-06-05)

**rag-worker (producer) — XONG**
- [x] `core_engine/contract.py` (registry, resolve_dimension, model_tag, index_id, fingerprint).
- [x] `SearchResult`/`EmbeddingService`/`VectorRepository` về `core_engine/types.py` (app.domain re-export).
- [x] `index_id` = `{collection}__{model_tag}__d{dim}`.
- [x] Ghi dấu niêm `{collection}__meta` lúc startup (`vectorstore/qdrant_contract.py`).
- [x] Gỡ search router/schema/use case → ingest-only (HTTP chỉ health).
- [x] Hygiene: `mapping.py` lazy-import ocr (read-path không kéo ocr).
- [x] `config.yaml`: `dimension` trống (auto) + block `vectorstore_contract`.

**mcp-service (consumer) — XONG (độc lập, không import core_engine)**
- [x] `app/core/` bản RIÊNG: `contract.py`, `config.py`, `embedding.py`, `text_utils.py`,
      `vectorstore.py` (reader + verify stamp), `rerank.py`, `search.py`.
- [x] `interfaces/mcp_server.py` (FastMCP, tool `rag_search`) + `main.py` (startup verify fail-closed) + `requirements.txt`.
- [x] document_ids no-op (§8).
- [x] Tests: contract parity (fp khớp rag-worker), config, verify+search roundtrip, 2 negative.

**Guard / CI — XONG**
- [x] CLI `scripts/check_vectorstore_contract.py` + job `contract` (luôn chạy).
- [x] Job `mcp-e2e` (Docker Qdrant): rag-worker seed → mcp verify+search; + negative drift fail-closed.
- [x] Scripts: `rag-worker/scripts/seed_qdrant_e2e.py`, `mcp-service/scripts/e2e_search.py`.

**Còn nợ**
- [ ] ACL thật cho `document_ids` (hiện no-op, fail-open) — §8, §13.
- [ ] LLM rerank ở mcp (v1 chỉ noop/lexical).
- [ ] Hybrid search (BM25 RRF) ở mcp (v1 dense-only).
- [ ] Cập nhật `docs/contracts.md`/`api-spec.md` (bỏ `rag.search`; rag-worker ingest-only; mcp đọc Qdrant). **Xin SA duyệt** (đội khác đang đọc spec cũ).

---

## 10. Hình dạng config 2 bên (phải khớp fingerprint)

**`src/rag-worker/config.yaml`** (và y hệt ở **`src/mcp-service/config.yaml`** cho block này):
```yaml
embedder:
  model:     ${EMBED_MODEL:-text-embedding-3-small}
  dimension: ${EMBED_DIMENSION:-}        # TRỐNG = auto theo model; chỉ set khi override Matryoshka

vector_store:
  impl: ${VECTOR_DB_PROVIDER:-qdrant}
  params:
    collection: ${VECTOR_COLLECTION:-rag_chatbot}
    url:        ${VECTOR_DB_URL:-}        # PHẢI cùng URL ở cả 2 service (Qdrant remote)
    api_key:    ${VECTOR_DB_API_KEY:-}

# Block dùng để tính fingerprint — derive từ các field trên, viết tường minh cho dễ soi:
vectorstore_contract:
  provider:    ${VECTOR_DB_PROVIDER:-qdrant}
  collection:  ${VECTOR_COLLECTION:-rag_chatbot}
  embed_model: ${EMBED_MODEL:-text-embedding-3-small}
  # dimension KHÔNG khai ở đây — resolve_dimension() suy ra từ embed_model (+ EMBED_DIMENSION nếu override)
```

> Cả rag-worker và mcp-service đọc cùng bộ env (`VECTOR_*`, `EMBED_*`) → prod = staging = dev tự khớp. DevOps phải cấp **cùng** giá trị cho cả 2 container.

---

## 11. TUYỆT ĐỐI KHÔNG (để tránh đội dev làm sai)

1. ❌ **KHÔNG import `core_engine` của rag-worker vào mcp-service.** mcp độc lập, dùng `app/core/` riêng. (Đổi: trước đây ghi "import chung" — đã bỏ.)
2. ❌ **KHÔNG sửa contract/index_id/fingerprint/`hash_embed` ở MỘT bản.** Sửa là sửa ĐỐI XỨNG cả `rag-worker/core_engine` lẫn `mcp-service/app/core` — nếu không guard sẽ nổ (đúng ý đồ) nhưng e2e đỏ.
3. ❌ **KHÔNG gõ tay `EMBED_DIMENSION`** trừ khi cố ý override Matryoshka. Mặc định để trống.
4. ❌ **KHÔNG đổi tên field payload** (`child_text`, `parent_text`, `source_uri`, `artifact_uri`, `heading_path`, `document_id`...) mà không **bump `PAYLOAD_SCHEMA_VERSION`** (cả 2 bản) + re-ingest.
5. ❌ **KHÔNG cấp `VECTOR_DB_URL` khác nhau** cho rag-worker và mcp-service. Phải cùng một Qdrant.
6. ❌ **KHÔNG dùng Qdrant in-process** ở môi trường thật. In-memory chỉ trong test rag-worker.
7. ❌ **KHÔNG bật production phục vụ user thật** khi `document_ids` còn no-op (fail-open ACL).
8. ❌ **KHÔNG bỏ qua guard startup** của mcp-service (không try/except nuốt lỗi stamp).
9. ❌ **KHÔNG đổi embed model** rồi trỏ vào collection cũ. Đổi model = re-ingest (migration).

---

## 12. Kiểm thử & xác minh

- **Unit:** `vectorstore_fingerprint` ổn định & nhạy (đổi 1 field → đổi hash); `resolve_dimension` (auto, override hợp lệ, override sai → raise, model lạ → raise).
- **CI tĩnh:** `check_vectorstore_contract.py` fail khi cố tình làm lệch 2 config.
- **Import hygiene:** test khẳng định import read-path không kéo parser/ocr.
- **E2E (có Qdrant):** ingest bằng rag-worker → mcp start (stamp pass) → search ra kết quả. Sau đó **cố tình** đổi `EMBED_MODEL` của mcp → mcp **phải crash** lúc startup (kiểm dấu niêm).
- **Negative:** xoá collection `__meta` → mcp crash; dựng collection sai dim → mcp crash.

---

## 13. Việc còn nợ (tương lai)

- **ACL thật** (`document_ids` fail-secure) — thread xuống `hybrid_search`, `None` ⇒ chỉ public.
- **Rotate model an toàn** (blue/green): ingest model mới vào collection mới (tag mới) song song, đổi mcp sang collection mới khi sẵn sàng, giữ collection cũ để rollback.
- **Quan sát**: log fingerprint + index_id ở cả 2 service để soi nhanh khi nghi lệch.

---

## 14. Thuật ngữ nhanh

| Từ | Nghĩa |
|----|------|
| **Producer** | rag-worker — ghi vector + dấu niêm vào Qdrant |
| **Consumer** | mcp-service — đọc vector, verify dấu niêm, search |
| **Fingerprint** | hash 16 ký tự của 5 field bất biến — "chữ ký" của vector store contract |
| **Dấu niêm (stamp)** | điểm `__contract__` trong `{collection}__meta` ghi fingerprint của producer |
| **index_id** | tên collection thật: `{collection}__{model_tag}__d{dim}` |
| **Fail-closed** | sai/thiếu điều kiện ⇒ crash, không phục vụ (an toàn) |
| **Fail-open** | thiếu kiểm tra vẫn chạy (rủi ro — hiện áp cho ACL no-op) |
