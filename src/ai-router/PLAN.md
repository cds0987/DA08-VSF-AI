# AI Router — Plan & Algorithm

> Trạng thái: **PLAN, chưa code.** Tài liệu để duyệt trước khi triển khai.
> Thay thế bản thiết kế cũ ở `query-service/Docs/ai-orchestration-design.md`
> (bản đó để trong query-service; nay router là **service riêng ngang hàng**).

---

## 1. Kiến trúc: AI Gateway tương thích OpenAI (standalone, stateless)

`src/ai-router/` là **một service riêng, ngang hàng** với query-service / rag-worker / mcp-service.

```
                 ┌─────────────────────────────────────────────┐
  query-service ─┤                                             │
  rag-worker    ─┤  base_url = http://ai-router:8010/v1        │
  mcp-service   ─┤  (dùng OpenAI SDK y như cũ, KHÔNG import gì) │
  ...           ─┤                                             │
                 └───────────────┬─────────────────────────────┘
                                 ▼
                          ┌──────────────┐     keys ← git secret (env)
                          │  AI ROUTER   │ ───────────────────────────
                          │ (stateless)  │     OPENAI_API_KEY_1..N
                          │  OpenAI-API  │     OPENROUTER_API_KEY_1..N
                          └──────┬───────┘
                          state ▼ (Redis)        ▼ forward
                    counters/quota/rpm     OpenAI · OpenRouter
```

**Vì sao là service (không phải library):**
| Yêu cầu của bạn | Gateway service đáp ứng |
|---|---|
| "ngang hàng với các service" | `src/ai-router/` là 1 container trong docker-compose |
| "dùng mà KHÔNG có dependency" | service chỉ đổi `base_url`, **không import code router** → zero coupling |
| "stateless" | router không giữ state; mọi counter ở **Redis** → scale ngang thoải mái |
| "chỉ liên kết git secret" | key đọc từ env (git secret → render-secrets.sh → env) |
| "logic optimize thay đổi linh hoạt" | thuật toán = **plugin** (`selector.impl` trong config) |
| "thêm api key linh hoạt" | **auto-discover** key theo pattern env, thêm secret là xong |
| "giám sát cao" | endpoint `/admin/quota` + Prometheus + log mỗi quyết định |
| "deploy tới KHÔNG crash product" | gateway OpenAI-compatible + flip base_url từng service + fallback |

**Service dùng như thế nào (zero dependency):**
```python
# trong query-service — KHÔNG đổi code, chỉ đổi 1 biến env:
#   OPENAI_BASE_URL = http://ai-router:8010/v1
client = AsyncOpenAI(base_url=os.getenv("OPENAI_BASE_URL"), api_key="internal-token")
resp = await client.chat.completions.create(model="auto", messages=[...])
#                                            ^^^^^ alias logic; router tự chọn key+model thật
```

---

## 1b. MOSA — module mở: service chỉ biết Ý ĐỊNH, không biết cơ chế

Nguyên tắc thiết kế: **Modular Open Systems Approach**. AI-logic của service khai *cái gì cần*,
KHÔNG biết *gọi thế nào*.

```
SERVICE AI-LOGIC khai (Ý ĐỊNH)          GATEWAY lo (CƠ CHẾ — service KHÔNG biết)
─────────────────────────────          ────────────────────────────────────────
• capability (model alias)              • model thật nào, provider nào
• inputs (messages / input / image)     • key nào, base_url nào, endpoint nào
• options (tools, temperature, …)       • chọn tier, tối ưu chi phí, quota
                                        • retry / fallback / circuit-breaker
                                        • chuẩn hoá response (quirk provider)
```

**Chuẩn mở = OpenAI API schema** (KHÔNG phải lib riêng của router) → zero dependency:
- Service & gateway cùng phụ thuộc *chuẩn OpenAI*, không phụ thuộc nhau (dependency inversion).
- Đổi gateway/provider/thuật toán → service **không phải sửa gì** (chỉ là cùng một chuẩn).

**4 module TÁCH RỜI, thay độc lập (severable):**
| Module | Thay bằng | Không ảnh hưởng |
|---|---|---|
| Provider (OpenAI/OpenRouter/…) | thêm key + catalog | service, thuật toán |
| Thuật toán (Selector) | đổi `selector.impl` | service, provider |
| Capability | thêm block routing.yaml | service khác |
| Service | trỏ `base_url` vào gateway | gateway, provider |

**Gateway BẢO ĐẢM response đã chuẩn hoá** → service miễn nhiễm với khác biệt provider
(content=None, reasoning field, tool_calls shape…). Service luôn nhận OpenAI shape ổn định
⇒ đúng tinh thần "không biết gì về cách gọi model".

**Không bắt buộc SDK riêng.** Mặc định service dùng OpenAI SDK chuẩn + alias. (Tuỳ chọn: một
helper mỏng `ai_client.call(capability, **inputs)` cho tiện — nhưng KHÔNG bắt buộc, để giữ
zero-dependency.)

## 2. Nguyên tắc đọc key (auto-discovery)

Lúc khởi động **và** lúc hot-reload, router quét `os.environ`:

```
OPENAI_API_KEY_{n}      n = 1..N   → pool OpenAI   (free mini 2.5M/account/ngày)
OPENROUTER_API_KEY_{n}  n = 1..N   → pool OpenRouter (free 1000 req/key/ngày, 20 RPM)
```

- **Mọi biến khác KHÔNG tính.**
- **Loại bỏ `OPENAI_API_KEY`** (key đơn đang chạy, không có số) — để không lẫn với hệ cũ.
- **Thêm key = thêm secret `OPENAI_API_KEY_6`** → deploy/reload → tự đăng ký. Không sửa code.

Mỗi key → 1 `KeyEntry` (xem §4). Số N tự do.

---

## 3. Cấu trúc thư mục

```
src/ai-router/
├── app/
│   ├── main.py            # FastAPI: /v1/chat/completions, /v1/models, /health, /admin/quota
│   ├── gateway.py         # handler: resolve → forward → normalize → account
│   ├── registry.py        # auto-discover key từ env (§2) + nạp routing.yaml
│   ├── catalog.py         # nạp model_catalog.json (window·fee·is_free·endpoint)
│   ├── selector/          # ❖ THUẬT TOÁN cắm-rút được
│   │   ├── base.py        #   interface Selector
│   │   └── cost_optimizer.py  # default Phase-1 (§5)
│   ├── counters.py        # Redis atomic (Lua): quota/reserve/rpm/cost/cooldown
│   ├── client_factory.py  # cache AsyncOpenAI theo (base_url, api_key)
│   ├── parser.py          # ❖ normalize response chống crash (§6)
│   ├── config.py          # routing.yaml + hot-reload (Pydantic validate)
│   └── observability.py   # metrics + structured log + Langfuse
├── config/
│   └── model_catalog.json # build từ openrouter.ai/api/v1/models lúc deploy
├── routing.yaml           # selector + tiers + quality floor + limits
├── scripts/build_catalog.py
├── Dockerfile
└── requirements.txt
```

---

## 4. Mô hình dữ liệu

```
KeyEntry            # auto-discover từ env
  id            "oai-1" | "or-3"
  provider      "openai" | "openrouter"
  base_url      None (openai) | "https://openrouter.ai/api/v1"
  api_key_env   "OPENAI_API_KEY_1"
  limit         tokens/day 2_500_000 (openai) | requests/day 1000 + rpm 20 (openrouter)

ModelEntry          # từ model_catalog.json
  id            "openai/gpt-4o-mini"
  provider      "openai"
  name_native   "gpt-4o-mini"          # gọi trên OpenAI key (tên trần)
  name_or       "openai/gpt-4o-mini"   # gọi trên OpenRouter key (có provider)
  context_length, price_in, price_out, price_*_with_fee
  is_free, supports_tools
  input_modalities  ["text"] | ["text","image"]   # vision? -> cho ocr/caption
  endpoint      "chat" | "responses" | "embeddings"   # codex-only=responses (§6)

RoutingTable (routing.yaml)
  selector { impl, params }            # ❖ đổi thuật toán ở đây
  tiers []                             # thứ tự cost + model cho mỗi tier
  route_quality_floor { answer: "..", triage: ".." }
```

---

## 4b. ❖ Đa năng lực (capability-aware) — rag-worker: ocr+caption+embed; query: llm+tool

Gateway phục vụ NHIỀU năng lực, mỗi cái có rule routing riêng. Service KHÔNG đổi cách gọi
(vẫn OpenAI SDK) — chỉ truyền **alias năng lực qua field `model`**, gateway map → route_key.

```
Service gọi              endpoint gateway        route_key   → model thật router chọn
─────────────────────────────────────────────────────────────────────────────────
model="answer"  +tools   /v1/chat | /responses   answer      chat LLM tool-capable
model="triage"           /v1/chat                triage      chat LLM rẻ
model="rerank"           /v1/chat                rerank      chat LLM (LLM-as-reranker)
model="caption" +image   /v1/chat                caption     VISION LLM (input_modalities⊇image)
model="ocr"     +image   /v1/chat                ocr         VISION LLM
model="embed"            /v1/embeddings          embed       ⚠️ embed model CỐ ĐỊNH (xem dưới)
```

**Mỗi capability = 1 block trong routing.yaml** (tier riêng, model riêng, quality-floor riêng,
counter riêng). Thêm capability mới = thêm 1 block, không sửa code.

### ⚠️ Bẫy embedding (CỰC KỲ quan trọng — sai là vỡ search)
Embedding **KHÔNG được tối ưu kiểu đổi model tự do** như chat:
- Vector store đã build bằng **1 embed model + 1 dimension** (rag-worker có `vectorstore_contract`).
- Ingest và search **PHẢI dùng ĐÚNG model đó**; đổi model → dimension/semantic mismatch → **search hỏng**.
- ⇒ route_key `embed` **PIN model cố định** (theo contract). "Tối ưu" duy nhất được phép =
  **load-balance KEY** phục vụ cùng model đó; KHÔNG bao giờ đổi sang model embed khác.
- Embed **limit/cost riêng** (text-embedding-3-small KHÔNG nằm trong túi free chat 2.5M) → counter riêng.

### Lọc feasible theo capability
```
ocr/caption : model.input_modalities ⊇ {"image"}     # loại model không vision
embed       : model == contract.embed_model           # PIN, không chọn khác
answer      : supports_tools (nếu request có tools)    # §6b
*           : context_window · quality_floor · endpoint (§5.4)
```

## 5. ❖ THUẬT TOÁN (Phase-1 cost optimizer) — "làm sao"

### 5.0 ❖ Hợp đồng Selector: tín hiệu sống → 1 triple → call ngu

Bộ não là `resolve()`. Mọi thứ khác chỉ là `OpenAI(api_key, base_url).create(model_name, …)`.

```
INPUT (tín hiệu SỐNG, bơm từ ngoài — chủ yếu Redis + request):
  per-key   : rpm dùng/còn · quota token|req còn hôm nay · inflight (đang phục vụ) · cooldown
  toàn cục  : U = số user đồng thời
  request   : capability · est_tokens · có tools? · user_id · conversation_id

          ▼
  resolve(input) ──►  (api_key, base_url, model_name)   # ĐÚNG 1 triple, 1 user, tại t

OUTPUT (đơn giản, KHÔNG thông minh):
  client = AsyncOpenAI(api_key=api_key, base_url=base_url)
  client.<chat|responses|embeddings>.create(model=model_name, **inputs)
```

### 5.0b ❖ Phân bố key cho concurrent users — "làm sao"

1. **State sống ở Redis**: mỗi request đang chạy đã `+1 inflight/rpm/quota` của key nó dùng →
   MỌI instance gateway thấy tải thật-thời (không cần biết nhau, vẫn stateless).
2. **resolve() chọn key headroom tốt nhất** (ít inflight nhất · còn nhiều RPM/quota · không
   cooldown) → user kế tiếp tự né key đang đông → **tải TRẢI ĐỀU N key** (không hot-spot).
3. **reserve() atomic (Lua)** → U user đồng thời KHÔNG overbook cùng 1 key (không read-then-decide).
4. **Trần thông lượng free ≈ Σ RPM_key**. U vượt ngưỡng → **SPILL paid** (thêm capacity) giữ latency.
5. **U (số user) dùng cho admission/pacing**: U cao gần bão hòa → chủ động spill sớm thay vì
   chờ reserve fail; rải quota ngày (leaky-bucket) để không cháy 2.5M trong 1 giờ.

**Ví dụ số:** 5 OpenAI key (RPM cao, trần = 2.5M tok/ngày/key) + 5 OpenRouter free (20 RPM/key =
100 req/phút). resolve() rải U user theo headroom; request có tool → chỉ key/model tool-capable;
embed → key phục vụ model đã pin. Cần thêm capacity → thêm secret `*_API_KEY_{N+1}` (auto-discover).

### 5.1 Tài nguyên & bậc thang (cost tăng dần)

```
TIER 0  FREE_OAI : OpenAI mini  trên OPENAI_API_KEY_1..N   (mỗi key 2.5M tok/ngày)
TIER 1  FREE_OR  : OpenRouter free models trên OPENROUTER_API_KEY_1..N (1000 req/ngày, 20 RPM)
TIER 2  PAID     : OpenAI small billed  ⊕  OpenRouter paid (deepseek)  → so giá, rẻ nhất
        (BIG 250k = GIỮ RIÊNG cho VIP/RBAC — Phase sau)
```

### 5.2 State trong Redis (vì router stateless)

```
quota_tok:{key}:{YYYYMMDD}   tokens dùng hôm nay   (OpenAI)   TTL 26h
req_day:{key}:{YYYYMMDD}     requests hôm nay       (OpenRouter free) TTL 26h
rpm:{key}:{YYYYMMDDHHMM}     requests phút này      TTL 90s
inflight:{key}               số request đang bay     (load balance)
cost:{key}:{YYYYMM}          USD đã tiêu            (paid) TTL 32d
cooldown:{key}               set khi 429/timeout    TTL ngắn (circuit-breaker)
```

### 5.3 Vòng resolve (mỗi request)

```python
def resolve(req):
    est = estimate_tokens(req.messages)          # ước lượng in+out
    floor = quality_floor(req.route_key)         # ngưỡng chất lượng

    for tier in selector.tier_order():           # [FREE_OAI, FREE_OR, PAID]
        cands = feasible(tier, req, est, floor)  # LỌC (5.4)
        if not cands:
            continue
        key, model = selector.pick(cands, est)   # CHỌN (5.5) — latency-first
        if reserve(key, est):                    # ĐẶT CHỖ nguyên tử (5.6)
            return Route(key, model, tier)
    # cạn mọi tier → spill paid đã nằm trong tier 2; nếu vẫn không → policy
    raise NoCapacity()                           # hoặc fallback theo config
```

### 5.4 `feasible(tier)` — lọc ứng viên KHẢ THI (chống crash + đúng quota)

Mỗi (key, model) trong tier chỉ vào danh sách nếu **TẤT CẢ** đúng:
```
✓ not cooldown[key]                              # key không đang nghỉ vì 429
✓ rpm[key] < key.rpm_limit                       # còn room RPM (OpenRouter 20)
✓ model.context_length >= est                    # token window đủ
✓ quality(model) >= floor                        # đạt sàn chất lượng route
✓ model.endpoint == tier.endpoint                # codex-only=responses → loại nếu sai
✓ nếu request có `tools` → model.supports_tools   # agent/tool-call: loại model không hỗ trợ
✓ provider-split hợp lệ:                          # (đã verify thực tế)
     openai key   → model.provider=="openai", dùng name_native
     openrouter   → dùng name_or (có provider)
✓ còn capacity:
     FREE_OAI : quota_tok[key] + est <= 2.5M     # hard-stop trước khi bị tính phí
     FREE_OR  : req_day[key] + 1   <= 1000
     PAID     : cost[key] trong budget (hoặc không cap)
```

### 5.5 `pick(cands)` — chọn key trong tier (latency-first, fan-out)

```
FREE tiers:   score = (inflight[key], -rpm_headroom[key], -remaining[key])
              → chọn key TẢI NHẸ NHẤT (power-of-two-choices, tránh herd)
PAID tier:    chọn model GIÁ RẺ NHẤT trước (deepseek vs gpt-4o-mini billed),
              rồi trong số key của model đó → key tải nhẹ nhất
```
→ phân tán đều ra N key = nhân concurrency, không key nào nghẽn.

### 5.6 `reserve(key, est)` — đặt chỗ nguyên tử (an toàn đồng thời)

```
Redis Lua (atomic):
   INCR inflight[key]
   INCR rpm[key]                       (set TTL nếu mới)
   nếu FREE_OAI: nếu quota_tok[key]+est > 2.5M → rollback, return False
   nếu FREE_OR : nếu req_day[key]+1  > 1000   → rollback, return False
   return True
```
→ X user đồng thời KHÔNG thể cùng vượt trần (không còn read-then-decide).

### 5.7 `account()` — sau khi gọi xong (đối soát chi phí thật)

```
DECR inflight[key]
OpenAI    : quota_tok[key] += real_total_tokens          # từ usage
            cost[key]      += real_tokens × catalog.price # OpenAI không trả cost
OpenRouter: req_day đã +1 lúc reserve
            cost[key]      += usage.cost  ← SỐ THẬT từ response (chính xác tuyệt đối)
429/timeout: set cooldown[key]; release reservation; resolve lại (loại key này)
```

### 5.8 Vì sao thuật toán "thay đổi linh hoạt được"

Toàn bộ `tier_order()` + `pick()` + `reserve policy` nằm trong **Selector plugin**.
`routing.yaml`:
```yaml
selector:
  impl: cost_optimizer          # ❖ đổi 1 dòng = đổi thuật toán
  params: { reserve_ratio: 0, allow_billed: true }
```
Registry impl: `cost_optimizer` · `round_robin` · `priority_list` · `opportunity_cost` · (sau) `rbac_by_rank`. Đổi thuật toán **không redeploy service nào khác**, không sửa call site.

---

## 6. ❖ Chống crush: robust response parser (đã probe thực tế)

Phát hiện khi gọi thử (mini + big OpenAI + deepseek OpenRouter):
- `content` có thể **None** (reasoning ăn hết budget / refusal / deepseek).
- Model reasoning ngốn `reasoning_tokens` trước content (o3-mini=192, o1=128…).
- Tham số: OpenAI mới **bắt buộc `max_completion_tokens`** (không phải `max_tokens`).
- Codex family (`gpt-5-codex`, `gpt-5.1-codex*`) **chỉ /v1/responses** → 404 ở chat.
- Vài model **không có quyền** (o1-mini, codex-mini-latest) → 404.
- OpenAI **không trả** text reasoning; OpenRouter (deepseek) **có** field `reasoning`.

→ Một hàm chuẩn hóa dùng chung:
```python
def normalize(resp) -> str:
    msg = resp.choices[0].message
    text = msg.content or msg.get("reasoning") or msg.get("reasoning_content") or ""
    if not text and finish_reason == "length":
        raise RetryWithMoreTokens          # tăng budget rồi gọi lại
    if msg.get("refusal"):
        return handle_refusal(msg.refusal)
    return text                            # KHÔNG bao giờ .strip() trên None
```
Catalog tag `endpoint` + quyền model → `feasible()` loại sẵn model gọi-không-được ⇒ không 404 lúc runtime.

---

## 6b. ❖ Tool calling & Agent support (BẮT BUỘC — query-service dùng LangGraph)

Gateway đứng GIỮA provider và agent-logic của service → phải **trong suốt với tool calling**,
nếu không agent sẽ chết.

**Nguyên tắc:**
1. **Pass-through tool nguyên vẹn**: forward `tools`, `tool_choice`, `parallel_tool_calls`;
   trả về `tool_calls` + `finish_reason="tool_calls"` không sửa đổi.
2. **Parser §6 phải giữ tool_calls**: chỉ normalize TEXT khi message KHÔNG có `tool_calls`.
   ```python
   def normalize(resp):
       msg = resp.choices[0].message
       if msg.get("tool_calls"):          # AGENT path — trả nguyên, KHÔNG đụng
           return msg                      # service tự chạy tool rồi gọi lại
       text = msg.content or msg.get("reasoning") or ""   # text path (§6)
       ...
   ```
3. **`supports_tools` = ràng buộc feasible** (§5.4): request có `tools` → loại model không hỗ trợ
   (nhiều model free OpenRouter không có tool → tự rớt sang model tool-capable).
4. **Hỗ trợ CẢ `/v1/responses` lẫn `/v1/chat/completions`**: query-service dùng Responses API.
   Gateway expose cả hai, map đúng shape (tool calling khác nhau giữa 2 endpoint).
5. **Session affinity (sticky model)**: agent đa-lượt cần model NHẤT QUÁN giữa các turn (đổi
   model giữa chừng → tool-calling lệch). Pin theo `conversation_id`/`session`:
   ```
   Redis: affinity:{conversation_id} = chosen_model_id   TTL ngắn (vd 30 phút)
   resolve(): nếu có affinity còn hạn & vẫn feasible → DÙNG LẠI; hết hạn/không feasible → chọn mới
   ```
   Vẫn stateless (affinity ở Redis), agent loop + state nằm ở service.
6. **Streaming SSE pass-through** cho agent (token streaming + tool_call streaming).

**Hệ quả chọn model Phase 1:** traffic có tool/agent chỉ đi tới model tool-capable
(gpt-4o-mini, gpt-4.1-mini, gpt-5-mini… và deepseek-v4 đều hỗ trợ). Model free không tool
chỉ phục vụ tác vụ không-tool (triage/summarize). `feasible()` lo việc này tự động.

## 7. Giám sát (observability cao)

| Kênh | Nội dung |
|---|---|
| `GET /admin/quota` | live JSON: mỗi key còn bao nhiêu token/req, %free đã dùng, cost hôm nay/tháng, key cooling-down, inflight |
| Prometheus → Grafana | phân bố model/tier, cost/ngày, tỉ lệ fallback, RPM, latency p50/p95 |
| Structured log/quyết định | route_key, chosen(key,provider,model), est/real tokens, cost, latency, tier, fallback?, table_version |
| Langfuse | trace + cost lịch sử (ngoài đường runtime) |

---

## 8. Triển khai an toàn (deploy tới KHÔNG crash product)

1. Deploy `ai-router` như 1 service mới — **chưa service nào trỏ vào** → product không đổi.
2. Build `model_catalog.json` lúc deploy (OpenRouter `/models`, public, không cần key).
3. Bật từng service một: đổi `OPENAI_BASE_URL` của **1 service** trỏ vào gateway, theo dõi.
4. Gateway OpenAI-compatible → happy path giống hệt; lỗi → **revert base_url về OpenAI direct** (1 biến env).
5. Gateway có fallback nội bộ: routing fail → dùng default key an toàn (cấu hình) thay vì 500.
6. Key cũ `OPENAI_API_KEY` của các service **giữ nguyên** tới khi cutover xong.

---

## 9. Thứ tự build

| # | Việc | Test độc lập |
|---|---|---|
| 1 | `scripts/build_catalog.py` + `catalog.py` (OpenRouter /models → JSON) | chạy, xem JSON |
| 2 | `registry.py` (auto-discover key) + `client_factory.py` + `parser.py` | unit test |
| 3 | `counters.py` (Redis Lua) + `selector/cost_optimizer.py` | unit + integration |
| 4 | `gateway.py` + `main.py` (FastAPI OpenAI-compatible) | gọi thử bằng OpenAI SDK |
| 5 | Dockerfile + thêm vào docker-compose + wiring secret (deploy-develop.yml, render-secrets.sh) | e2e |
| 6 | Flip base_url query-service (an toàn, có revert) | smoke prod |

---

## 10. Còn chờ (non-blocking — điền config sau)
- Ngưỡng `route_quality_floor.answer` (model tối thiểu).
- Mốc reset free tier (mặc định UTC daily).
- Endpoint OpenAI: chat vs responses (mặc định khớp query-service đang dùng = responses).
- Port nội bộ của gateway (mặc định 8010).
