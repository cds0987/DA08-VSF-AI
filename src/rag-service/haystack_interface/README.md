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
  vectorstore/ port VectorRepository (Haystack hybrid RRF; → Qdrant)
  access/      classification filter (policy access control)
  config.py    HaystackSettings (split · retrieval · store — phần KHÔNG-AI)
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
```

> Offline dùng `OfflineProvider` (hash-embed tất định + LLM-rerank giả lập) +
> InMemoryDocumentStore → chạy ngay. Production swap `OpenAIProvider`/Qdrant/BGE
> **qua đúng interface này**, không đổi engine.

## Dùng trong code

```python
from haystack_interface import build_engine, IngestInput
from app.domain.repositories.vector_repository import UserContext

engine = build_engine()                   # auto theo env (offline nếu không có key)
await engine.ingest(IngestInput(document_id="d1", document_name="Doc",
                                file_type="md", markdown="# Title\nNội dung..."))
hits = await engine.search("câu hỏi", UserContext("u1", "user", "eng"))
```

Mọi vùng khác cần AI (query-rewrite, eval, caption...) dùng chung gateway, **không
tự dựng client**:

```python
from haystack_interface.ai import get_ai_provider
provider = get_ai_provider()
vecs = await provider.embed(["..."])
txt  = await provider.chat("...", capability="caption")
```

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
- **Classification filter** — public/internal/secret/top_secret theo `UserContext`.
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
- Access filter áp **post-retrieval** trên in-memory store (union rộng ×5 trước
  filter để giảm cắt mất); production Qdrant nên **pre-filter** trên payload index.
- Chưa gắn S3 / Azure OCR (parser adapter ngoài — `parser.md`); engine nhận sẵn
  Markdown canonical.
