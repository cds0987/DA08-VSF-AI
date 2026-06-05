# Execution guide — Config-driven pipeline refactor

> Đi kèm [`config-driven-pipeline.md`](./config-driven-pipeline.md) (design). Tài liệu này
> ghi **từng phase làm gì**, đến mức file/bước, **cách verify**, và **lưu ý để refactor đúng**.
> Quy tắc bao trùm: **mỗi phase phải để test cũ xanh trước khi sang phase sau**; commit theo phase.

---

## 0. Lưu ý chung (đọc trước khi chạm code)

Những điều này áp cho MỌI phase — vi phạm là refactor sai dù test có vẻ xanh.

1. **Không đổi chữ ký public.** Giữ nguyên: `build_engine`, `build_engine_probe`,
   `split_sections`, `Section`, `get_ai_provider`, `set_ai_provider`, `reset_ai_provider`,
   `OfflineProvider`, `IngestInput`. ~12 file (`tests/`, `core_engine/tests/selftest*`,
   `scripts/benchmark.py`, `eval/*.ipynb`) phụ thuộc trực tiếp.

2. **Tôn trọng layering — đây là cạm bẫy lớn nhất.**
   `core_engine` được phép import `app.domain` (port: `EmbeddingService`, `VectorRepository`,
   `Parser`) nhưng **TUYỆT ĐỐI không import `app.infrastructure`**. Hệ quả thực tế:
   - Engine-scope component (embedder, chunker, captioner, reranker, vector_store, ai) →
     registry nằm ở **`core_engine/mapping.py`**.
   - `parser` (LocalFileParser là `app.infrastructure`), `artifact_store`, `metadata repo`
     → registry nằm ở **tầng app** (vd `app/interfaces/api/composition.py`), KHÔNG ở core_engine.
   - → một `config.yaml` nuôi **hai scope composition**: engine (core) + parser/use-case (app).
     `config_loader` trả một `PipelineConfig` typed, cả hai scope cùng đọc.

3. **Bất biến dimension.** Lúc lắp ráp phải ép `vector_store.dimension == embedder.dimension`
   và `HaystackSettings.embed_dimension == dim` (giữ logic `replace(settings, embed_dimension=dim)`
   + `VectorStoreConfig.with_dimension(dim)` của factory hiện tại). Offline: dim lấy từ
   `provider.dimension`. OpenAI: dim từ `cfg.embedder.dimension` (probe là tùy chọn,
   không bắt buộc cho path config-driven).

4. **Embed một-nguồn.** `embedder` chỉ được khai ở block riêng. Loader phải **reject** nếu
   thấy `embed`/`embedder` bên trong bất kỳ component nào (chặn lỗ hổng ingest≠query).

5. **Kế thừa capability AI** (giữ như `load_ai_settings`): caption/rerank/ocr trống base_url/api_key
   → kế thừa embedder → caption. `ai_mode=auto` giữ logic auto-detect cũ
   (`has_real = embed.api_key or embed.base_url`).

6. **Secret.** Chỉ `${VAR}`; không bao giờ log/echo giá trị secret đã resolve (redact ở
   health report + bất kỳ dump config nào).

7. **Phân loại tham số reranker (dễ sai).** Đọc [`engine.search`](../../core_engine/engine.py):
   `threshold` và `top_k` là tham số **search-time** lấy từ `settings.rerank_threshold` /
   `settings.rerank_top_k`, KHÔNG phải tham số dựng reranker. Chỉ `passage_chars` mới là tham
   số constructor của `LLMReranker`. → Khi map config:
   - `threshold`, `top_k` → đổ vào `HaystackSettings` (nhóm cùng `retrieval`).
   - `passage_chars` → constructor `LLMReranker(passage_chars=...)`.
   **Khuyến nghị:** trong yaml để `threshold`/`top_k` dưới `retrieval:` cho đúng bản chất; block
   `reranker` chỉ giữ `impl` + `model` + `passage_chars`. (Cập nhật lại ví dụ ở design doc cho khớp.)

---

## Phase 0 — Chunker → port + parser → registry (0 đổi hành vi)

**Mục tiêu:** đóng 2 lỗ hổng port, KHÔNG đổi output pipeline. Là nền cho mọi phase sau.

**Tạo mới**
- `core_engine/chunking/base.py`:
  - `Chunker` (Protocol, `runtime_checkable`): `def split(self, markdown: str) -> list[Section]`.
  - `SectionChunker`: ôm `parent_max_words/child_max_words/child_overlap_words`, `split()` gọi
    `split_sections(markdown, **self._params)`. **Giữ nguyên thuật toán** — chỉ là wrapper.

**Sửa**
- `core_engine/chunking/__init__.py`: export thêm `Chunker`, `SectionChunker` (giữ `Section`,
  `split_sections`).
- [`core_engine/engine.py`](../../core_engine/engine.py):
  - `__init__` thêm tham số `chunker: Chunker` (đặt sau `captioner` hoặc trước — miễn `build_engine`
    truyền bằng keyword). Lưu `self.chunker`.
  - Dòng gọi `split_sections(...)` → `self.chunker.split(doc.markdown)`. Giữ nguyên `split_sw`
    đo `split_ms`. **Không** đọc `settings.parent_max_words` ở đây nữa (đã chuyển vào chunker).
- [`core_engine/factory.py`](../../core_engine/factory.py) `_wire`: dựng
  `SectionChunker(parent_max_words=settings.parent_max_words, child_max_words=settings.child_max_words,
  child_overlap_words=settings.child_overlap_words)` và truyền `chunker=...` vào `HaystackRagEngine`.
  → `build_engine` giữ nguyên chữ ký, callers không đổi.
- Parser registry (tầng app, vì layering): tạo `app/interfaces/api/composition.py` (hoặc
  `app/infrastructure/external/parser_registry.py`) với `register_parser(name, factory)` +
  built-in `"local"` → `LocalFileParser`. Sửa [`build_parser`](../../app/interfaces/api/runtime.py)
  để resolve qua registry (mặc định `"local"`), vẫn nhận `image_text_extractor` từ provider.

**Verify**
```bash
python -m core_engine.tests.selftest
python -m core_engine.tests.selftest_vectorstore   # nếu có qdrant-client
pytest tests/core_engine tests/e2e -q
```
**Lưu ý phase 0**
- `SectionChunker.split` phải cho **kết quả y hệt** `split_sections` cũ (so sánh trên một
  markdown mẫu). Đây là phase behavior-preserving — nếu test ranking/search đổi kết quả là sai.
- Không nơi nào dựng `HaystackRagEngine(...)` trực tiếp (đã grep) → thêm tham số `chunker`
  an toàn; nhưng nếu test nào đó dựng tay thì phải cập nhật.

---

## Phase 1 — `core_engine/mapping.py` (engine-scope)

**Mục tiêu:** một manifest + assembler cho engine-scope; `build_engine` reimplement trên nó.

**Tạo mới** `core_engine/mapping.py`:
- `_REGISTRY: dict[str, dict[str, Factory]]` + `register(component, name, factory, *, override=False)`
  + `resolve(component, stage_cfg, ctx)`.
- `WireContext(provider, dim, ocr_extractor)`.
- `build_ai_provider(cfg)`: gom `common` + `embedder` + `captioner.model` + `reranker.model` +
  `parser.ocr` → `AISettings` → `_build_provider` (tái dùng `core_engine.ai`).
- `build_engine_from_config(cfg) -> HaystackRagEngine`: như mã trong design doc §5.
- Đăng ký built-in cho: `chunker` (heading_sections [+ token_window/semantic nếu làm]),
  `captioner` (provider/none), `reranker` (llm/lexical/none), `vector_store` (qdrant/chromadb/milvus).
  `embedder` KHÔNG cần `impl` (xem §0.4 design): luôn `ProviderEmbeddingService`.

**Sửa**
- `core_engine/factory.py`: `build_engine(...)` trở thành **shim** — dựng một `PipelineConfig`
  tạm từ kwargs (`provider`, `caption`, `reranker`, `vector_config`, settings) rồi gọi
  `build_engine_from_config`. Mục tiêu: **một đường lắp ráp**, không hai bản wiring.
- `core_engine/__init__.py`: export `build_engine_from_config`, `register`, `Chunker`.

**Verify:** toàn bộ test cũ vẫn xanh (đi qua shim). Thêm `tests/core_engine/test_mapping.py`:
register/resolve/override; `build_engine_from_config` dựng đúng loại component theo cfg.

**Lưu ý phase 1**
- Shim `build_engine` phải map đúng: `caption=False` → captioner impl `none`;
  `reranker=<obj>` truyền tay → resolve trả thẳng obj đó (giữ nhánh "reranker is not None"
  của factory cũ); `vector_config` → vector_store config.
- Giữ phân loại tham số reranker (§0.7): shim đặt threshold/top_k vào settings.

---

## Phase 2 — Config layer (`config_schema.py` + `config_loader.py`)

**Mục tiêu:** đọc & validate `config.yaml` thành `PipelineConfig` typed (pydantic).

**Tạo mới**
- `core_engine/config_schema.py` (pydantic): `PipelineConfig` với sub-model
  `Common`, `Embedder`, `Captioner`, `Reranker`, `Parser`, `Chunker`, `VectorStore`, `Retrieval`.
  Dời **nguyên văn** các kiểm tra trong [`runtime.py`](../../app/interfaces/api/runtime.py)
  (`validate_runtime_settings`, `validate_vector_config`, `validate_ai_config`) thành pydantic
  validator, **giữ y nguyên message** để không đổi hành vi lỗi.
- `core_engine/config_loader.py`:
  1. đọc yaml,
  2. **interpolate** `${VAR}` / `${VAR:-default}` (thiếu, không default → raise),
  3. chọn profile (`active`, override bằng env `PIPELINE_PROFILE`),
  4. resolve `extends` bằng **deep-merge** (KHÔNG dùng YAML anchor),
  5. validate qua schema,
  6. **reject** `embed`/`embedder` lạc trong component (§0.4).

**Verify** `tests/core_engine/test_config_loader.py`: interpolation (có/không default, thiếu →
lỗi), `extends` deep-merge lồng nhau + override, chọn profile theo env, schema lỗi → fail-fast,
chặn embed lạc chỗ.

**Lưu ý phase 2**
- Deep-merge: dict merge đệ quy; với list quyết định rõ (mặc định **replace** cả list, đừng
  concat — tránh kết quả bất ngờ). Ghi rõ quy ước này trong docstring + test.
- Interpolation chạy **trước** parse YAML→object hay sau? Làm trên **chuỗi/scalar sau khi load
  YAML** (duyệt cây, thay scalar) để không phá cú pháp YAML. Không interpolate khóa, chỉ giá trị.
- Validator không được làm rò secret (đừng đưa giá trị api_key vào message lỗi).

---

## Phase 3 — Rewire bootstrap (tầng app)

**Mục tiêu:** `bootstrap_runtime` chạy bằng config.yaml; giữ fallback env một nhịp.

**Sửa** [`app/interfaces/api/runtime.py`](../../app/interfaces/api/runtime.py) `bootstrap_runtime`:
- Đọc `PIPELINE_CONFIG` (mặc định `config.yaml`). Nếu có file → `cfg = load_config(...)`:
  - engine = `build_engine_from_config(cfg)`,
  - parser = parser-registry app resolve theo `cfg.parser` (+ `ProviderImageTextExtractor(provider)`),
  - dựng `IngestDocumentUseCase` / `RetrievalUseCase` như cũ.
- Nếu **không** có file → đi nguyên path env cũ (`build_engine` + `build_parser`) — fallback giữ
  deploy hiện tại sống. (Xóa fallback ở PR sau khi yaml ổn định.)
- Ops/infra (worker_count, lease, rate-limit, DATABASE_URL, source_root, log_level, app_env)
  **vẫn đọc env** — không đưa vào config.yaml (xem ranh giới ở design §3).

**Verify** `pytest tests/e2e -q` (ingest/search end-to-end qua FastAPI lifespan), cả nhánh
có-file lẫn không-có-file config.

**Lưu ý phase 3**
- Health report (`compute_health`) đang in `ai_provider`, `vector_provider`, `vector_index`…
  Cập nhật để lấy từ cfg, **redact** secret. Giữ logic fail-closed production
  (offline/in_process/non-postgres → refuse boot khi `APP_ENV=prod`).
- Provider: dùng provider dựng từ config, **không** gọi `get_ai_provider()` global song song
  (tránh hai provider khác cấu hình). `reset_ai_provider()` chỉ cần nếu vẫn còn nơi đọc global.

---

## Phase 4 — Ship

**Mục tiêu:** đưa vào dùng + tài liệu.

**Tạo/sửa**
- `config.yaml` mẫu (ở `src/rag-worker/`): `baseline` + ≥1 profile thí nghiệm (vd
  `exp_semantic_chunk`, `exp_rerank_4o`). Có chú thích `${VAR}` cho secret.
- `.env.example`: liệt kê env còn lại (ops + secret + endpoint) sau khi pipeline-param dời sang yaml.
- `core_engine/README.md`: cập nhật mục "Chạy / Dùng trong code" → nói về config.yaml + profile.
- `scripts/benchmark.py`: đổi A/B sang `PIPELINE_PROFILE=<profile>` thay vì sửa `.env`.
- `deploy/k8s/configmap.yaml`: mount `config.yaml`; secret giữ ở `secret.example.yaml`.

**Verify:** chạy benchmark 2 profile khác nhau, xác nhận đổi module = đổi profile, 0 dòng code.

**Lưu ý phase 4**
- Đừng commit secret thật vào `config.yaml`/`.env.example`.
- Kiểm tra `VECTOR_COLLECTION` trong yaml **không** tự encode `__d\d+` (validate cũ vẫn áp).

---

## Thứ tự commit đề xuất
1. `docs: reorg gap/ + add refactor design` (đã làm).
2. `refactor(phase0): Chunker port + parser registry (no behavior change)`.
3. `refactor(phase1): core_engine/mapping.py; build_engine becomes shim`.
4. `feat(phase2): config schema + loader (yaml, interpolation, profiles)`.
5. `refactor(phase3): bootstrap reads config.yaml (env fallback kept)`.
6. `feat(phase4): example config.yaml + docs + benchmark profiles`.

Mỗi commit: chạy `pytest -q` + selftest, mô tả phase trong message.
