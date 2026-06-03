# haystack_interface

**Core working RAG** của `rag-service`, dựng trên Haystack. Nằm *ngoài* thư mục
`haystack/` (bản clone framework upstream — không sửa). Package này tổ chức theo
**module severable** (MOSA / hexagonal): mỗi thư mục một nhiệm vụ, giao tiếp qua
interface mở, đổi backend không phá module khác.

## Kiến trúc module

```
haystack_interface/
  ai/          ★ AI gateway — điểm vào DUY NHẤT cho mọi outbound AI call
               (embed · caption · rerank). OpenAI SDK trước; swap provider 1 chỗ.
  embedding/   port EmbeddingService qua provider
  chunking/    section split (đơn vị nghĩa, không token-chunk mù)
  caption/     ý-nghĩa-nén section qua provider
  rerank/      Reranker: LLM-as-reranker (qua gateway) + lexical fallback
  vectorstore/ provider-first: VectorStoreConfig (provider, url) → registry chọn
               providers/<db>/ (qdrant · chromadb · milvus); mỗi db 2 file:
               remote.py (có url, async thuần) · inprocess.py (ko url, to_thread)
  config.py    HaystackSettings (split · retrieval — phần pipeline, KHÔNG-AI/KHÔNG-storage)
  engine.py    orchestrator (ingest + search) — chỉ phụ thuộc port
  factory.py   composition root — wire backend theo env (offline | OpenAI)
```

**Nguyên tắc cốt lõi:** mọi nơi cần AI gọi qua `ai/` (một provider singleton).
Chế độ offline↔OpenAI chỉ chuyển ở **một chỗ** (provider) → caption/rerank/embed
mỗi thứ chỉ một implementation, không dàn trải. Ingest & query do đó dùng **cùng
provider/model/dimension** — đảm bảo bằng kiến trúc, không bằng kỷ luật
(`embedding.md` §0, `search.md` §2).

## Chạy (offline — không cần key/Qdrant/Azure)

```bash
cd src/rag-service
.venv\Scripts\python -m pip install -r haystack_interface/requirements.txt

.venv\Scripts\python -m haystack_interface.demo                    # demo end-to-end
.venv\Scripts\python -m haystack_interface.tests.selftest          # assert bất biến (offline)
.venv\Scripts\python -m haystack_interface.tests.selftest_provider # AI gateway: SDK wiring + e2e
.venv\Scripts\python -m haystack_interface.tests.selftest_async    # async qua các stage (concurrency/to_thread/retry)
.venv\Scripts\python -m haystack_interface.tests.selftest_vectorstore # chọn backend + CONTRACT chung cho mọi DB
```

> Offline dùng `OfflineProvider` (hash-embed tất định + LLM-rerank giả lập) +
> InMemoryDocumentStore → chạy ngay. Production swap `OpenAIProvider`/Qdrant/BGE
> **qua đúng interface này**, không đổi engine.

## Dùng trong code

```python
from haystack_interface import build_engine, IngestInput

engine = build_engine()                   # auto theo env (offline nếu không có key)
await engine.ingest(IngestInput(document_id="d1", document_name="Doc",
                                file_type="md", markdown="# Title\nNội dung..."))
hits = await engine.search("câu hỏi")     # trả raw unit + lineage; access ở caller
```

Mọi vùng khác cần AI (query-rewrite, eval, caption...) dùng chung gateway, **không
tự dựng client**:

```python
from haystack_interface.ai import get_ai_provider
provider = get_ai_provider()
vecs = await provider.embed(["..."])
txt  = await provider.chat("...", capability="caption")
```

## Vector backend (`vectorstore/`) — chọn nhiều DB option

Interface ra ngoài THỐNG NHẤT giờ là facade async `VectorStore`:
- `insert` / `insert_many`
- `upsert` / `upsert_many`
- `search` (alias tương thích cũ: `hybrid_search`)
- `delete` / `delete_many` / `delete_by_document`

`VectorStore` vẫn conform port async `VectorRepository` để `engine` cũ không phải
sửa. Kiến trúc **provider-first** (xem sơ đồ):

    Application → VectorDB Interface → Registry (chọn provider) → Provider package
                                                                   ├ remote.py    (có url)
                                                                   └ inprocess.py (ko url)

**`VectorStoreConfig` (config object) quyết định** provider + kết nối. Registry chọn
provider theo `config.provider`. **Deployment SUY RA TỪ `url`**: có url → `remote`
(service riêng, client async-native, **async thuần**); ko url → `in_process`
(embedded chạy thẳng trong tiến trình, client sync bọc **`to_thread`**). Mỗi provider
là MỘT package, có HAI file implement cho hai deployment đó:

| Provider | `remote.py` (có url, async thuần) | `inprocess.py` (ko url, to_thread) |
|---|---|---|
| `qdrant` (mặc định) | `AsyncQdrantClient` server | `QdrantClient` `:memory:`/path |
| `chromadb` | `AsyncHttpClient` server | `Ephemeral`/`Persistent` |
| `milvus` | `AsyncMilvusClient` server | `MilvusClient` Milvus Lite (file) |

> 🟡 Mới qdrant in_process chạy offline ngay; chromadb/milvus + mọi mode remote viết
> theo API chuẩn nhưng **chưa verify qua DB/server thật**. Không còn provider
> `inmemory`: dev/offline = `qdrant` in_process (`:memory:`), embedded, KHÔNG cần
> server, chỉ cần `pip install qdrant-client`.

```python
from haystack_interface import build_engine, VectorStoreConfig
from haystack_interface.vectorstore import build_vector_store, register_backend

# Có url -> remote (service riêng); bỏ url -> in_process (embedded):
remote = VectorStoreConfig(provider="qdrant", url="http://localhost:6333", collection="rag")
local  = VectorStoreConfig(provider="qdrant")          # ko url -> in_process :memory:
engine = build_engine(vector_config=local)             # hoặc VECTOR_DB_URL=... (from_env)
store = build_vector_store(remote)                      # facade async thống nhất

# Bên thứ ba cắm provider mới (đặt package ở providers/<db>/), không sửa core:
register_backend("weaviate", lambda c: MyWeaviateBuild(c))
```

`build_engine()` **ép `VectorStoreConfig.dimension = dimension của embedder`** →
ingest==query==store cùng không gian vector (search.md §2). Đổi DB = đổi config
object/`VECTOR_DB_PROVIDER`, KHÔNG sửa engine/use-case (hexagonal). Provider dựng
**lazy** (chỉ kéo qdrant-client/pymilvus... khi thực sự chọn).

**Conformance — mọi provider phải pass contract chung.** `tests/_contract.py` ép
các bất biến backend-agnostic (dimension guard · idempotent re-upsert · trả full
content · delete gỡ hết) qua *port*, không đụng nội bộ. Qdrant in_process (`:memory:`)
chạy trong selftest khi có qdrant-client; chromadb/milvus chạy khi cài lib tương ứng.
Bên thứ ba thêm DB mới → chạy chính contract này để chứng minh tuân thủ (MOSA §4).

**Capability gap (đọc kỹ).** Contract ghim những gì PHẢI giống, KHÔNG ghim chất
lượng ranking. Hiện cả ba provider chạy **dense-only** (hybrid sparse/BM25 còn TODO)
→ rerank bước sau (trên parent_text) bù chất lượng.

**KHÔNG enforce access control.** Retrieval layer trả raw unit + lineage; filtering
theo org/role/classification là việc của **caller tầng trên** (search.md §6,
handoff/LESSONS §1 discovery). `search()` không nhận `UserContext`. Nếu cần phân quyền,
ingest có thể nhét scope/tags vào payload như **metadata thụ động** để caller tự lọc —
nhưng rag-service KHÔNG tự lọc.

## AI gateway (`ai/`) — MỌI call AI đi qua đây

Một `AIProvider` (interface mở) với 2 năng lực `embed` / `chat`; `capability`
định tuyến per-capability (embedding.md §5). Reliability policy đồng nhất
(retry+backoff+jitter — LESSONS §4.9). Hai provider:

| Provider | Khi nào | Cơ chế |
|---|---|---|
| `OfflineProvider` | dev / eval / selftest | hash-embed tất định + chat giả lập, không mạng |
| `OpenAIProvider` | production | `openai.AsyncOpenAI` trực tiếp; OpenAI-compatible (vLLM/OpenRouter/gateway) |

Env (per-capability, kế thừa embed→caption→rerank nếu để trống):

| Capability | Env |
|---|---|
| Embedding | `EMBED_BASE_URL` · `EMBED_API_KEY`/`OPENAI_API_KEY` · `EMBED_MODEL` · `EMBED_DIMENSION` |
| Caption (LLM) | `CAPTION_BASE_URL` · `CAPTION_API_KEY` · `CAPTION_MODEL` |
| Rerank (LLM) | `RERANK_BASE_URL` · `RERANK_API_KEY` · `RERANK_MODEL` |

`AI_PROVIDER=auto|openai|offline` ép chế độ (auto: có key/base_url → openai).

```bash
set OPENAI_API_KEY=sk-...           # hoặc EMBED_BASE_URL=http://localhost:8000/v1
```

```python
from haystack_interface import build_engine_probe
engine = await build_engine_probe()   # OpenAI: probe dimension thật từ model
```

Đổi nhà cung cấp sau này = viết `AIProvider` mới + `set_ai_provider(...)`, **không
sửa nơi gọi** (execution-fallback.md §4b: backend abstraction từ ngày 1).

## Bất biến tuân theo (từ docs)

- **Section nghĩa, không token-chunk mù** — split theo heading; section dài →
  sub-split. parent_text = full content, child = cửa sổ embed. (`ingestion.md` §5)
- **Embed caption, index full content** — embed *caption* (ý-nghĩa-nén); BM25 +
  rerank trên *full content* (parent_text) để bù caption-only. (`search.md` §4)
- **Cùng provider/model/dimension cho ingest & query** — một AI gateway singleton
  đảm bảo. (`embedding.md` §0, `search.md` §2)
- **Index id encode dimension** — đổi dimension là *migration*; `upsert` reject
  vector sai dimension. (`ingestion.md` §8)
- **Idempotent** — `chunk_id` deterministic + `DuplicatePolicy.OVERWRITE`. (`ingestion.md` §7)
- **Không enforce access** — retrieval trả raw unit + lineage; phân quyền ở caller. (`search.md` §6)
- **No-answer** — rerank threshold lọc kết quả yếu thay vì bịa. (`search.md` §3)
- **Reliability đồng nhất** — mọi AI call qua gateway: retry+backoff+jitter. (LESSONS §4.9)

## Đường lên production (đổi gì, KHÔNG đổi gì)

| Offline | Thay bằng | KHÔNG đổi |
|---|---|---|
| `OfflineProvider` (hash + rerank giả) | `OpenAIProvider` (set key/`*_BASE_URL`) | interface `AIProvider`, nơi gọi |
| `InMemoryVectorRepository` + RRF | Qdrant store + hybrid native | chữ ký `VectorRepository` |
| LLM-rerank offline | BGE-Reranker / LLM thật (`RERANK_*`), threshold 0.7 | bước rerank trong `engine.search` |

Vì engine/use-case chỉ phụ thuộc **port** trừu tượng, đổi backend là thay wiring ở
`factory.py` + `ai/`, không sửa engine (hexagonal — `execution-fallback.md` §4b).

## Giới hạn đã biết (bản offline)

- `OfflineProvider` embed **không phải semantic thật** — chỉ để pipeline chạy/eval
  cấu trúc; recall thật cần model embedding thật.
- Chưa gắn S3 / Azure OCR (parser adapter ngoài — `parser.md`); engine nhận sẵn
  Markdown canonical.
- Interface `VectorRepository`/`EmbeddingService` hiện là **Python ABC nội bộ**, chưa
  phải chuẩn mở cộng đồng (OpenAPI/gRPC IDL). Đủ cho mục tiêu severable + swap
  backend; nếu cần liên thông đa-ngôn-ngữ/đa-team thì nâng lên IDL sau (MOSA §2).
