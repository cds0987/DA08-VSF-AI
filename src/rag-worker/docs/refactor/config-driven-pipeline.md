# Refactor: Config-driven pipeline (config.yaml + mapping.py)

> Trạng thái: **design đã chốt, chưa thực thi**. Tài liệu này là nguồn sự thật cho
> đợt refactor đưa pipeline `rag-worker` từ wiring-mệnh-lệnh (env rải rác trong
> `factory.py`) sang **wiring khai báo**: một `config.yaml` mô tả đồ thị component,
> một `mapping.py` resolve name→implementation và lắp ráp engine.

## 1. Động lực

Hiện [`core_engine/factory.py`](../../core_engine/factory.py) là composition root nhưng
đọc env rải rác (`AI_PROVIDER`, `RERANK_PROVIDER`, `CAPTION_ENABLED`, `VECTOR_DB_*`,
`EMBED_*`…) qua các nhánh `match/if`. Hệ quả:

- Muốn đổi một module phải biết đúng env nào; không có "một nơi" thấy toàn cảnh.
- Không A/B được các biến thể module (parser, chunker, reranker) để **đánh giá**.
- `parser` bị hardcode (`build_parser` luôn dựng `LocalFileParser`); `chunker` thậm chí
  không có port — `split_sections` được gọi thẳng trong `engine.ingest`.

Mục tiêu: **module hóa triệt để** — đổi implementation/tham số của bất kỳ stage nào
bằng cách sửa `config.yaml` (hoặc đổi profile), engine không sửa một dòng.

## 2. Nguyên tắc cốt lõi

1. **Khai báo, không mệnh lệnh.** `config.yaml` nói *dùng gì + tham số gì*; `mapping.py`
   biết *vũ trụ implementation có sẵn* (name→factory) và lắp ráp.
2. **Một đường lắp ráp duy nhất.** `build_pipeline(cfg)` là đường thật; `build_engine(...)`
   cũ trở thành shim mỏng gọi `build_pipeline` → không drift, không phá ~12 file test.
3. **Tách shape khỏi value.** yaml = *hình dạng* (versioned, review qua PR); env = *giá trị
   bí mật / theo môi trường* (inject lúc deploy). yaml tham chiếu env qua `${VAR}` — **secret
   không bao giờ là literal trong yaml**.
4. **Giữ bất biến bằng kiến trúc:** `store.dimension == embedder.dimension`, và
   `index_id()` luôn encode dimension (đổi dimension = migration).

## 3. Phân lớp config (quan trọng nhất cho production)

Hai loại config có **vòng đời và chủ sở hữu khác nhau** — không trộn:

| | App / ML config | Ops / deploy config |
|---|---|---|
| Là gì | component graph, model, chunk size, threshold, cost/quality guard | secret, db url, worker count, rate-limit, lease, resource limit |
| Ai sửa | dev / researcher | SRE / platform |
| Đổi khi | theo code / thí nghiệm | theo môi trường / cluster / tải |
| Giao bằng | **PR review**, versioned (`config.yaml`) | **inject lúc deploy** (k8s ConfigMap/Secret, env) |

**Ranh giới không phải "component vs infra"** mà là:
> **"ảnh hưởng kết quả retrieval/ingest → yaml"** vs **"thuần vận hành/deploy → env"**.

- → **yaml**: 7 component + params + `max_ocr_pages`, `pdf_ocr_scale`, `ocr_min_pixels`,
  chunk sizes, thresholds, `top_k`.
- → **env**: `worker_count`, `poll_interval`, lease timeouts, `rate_limit`, body size,
  `SOURCE_ROOT`, `DATABASE_URL`, `LOG_LEVEL`, `APP_ENV`, và **giá trị** secret/endpoint.

"Single source of truth" đạt được bằng **layering**, không phải gộp file: `config.yaml`
mount qua ConfigMap, chọn profile bằng env `PIPELINE_PROFILE`, secret bơm qua env và yaml
tham chiếu `${VAR}`. `${VAR}` thiếu (không default) → **fail-fast lúc load** (miễn phí lợi
ích "khai báo secret cần thiết").

## 4. `config.yaml` — schema

### 4.1 Quy ước
- `${VAR}` — bắt buộc có env, thiếu = lỗi load. `${VAR:-default}` — trống thì dùng default.
  Áp cho **mọi block**, không riêng AI.
- `active:` — chọn profile đang dùng; override được bằng env `PIPELINE_PROFILE`.
- `extends: <profile>` — kế thừa rồi **deep-merge** override (do loader xử lý, KHÔNG dùng
  YAML anchor vì anchor chỉ merge một tầng).

### 4.2 Bố trí AI = hybrid
- `common:` — substrate **dùng chung** (không riêng AI): `ai_mode` (offline|openai|auto —
  một provider singleton), `timeout`, `max_retries`.
- `embedder:` — block **riêng, ngang hàng** captioner/reranker. Một block = một embed config
  → giữ bất biến ingest==query. **Không có `impl`** (offline/openai là công tắc toàn cục
  `common.ai_mode`; embed luôn qua gateway theo decision R10 — không có biến thể).
- `captioner` / `reranker` **có** `impl` vì có lựa chọn ngoài AI (`none`, `lexical`).
  Model AI của caption/rerank/ocr nằm **cạnh component tiêu thụ** (locality).
- `mapping.py` gom `common.*` + `embedder.*` + `captioner.model` + `reranker.model` +
  `parser.ocr.*` → dựng **một** `AISettings` → **một** `AIProvider`. Kế thừa key/url
  (caption/rerank/ocr trống → mượn embedder) giữ như `load_ai_settings` hiện tại.
- **Ràng buộc fail-fast:** cấm khai `embed` bên trong bất kỳ component nào (không mở lại
  lỗ hổng ingest≠query).

### 4.3 Ví dụ đầy đủ

```yaml
active: ${PIPELINE_PROFILE:-baseline}

profiles:
  baseline:
    common:                              # SHARED — không riêng AI
      ai_mode:     ${AI_PROVIDER:-offline}   # offline | openai | auto
      timeout:     60
      max_retries: 5

    embedder:                            # block riêng, ngang captioner/reranker; KHÔNG có impl
      model:     text-embedding-3-small
      base_url:  ${EMBED_BASE_URL:-}
      api_key:   ${OPENAI_API_KEY:-}     # SECRET — chỉ là tham chiếu, không phải giá trị
      dimension: 1024

    captioner:
      impl:  provider                    # provider | none
      model: gpt-4o-mini                 # base_url/api_key trống -> kế thừa embedder
      params: { max_chars: 6000 }

    reranker:
      impl:  llm                         # llm | lexical | none
      model: gpt-4o-mini
      params: { passage_chars: 800 }     # threshold/top_k là search-time -> ở `retrieval`

    parser:
      impl: local                        # local | markitdown | unstructured
      params: { max_workers: 2 }
      ocr:  { model: gpt-4o-mini }       # vision; trống -> kế thừa caption

    chunker:
      impl: heading_sections             # heading_sections | token_window | semantic
      params: { parent_max_words: 220, child_max_words: 90, child_overlap_words: 15 }

    vector_store:
      impl: qdrant                       # qdrant | chromadb | milvus
      params: { collection: rag_chatbot, url: ${VECTOR_DB_URL:-}, api_key: ${VECTOR_DB_API_KEY:-} }

    retrieval:                           # các knob search-time gom một chỗ
      top_k_candidates: 20
      rerank_top_k:     3
      rerank_threshold: 0.7

  # Thí nghiệm: chỉ override đúng phần khác baseline (phục vụ đánh giá A/B)
  exp_semantic_chunk:
    extends: baseline
    chunker: { impl: semantic, params: { breakpoint_percentile: 95 } }

  exp_rerank_4o:
    extends: baseline
    reranker:  { impl: llm, model: gpt-4o }
    retrieval: { rerank_threshold: 0.6 }

  # Production: ép OpenAI + Qdrant remote, secret bắt buộc (không default)
  prod:
    extends: baseline
    common:       { ai_mode: openai }
    vector_store: { impl: qdrant, params: { url: ${VECTOR_DB_URL}, api_key: ${VECTOR_DB_API_KEY} } }
```

Chạy A/B không sửa file:
```bash
PIPELINE_PROFILE=exp_semantic_chunk python scripts/benchmark.py
PIPELINE_PROFILE=exp_rerank_4o      python scripts/benchmark.py
```

## 5. `mapping.py` — manifest tập trung + register() mỏng

Hướng "optimal": **manifest dict tập trung làm nguồn đọc duy nhất**, đặt trên một primitive
`register()` để plugin/test cắm hoặc override impl mà không sửa core (giữ MOSA như
`vectorstore/registry.py` đã có, tổng quát ra mọi stage).

```python
_REGISTRY: dict[str, dict[str, Factory]] = defaultdict(dict)

def register(component, name, factory, *, override=False): ...
def resolve(component, stage_cfg, ctx): ...

# ── BUILT-INS: đọc khối này là thấy toàn bộ vũ trụ component ──
register("parser",      "local",            lambda p, ctx: LocalFileParser(**p, image_text_extractor=ctx.ocr))
register("chunker",     "heading_sections", lambda p, ctx: SectionChunker(**p))
register("chunker",     "token_window",     lambda p, ctx: TokenWindowChunker(**p))
register("captioner",   "provider",         lambda p, ctx: ProviderCaptioner(ctx.provider, **p))
register("captioner",   "none",             lambda p, ctx: None)
register("reranker",    "llm",              lambda p, ctx: LLMReranker(ctx.provider, **p))
register("reranker",    "lexical",          lambda p, ctx: LexicalRerankerService())
register("reranker",    "none",             lambda p, ctx: NoopRerankerService())
register("vector_store","qdrant",           lambda p, ctx: build_qdrant(p, dimension=ctx.dim))

def build_pipeline(cfg: PipelineConfig) -> HaystackRagEngine:
    provider = build_ai_provider(cfg)                 # gom common + embedder + caption/rerank/ocr
    dim = provider.dimension if cfg.common.ai_mode == "offline" else cfg.embedder.dimension
    ctx = WireContext(provider=provider, dim=dim, ocr=ProviderImageTextExtractor(provider))
    return HaystackRagEngine(
        settings  = HaystackSettings(embed_dimension=dim, **cfg.retrieval),
        embedder  = ProviderEmbeddingService(provider, dimension=dim),
        chunker   = resolve("chunker",      cfg.chunker,      ctx),
        captioner = resolve("captioner",    cfg.captioner,    ctx),
        reranker  = resolve("reranker",     cfg.reranker,     ctx),
        vectors   = resolve("vector_store", cfg.vector_store, ctx),   # dim ép tại đây
    )
```

`WireContext` bơm những thứ **không** khai trong yaml mà phải suy ra runtime: `provider` đã
dựng, `dim` (ép `vector_store.dimension == embedder.dimension`), `ocr extractor` cho parser.

## 6. Điều kiện tiên quyết (thay đổi code)

`engine` đã nhận mọi thứ qua constructor → tốt. Để "triệt để" mọi stage, phải đóng 2 lỗ hổng:

1. **Chunker → port.** `split_sections` hiện là free-function gọi thẳng trong
   [`engine.ingest`](../../core_engine/engine.py). Cần `Chunker` Protocol
   (`split(markdown)->list[Section]`) + `SectionChunker` bọc `split_sections`; engine nhận
   `chunker` qua `__init__`.
2. **Parser → registry.** Port đã sạch ([`Parser`](../../app/domain/repositories/parser.py));
   chỉ thiếu name→factory + bỏ hardcode `build_parser`.
3. **Bỏ phụ thuộc AI singleton toàn cục** (`get_ai_provider()` default): build provider tường
   minh từ config rồi inject (factory đã truyền provider sẵn nên nhẹ).
4. **Validate bằng pydantic** (đã có qua FastAPI): gom các `validate_*` trong
   [`runtime.py`](../../app/interfaces/api/runtime.py) vào schema, fail-fast lúc startup.

## 7. Kế hoạch thực thi (mỗi phase test xanh trước khi sang phase sau)

- **Phase 0 — Chunker port + parser registry** (0 đổi hành vi). Verify:
  `python -m core_engine.tests.selftest` + `pytest tests/core_engine`.
- **Phase 1 — mapping.py**: `register()` + manifest 7 stage + `build_pipeline()`; `build_engine`
  reimplement trên `build_pipeline`. Verify: toàn bộ test cũ vẫn xanh (qua shim).
- **Phase 2 — config layer**: `config_schema.py` (pydantic) + `config_loader.py`
  (interpolation + `extends` deep-merge + chọn profile + validate; chặn `embed` lạc chỗ).
- **Phase 3 — rewire bootstrap**: `bootstrap_runtime` đọc `PIPELINE_CONFIG=config.yaml` →
  `build_pipeline`; giữ fallback đường env một nhịp để không vỡ deploy hiện tại.
- **Phase 4 — ship**: `config.yaml` mẫu (baseline + profile thí nghiệm); cập nhật README +
  `scripts/benchmark.py` sang profile.

## 8. Backward-compat & rủi ro

| Rủi ro | Cách chặn |
|---|---|
| Đổi `engine.__init__` phá callers | `build_engine` default-dựng `SectionChunker`; không nơi nào gọi `HaystackRagEngine(...)` trực tiếp (đã grep) |
| `build_engine`/`split_sections`/`get_ai_provider` đổi chữ ký | **giữ nguyên** — 12 file test + ipynb + benchmark không vỡ |
| Drift validate cũ ↔ pydantic | Phase 2 dời nguyên văn từng check + giữ message; test đối chiếu |
| Secret lọt vào yaml | loader chỉ chấp nhận `${VAR}` cho key nhạy cảm; literal secret → cảnh báo |
| `extends` deep-merge sai | `test_config_loader` phủ merge lồng + override |

## 9. Quyết định đã chốt

| Hạng mục | Quyết định |
|---|---|
| Profiles | Đa profile + `active`; experiment dùng `extends` (deep-merge) |
| Secret | `${VAR}` env interpolation; fail-fast nếu thiếu; không literal trong yaml |
| Registry | Manifest dict tập trung trong `mapping.py` + `register()` mỏng cho extension/override |
| Scope module | Triệt để cả 7 stage (gồm chunker→port, parser→registry) |
| Bố trí AI | Hybrid: `common` (mode/timeout/retries) + `embedder` block riêng + caption/rerank/ocr cạnh component |
| Tên block shared | `common` (đề xuất — chờ chốt cuối) |
| Phạm vi config | Component-only; ranh giới "ảnh hưởng kết quả → yaml" vs "vận hành/deploy → env" |
```
