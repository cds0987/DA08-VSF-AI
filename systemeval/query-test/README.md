# query-test — load-test query-service (chat) + Claude-as-judge chất lượng

Bộ câu hỏi + harness mô phỏng **peak-time** (chat QPS đồng thời ingest), đo tải + CHẤT LƯỢNG
(route / agent response / ingest) dưới tải lớn. Khác queryeval (latency thuần) — đây là combined
system load + quality-judge.

## questions/ — 450 câu, đa dạng real-world (grounded trên corpus HR trong Qdrant)
| Loại | n | Mô tả | Hành vi mong đợi |
|---|---|---|---|
| **simple_rag** (single_fact) | 330 | tra 1 quy định/fact cụ thể | triage→RAG, 1 worker, nhanh, grounded |
| **multiagent** (multi_topic) | 72 | gộp ≥2 chủ đề HR | fan-out ≥2 worker, phủ đủ |
| **hr_intent** | 28 | payroll/leave_balance/leave_requests/attendance/benefits/onboarding/performance | route HR-tool per-user (KHÔNG bịa) |
| **non_rag** (edge) | 20 | identity·off_topic·out_of_scope·clarification·**prompt_injection** | route đúng / từ chối an toàn / hỏi lại |

- `gt_doc` = tài liệu đáp án (RAG); `ref_answer` = đáp án tham chiếu (cho judge). Grounded trên doc
  ĐANG có trong Qdrant (khảo sát 2026-06-29: 262 doc, docx/pdf + ảnh/sheet/text) → tránh false-negative.
- ⚠️ Qdrant hiện có **residue 262 doc** (tích lũy nhiều lần ingest); nên **clear + re-ingest 1 corpus
  KNOWN** trước khi chạy load-test chính thức để recall/judge sạch.

## Kế hoạch load-test (xem chi tiết khi chạy)
Chat 5-7 q/s × 60s (450 câu) **ĐỒNG THỜI** ingest 50-60 doc/phút → mô phỏng peak ~1200 user.
Đo: TTFT/latency/error per-capability + ingest throughput + cross-effect. Claude-judge: chất lượng
route / agent-response / ingest(OCR+parse) dưới tải.
