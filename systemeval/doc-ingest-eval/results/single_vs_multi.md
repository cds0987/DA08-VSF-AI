# Single qwen8b vs Multi-collection shard — QUYẾT KIẾN TRÚC (2026-06-29)

Cùng corpus 120 doc HR-VN + 480 câu gold, đo recall (shard-merge cho multi / single-collection cho single) + latency.

| | Multi-collection shard (4 model) | **Single qwen8b** |
|---|---|---|
| recall@1 | 0.53 | **0.73** (+0.20) |
| recall@3 / @10 | 0.78 / 0.90 | 0.86 / 0.91 |
| MRR | 0.67 | **0.80** |
| latency p50 / p95 | 1.1s / 4.3s | 1.4s / 8.4s |
| ingest throughput | 45 doc/phút | ~tương đương |

**QUYẾT**: Single qwen8b THẮNG (recall@1 +0.20, MRR +0.13; latency/throughput tương đương). Multi
shard = lỗ ròng (model phụ pplx/te3s 0.41@1 kéo xuống; shard=1embed/doc=bằng single, không ×N).
→ PRODUCTION = single qwen8b (MULTI_EMBED_ENABLED=0). Hạ tầng multi-collection GIỮ (bật lại nếu có
model phụ mạnh ≥ qwen8b). Chi tiết journey: src/rag-worker/docs/optimize.md (bm0→bm8).
