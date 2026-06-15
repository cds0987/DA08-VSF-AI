# Evaluation Improvement Plan

Ghi chú này tổng hợp kết quả từ `20260614-145538-dataset_new/` và đề xuất hướng cải thiện hệ thống AI/RAG trước khi tiếp tục Phase 2.

## 1. Kết Luận Hiện Tại

Kết quả evaluation hiện tại: **TUNE BEFORE PHASE 2**.

Hệ thống không hỏng flow, nhưng chất lượng AI chưa đạt production-ready:

- Hệ thống chạy được, không có lỗi request nghiêm trọng.
- Retrieval tìm đúng document khá tốt.
- Bot chưa tìm đúng chunk/đoạn chứa đáp án đủ tốt.
- Answer synthesis chưa bám chặt context.
- Fallback/no-info chưa cứng.
- Citation/source object chưa đủ đáng tin.
- Latency p95 quá cao.

## 2. Số Liệu Chính

Nguồn: `20260614-145538-dataset_new/report.md`, `ragas_summary.json`, `retrieval_diagnostics.json`, `performance_cold.json`, `safety_reliability.json`.

### RAG Quality

| Metric | Kết quả | Target | Trạng thái |
|---|---:|---:|---|
| Faithfulness | 0.6032 | >= 0.90 | Fail |
| Answer relevancy | 0.4103 | >= 0.85 | Fail |
| Context precision | 0.8718 | >= 0.80 | Pass |
| Context recall | 0.8389 | >= 0.80 | Pass |
| Answer correctness | 0.5252 | >= 0.80 | Fail |

Diễn giải:

- Context nhìn tổng thể không quá tệ.
- Câu trả lời cuối vẫn yếu.
- Lỗi không chỉ nằm ở retrieval, mà còn ở prompt, answer synthesis và fallback policy.

### Retrieval

| Metric | Kết quả |
|---|---:|
| Document hit@k | 1.0000 |
| Expected chunk hit@k | 0.2000 |
| Average retrieval score | 0.6152 |
| Knowledge gaps | 1 |

Diễn giải:

- Bot thường tìm đúng file.
- Bot chưa tìm đúng chunk kỳ vọng.
- Đúng file nhưng sai đoạn vẫn khiến LLM trả lời lệch hoặc thiếu căn cứ.

### Safety & Reliability

| Metric | Kết quả | Target | Trạng thái |
|---|---:|---:|---|
| Hallucination rate | 0.6000 | < 0.0500 | Fail |
| Graceful rejection rate | 0.5833 | >= 0.9500 | Fail |
| Access control accuracy | 1.0000 | 1.0000 | Pass |

Raw QA summary:

- 30 câu total.
- 25 `SUCCESS`.
- 4 `CLARIFY`.
- 1 `OFF_TOPIC`.
- 10/30 câu không có source object sau filter.
- `fallback_true = 0`.

Diễn giải:

- ACL đang ổn.
- Fallback/no-info gần như chưa được kích hoạt đúng cách.
- Bot còn cố trả lời hoặc hỏi vòng vo khi không đủ thông tin.

### Performance

| Metric | Kết quả | Target | Trạng thái |
|---|---:|---:|---|
| Concurrent users | 5 | >= 50 | Fail |
| First token latency p95 | 20.58s | < 2s | Fail |
| Total latency p95 | 24.48s | < 8s | Fail |
| Error rate | 0.0 | < 1% | Pass |
| Requests/sec | 0.2895 | TBD | Yếu |

Diễn giải:

- Hệ thống không lỗi 500.
- Nhưng tốc độ quá chậm cho trải nghiệm production.
- Không nên ưu tiên latency trước khi sửa hallucination/fallback.

## 3. Bối Cảnh Của Evaluation

Run hiện tại là local/e2e-local sample:

```json
{
  "target": "e2e-local",
  "question_count_total": 100,
  "question_count_selected": 30,
  "sample_strategy": "stratified",
  "concurrency": 5,
  "warm_cache": false
}
```

Ý nghĩa:

- Đây là kết quả chẩn đoán local, chưa phải GCP production eval.
- Vẫn có giá trị để phát hiện lỗi chất lượng pipeline.
- Sau khi tune local đạt, cần chạy lại full dataset và chạy against GCP domain.

## 4. Vấn Đề Gốc Cần Sửa

### 4.1 Fallback/no-info chưa cứng

Hiện tượng:

- `fallback_true = 0`.
- Graceful rejection chỉ đạt 0.5833.
- Negative/no-info case không luôn trả lời "không tìm thấy".

Rủi ro:

- Bot bịa khi không có context.
- Hallucination tăng.
- Người dùng tin nhầm câu trả lời không có căn cứ.

Hướng sửa:

- Nếu `rag_search` không có qualified source, trả `NO_INFO` ngay.
- Không cho LLM tự sinh câu trả lời khi `sources[]` rỗng.
- Negative case phải có câu trả lời chuẩn:

```text
Mình không tìm thấy thông tin này trong tài liệu nội bộ hiện có.
```

### 4.2 Citation/source chưa đủ đáng tin

Hiện tượng:

- 10/30 câu không có source object.
- Có nguy cơ answer tự ghi "Nguồn: ..." trong text nhưng `sources[]` thật lại rỗng.

Rủi ro:

- Citation bị bịa.
- Frontend không mở được đúng source.
- Reload conversation history không chứng minh được câu trả lời.

Hướng sửa:

- Citation chính thức chỉ lấy từ `sources[]`.
- Prompt cấm LLM tự viết citation nếu hệ thống đã có source renderer.
- Nếu answer là `SUCCESS` cho RAG path thì nên có ít nhất 1 source hợp lệ.
- Thêm `chunk_id`, `page_number`, `document_id`, `source_gcs_uri` vào eval output.

### 4.3 Đúng document nhưng sai chunk

Hiện tượng:

- `Document hit@k = 1.0`.
- `Expected chunk hit@k = 0.2`.

Rủi ro:

- LLM nhận đoạn không chứa đáp án.
- Câu trả lời thiếu ý hoặc tự bổ sung ngoài context.

Hướng sửa:

- Kiểm tra chunking strategy.
- Tăng/tune `top_k_candidates`.
- Tune `rerank_top_k` và `rerank_threshold`.
- Thử lexical/LLM rerank nếu dense-only chưa đủ.
- Đảm bảo eval có mapping stable chunk id -> runtime chunk id.

### 4.4 Prompt answer synthesis chưa đủ chặt

Hiện tượng:

- Faithfulness, answer relevancy, answer correctness đều fail.
- Context precision/recall pass nhưng answer vẫn thấp.

Rủi ro:

- LLM diễn giải ngoài tài liệu.
- Trả lời dài nhưng không đúng trọng tâm.
- Thêm lời khuyên không có trong context.

Hướng sửa:

- Prompt phải yêu cầu trả lời chỉ từ tool results.
- Nếu context chỉ trả lời một phần, nói rõ phần có căn cứ và phần chưa tìm thấy.
- Không thêm thông tin ngoài context.
- Trả lời ngắn, đúng câu hỏi.
- Không tự tạo nguồn/citation trong text.

### 4.5 Latency quá cao

Hiện tượng:

- First token p95 20.58s.
- Total p95 24.48s.
- Mới concurrency 5 đã chậm.

Rủi ro:

- Trải nghiệm chat kém.
- Khó đạt target production.

Hướng sửa sau khi chất lượng ổn:

- Đo số lần gọi LLM trên mỗi request: triage, think, rerank, answer.
- Kiểm tra model đang dùng có quá chậm không.
- Kiểm tra MCP/Qdrant/OpenAI timeout.
- Bật/warm semantic cache cho regression.
- Tối ưu SSE để stream sớm hơn.

## 5. Thứ Tự Ưu Tiên Cải Thiện

Không nên sửa tất cả cùng lúc. Nên làm theo từng vòng và chạy lại eval sau mỗi vòng.

### Vòng 1: Fix fallback và hallucination

Mục tiêu:

- Giảm hallucination.
- Tăng graceful rejection.
- Đảm bảo không có source thì không trả lời như có căn cứ.

Việc cần làm:

- Hard gate `NO_INFO` khi không có qualified sources.
- Không cho LLM trả lời RAG nếu `sources[]` rỗng.
- Chuẩn hóa message fallback.

Kỳ vọng sau vòng 1:

- Hallucination rate giảm rõ.
- Graceful rejection > 0.85.
- `fallback_true` bắt đầu có số liệu đúng.

### Vòng 2: Siết prompt grounding và citation

Mục tiêu:

- Tăng faithfulness.
- Tăng answer relevancy.
- Không còn fake citation trong answer text.

Việc cần làm:

- Cập nhật `AGENT_SYSTEM_PROMPT`.
- Cấm LLM tự viết citation.
- Yêu cầu trả lời chỉ từ tool result.
- Nếu thiếu context, nói thiếu context.

Kỳ vọng sau vòng 2:

- Faithfulness tăng.
- Answer relevancy tăng.
- Source empty giảm.

### Vòng 3: Tune retrieval đúng chunk

Mục tiêu:

- Tăng expected chunk hit@k.
- Giữ context precision/recall >= target.

Việc cần làm:

- Kiểm tra chunk size/overlap.
- Kiểm tra caption có làm mất ý gốc không.
- Tune top-k candidate pool.
- Tune reranker.
- Kiểm tra stable chunk mapping trong eval.

Kỳ vọng sau vòng 3:

- Expected chunk hit@k từ 0.2 lên ít nhất 0.6.
- Answer correctness tăng.

### Vòng 4: Tối ưu latency

Mục tiêu:

- Giảm first token latency.
- Giảm total latency.
- Chuẩn bị load test cao hơn.

Việc cần làm:

- Đếm số LLM calls/request.
- Xem triage/think/answer có thể rút gọn không.
- Kiểm tra rerank LLM nếu có.
- Tối ưu model, timeout, cache.

Kỳ vọng sau vòng 4:

- First token p95 < 5s trước.
- Total p95 < 12s trước.
- Sau đó mới nhắm target production < 2s / < 8s.

## 6. Các File Code Liên Quan

Query/runtime:

- `src/query-service/app/application/prompts.py`
- `src/query-service/app/application/langgraph_nodes.py`
- `src/query-service/app/application/use_cases/query/orchestration.py`
- `src/query-service/app/infrastructure/config.py`

Retrieval:

- `src/mcp-service/app/tools/rag_search.py`
- `src/mcp-service/app/core/search.py`
- `src/mcp-service/app/core/vectorstore.py`
- `src/mcp-service/app/core/rerank.py`

Ingestion/chunking:

- `src/rag-worker/core_engine/engine.py`
- `src/rag-worker/core_engine/chunking/`
- `src/rag-worker/app/application/use_cases/ingestion/ingest_document_use_case.py`

Eval artifacts:

- `20260614-145538-dataset_new/report.md`
- `20260614-145538-dataset_new/ragas_summary.json`
- `20260614-145538-dataset_new/retrieval_diagnostics.json`
- `20260614-145538-dataset_new/safety_reliability.json`
- `20260614-145538-dataset_new/performance_cold.json`

## 7. Quy Trình Rerun Eval

Sau mỗi vòng sửa:

1. Chạy lại local 30 câu stratified.
2. So sánh với baseline hiện tại.
3. Nếu cải thiện, chạy full 100/200 câu.
4. Nếu local đạt, chạy against GCP domain.
5. Lưu report mới vào folder timestamp riêng.

Không so sánh lẫn lộn các target khác nhau:

- `e2e-local` chỉ so với `e2e-local`.
- `gcp-staging` chỉ so với `gcp-staging`.
- `gcp-production` chỉ so với `gcp-production`.

## 8. Tiêu Chí Qua Phase 2

Tạm thời chưa cần đạt tuyệt đối ngay, nhưng trước Phase 2 nên có:

- Faithfulness >= 0.85 trước, rồi nhắm 0.90.
- Answer relevancy >= 0.75 trước, rồi nhắm 0.85.
- Answer correctness >= 0.75 trước, rồi nhắm 0.80.
- Expected chunk hit@k >= 0.60.
- Hallucination rate < 0.15 trước, rồi nhắm < 0.05.
- Graceful rejection >= 0.85 trước, rồi nhắm 0.95.
- Citation source object có mặt ở hầu hết answerable RAG answers.
- ACL vẫn giữ 1.0.
- First token p95 giảm rõ so với baseline 20.58s.

## 9. Câu Tóm Tắt Cho Team

Evaluation hiện tại cho thấy hệ thống đã chạy được end-to-end, nhưng chưa đạt chất lượng AI production-ready. Retrieval đang tìm đúng document nhưng sai chunk nhiều; answer synthesis và fallback chưa đủ chặt nên hallucination cao; citation/source object chưa ổn định; latency p95 còn quá cao. Cần ưu tiên sửa fallback và hallucination trước, sau đó tune retrieval đúng chunk, rồi mới tối ưu latency và chạy lại full eval trên GCP.

