# Pipeline Service — Ranh giới và Tích hợp

> **Audience:** AI service · BE service · FE service
> **Cập nhật:** 2026-05-31

---

## Service này là gì

Một **retrieval substrate** — tương tự Google Search Index.

Nhận tài liệu thô → chuẩn hóa → index. Khi có query → trả về danh sách section liên quan nhất, kèm lineage đủ để caller tự quyết định cách dùng.

Không hơn, không kém.

---

## Ranh giới cứng

### Service này sở hữu hoàn toàn — không service nào can thiệp

- Cách parse tài liệu: parser backend, OCR strategy
- Cách chia section: heading hierarchy, fallback strategy
- Cách tạo caption cho section
- Cách embed: model, dimension, batching, cache
- Cách index: vector store, payload schema
- Cách score và filter kết quả tìm kiếm

Những thứ trên là **implementation detail**. Có thể thay đổi mà không làm đổi API contract, miễn response shape và semantics vẫn giữ nguyên.

### Service này không làm — không đưa vào đây

| Không làm | Thuộc về |
|---|---|
| Ai được đọc tài liệu nào | BE service |
| Filter kết quả theo quyền user | BE service |
| Query rewriting | AI service |
| Reranking sau khi search | AI service |
| Sinh câu trả lời cuối cùng | AI service |
| Prompt strategy, tone, format | AI service |
| Hiển thị citation trong UI | FE / AI service |
| Product logic, API composition | BE service |

---

## API contract

### Consumer endpoint

```
POST /search
Content-Type: application/json
X-Request-ID: <caller-generated-id>   ← optional, dùng để trace xuyên service

{
  "query": "...",
  "top_k": 5
}
```

Constraints:

- `query` là bắt buộc, không được để trống sau khi trim.
- `query` tối đa `2000` ký tự.
- `top_k` từ `1` đến `50`.

**Correlation ID:** Nếu caller truyền header `X-Request-ID`, service dùng đúng giá trị đó làm `request_id` trong response và log nội bộ. Nếu không có header, service tự sinh UUID4. Giá trị cuối cùng luôn được echo lại trong cả response body (`request_id`) và response header (`X-Request-ID`) để middleware hoặc proxy có thể forward tiếp.

```
FE  →  BE (sinh X-Request-ID: trace-abc)
        →  AI service (forward X-Request-ID: trace-abc)
            →  POST /search  header: X-Request-ID: trace-abc
                ←  response:  request_id: trace-abc
                              X-Request-ID: trace-abc  (header)
```

Tất cả log của request đó sẽ mang `request_id=trace-abc`, giúp correlate trace xuyên service mà không cần distributed tracing infrastructure.

Response:

```json
{
  "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "results": [
    {
      "section_id": "doc_123_section_0007",
      "document_id": "doc_123",
      "document_name": "travel_policy.pdf",
      "caption": "Quy định về mức hoàn tiền tối đa cho vé máy bay công tác",
      "section_content": "## Hoàn tiền vé máy bay\n...\n",
      "heading_path": ["Chính sách công tác", "Hoàn tiền vé máy bay"],
      "score": 0.91,
      "source_s3_uri": "s3://bucket/raw/hr/travel_policy.pdf",
      "markdown_s3_uri": "s3://bucket/rag-derived/markdown/doc_123.md"
    }
  ]
}
```

**Ý nghĩa từng field:**

| Field | Dùng để |
|---|---|
| `request_id` | Correlate log / trace giữa các service |
| `section_id` | Dedup, reference lại một section cụ thể |
| `document_id` | Group results theo tài liệu |
| `document_name` | Hiển thị tên nguồn cho user |
| `caption` | Nhãn ngắn cho section để hiển thị hoặc đưa vào prompt. Có thể là caption sinh bởi AI hoặc fallback heuristic từ nội dung section |
| `section_content` | Processed Markdown của section — có thể đưa thẳng vào LLM prompt |
| `heading_path` | Breadcrumb từ root đến section — dùng để render citation hoặc navigation |
| `score` | Similarity score sau vector search và threshold filter |
| `source_s3_uri` | URI file gốc — dùng để cite nguồn hoặc fallback download |
| `markdown_s3_uri` | URI Markdown của toàn tài liệu — dùng khi cần context rộng hơn một section |

**Lưu ý về score threshold:** Service filter kết quả dưới ngưỡng trước khi trả về. Mặc định hiện tại là `0.5`. Số results thực tế có thể ít hơn `top_k` nếu nhiều candidates không đạt ngưỡng.

---

## Operational endpoints

Các endpoint dưới đây phục vụ vận hành hoặc orchestration nội bộ; không phải contract chính cho consumer thông thường.

### `POST /scan`

Trigger scan nguồn tài liệu và enqueue ingest jobs.

Request body:

```json
{
  "bucket": "optional-bucket",
  "prefix": "optional-prefix"
}
```

Lưu ý:

- `bucket` và `prefix` đều optional.
- Nếu scan đang chạy, endpoint trả `409` với detail `scan already in progress`.
- Response thành công có dạng:

```json
{
  "status": "scan started",
  "queued": 2
}
```

- `queued` là số job thực tế được đưa vào dispatcher queue, có thể nhỏ hơn số file scanner nhìn thấy nếu có dedupe hoặc queue full.

### `GET /status/{doc_id}`

Trả trạng thái ingest của một document.

Response thành công:

```json
{
  "doc_id": "doc_123",
  "status": "indexed",
  "file_path": "s3://bucket/raw/hr/travel_policy.pdf",
  "source_s3_uri": "s3://bucket/raw/hr/travel_policy.pdf",
  "markdown_s3_uri": "s3://bucket/rag-derived/markdown/doc_123.md",
  "file_type": "pdf",
  "section_count": 7,
  "parser_version": "pipeline.parsers.v1",
  "caption_model": "heuristic",
  "embedding_model": "text-embedding-3-small",
  "uploaded_at": "2026-05-31T10:15:00+00:00",
  "processed_at": "2026-05-31T10:15:08+00:00"
}
```

Lưu ý:

- Nếu `doc_id` không tồn tại, endpoint trả `404`.
- `status` phản ánh trạng thái ingest thực tế như `pending`, `indexing`, `indexed`, `failed`.
- `processed_at` có thể là `null` nếu ingest chưa hoàn tất.

### `GET /health`

Trả tình trạng vận hành của service.

Payload gồm:

- `status`: `ok` hoặc `degraded`
- `vector_store`
- `metadata_store`
- `ai_provider`
- `scanner`: `enabled` hoặc `disabled`
- `dispatcher`: thống kê queue/running jobs
- `degraded_reasons`: danh sách lý do degraded

Lưu ý:

- Khi service healthy, endpoint trả HTTP `200`.
- Khi service degraded, endpoint trả HTTP `503`.

---

## Cách tích hợp

### AI service

Gọi `/search` → nhận sections → tự làm phần còn lại.

```
user query
  → (tuỳ chọn) query rewriting ở AI layer
  → POST /search
  → nhận sections
  → (tuỳ chọn) rerank bằng cross-encoder: dùng section_content + query
  → assemble prompt: nhét section_content làm context
  → gọi LLM → sinh answer
  → assemble citation: heading_path + document_name + source_s3_uri
```

- `section_content` là processed Markdown — nhét thẳng vào prompt được.
- `caption` là nhãn ngắn để làm snippet hoặc label context, không nên coi là ground truth độc lập với `section_content`.
- `markdown_s3_uri` là full document Markdown — dùng khi cần mở rộng context vượt quá một section.
- `source_s3_uri` là file gốc — dùng để cite nguồn hoặc offer download link.
- `request_id` trả về từ `/search` nên được forward tiếp để correlate trace.

### BE service

Service này không làm permission. Nếu cần ACL hoặc filter theo user, BE service phải tự làm sau khi nhận kết quả.

```
POST /search  với top_k đủ lớn để bù sau khi filter
  → filter kết quả theo quyền user
  → trả kết quả đã lọc cho FE hoặc AI layer
```

Vì score threshold có thể loại bớt một phần results trước khi trả về, BE nên gọi `top_k` cao hơn mức mong muốn. Ví dụ muốn trả 5 kết quả sau khi filter quyền thì `top_k=20` là điểm khởi đầu hợp lý; điều chỉnh theo tỉ lệ filter thực tế.

### FE service

Không gọi trực tiếp pipeline service. FE nhận kết quả đã được BE hoặc AI layer xử lý.

- `heading_path` — render breadcrumb dẫn đến section
- `document_name` — hiển thị tên nguồn
- `source_s3_uri` — link download hoặc view file gốc nếu cần

---

## Nguyên tắc một câu

> Service này trả **context thô tốt nhất có thể**. Mọi quyết định về cách dùng context đó — ai được xem, dùng để làm gì, trả lời thế nào — là trách nhiệm của caller.
