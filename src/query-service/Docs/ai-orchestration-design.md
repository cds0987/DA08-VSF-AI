# Thiết kế: Lớp điều phối AI (AI Orchestration / Model Router)

> Trạng thái: **DESIGN ONLY — chưa code**. Tài liệu để duyệt trước khi triển khai.

## 1. Vấn đề

Hiện tại model/key/endpoint được nạp từ `env` **một lần lúc boot** rồi cache cứng:

- `get_settings()` đọc env khi khởi động.
- Các provider client có `@lru_cache` → `AsyncOpenAI` được tạo 1 lần, dùng suốt vòng đời process.
- `query-service` còn **không truyền `base_url`** → khóa cứng vào `api.openai.com`.

→ Đổi model/provider **bắt buộc redeploy**. Thiếu một lớp điều phối ở runtime.

## 2. Nhận định mấu chốt

**Tất cả call site đều dùng OpenAI SDK** (`AsyncOpenAI`). Vì vậy một "route" chỉ là bộ 3:

```
(base_url, model_name, api_key)
```

`api_key` gắn với `base_url` (mỗi provider 1 key) → biến quyết định thực sự chỉ là **`base_url` + `model_name`**.

> Toàn bộ "router điều phối" = **runtime resolve ra đúng `(base_url, model_name, api_key)`** rồi đưa cho SDK. Không cần viết lại cách gọi model.

## 3. Mục tiêu

1. Đổi `base_url` + `model_name` (và key tương ứng) **ở runtime, không redeploy**.
2. Tổ chức thành **một folder/module riêng** chuyên điều phối AI.
3. **Cost-aware routing**: chọn model theo tín hiệu chi phí — ước lượng số token, tiết kiệm, linh hoạt.
4. Không phá vỡ call site hiện có: thay `AsyncOpenAI(...)` + `model=...` cứng bằng 1 lệnh resolve.

## 4. Folder đề xuất

```
src/query-service/app/infrastructure/ai_orchestration/
├── __init__.py
├── schema.py          # Pydantic: ProviderProfile, ModelEntry, RoutingRule, RoutingTable
├── registry.py        # ProviderRegistry: base_url + api_key theo provider (env/secret)
├── config_store.py    # Nguồn config runtime-mutable (file hot-reload / Redis / DB) + version
├── policy.py          # RoutingPolicy: (route_key + cost signals) -> chọn ModelEntry
├── cost.py            # Bảng giá/1K token, ước lượng token, cộng dồn usage, ngân sách
├── router.py          # ModelRouter.resolve(route_key, signals) -> ResolvedRoute
├── client_factory.py  # Cache AsyncOpenAI theo (base_url, api_key); trả (client, model_name)
└── admin.py           # (tùy chọn) FastAPI router cập nhật nóng routing table
```

> Đặt trong `query-service` trước (nơi đang khóa cứng). Có thể tách thành package dùng chung cho `rag-worker`/`mcp-service` ở giai đoạn sau.

## 5. Mô hình dữ liệu (schema.py)

```text
ProviderProfile
  name: str                 # "openai" | "openrouter" | "vllm-internal" | ...
  base_url: str | None      # None = OpenAI mặc định
  api_key_env: str          # tên biến env chứa key (KHÔNG lưu key trong config)
  timeout_seconds: int = 30

ModelEntry
  id: str                   # alias logic, vd "fast", "balanced", "strong"
  provider: str             # -> ProviderProfile.name
  model_name: str           # "gpt-5.4-mini", "gpt-4o-mini", model OpenRouter, ...
  price_in_per_1k: float    # giá input / 1K token (USD)
  price_out_per_1k: float   # giá output / 1K token
  max_context: int

RoutingRule
  route_key: str            # capability: "triage" | "think" | "answer" | "rerank"
                            #            | "intent" | "guardrail"
  default_model: str        # ModelEntry.id mặc định cho capability này
  tiers: list[TierRule]     # ngưỡng cost-balancing (mục 7)
  fallback: list[str]       # danh sách ModelEntry.id dự phòng khi lỗi/timeout

RoutingTable
  version: int
  providers: list[ProviderProfile]
  models: list[ModelEntry]
  rules: list[RoutingRule]
```

**Nguyên tắc bảo mật**: config chỉ chứa **tên biến env** của key (`api_key_env`), không bao giờ chứa giá trị key. Key thật vẫn lấy từ env/secret manager.

## 6. Luồng resolve ở runtime (router.py)

```text
ModelRouter.resolve(route_key, signals) -> ResolvedRoute(client, model_name, model_entry)

1. Lấy RoutingTable hiện hành từ config_store (đã hot-reload, có version).
2. Tìm RoutingRule theo route_key (vd "answer").
3. policy.choose(rule, signals): áp tier cost-balancing -> ModelEntry.id.
4. Tra ModelEntry -> provider -> ProviderProfile (base_url + api_key_env).
5. client_factory.get(base_url, api_key) -> AsyncOpenAI (cache theo base_url+key).
6. Trả (client, model_name) cho call site dùng nguyên SDK như cũ.
```

Call site đổi từ:

```python
# CŨ (cứng)
client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=...)
resp = await client.responses.create(model=settings.openai_llm_model, ...)
```

thành:

```python
# MỚI (điều phối runtime)
route = await ai_router.resolve("answer", signals=CostSignals(...))
resp = await route.client.responses.create(model=route.model_name, ...)
```

→ Thay đổi tối thiểu, giữ nguyên cách gọi OpenAI SDK.

## 7. Cost-balancing (policy.py + cost.py)

Tiêu chí: **theo số token đã/ sẽ xử lý + tiết kiệm chi phí**.

**Tín hiệu (CostSignals)** đưa vào lúc resolve:
- `est_input_tokens` — ước lượng từ độ dài prompt + context (cost.estimate_tokens).
- `est_output_tokens` — ước lượng theo loại tác vụ.
- `complexity_hint` — (tùy chọn) gợi ý độ khó (vd từ bước triage).
- `tokens_spent_in_request` — token đã tiêu trong cùng 1 request/phiên (chống lạm dụng model mạnh).

**Quy tắc tier (ví dụ cho route "answer")**:

| Điều kiện | Chọn model |
|---|---|
| `est_total_tokens < T_small` | tier `fast` (model rẻ) |
| `T_small <= tokens < T_large` | tier `balanced` |
| `tokens >= T_large` hoặc complexity cao | tier `strong` |
| Đã vượt ngân sách phiên | ép về `fast` + cảnh báo |

- Ngưỡng `T_small`, `T_large`, bảng giá nằm trong RoutingTable → **đổi nóng được**.
- `cost.py` cộng dồn token thực tế sau mỗi call (từ `usage` trả về của SDK) để theo dõi chi phí theo request/người dùng/ngày, phục vụ quyết định route tiếp theo và báo cáo.

## 8. Đổi config runtime không redeploy (config_store.py)

Hỗ trợ theo thứ tự ưu tiên triển khai:

1. **File + hot-reload** (giai đoạn 1 — đơn giản nhất): đọc `routing.yaml`, watch mtime, reload khi đổi. Không cần DB.
2. **Redis** (giai đoạn 2): publish/subscribe key `ai:routing_table` → mọi instance reload đồng bộ tức thì.
3. **Admin API** (admin.py, tùy chọn): `GET/PUT /internal/ai/routing-table` (chỉ internal token) để cập nhật + bump `version`; ghi xuống store, invalidate cache `client_factory` nếu provider đổi.

Mọi nguồn đều validate qua `schema.RoutingTable` trước khi áp; lỗi validate → giữ bản cũ + log.

## 9. Điểm tích hợp trong query-service

Các call site cần chuyển sang `ai_router.resolve(...)`:

| route_key | File hiện tại |
|---|---|
| `answer` | `external/openai_client.py` |
| `answer`/LangChain | `external/langchain_responses_adapter.py` |
| `intent` + `embedding` | `external/intent_ai_client.py` |
| `tool_decision` | `external/tool_decision_client.py` |
| `guardrail` | `guardrails/llm_guard_service.py` |

`get_settings()` giữ nguyên cho các giá trị khởi tạo mặc định/bootstrap; `@lru_cache` cấp client được thay bằng cache trong `client_factory` (key theo base_url+api_key, không theo toàn bộ settings).

## 10. Tương thích ngược

- Nếu chưa có `routing.yaml`/store → sinh RoutingTable mặc định từ env hiện tại (`OPENAI_API_KEY`, `OPENAI_LLM_MODEL`, base_url=None). Hành vi giống hệt hôm nay.
- Bật/tắt lớp điều phối bằng cờ `AI_ROUTER_ENABLED` (mặc định bật, fallback an toàn về OpenAI nếu store lỗi).

## 11. Quan sát & vận hành (observability)

- Log mỗi quyết định route: `route_key, chosen_model, provider, est_tokens, real_tokens, cost_usd, table_version`.
- Metric: phân bố model theo capability, chi phí theo ngày, tỉ lệ fallback.
- Trace gắn `model_name` + `provider` vào span hiện có (Langfuse/LangSmith đã có sẵn trong repo).

## 12. Kế hoạch triển khai theo giai đoạn

- **GĐ0 (an toàn)**: thêm `base_url` configurable cho query-service + RoutingTable mặc định từ env. Không đổi hành vi.
- **GĐ1**: dựng module `ai_orchestration`, file hot-reload, resolve theo capability (chưa cost-balancing).
- **GĐ2**: thêm `cost.py` + policy tier cost-balancing + accounting token.
- **GĐ3**: Redis sync + Admin API cập nhật nóng + fallback đa provider.
- **GĐ4 (tùy chọn)**: tách thành package dùng chung cho rag-worker/mcp-service.

## 14. (Phase 1 — small model) Bộ quy định: token-price · key · limit/key

> Phạm vi Phase 1: **chỉ small/cheap model**. Model lớn (BIG bucket 250k) + phân quyền
> theo task & cấp bậc nhân viên → **triển khai sau**.

### 14.1 Điểm then chốt: free tier KHÔNG báo lỗi khi cạn

OpenAI free tier: *"usage beyond these limits will be billed at standard rates"* →
**không có lỗi/HTTP 429 khi vượt 2.5M**, hệ thống bị **âm thầm tính phí**.
→ Cách duy nhất biết "share token đã hết" là **tự đếm token đối chiếu với `limit` khai báo**.
Đây là lý do bộ quy định dưới đây là bắt buộc (vừa là ranh giới free→paid, vừa là input để
router chọn nguồn rẻ nhất).

### 14.2 Ba thực thể: KEY · LIMIT · PRICE

```yaml
# ai_orchestration/routing.yaml  (Phase 1 — small model only)

providers:
  - name: openai
    base_url: null                      # null = endpoint OpenAI mặc định
    keys:
      - id: oa-1
        api_key_env: OPENAI_API_KEY_1   # chỉ lưu TÊN env, không lưu key thật
        limits:
          mini:                         # bucket small/nano/mini
            tokens_per_day: 2_500_000   # <-- LIMIT/KEY (ranh giới free)
            reset: utc_daily            # giả định; cần xác nhận mốc reset
      - id: oa-2
        api_key_env: OPENAI_API_KEY_2
        limits:
          mini: { tokens_per_day: 2_500_000, reset: utc_daily }
  - name: openrouter
    base_url: https://openrouter.ai/api/v1
    keys:
      - id: or-1
        api_key_env: OPENROUTER_API_KEY
        limits:
          mini:
            budget_usd_per_day: 5.0     # OpenRouter: cap theo CHI PHÍ thay vì token

models:                                 # chỉ small/cheap ở Phase 1
  - id: mini-openai
    provider: openai
    model_name: gpt-4o-mini             # hoặc gpt-5.4-mini / gpt-5.4-nano
    bucket: mini
    price_in_per_1k:  0.15              # PRICE — giá standard SAU khi hết free (USD/1K)
    price_out_per_1k: 0.60
    free_in_bucket: true                # nằm trong hạn mức free 2.5M
  - id: mini-openrouter
    provider: openrouter
    model_name: <model-re-cua-openrouter>
    bucket: mini
    price_in_per_1k:  <gia>
    price_out_per_1k: <gia>
    free_in_bucket: false               # OpenRouter trả phí (rẻ) ngay từ đầu

rules:
  default_tier: mini
  selection: cheapest_free_then_cheapest_paid
```

> **Bảo mật**: file chỉ lưu `api_key_env` (tên biến), không bao giờ lưu giá trị key.
> Giá trị key lấy từ env/secret manager lúc chạy.

### 14.3 Bộ đếm runtime (nguồn sự thật)

```
Redis key:   quota:{key_id}:{bucket}:{YYYYMMDD}     (TTL ~26h, tự hết hạn)
Sau mỗi call: INCRBY theo usage THẬT từ response (input+output tokens)
remaining(key, bucket) = limits[bucket].tokens_per_day - GET(quota key)
```

OpenRouter (cap theo USD): `cost:{or-key}:{YYYYMMDD}` cộng dồn USD = tokens × price.

### 14.4 Luật chọn tối ưu (Phase 1)

```
resolve(route_key="mini", est_tokens):
  cands = models thuộc tier MINI (enabled)

  # 1) Ưu tiên nguồn FREE còn quota — giá hiệu dụng ≈ 0
  free = [m in cands  if m.free_in_bucket
                       and remaining(key_of(m), m.bucket) >= est_tokens]
  if free:
      # nhiều key OpenAI -> chọn key CÒN DƯ NHIỀU NHẤT (least-used) để gom hết free
      return pick_key_most_remaining(free)

  # 2) Free đã cạn -> chọn PAID rẻ nhất theo giá pha trộn input/output
  paid = [m in cands  if has_budget(m)]          # vd OpenRouter còn budget USD
  return min(paid, key=lambda m:
             est_in*m.price_in_per_1k + est_out*m.price_out_per_1k)

# sau call: ghi usage thật vào counter của (key, bucket)
```

**Hệ quả tối ưu hóa:**
- Pool nhiều key OpenAI ⇒ tổng free MINI = N × 2.5M/ngày; router gom cạn từng key rồi mới sang paid.
- Khi `remaining` chạm 0 ở mọi key OpenAI ⇒ tự động sang OpenRouter (rẻ) — **không bị âm thầm tính phí OpenAI** vì counter đã chặn đúng ranh giới `limit`.
- `price` trong config cho phép so sánh và chọn paid rẻ nhất khi có nhiều lựa chọn trả phí.

### 14.5 Việc để lại cho sau (ngoài Phase 1)

- BIG bucket (250k) + reserve margin cho câu khó.
- Phân quyền model theo **loại task** và **cấp bậc nhân viên** (RBAC trên route_key).
- Cost-balancing động theo độ phức tạp câu hỏi.

## 15. Thiết kế đăng ký (mô phỏng rag-worker) — hấp thụ N key tùy ý

Mục tiêu: **thêm key/provider mới = sửa config, KHÔNG sửa code**; thuật toán chọn key
là **chiến lược cắm-rút được** (linh hoạt). Mượn 5 ý từ rag-worker
(`core_engine/ai/base.py`, `config_schema.py`):

| Ý của rag-worker | Áp vào router |
|---|---|
| `AIProvider` (ABC) — 1 cổng vào, đổi provider không sửa call site | `LLMGateway` 1 cổng `resolve()`; call site chỉ gọi gateway |
| `CapabilityConfig = (base_url, api_key, model)` | `KeyEntry` = bộ 3 đó **+ limits + counters** |
| Định tuyến theo `capability` | route_key (triage/answer/…) → tier |
| `ComponentWithParams {impl, params}` tra registry | **`Selector {impl, params}`** — thuật toán chọn key cắm-rút được |
| `retry_async` backoff+jitter dùng chung | policy reliability + cooldown khi 429 |

### 15.1 Ba lớp trừu tượng

```
KeyEntry        # 1 API key cụ thể (đơn vị "hấp thụ")
  id, provider, base_url, api_key_env, model_aliases[]
  limit: { kind: "tokens_per_day" | "requests_per_day" | "budget_usd_per_day",
           value, rpm?, tpm? }          # kind khác nhau cho từng pool
  enabled, weight

ProviderPool    # nhóm KeyEntry cùng provider — danh sách, thêm key = thêm 1 dòng
  name (openai|gemini|openrouter_free|openrouter_paid|...), keys: list[KeyEntry]

Selector        # CHIẾN LƯỢC chọn key — pluggable qua {impl, params}
  impl: "opportunity_cost" | "cheapest_free_then_paid" | "round_robin" | ...
  params: { reserve_ratio, allow_billed, ... }
```

> **Hấp thụ key mới**: chỉ thêm một `KeyEntry` vào `keys[]` của pool (file/Redis/Admin API),
> validate qua Pydantic (`extra="forbid"`), router tự đưa vào vòng chọn. Không đụng code.
> **Provider mới** (vd thêm Anthropic/Groq): thêm 1 `ProviderPool` + base_url; vì đều
> OpenAI-compat nên dùng chung client factory.

### 15.2 Selector là plugin → thuật toán "linh hoạt"

Thuật toán tối ưu chi phí ở Mục 3–4 (opportunity_cost đa-pool) chỉ là **một** impl của
`Selector`. Đổi chiến lược = đổi `selector.impl` trong config, không sửa nơi gọi:

```yaml
selector:
  impl: opportunity_cost          # mặc định: free trước (opp-cost), hết → paid rẻ nhất
  params:
    reserve_ratio: 0.0            # Phase 1 small: không giữ dự phòng
    allow_billed: false          # cạn hết → báo lỗi thay vì tính phí OpenAI
```

Registry các impl (đăng ký như `_READER_REGISTRY` của rag-worker):
`opportunity_cost` · `cheapest_free_then_paid` · `round_robin` · `priority_list` ·
(sau này) `quality_floor`, `rbac_by_role`.

### 15.3 Interface gateway

```
class LLMGateway:
    def resolve(route_key, est_in, est_out) -> ResolvedRoute(client, model, key_id)
        pools   = registry.pools_for_tier(required_tier(route_key))
        key,mdl = selector.choose(pools, est_in, est_out, counters)   # <- chiến lược
        client  = client_factory.get(key.base_url, env[key.api_key_env])
        return ResolvedRoute(client, mdl, key.id)
    def record(key_id, usage)          # cập nhật counter Redis sau call
```

Call site (mọi service) chỉ thấy `gateway.resolve(...)` — y như rag-worker chỉ thấy
`AIProvider`. Giá lấy từ **`PriceCatalog` sẵn có** (HF dataset, Mục liên quan price) —
không dựng bảng giá riêng.

## 16. Dashboard quan sát

Có — chia 2 tầng, vì 2 loại dữ liệu khác nhau:

| Tầng | Dữ liệu | Nguồn | Công cụ |
|---|---|---|---|
| **Lịch sử/cost/chất lượng** | token, cost, model, outcome theo trace | **Langfuse** (đã có) | UI Langfuse self-host |
| **Trạng thái quota LIVE** | remaining token/request mỗi key, %free đã dùng, cost hôm nay, tỉ lệ fallback, key cooling-down | **Redis counters** của router | (a) endpoint `/internal/ai/quota` (JSON) + trang nhẹ; hoặc (b) export **Prometheus** → **Grafana** |

- **Langfuse không thấy trạng thái quota/key-pool** (nó chỉ có cost lịch sử) → cần tầng 2.
- Đề xuất tối thiểu Phase 1: endpoint `GET /internal/ai/quota` (internal token) trả JSON
  từ Redis → render bảng đơn giản. Phase sau: bắn metrics Prometheus → Grafana dashboard
  (remaining theo key, cost/ngày, phân bố provider, alert khi free sắp cạn).

## 17. Nguyên tắc lõi: hợp đồng gọi tối thiểu (base_url + model_name)

> Đây là invariant trung tâm. Mọi mục khác (limit/fee/window/selector) chỉ là tầng phủ lên.

### 17.1 Hai tầng tách biệt

```
TẦNG 0 — HỢP ĐỒNG GỌI (bắt buộc, và CHỈ có thế):
    (base_url, api_key, model_name)  ->  OpenAI SDK gọi được.
    => Thêm T key + T url = thêm T dòng (base_url, api_key_env, model). Gọi được NGAY.

TẦNG 1 — METADATA TỐI ƯU (tùy chọn, làm giàu dần):
    limit_per_day · fee · context_window · rpm
    - THIẾU  -> router vẫn chạy, chọn naïve (round-robin / least-used). Không vỡ.
    - CÓ     -> router tối ưu chi phí/quota (opportunity_cost, hard-stop, ...).
```

**Hệ quả:** key/provider mới **luôn callable ngay**; tối ưu hóa là phần *cộng thêm*,
không phải điều kiện để hoạt động. Đây là định nghĩa "flexible" cho hệ thống.

### 17.2 KeyEntry — trường bắt buộc vs tùy chọn

```python
KeyEntry:
  # --- TẦNG 0: bắt buộc ---
  id: str
  base_url: str | None          # None = OpenAI mặc định; mọi url khác = 1 provider mới
  api_key_env: str
  model: str | list[str]        # model_name gọi được

  # --- TẦNG 1: tùy chọn (default None -> bỏ qua tối ưu, không vỡ) ---
  limit: Limit | None = None    # tokens/day | requests/day | budget_usd/day
  rpm: int | None = None
  # fee, context_window KHÔNG để ở đây -> tra Catalog theo model (Mục 15.1)
```

### 17.3 Điều kiện duy nhất để "hấp thụ" 1 provider

Provider phải **nói được giao thức OpenAI SDK** (chat/responses/embeddings). Thực tế gần
như mọi nhà đều có endpoint OpenAI-compatible: OpenAI, Gemini (`/v1beta/openai/`),
OpenRouter, Groq, Together, Fireworks, vLLM, Ollama... → chỉ cần đổi `base_url`.
Nếu một provider KHÔNG OpenAI-compat (hiếm) → viết 1 adapter mỏng, vẫn không đụng call site.

### 17.4 client_factory hấp thụ T url/key vô hạn

```
client_factory.get(base_url, api_key) -> AsyncOpenAI   # cache theo (base_url, api_key)
```
Không giới hạn số (base_url, api_key) → T key + T url chỉ là T entry cache. Không sửa code.

## 18. Concurrency & Async — phục vụ tối đa X user, latency-first

**Chính sách đã chốt: SPILL (không QUEUE).** Free cạn → tràn sang paid rẻ (deepseek-v4 +
model rẻ) NGAY, không bắt user chờ. Tối ưu chi phí đạt bằng *free-first + model rẻ*,
KHÔNG bằng xếp hàng.

### 18.1 Fan-out: pool key = bộ nhân song song

Mỗi key là **một làn độc lập**: RPM/quota riêng + connection pool (httpx) riêng. ⇒
tổng concurrency ≈ `Σ_key (RPM_key & in-flight cap)`. Phân tán tải ra toàn key để
không key nào thành nút cổ chai.

```
Thứ tự tier (cost):   OpenAI free (M key)  ->  OpenRouter paid (T key: deepseek-v4 + rẻ)
Trong 1 tier (latency): chọn KEY tải-thấp-nhất, KHÔNG round-robin mù
```

### 18.2 Chọn key trong tier = least-loaded (đảm bảo latency)

```
score(key) = (in_flight(key),            # ưu tiên 1: ít request đang bay nhất
              -rpm_headroom(key),         # ưu tiên 2: còn nhiều room RPM
              -remaining_quota(key))      # ưu tiên 3: còn nhiều quota
chọn key có score nhỏ nhất, BỎ QUA key đang cooling-down (429)
# "power of two choices": bốc 2 key ngẫu nhiên, lấy cái tải nhẹ hơn -> rẻ & tránh herd
```

Cost quyết định **tier**; load quyết định **key trong tier** (paid thì mọi deepseek call
≈ cùng giá → tiebreaker là latency).

### 18.3 Cơ chế async (an toàn dưới đồng thời)

```
a) Atomic reserve (KHÔNG read-then-decide):
   reserve(key, est_tokens) = Redis Lua INCR-and-check  -> true/false nguyên tử
   vượt limit -> false -> thử key kế. Sau call: reconcile(actual vs est).
b) Per-key: asyncio.Semaphore(max_inflight) + token-bucket RPM  -> chặn 429-storm.
c) 429/timeout -> mark cooling-down (circuit-breaker) -> re-route key/tier khác.
d) Spill: nếu không key OpenAI nào reserve được -> sang OpenRouter paid (cũng fan-out T key).
```

### 18.4 Pacing để "rẻ" không phản tác dụng

2.5M/ngày mà đốt sạch trong 1 giờ ⇒ 23 giờ sau phải trả tiền. ⇒ rải quota free theo
**leaky-bucket ngày** (nhịp ~ `limit / 86400` + cho phép burst). Spill sang paid khi vượt
nhịp, không chỉ khi cạn tuyệt đối — trừ khi cấu hình "đốt nhanh".

### 18.5 Bài toán hoàn chỉnh (gộp micro + macro)

```
Tại t, request user A:
  feasible = {(X,N) | entitlement, window>=tokens, reserve(X) OK, không cooling-down}
  tier     = rẻ nhất có feasible (free -> paid)
  (X,N)    = trong tier: least-loaded key  (18.2)
  nếu free saturated -> SPILL paid (deepseek-v4 + rẻ), fan-out T key
  mục tiêu hệ thống: phục vụ hết X user, chi phí ↓, latency giữ (không queue)
```

## 13. Quyết định đã chốt & dữ kiện then chốt

### 13.1 Đã chốt
| Vấn đề | Quyết định |
|---|---|
| Phạm vi Phase 1 | 2 pool: **OpenAI free (mini)** + **OpenRouter free** → spill **OpenRouter paid** |
| Privacy / data-sharing | **Cho phép free toàn bộ**, KHÔNG hạn chế luồng HR |
| Concurrency | **SPILL không QUEUE** (latency-first), fan-out toàn key, chọn key least-loaded |
| Khi free cạn | Spill **OpenRouter paid** (deepseek-v4 + model rẻ), KHÔNG đụng túi BIG |
| Quality floor `answer` | **CÓ** — user sẽ cấp ngưỡng; user thường cần cao hơn mini → đi paid (deepseek) |
| Nguồn config nóng | **File `routing.yaml` + hot-reload** (Pydantic validate, giữ bản tốt khi lỗi). Redis chỉ cho counter. Admin API+Redis = Phase 3 |

### 13.2 Dữ kiện free tier (đã xác nhận)
- **Free tier theo ACCOUNT/org, KHÔNG theo key.** Mỗi key OpenAI của user = **1 account email RIÊNG**
  → tổng free = **M × (2.5M mini + 250k big)/ngày**, M làn độc lập (quota + RPM + billing riêng)
  → nhân được cả quota lẫn concurrency.
- **MINI 2.5M = túi DÙNG CHUNG** cho mọi mini model trong 1 account (đổi mini model trên cùng
  account KHÔNG có thêm free).
- **BIG 250k = túi RIÊNG, KHÔNG dùng làm fallback chung.** Dành riêng cho **task lớn / user
  quan trọng (sếp, giám đốc)** qua **RBAC theo cấp bậc — Phase sau.** Router phải **giữ** túi big,
  không đổ traffic thường vào.
- ⚠️ Rủi ro: multi-account để nhân free có thể chạm **ToS OpenAI** → circuit-breaker spill sang
  OpenRouter khi 1 account bị khóa (đã có trong Mục 18.3).

### 13.3 Còn chờ user cung cấp (điền số, KHÔNG chặn thiết kế)
1. **OpenRouter API key** (free + paid) + **giá deepseek-v4 / model rẻ** (để điền `fee`).
2. **Ngưỡng quality floor** cho route `answer` (model tối thiểu).
3. **Mốc reset free tier** (đang giả định **UTC daily** cho counter TTL).
4. Số lượng **M** (OpenAI account) và **K** (OpenRouter free key) thực tế để tính quota tổng.

### 13.4 Việc kỹ thuật trước khi tối ưu hoá
- Mở rộng `scripts/build_price_catalog.py` lấy thêm **`context_length` + `is_free`**
  (catalog hiện chỉ có prompt/completion/cache_read → thiếu token window cho ràng buộc feasibility).
