# AI Router — Observability & Activation Runbook

Router đứng giữa service AI-logic và provider (OpenAI/OpenRouter): tại mỗi thời điểm chọn bộ ba
`(api_key, base_url, model_name)` để **cân bằng tải 5 key OpenAI + 5 key OpenRouter**, đếm
**cost/token per key** (Redis), và fallback theo bậc thang `routing.yaml`. User cuối không biết;
devops thấy đủ qua Grafana + Langfuse.

## 1. Observability (làm TRƯỚC khi activate — dựng "mắt" trước)

- ai-router expose `GET /metrics` (Prometheus). Per-key gauge từ Redis + leading-indicator counter.
  `key_id` = định danh GitHub secret (`oai-3` ↔ `OPENAI_API_KEY_3`); **không bao giờ lộ raw key**.
- **Prometheus**: thêm job trong [prometheus-ai-router.yml](prometheus-ai-router.yml) vào `scrape_configs` rồi reload.
- **Grafana**: import [grafana-ai-router-dashboard.json](grafana-ai-router-dashboard.json), chọn datasource Prometheus.
  Panels: load/RPM per key, cost theo tier, cost+quota per key, **fallback rate** (leading indicator
  drift), quota burndown, resolve failures.
- **Langfuse**: mỗi generation gắn `model THẬT` + metadata `router_key_id/router_tier` → lọc
  "request này dùng key/tier nào" (per-key aggregate để Grafana, đây chỉ per-request).
- Đối soát: `sum(airouter_key_cost_month_usd)` ≈ tổng cost Langfuse. Lệch >10% = bug accounting.

Kiểm nhanh trên VM (qua SSH tunnel): `curl -s localhost:8010/metrics | grep airouter_keys_total`
và `curl -s -H "X-Internal-Token: $AIROUTER_INTERNAL_TOKEN" localhost:8010/admin/quota` →
mảng `keys` phải = 10 (5 oai + 5 or). Thiếu = secret chưa set (render-secrets ghi rỗng, không lỗi).

## 2. Activation — thứ tự AN TOÀN (master switch mặc định TẮT)

Mọi thay đổi luồng đều sau **kill-switch + parity test**, bật dần canary. Prod hiện KHÔNG đổi.

### Bước 0 — secret (1 lần)
GitHub Secrets `cds0987/DA08-VSF-AI`: `OPENAI_API_KEY_1..5`, `OPENROUTER_API_KEY_1..5`,
`AIROUTER_INTERNAL_TOKEN` (đã có CI forward + render-secrets). Đặt `OPENAI_API_KEY` (secret.env)
= `AIROUTER_INTERNAL_TOKEN` khi route (router giữ key thật, service chỉ gửi token).

### Bước 1 — chuẩn hóa Chat Completions (query-service)
`query-service.env`: `LLM_MODEL_ADAPTER=chat`. Adapter đổi Responses API → Chat Completions chuẩn
(graph LangGraph KHÔNG đổi — xem test contract). Chạy parity test golden-set so output trước/sau.

### Bước 2 — route LLM qua router
`query-service.env`: `OPENAI_BASE_URL=http://ai-router:8010/v1`. LLM gửi capability `think/triage/guardrail`
→ router xoay key + fallback ladder. Theo dõi Grafana fallback rate + cost.

### Bước 3 — route embeddings (rag-worker + mcp-service)
`common.env`: `EMBED_BASE_URL=http://ai-router:8010/v1` (hiện rỗng = direct). rag-worker & mcp-service
**đã hỗ trợ base_url sẵn** (`OpenAIProvider`/`OpenAIEmbedder`/`LlmReranker`) → chỉ đổi env, không sửa code.
- rag-worker caption/rerank: trỏ `CAPTION_MODEL`/`RERANK_MODEL` → capability `caption`/`rerank` nếu muốn
  route cả chat (caption/rerank). Embeddings đi `/v1/embeddings` (router bỏ qua model, resolve `embed`).
- mcp-service: `embed_base_url`/`rerank_base_url` trong config.yaml → `http://ai-router:8010/v1`.

### Rollback tức thì
Xoá `OPENAI_BASE_URL`/`EMBED_BASE_URL` hoặc `LLM_MODEL_ADAPTER=responses` → mọi thứ về thẳng OpenAI
(base_url=None là default). ai-router chết KHÔNG kéo service khác (không ai `depends_on`).

## 3. Test gác (CI đỏ = không lên prod)

- `query-service/tests/test_chat_adapter_contract.py` — hợp đồng adapter chat (tool_calls, usage shape,
  model thật, _router, system prompt, base_url).
- `query-service/tests/test_llm_architecture_enforcement.py` — GATE kiến trúc:
  - SDK LLM call chỉ trong allowlist adapter (cấm gọi thẳng bypass router).
  - capability hợp lệ (chống typo 404) + chống drift vs `routing.yaml`.
  - adapter giữ surface BaseChatModel (LangGraph).
- `ai-router/tests/test_app_smoke.py::test_metrics_*` — /metrics có per-key + không lộ raw key.
