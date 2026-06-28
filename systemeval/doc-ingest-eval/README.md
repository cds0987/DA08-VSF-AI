# doc-ingest-eval — nạp tài liệu + recall truy hồi (multi-collection)

Đo 2 thứ trên pipeline nạp tài liệu THẬT (prod `https://vsfchat.cloud`):

1. **Throughput / latency ingest** — nạp N tài liệu, đo `pdf/phút`, `chunk/phút`, e2e p50/p95, fail.
2. **Recall truy hồi** — câu hỏi gold → hệ trả về chunk → tài liệu đúng có được tìm thấy không.

## ⚠️ Multi-collection: phương pháp recall CŨ KHÔNG dùng được

Kiến trúc hiện tại = **shard N model**: mỗi tài liệu chỉ embed vào **1 trong N collection**
(qwen3-emb-8b / bge-m3 / text-embedding-3-small / pplx-embed), mỗi collection 1 model + 1 vector-space.

- **Cách CŨ** (`per_model_recall`, openragbench single-collection): embed query bằng 1 model → search
  1 collection. Giả định **mọi doc nằm trong 1 collection**. Với shard, 1 collection chỉ chứa ~1/N doc
  → recall per-collection **vô nghĩa**, và **không so được** baseline single-model cũ (vd 0.944@1).
- **Cách ĐÚNG** = đo qua **đường THẬT của hệ** (shard-read merge):
  ```
  gold query → /api/search:  embed query bằng CẢ N model → search CẢ N collection
                              → merge dedup → rerank → top-k   → gt ∈ top-k ?
  ```
  Đây mới là recall hệ thực sự trả về. Harness: `runners/shard_recall.py`.

## Domain: recall PHẢI đúng domain
- **openragbench** = academic tiếng Anh → CHỈ hợp đo **throughput ingest** (domain-agnostic).
- **Recall** PHẢI trên **corpus đích** (HR tiếng Việt). Gold ở `labels/` sinh từ chính doc HR.

## Hai cách chấm recall
1. **Gold gt-match** (tự động, `shard_recall.py`): gt_doc_id ∈ top-k. Nhanh nhưng chỉ doc-level binary.
2. **Judge relevance** (`judge_recall.py`, sát thực tế hơn): LLM mạnh đọc (query + chunk hệ trả về) →
   phán *chunk có chứa câu trả lời không*. Đo "tỉ lệ câu được trả lời đúng" — đúng cái user cuối cần.

## runners/
| file | đo gì |
|---|---|
| `run_ingest_load.py` (eval/ingest-load) | throughput + latency ingest (open-loop, poll terminal) |
| `verify_multicollection.py` | BẰNG CHỨNG: mỗi collection lưu model THẬT (cos vs qwen8b ≈ 0) + shard-read merge phủ N/N collection |
| `shard_recall.py` | recall@k qua shard-read merge (cách ĐÚNG cho multi-collection) |
| `judge_recall.py` | chấm relevance từng câu bằng LLM-judge (chấm "tay" ở quy mô) |

## labels/
- `team_hr_56.jsonl`, `team_hr_143.jsonl` — câu hỏi HR-VN, `gt_doc_id` = tài liệu đáp án (sinh từ doc).

## results/
- `load_openragbench.md`, `recall_multicollection.md` — kết quả từng lần đo (ghi rõ ngày + config).

## Eval-data dùng chung qua HuggingFace
Gold labels + harness + results đồng bộ lên **HF dataset private `gunnybd01/vsf-systemeval`**
(nhiều máy/Claude cùng làm). **Corpus 121 doc HR MẬT KHÔNG upload** (gitignore + chỉ local).
Pull: `huggingface_hub.snapshot_download("gunnybd01/vsf-systemeval", repo_type="dataset", token=...)`.
