# Recall FULL corpus — 120 doc HR-VN (2026-06-29)

Hệ: shard 4-model (qwen8b/bge-m3/te3s/pplx), **120 doc** (full team dataset, ingest 45.7 doc/phút
0 fail), 480 câu gold (4/doc), shard-read merge qua `/api/search`.

## Recall toàn corpus (shard-read merge, n=480)
| @1 | @3 | @5 | @10 | MRR | latency p50 / p95 |
|---|---|---|---|---|---|
| **0.53** | 0.78 | 0.85 | 0.90 | 0.67 | 1.1s / 4.3s |

## ⭐ Per-model — model nào TỐT/TỆ (recall trên doc shard của model đó)
| model | n | @1 | @3 | @5 | @10 | |
|---|---|---|---|---|---|---|
| **qwen3-embedding-8b** | 104 | **0.73** | 0.91 | 0.95 | **0.99** | 🥇 áp đảo |
| baai/bge-m3 | 132 | 0.58 | 0.77 | 0.86 | 0.89 | 🥈 khá |
| openai/text-embedding-3-small | 132 | 0.42 | 0.70 | 0.82 | 0.88 | 🥉 yếu |
| perplexity/pplx-embed-0.6b | 112 | 0.41 | 0.76 | 0.78 | 0.84 | ❌ tệ nhất |

## 🎯 KẾT LUẬN QUYẾT ĐỊNH: shard ĐANG HẠI recall
qwen8b trên shard của nó = **0.73@1**, nhưng tổng shard chỉ **0.53@1** — vì pplx/te3s yếu
(0.41-0.42@1) kéo xuống. 3/4 doc rơi vào model yếu hơn qwen8b.

→ **Trade-off rõ bằng DATA**: shard cho throughput (45 doc/phút) NHƯNG mất ~0.20 recall@1 so với
qwen8b-đơn (replicate). Multi-model **về recall KHÔNG đáng** — qwen8b mạnh hơn hẳn. Đề xuất cân nhắc:
replicate qwen8b (recall cao) thay shard, hoặc shard chỉ giữa model MẠNH (qwen8b + bge-m3, bỏ
te3s/pplx). [Đang chạy test replicate single-qwen8b trên full corpus để chốt số.]
