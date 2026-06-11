# Kế hoạch cải thiện Query Service — Phân công nhóm

> **Mục tiêu:** Cải thiện **Query Service** (agent + RAG) — đang chậm và chất lượng truy hồi chưa ổn.
> **Bối cảnh:** Đây là phần cả nhóm chưa làm tới nơi, nên phát sinh đợt này để **cùng nhau xử lý**.
> **Thời gian:** **11/6 → 15/6**
> - **Việc chính:** 11–12/6 (T5–T6) — mỗi người làm phần của mình.
> - **Cùng hỗ trợ query-service:** 13–14/6 (T7–CN) — cả nhóm dồn vào query-service.
> - **Demo + báo cáo mentor:** 15/6 (T2).

---

## 1. Vấn đề

- **3 lần gọi LLM tuần tự + 1 lần retrieval (có rerank), nối đuôi nhau — độ trễ gốc.**
  Một câu hỏi phải qua: *triage* (phân loại) → *think* (chọn tool) → *retrieval* (search + rerank) → *think* (tổng hợp). Mỗi bước chờ bước trước xong → cộng dồn thành chậm.

- **Chưa stream thật (gốc ở backend, không phải FE).**
  Adapter backend thiếu hàm `_astream` nên agent **đợi sinh xong cả câu** rồi mới đẩy ra từng chữ → user thấy “đứng im” vài giây rồi mới có chữ đầu. FE chỉ cần render token khi backend đã stream đúng.

- **MCP dựng session mới mỗi call.**
  Mỗi lần gọi tool, query-service mở kết nối mới + bắt tay (handshake) với mcp-service rồi đóng. Lặp lại nhiều lần → tốn thời gian thừa. (Cache tool list cũng đang tắt.)

- **Threshold chỉnh tay, chưa khớp docs.**
  Đang hạ tay 0.70 → 0.35 theo cảm tính; chưa rõ điểm đang lọc theo *cosine* hay *rerank score* (2 thang khác nhau) → cao thì “không tìm thấy”, thấp thì nhận nhầm tài liệu lạc.

---

## 2. Giải pháp

- **Fix streaming.**
  Thêm `_astream` ở backend để stream token thật, FE render ngay → chữ đầu ra nhanh.

- **Bỏ/gộp triage vào intent_classifier hybrid (rule + embedding) đã có.**
  Phân loại off-topic/clarify bằng rule + embedding (nhanh, không tốn LLM); chỉ khi thật cần mới gọi LLM → bớt 1 vòng gọi LLM.

- **Bật cache tool + tái dùng session MCP.** *(vá cho vấn đề MCP)*
  Bật `mcp_tool_cache_ttl` (đang tắt) và dùng lại kết nối → bỏ phần handshake lặp. Đổi rất ít code mà nhanh thấy rõ.

- **Chốt threshold bằng eval (bộ 20–30 câu RAGAS, đo Context Precision/Recall), gate theo rerank score.**
  Lấy số liệu để chọn ngưỡng thay vì đoán; quyết rõ lọc theo **rerank score**.

- **Query rewriting / multi-query + RRF cho recall tiếng Việt (thêm ở rag-worker nếu chưa có).**
  Sinh vài biến thể câu hỏi rồi gộp kết quả → tìm trúng tài liệu hơn với tiếng Việt.

- **Dùng model mạnh hơn cho node tổng hợp (giữ mini cho phân loại).**
  Model mạnh viết câu trả lời chuẩn hơn, ít trả lời sai/“không tìm thấy” oan; việc phân loại nhẹ thì vẫn để mini cho rẻ.

---

## 3. Phân công

| Thành viên | Việc chính (11–12/6) | Hỗ trợ query-service (13–14/6) |
|---|---|---|
| **Hải** | FE streaming + citation — render token SSE realtime + hiển thị nguồn trích dẫn. *(Chạy được phải đợi backend `_astream` xong trước.)* | Test E2E luồng chat + tinh chỉnh UI hiển thị nguồn/độ trễ. |
| **Quốc Dũng + Hưng** | Quốc Dũng: gộp triage vào intent_classifier (bớt 1 LLM call). Hưng: chạy RAGAS trên golden data + chốt threshold theo số liệu. | Hoàn thiện + tích hợp các thay đổi vào query-service, chạy lại eval. |
| **Huy + Quang Dũng** | Tìm dataset 600 file (pdf/word/png…) + tạo golden data. Ưu tiên **20–30 cặp câu hỏi–đáp án mẫu (golden) trước**; 600 file ingest làm nền sau. | Ingest dữ liệu + cùng chạy eval RAGAS, đối chiếu kết quả truy hồi. |
| **Nguyên** | Fix CI ổn định + dựng Langfuse monitoring. **Làm sớm nhất** — Langfuse cho thấy chặng nào chậm để cả nhóm tối ưu đúng chỗ. | Đo before/after (first-token, P95, Precision/Recall) + hỗ trợ tích hợp. |

> **Lưu ý:** từ **13–14/6** mọi người gác việc chính, **cùng vào query-service** để gộp nhánh, đo đạc và tinh chỉnh chung. Các phần *Việc chính* nên cố gắng xong trong 11–12/6 để 2 ngày này không bị kẹt.

---

## 4. Lưu ý phối hợp

- Query-service là **1 codebase** → 5 người sửa cùng lúc dễ đụng nhau. Mỗi người bám đúng **vùng file của mình**: streaming / triage / threshold / data / infra.
- **Thứ tự phụ thuộc:** Langfuse (Nguyên) + golden data (Huy + Quang Dũng) nên xong sớm trong 11–12/6 → là đầu vào cho phần đo threshold (Hưng) và đánh giá tốc độ trước/sau.
- **13–14/6 (cùng query-service):** gộp nhánh, chạy lại test, **đo before/after** (first-token, P95, Context Precision/Recall) trên Langfuse.
- **15/6 (demo):** chốt số liệu, chuẩn bị slide + báo cáo cho mentor → phần before/after là điểm thuyết phục nhất.
