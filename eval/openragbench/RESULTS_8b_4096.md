# Kết quả benchmark 8b/4096 NATIVE (2026-06-27)

Embedding `qwen/qwen3-embedding-8b` @ **dimension 4096 native**, collection
`rag_chatbot__qwen3emb8b__d4096__s2` (hybrid dense+sparse). Corpus OpenRAGBench 96 doc
học thuật (38 eval + 58 distractor, 318 query).

## RECALL@k — RAW retrieval (rag-worker `/api/search`, BYPASS orchestrator)

| metric | @1 | @3 | @5 | @10 | MRR |
|---|---|---|---|---|---|
| **all (N=71)** | **0.944** | **1.000** | **1.000** | **1.000** | **0.972** |
| extractive (29) | 0.931 | 1.000 | 1.000 | 1.000 | |
| abstractive (42) | 0.952 | 1.000 | 1.000 | 1.000 | |

➤ Embedding 8b/4096 retrieval **xuất sắc**: 94.4% đúng ngay rank-1, 100% trong top-3.

### ⚠ Tại sao PHẢI đo qua /api/search (không /api/query)
Đo qua `/api/query` (MOSA orchestrator HR) ra **recall=0**: orchestrator **topic-gate**
câu hỏi academic (toán/lý/kinh tế) là OFF_TOPIC → trả 0 sources (`top=[]`). Đó là hành
vi ĐÚNG của chatbot HR (từ chối off-domain), KHÔNG phải embedding kém. `/api/search` đo
thuần embed+vector+RRF → đúng chất lượng retrieval.

### Bug harness đã fix
`_norm` cũ dùng `Path.stem` → arxiv id "2405.04904v2" (không .pdf) bị cắt thành "2405"
→ gt không khớp uploaded_gt → N=0 recall giả. Fix: chỉ strip đuôi tài liệu thật.

## LATENCY / PERF — upload song song 96 PDF nặng (concurrency 12, WL=8)

| metric | giá trị |
|---|---|
| accepted / indexed / failed | 96 / 84 / 12 (9 doc >13MB oversized + 3) |
| accept latency | p50=31.6s p95=65s p99=78.1s max=111.7s |
| upload window (96 doc) | 300.9s |
| ingest drain (84 doc) | ~37 phút (06:05→06:42) |
| retries (connection-reset recovery) | 22 (→ 0 upload fail) |

### ⚠ Phát hiện perf
- **Concurrency 20 PDF nặng → tầng upload reset ~48% kết nối** (ConnectionReset 10054).
  Concurrency 12 + retry 4× → 0 fail. (100 file synthetic NHẸ thì conc 20 OK.)
- **Nghẽn ingest = vision-OCR** trên trang nhiều hình/công thức (`OCR_VECTOR_PAGES=true`,
  ~26s/doc) + chỉ `INGEST_WORKER_COUNT=8` trong khi VM 16-core/19GB-free rảnh.
- Đòn cải thiện (chưa áp dụng): nâng worker 8→14 + OCR_MAX 6→8; skip vision-OCR khi PDF
  có text-layer tốt (~3-5× cho doc số hóa); scale ngang rag-worker.

## Harness
- `run_recall_raw.py` — upload song song (latency) + recall raw qua /api/search.
- `_vm_search_loop.py` — chạy trong container rag-worker (docker exec) gọi localhost:8000.
- Chạy: build_dataset.py --n 38 → run_recall_raw.py --dir data/38 (phase1) →
  docker exec raw-search (phase2) → run_recall_raw.py --score ranks.json (phase3).
