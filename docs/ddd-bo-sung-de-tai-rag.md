# Bổ sung DDD vào đề tài RAG Chatbot

> Những ý còn thiếu từ tài liệu DDD cần bổ sung vào đề tài  
> **Xây dựng Chatbot Hỏi–Đáp dựa trên Tài liệu Nội bộ (RAG-based Q&A System)**

---

## 1. Domain Expert — Ai validate câu trả lời?

**Thiếu từ concept:** Building Domain Knowledge (Chương 2 DDD)

DDD nói rõ: không thể xây phần mềm tốt nếu chỉ có developer, phải có **domain expert** tham gia từ đầu để xác nhận model là đúng.

**Cần bổ sung vào đề tài:**

| Câu hỏi | Trả lời cần xác định |
|---------|----------------------|
| Ai là domain expert của hệ thống này? | Người hiểu nội dung tài liệu nội bộ nhất (HR, IT Lead, Manager phòng ban) |
| Ai validate câu trả lời của chatbot là đúng hay sai? | Phải có người chịu trách nhiệm review output trước khi go-live |
| Quy trình nào khi chatbot trả lời sai? | Escalation path: chatbot sai → báo ai → sửa tài liệu hay sửa prompt? |
| Ai duyệt tài liệu trước khi index? | Admin, nhưng Admin có đủ context để biết tài liệu đúng không? |

**Đề xuất bổ sung vào đề tài:**

> Trước khi build, cần xác định **Document Owner** cho từng loại tài liệu:
> - Tài liệu HR → HR Manager là domain expert, validate câu trả lời liên quan policy nghỉ phép, lương
> - Tài liệu kỹ thuật → Tech Lead validate
> - Tài liệu quy trình → Process Owner validate
>
> Sau MVP, chạy **User Acceptance Test** với đúng domain expert đó, không phải chỉ test nội bộ dev team.

---

## 2. Ubiquitous Language — Định nghĩa thuật ngữ cốt lõi

**Thiếu từ concept:** Ubiquitous Language (Chương 3 DDD)

DDD yêu cầu team phải có ngôn ngữ chung, nhất quán từ code đến tài liệu đến cuộc họp. Đề tài hiện tại dùng nhiều thuật ngữ kỹ thuật nhưng chưa định nghĩa rõ ràng.

**Bảng thuật ngữ cần định nghĩa (Ubiquitous Language):**

| Thuật ngữ | Định nghĩa trong hệ thống này |
|-----------|-------------------------------|
| **Document** | Tài liệu nội bộ đã được Admin approve và index vào hệ thống. Chưa approve không phải Document, chỉ là Upload. |
| **Chunk** | Đơn vị văn bản được cắt từ Document theo chiến lược Parent-Child (LlamaIndex HierarchicalNodeParser). Child node dùng để search; Parent node đưa vào LLM context. Config sizes TBD. |
| **Embedding** | Vector số 1536 chiều đại diện cho nghĩa của một Chunk, được sinh bởi model `text-embedding-3-small`. |
| **Query** | Câu hỏi của người dùng sau khi đã được normalize (lowercase, unicode NFC). |
| **Retrieved Context** | Tập hợp top-K Chunk có similarity score cao nhất với Query, dùng làm context cho LLM. |
| **Citation** | Thông tin trích dẫn nguồn gồm: tên file, số trang (nếu có), chunk_id. Bắt buộc đi kèm mọi câu trả lời. |
| **Fallback** | Trạng thái chatbot từ chối trả lời vì không tìm được Chunk nào có similarity ≥ 0.7. LLM không được gọi. |
| **Hallucination** | Câu trả lời LLM bịa đặt thông tin không có trong Retrieved Context — điều hệ thống này phải ngăn chặn. |
| **Score Threshold** | Ngưỡng similarity tối thiểu = 0.7. Dưới ngưỡng → Fallback. Trên ngưỡng → gọi LLM. |
| **Ingestion** | Toàn bộ pipeline xử lý tài liệu: Parse → Clean → Chunk → Embed → Store vào Vector DB. |
| **Index** | Quá trình đưa Embedding vào Qdrant để có thể tìm kiếm. Sau Approve → Index. Sau xóa → De-index. |

---

## 3. Bounded Context — Phạm vi hệ thống (In scope / Out of scope)

**Thiếu từ concept:** Bounded Context (Chương 6 DDD)

DDD yêu cầu vẽ ranh giới rõ ràng: hệ thống này làm gì, không làm gì. Đề tài hiện tại chưa nói rõ điều này.

**Cần bổ sung:**

### Trong phạm vi (In scope)

- Trả lời câu hỏi bằng tiếng Việt và tiếng Anh
- Xử lý tài liệu: PDF text-based, PDF scan (OCR), DOCX, TXT, Excel/CSV, PPTX, Markdown
- Tài liệu tối đa 50MB mỗi file
- Trả lời câu hỏi cá nhân HR: ngày nghỉ còn lại, trạng thái đơn nghỉ phép (Function Calling)
- Dẫn nguồn cụ thể: tên file, số trang
- Từ chối trả lời khi không có thông tin trong tài liệu

### Ngoài phạm vi (Out of scope — không làm)

- Không trả lời câu hỏi dùng thông tin ngoài tài liệu nội bộ (không search internet)
- Không thực hiện hành động thay đổi dữ liệu (read-only hoàn toàn)
- Không xem thông tin HR của nhân viên khác
- Không hỗ trợ file audio, video, hình ảnh (chỉ OCR PDF scan)
- Không tự động cập nhật tài liệu — phải qua Admin approve
- Không hỗ trợ câu hỏi multi-hop phức tạp đòi hỏi suy luận nhiều bước (Phase 4+)

### Ranh giới phòng ban

- Tài liệu được phân loại theo classification: Public / Internal / Secret / Top Secret
- End User chỉ thấy tài liệu ở cấp classification mà họ được phép truy cập

---

## 4. Tiêu chí "câu trả lời đúng" — Định nghĩa rõ ràng

**Thiếu từ concept:** Building Domain Knowledge + Ubiquitous Language

Đề tài nói "đảm bảo câu trả lời chính xác" nhưng chưa định nghĩa **chính xác theo tiêu chí nào**.

**Cần bổ sung bộ tiêu chí đánh giá:**

| Tiêu chí | Định nghĩa | Công cụ đo |
|----------|------------|-----------|
| **Faithfulness** | Câu trả lời không chứa thông tin ngoài Retrieved Context | RAGAS Faithfulness > 0.8 |
| **Answer Relevancy** | Câu trả lời đúng trọng tâm câu hỏi, không lan man | RAGAS Answer Relevancy > 0.8 |
| **Context Recall** | Retriever tìm được chunk chứa đáp án | RAGAS Context Recall > 0.75 |
| **Fallback Rate** | Tỷ lệ từ chối khi không có thông tin | 10–20% là mức kỳ vọng |
| **Latency** | Tốc độ phản hồi | p50 < 3 giây, p95 < 5 giây |

**Bộ test 40 câu hỏi mẫu (Ground Truth):**

Chia theo 4 loại:
- **Easy (10 câu):** câu hỏi fact đơn giản, câu trả lời nằm trong 1 chunk
- **Medium (15 câu):** câu hỏi cần tổng hợp từ 2–3 chunk
- **Hard (10 câu):** câu hỏi mơ hồ, cần hiểu ngữ cảnh
- **Edge case (5 câu):** câu hỏi không có câu trả lời trong tài liệu → phải Fallback

---

## 5. Anticorruption Layer — Cách ly LLM khỏi Domain

**Thiếu từ concept:** Anticorruption Layer (Chương 6 DDD)

Hiện tại đề tài chưa nói rõ cơ chế cách ly giữa domain logic và external LLM API. Nếu đổi LLM (từ OpenAI sang DeepSeek, Claude...) thì ảnh hưởng đến đâu?

**Cần bổ sung:**

```
Domain Logic (RAG Service)
        │
        ▼
[LLM Gateway — Anticorruption Layer]
   - Chuẩn hóa input prompt
   - Xử lý response format
   - Retry / timeout / error handling
        │
        ▼
External LLM API (OpenAI / DeepSeek / Claude...)
```

**Lợi ích:** Đổi LLM provider chỉ cần thay implementation của LLM Gateway, toàn bộ domain logic không đổi.

**Đề xuất interface:**

```python
class LLMGateway(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        context: list[str],
        max_tokens: int = 1000
    ) -> GenerationResult:
        ...

class OpenAIGateway(LLMGateway):
    # implement với OpenAI
    ...

class DeepSeekGateway(LLMGateway):
    # implement với DeepSeek
    ...
```

---

## 6. Core Domain vs Generic Subdomain — Xác định điểm sáng

**Thiếu từ concept:** Distillation (Chương 6 DDD)

DDD yêu cầu xác định rõ đâu là **Core Domain** (điểm tạo ra giá trị, cần đầu tư nhiều nhất) và đâu là **Generic Subdomain** (chức năng hỗ trợ, có thể dùng thư viện có sẵn).

**Phân loại cho đề tài này:**

| Loại | Component | Lý do |
|------|-----------|-------|
| **Core Domain** ⭐ | RAG Retrieval Pipeline | Đây là điểm tạo ra giá trị chính — chunking strategy, embedding, re-ranking, score threshold |
| **Core Domain** ⭐ | Hallucination Control | Cơ chế Fallback khi score < 0.7 — đây là điểm khác biệt với các sản phẩm khác |
| **Core Domain** ⭐ | Answer Generation với Citation | Sinh câu trả lời có dẫn nguồn rõ ràng |
| **Generic Subdomain** | Authentication (JWT, SSO) | Dùng thư viện có sẵn (python-jose, msal) |
| **Generic Subdomain** | File Storage (S3) | Infrastructure chuẩn |
| **Generic Subdomain** | Logging, Monitoring | Langfuse + CloudWatch |
| **Generic Subdomain** | UI/UX Chat Interface | Next.js + Tailwind, không phải điểm sáng |

**Kết luận:** Đầu tư chính vào Core Domain — chunking strategy, threshold tuning, citation format. Đừng tự build lại Generic Subdomain.

---

## 7. Refactoring — Các tham số cần tune sau thực tế

**Thiếu từ concept:** Refactoring Toward Deeper Insight (Chương 5 DDD)

DDD nói: model ban đầu luôn nông cạn, phải refactor liên tục sau khi có feedback thực tế. Đề tài cần nói rõ những gì sẽ được tune sau Phase 1.

**Danh sách tham số cần eval và tune:**

| Tham số | Giá trị ban đầu | Cần tune khi |
|---------|----------------|--------------|
| Parent chunk size | TBD | RAGAS Context Recall < 0.75 |
| Child chunk size | TBD | Câu trả lời bị đứt đoạn ngữ nghĩa |
| Top-K retrieval | 5 chunks | Câu trả lời thiếu thông tin hoặc nhiễu |
| Score threshold | 0.7 | Fallback rate > 30% hoặc hallucination xuất hiện |
| Re-ranker | BGE-Reranker-v2-m3 (Top-5 → Top-3) | Nếu context quality vẫn thấp sau Top-5 |
| Embedding model | text-embedding-3-small (1536 dims) | Khi tiếng Việt accuracy kém |

**Quy trình tune:**
1. Chạy bộ 40 câu Ground Truth sau mỗi thay đổi
2. So sánh RAGAS scores trước/sau
3. Ghi lại quyết định trong Langfuse
4. Không tune mù — phải có số liệu

---

## Tóm tắt — Checklist bổ sung

| # | Mục cần bổ sung | Trạng thái |
|---|-----------------|-----------|
| 1 | Xác định Domain Expert (HR, IT Lead, Manager) cho từng loại tài liệu | ⬜ Chưa có |
| 2 | Bảng Ubiquitous Language — định nghĩa 11 thuật ngữ cốt lõi | ⬜ Chưa có |
| 3 | Bounded Context — In scope / Out of scope rõ ràng | ⬜ Chưa có |
| 4 | Tiêu chí "câu trả lời đúng" — RAGAS metrics + bộ test 40 câu | ✅ Đã có một phần |
| 5 | LLM Gateway (Anticorruption Layer) — interface cách ly LLM | ⬜ Chưa rõ |
| 6 | Phân loại Core Domain vs Generic Subdomain | ⬜ Chưa có |
| 7 | Kế hoạch Refactoring — danh sách tham số sẽ tune sau MVP | ⬜ Chưa rõ |
