# systemeval — đánh giá TOÀN HỆ (ingest + query)

Khác `queryeval` (chỉ chấm query-service: latency/correctness MOSA), `systemeval` đo **cả pipeline hệ
thống**: từ **nạp tài liệu** (document-service → NATS → rag-worker → Qdrant) đến **truy hồi**
(retrieval) và (về sau) đến **trả lời** (query-service).

## Cấu trúc (mở rộng dần)

```
systemeval/
  doc-ingest-eval/      ← HIỆN CÓ: nạp tài liệu + recall truy hồi (multi-collection)
    README.md
    runners/            harness đo (throughput ingest, recall shard-merge, judge relevance)
    labels/             gold question (gt = doc) cho recall
    corpus/             danh sách doc corpus
    results/            kết quả đo
  (query-eval/)         ← CHƯA gộp vào đây — query vẫn ở queryeval/ cho tới khi thống nhất
```

## Vì sao tách khỏi queryeval
- `queryeval` giả định corpus **đã có sẵn** trong Qdrant, chỉ chấm phần hỏi-đáp.
- `systemeval/doc-ingest-eval` chấm **chính khâu nạp**: throughput, độ trễ ingest, tỉ lệ fail, và
  **chất lượng truy hồi của data vừa nạp** — đặc biệt với kiến trúc **multi-collection (shard N model)**
  mà phương pháp recall cũ (per-collection, single-model) KHÔNG đo đúng (xem doc-ingest-eval/README).
