# AI Router

Gateway tương thích OpenAI, **stateless**, đa pool key — đứng giữa AI-logic của các service
và nhà cung cấp (OpenAI / OpenRouter). Service chỉ đổi `base_url`, dùng OpenAI SDK như cũ
(MOSA, zero dependency). Thiết kế đầy đủ: [PLAN.md](PLAN.md).

## Chạy nhanh (dev)
```bash
pip install -r requirements.txt
python scripts/build_catalog.py config/model_catalog.json   # tải model + giá (public)
export OPENAI_API_KEY_1=sk-...        # auto-discover theo pattern
export OPENROUTER_API_KEY_1=sk-or-...
uvicorn app.main:app --port 8010
```

## Dùng từ service (zero dependency)
```python
client = AsyncOpenAI(base_url="http://ai-router:8010/v1", api_key="internal")
# `model` = ALIAS capability, KHÔNG phải tên model thật:
await client.chat.completions.create(model="answer", messages=[...], tools=[...])
await client.embeddings.create(model="embed", input=[...])
```
Router chọn `(api_key, base_url, model_name)` tối ưu chi phí + phân bố tải, gọi giúp, trả OpenAI shape.

## Endpoint
| | |
|---|---|
| `POST /v1/chat/completions` | chat + tool + stream (alias ở field `model`) |
| `POST /v1/embeddings` | embed (PIN model theo contract) |
| `POST /v1/route` | resolver: trả triple `(api_key,base_url,model)` cho client động |
| `GET /health` | trạng thái |
| `GET /admin/quota` | giám sát quota/RPM/cost mỗi key (live) |
| `POST /admin/reload` | hot-reload routing.yaml + catalog |

## Cấu hình
- `routing.yaml` — selector (thuật toán), tiers, capability, model mỗi tier, quality floor. Hot-reload.
- `config/model_catalog.json` — build từ OpenRouter `/models` mỗi deploy; fail → giữ seed.
- Env: `OPENAI_API_KEY_{n}`, `OPENROUTER_API_KEY_{n}` (auto-discover; loại key đơn cũ),
  `AIROUTER_REDIS_URL` (None = in-memory dev), `AIROUTER_INTERNAL_TOKEN`.

## Thuật toán
`sticky_rotation_soft` (PLAN §5.9): 1 key active phục vụ tới ngưỡng → tràn key kế →
spill tier (free_oai → free_or → paid). Đổi thuật toán = đổi `selector.impl` trong routing.yaml.

## Test
```bash
PYTHONIOENCODING=utf-8 python tests/test_router_core.py
```
