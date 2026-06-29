---
last-verified: 59551e39 (2026-06-29)
code-refs:
  - src/rag-worker/embeddings.yaml
  - src/rag-worker/core_engine/contract.py (EMBED_MODELS, MODEL_TAGS)
  - src/ai-router/routing.yaml (aliases, capabilities)
  - src/ai-router/config/model_catalog.json
  - infra/ci/embed_model_lint.py
---

# Hợp đồng embed models + collection

T1 — sinh từ code. Bắt class drift IM LẶNG (bug qwen8b 2026-06-28: router hardcode
ép mọi model về qwen8b → multi-collection giả). Gate `embed_model_lint.py` (thuần
YAML/JSON + AST, lệch = exit 1).

## Nguồn sự thật (mỗi fact đúng 1 nơi)

| nơi | fact |
|-----|------|
| `embeddings.yaml.embed_models` | MODEL ACTIVE (tập phải phủ ở mọi nơi dưới) |
| `contract.py EMBED_MODELS` | native dim mỗi model |
| `contract.py MODEL_TAGS` | collection-tag (phải distinct giữa model active) |
| `routing.yaml aliases` | model → capability |
| `routing.yaml capabilities` | capability → `pinned_model` (PHẢI = model) + `tiers` |
| `model_catalog.json` | model selector pick được (ai-router) |

## Chuỗi gate (mỗi model active PHẢI nhất quán xuyên service)

`embeddings.yaml ⊆ contract.py (EMBED_MODELS + MODEL_TAGS) ⊆ routing.yaml (alias →
capability pinned_model=model + có tiers) ⊆ model_catalog.json`.

Bổ sung: collection-tag PHẢI distinct giữa các model active (else 2 model ghi chung
1 collection). Mỗi model → collection `{base}__{tag}__d{native}[__s{sparse}]`.

## Model active hiện tại (`embeddings.yaml`, `mode: shard`)

| model                            | native dim | tag         | capability      | tier      |
|----------------------------------|-----------|-------------|-----------------|-----------|
| `qwen/qwen3-embedding-8b` (PRIMARY) | 4096   | qwen3emb8b  | `embed`         | embed_or  |
| `baai/bge-m3`                    | 1024      | bgem3       | `embed_bgem3`   | embed_or  |
| `openai/text-embedding-3-small`  | 1536      | te3s        | `embed_te3s`    | embed_oai |
| `perplexity/pplx-embed-v1-0.6b`  | 1024      | pplxembed   | `embed_pplx`    | embed_or  |

`intfloat/multilingual-e5-large` đã GỠ 2026-06-28 (ctx chỉ 512 — mắt xích yếu); alias
`embed_e5large` vẫn còn trong routing.yaml nhưng không còn active → collection cũ GC khi clear.

## Production: single qwen8b

Capability `embed` PIN `qwen/qwen3-embedding-8b` (qua OpenRouter, MRL dim=2560 giữ
nguyên vector size hạ tầng; 3 provider Nebius/DeepInfra/SiliconFlow → hết
engine_overloaded). Alias `qwen/qwen3-embedding-4b → embed` giữ cho rollback an toàn.

Embed selector = `adaptive_balanced` (rải đều key: OpenAI TPM-headroom, OpenRouter
AIMD). CẤM `save_mode` cho embed (đổi model = vỡ vector space collection).
