# Load-test ingest — openragbench (2026-06-28)

Config: 40 PDF academic (openragbench combined150), concurrency=8, hệ 4-model shard
(qwen8b/bge-m3/te3s/pplx), 8 rag-ingest-worker, ai-router no_inflight_cap embed.

| metric | giá trị |
|---|---|
| docs | 40/40 indexed (0 fail) |
| **throughput** | **8.5 pdf/phút** (≈ baseline cũ 7-9) · 2795 chunk/phút |
| e2e/pdf | p50=140s · p95=256s · max=284s |
| chunk/pdf | 449-1025 (PDF academic NẶNG, vision-OCR) |

Nhận xét: 4-model shard KHÔNG cải thiện throughput vs single-model cũ — bottleneck là
**parse + vision-OCR PDF khổng lồ**, không phải số collection (shard chỉ 1 model/doc nên embed-load
tương đương). Throughput nằm đúng dải benchmark cũ.
