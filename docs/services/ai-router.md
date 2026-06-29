---
service: ai-router
path: src/ai-router
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/ai-router/app/main.py
  - src/ai-router/ai_router/router.py
  - src/ai-router/ai_router/config.py
  - src/ai-router/routing.yaml
  - src/ai-router/ai_router/registry.py
  - src/ai-router/ai_router/selector/base.py
  - src/ai-router/ai_router/selector/__init__.py
  - src/ai-router/ai_router/counters.py
  - src/ai-router/ai_router/observability.py
  - src/ai-router/ai_router/embed_coalescer.py
---
# AI Router

Gateway FastAPI tương thích OpenAI. Service khác chỉ đổi `base_url -> http://ai-router:8010/v1`
và dùng OpenAI SDK như cũ; field `model` mang **alias capability** (answer/triage/ocr/embed/...)
chứ không phải model thật.

## Trách nhiệm
- 1 cổng duy nhất cho mọi call LLM/embed/rerank: resolve capability -> chọn (key, base_url, model)
  theo routing.yaml -> gọi provider -> parse usage -> accounting + cooldown + retry/failover.
- Phân bổ tải đa-key (banded rotation / adaptive AIMD / TPM-headroom) + quota-aware (counters Redis).
- Observability: Prometheus `/metrics` (per-key gauge + counter leading-indicator) + log có cấu trúc
  mỗi call (key/model/tier/tokens/cost/latency/conversation_id). Langfuse chỉ trace ở caller (đọc field `model`).

## API / giao diện (HTTP, từ app/main.py)
- `POST /v1/chat/completions` — chat; hỗ trợ `stream=true` (SSE `data:` + `[DONE]`). Header tuỳ chọn `X-Conversation-Id`.
- `POST /v1/embeddings` — embed; route THEO `body["model"]` (multi-collection), qua EmbedCoalescer (coalesce opt-in, mặc định passthrough).
- `POST /v1/rerank` — Cohere `/rerank` passthrough (raw httpx, không OpenAI SDK).
- `POST /v1/route` — resolver: nhận `{capability, est_tokens?, has_tools?, messages?, conversation_id?, endpoint?}` -> trả RouteDecision (cần internal token).
- `GET /health` — `{status, keys, models, selector}`.
- `GET /metrics` — Prometheus text (shared qua Redis nếu có sink, không thì in-process). KHÔNG lộ secret (chỉ key_id/secret_env).
- `GET /admin/quota` — snapshot quota/key live (auth).
- `POST /admin/reload` — hot-reload routing.yaml + catalog + key (auth).
- `POST /admin/key/{key_id}/drain` + `/resume` — HITL: rút/khôi phục key khỏi vòng xoay (TTL 24h, guardrail không drain key sống cuối; auth).

Auth nội bộ: `_auth` so `X-Internal-Token` hoặc `Authorization: Bearer` với `AIROUTER_INTERNAL_TOKEN`;
không set token -> bỏ qua (dev). `/v1/chat/completions` + `/v1/embeddings` + `/v1/rerank` cũng gọi `_auth`.

## Luồng nội bộ chính
1. `resolve_capability(alias)` (aliases trong routing.yaml) -> capability -> chọn selector (per-capability nếu khai `selector`, else global).
2. Selector `banded_tier`: lọc key theo provider, bỏ key cooldown/drained -> banded rotation (dính 1 key tới `band_tokens` est rồi xoay) -> `pick_model` (pinned > danh sách interchange bỏ model cooldown > auto rẻ nhất khả thi) -> `feasible_model` gate (provider-split, free/paid, tools, vision, context_length, endpoint) -> `reserve()` nguyên tử (RPM + daily cap).
3. Cạn mọi tier -> `save_mode`: degrade `xiaomi/mimo-v2.5` (paid OpenRouter), bỏ trần free -> tránh 503.
4. Gọi provider (`chat`/`chat_stream`/`embeddings`/`rerank`), `_prep_body` chuẩn hoá param theo provider (reasoning chỉ OpenRouter; OpenAI dùng `max_completion_tokens`; ocr tự inject `reasoning:{enabled:false}`).
5. `account()` ghi usage/cost (cost từ response hoặc tính từ catalog) + AIMD grow khi OpenRouter OK.
6. Lỗi: `classify_provider_error` -> `quota` (cooldown key tới nửa đêm UTC) / `rate` (key 30s, embed+rerank 3s + AIMD shrink) / `model` (cooldown model 30s). Retry `MAX_ATTEMPTS=4`; cạn -> `NoCapacityError`(503) / `RouterCallError`(502).

Selector plugins (`selector/__init__.py`): `banded_rotation` (default), `weighted_banded`, `sticky_rotation_soft`, `elastic_banded`, `adaptive_balanced` (OpenAI=TPM-headroom · OpenRouter=AIMD tự dò 429). Đổi thuật toán = đổi `impl` trong routing.yaml.

## Config / ENV
- Settings prefix `AIROUTER_` (config.py): `redis_url` (None -> in-memory counter), `routing_path` (default `routing.yaml`), `catalog_path` (`config/model_catalog.json`), `internal_token`, `request_timeout` (60s), `enabled`, `reconcile_on_boot` (off), `metrics_flush_interval_seconds` (3s).
- registry.py: `AIROUTER_OPENAI_TOKENS_PER_DAY` (2.5M), `AIROUTER_OPENROUTER_REQ_PER_DAY` (1000), `AIROUTER_OPENROUTER_RPM` (600).
- counters.py AIMD: `AIROUTER_AIMD_INIT/MIN/MAX/TTL` (8/2/64/300).
- embed_coalescer.py: `EMBED_COALESCE_ENABLED` (0 = passthrough).
- Keys auto-discover từ env: chỉ pattern `OPENAI_API_KEY_{n}` + `OPENROUTER_API_KEY_{n}` (key đơn cũ bị loại). Thêm key = thêm secret.

## Phụ thuộc
- Providers: OpenAI (`OPENAI_API_KEY_{n}`) + OpenRouter (`OPENROUTER_API_KEY_{n}`, base `https://openrouter.ai/api/v1`); Cohere rerank qua OpenRouter `/rerank`.
- Redis (`AIROUTER_REDIS_URL`): counters (reserve/quota/cooldown/band/inflight/AIMD) + shared metrics sink. Không có Redis -> in-memory (dev/test 1 process).
- Langfuse: KHÔNG gọi từ router; router gắn `_router`(key_id/tier/served_model) vào response để caller tag trace.

## Code map
- [app/main.py](src/ai-router/app/main.py) — FastAPI endpoints, auth, startup hooks (reconcile, metrics flush loop).
- [ai_router/router.py](src/ai-router/ai_router/router.py) — engine: resolve/chat/chat_stream/embeddings/rerank, account, cooldown, error-classify, drain, snapshot.
- [ai_router/config.py](src/ai-router/ai_router/config.py) — Settings + RoutingTable/CapabilityConfig/SelectorConfig, load + hot-reload routing.yaml.
- [routing.yaml](src/ai-router/routing.yaml) — tiers, aliases, capabilities (answer/plan/synth/triage/triage_fast/think/worker/rerank/rerank_api/guardrail/summary/caption/ocr/embed*), selector per-node.
- [ai_router/registry.py](src/ai-router/ai_router/registry.py) — discover key từ env, TIER_DEFS (free_oai/free_or/paid/embed_oai/embed_or).
- [ai_router/selector/](src/ai-router/ai_router/selector/) — base (banded_tier/save_mode/feasible_model/pick_model) + 5 plugin selector.
- [ai_router/counters.py](src/ai-router/ai_router/counters.py) — Redis/Memory counters: reserve nguyên tử, band, RPM/quota/cost, cooldown, inflight, AIMD.
- [ai_router/observability.py](src/ai-router/ai_router/observability.py) — Metrics in-process + RedisMetricsSink + render Prometheus.
- [ai_router/embed_coalescer.py](src/ai-router/ai_router/embed_coalescer.py) — gom batch embed theo cửa sổ (opt-in).
- Phụ trợ: catalog.py, parser.py (extract_usage), reconcile.py, client_factory.py, schemas.py.
