# ingest-load — Benchmark latency INGEST dưới tải (100 file liên tục)

Đo **latency end-to-end của đường ingest** (`document-service` nhận + `rag-worker`
parse/OCR/chunk/caption/embed/Qdrant) khi **N file đập vào server liên tục** trên prod
(`https://vsfchat.cloud`). Tổ chức **mirror `queryeval/`** nhưng cho đường INGEST thay vì query.

> Mục tiêu: định lượng p50/p95/**p99** thời gian từ lúc upload tới lúc doc `indexed`,
> nút thắt (queue drain 1-worker, OCR vision tuần tự), throughput — trước/sau cải tiến.

## Vì sao cần benchmark riêng (queryeval không đo cái này)

- `queryeval/` đo phía **query** (TTFT, latency trả lời, fan-out worker).
- `eval/openragbench/` đo **precision/recall@k** (chất lượng truy hồi), upload tuần tự + poll — KHÔNG đo latency dưới tải.
- → Chưa có chỗ nào đo **latency ingest khi 100 file đập vào cùng lúc**. Đây là chỗ đó.

## Cấu trúc (giống queryeval)

```
eval/ingest-load/
  benchmark/
    run_ingest_load.py   # open-loop upload N file (rate hoặc burst) + poll tới terminal
    aggregate.py         # p50/p90/p95/p99 e2e, accept latency, throughput, peak in-flight, degradation
  results/               # *.jsonl + summary
```

## Chỉ số

| Chỉ số | Ý nghĩa |
|---|---|
| `accept_latency` | document-service trả 202 (store + publish NATS) — nhanh, ~0.3s |
| **`e2e_latency`** | dispatch → `indexed` (gồm chờ queue + parse + OCR + embed + Qdrant) — **chỉ số chính** |
| `throughput` | doc/s rag-worker drain được |
| `PEAK in-flight` | số doc đồng thời queued+processing (độ sâu hàng đợi) |
| degradation bucket | doc đến sau chờ queue lâu hơn bao nhiêu (1-worker → tuyến tính) |

## Chạy (creds qua ENV, KHÔNG hardcode)

```bash
export CE=admin@company.com CP='...'
# burst 100 file, 20 luồng upload song song
PYTHONUTF8=1 python benchmark/run_ingest_load.py --count 100 --files-dir <dir> --concurrency 20 --label baseline
# hoặc open-loop 5 file/s
PYTHONUTF8=1 python benchmark/run_ingest_load.py --count 100 --files-dir <dir> --rate 5 --label baseline

python benchmark/aggregate.py results/ingest_results.jsonl

# DỌN (bulk-delete mọi doc test)
CE=.. CP=.. python benchmark/run_ingest_load.py --cleanup results/ingest_results.jsonl
```

## Lưu ý

- Pollute prod: tạo N doc thật → **luôn chạy `--cleanup` sau khi đo**.
- 1 worker (`INGEST_WORKER_COUNT=1`) + OCR vision tuần tự → 100 file có thể drain ~25-30 phút.
  Đây chính là baseline để so sau khi nâng worker + OCR fan-out.
- e2e_latency lấy bằng poll status (interval 4s) → sai số ±4s, đủ cho p99 thang phút.
