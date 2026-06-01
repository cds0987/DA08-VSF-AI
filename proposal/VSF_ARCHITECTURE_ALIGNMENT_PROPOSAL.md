# Đề Xuất Đồng Bộ Kiến Trúc VSF Với Pipeline Refactor Markdown - Section - Caption

## 1. Mục đích tài liệu

Tài liệu này mô tả đề xuất đồng bộ kiến trúc của VSF theo đúng target architecture đã được chốt trong pipeline của repo này.

Mục tiêu của tài liệu không chỉ là chỉ ra conflict giữa VSF hiện tại và pipeline mới, mà còn:

- diễn giải đầy đủ retrieval model mới
- chốt các contract cốt lõi mà VSF phải tuân theo
- làm rõ module boundaries, data contracts và dependency direction
- xác định các tài liệu VSF cần sửa để đồng bộ hoàn toàn

Tài liệu gốc làm chuẩn đối chiếu:

- [REFATOR_CAPTION_SECTION_ARCHITECTURE.md](D:/Training/e-commerce events/docs/REFATOR_CAPTION_SECTION_ARCHITECTURE.md:1)

Các tài liệu VSF hiện tại cần đồng bộ:

- [architecture.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/architecture.md:1)
- [contracts.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/contracts.md:1)
- [api-spec.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/api-spec.md:1)
- [data-schema.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/data-schema.md:1)
- [team-ownership.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/team-ownership.md:1)
- [roadmap.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/roadmap.md:1)
- [SA_RAG_Chatbot_Final.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/SA_RAG_Chatbot_Final.md:1)

## 2. Kết luận kiến trúc

Kiến trúc chunk-based hiện tại trong bộ docs VSF không còn phù hợp với mục tiêu của pipeline mới.

Target architecture cần được chốt thống nhất cho cả pipeline và VSF là:

`Source file -> Markdown -> Section -> Caption -> Embedding -> Search by caption -> Return section + references`

Điểm thay đổi cốt lõi:

- không còn lấy `chunk token` làm retrieval unit
- không embed `raw chunk text` làm đơn vị tìm kiếm chính
- không trả về fragment text đứt đoạn như contract mặc định
- phải có `markdown_s3_uri` và `source_s3_uri` trong search response

Nếu VSF không đồng bộ theo mô hình này, hệ thống sẽ rơi vào trạng thái:

- ingestion theo một hướng
- retrieval contract theo hướng khác
- AI/Agent consumption theo hướng cũ
- đội phát triển làm việc trên hai kiến trúc mâu thuẫn nhau

## 3. Mục tiêu sản phẩm thống nhất

Kiến trúc mới phục vụ chatbot nội bộ cho tập đoàn lớn, nơi chất lượng trả lời và khả năng truy vết quan trọng hơn việc chỉ tìm đúng vài token giống nhau.

Mục tiêu sản phẩm đã chốt:

1. Mọi tài liệu đầu vào được chuẩn hóa về Markdown.
2. Markdown trở thành canonical artifact sau parse.
3. Markdown được chia thành các section hoàn chỉnh theo heading hoặc cấu trúc tương đương.
4. Mỗi section có caption 2-3 câu mô tả ý chính.
5. Vector search dựa trên caption embedding.
6. Search trả về full section, không trả về text fragment bị cắt.
7. Search luôn trả thêm `markdown_s3_uri` và `source_s3_uri`.

Ý nghĩa thực tế:

- chatbot trả lời dựa trên đơn vị tri thức hoàn chỉnh hơn
- AI team hiểu nhanh nhờ caption
- caller có bản Markdown chuẩn hóa để đọc rộng hơn
- caller có file nguồn để đối chiếu khi cần độ chắc chắn cao

## 4. Vấn đề của kiến trúc chunk hiện tại

### 4.1. Chunk là đơn vị kỹ thuật, không phải đơn vị nghĩa

Chunk token chỉ hữu ích cho chia nhỏ dữ liệu kỹ thuật. Nó không phản ánh ranh giới ý nghĩa của tài liệu.

Hệ quả:

- một policy có thể bị cắt thành nhiều chunk
- query có thể match đúng từ khóa nhưng sai ý
- chatbot nhận context thiếu đầu hoặc thiếu cuối

### 4.2. Search result hiện tại không đủ để kiểm tra chéo

Response kiểu:

- `chunk_id`
- `content`
- `page_number`
- `score`

là không đủ cho môi trường enterprise. Nó thiếu:

- section đầy đủ
- caption để hiểu nhanh
- URI đến Markdown chuẩn hóa
- URI đến file gốc

### 4.3. VSF hiện tại đang khóa contract vào chunk model

Điểm conflict chính đang nằm ở:

- [contracts.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/contracts.md:1)
- [api-spec.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/api-spec.md:1)
- [data-schema.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/data-schema.md:1)

Nếu giữ nguyên, mọi thành phần phía trên RAG vẫn sẽ bị ép tiêu thụ dữ liệu kiểu chunk.

## 5. Retrieval model mới cần áp dụng cho VSF

Retrieval model mới của pipeline phải được VSF áp dụng nguyên vẹn.

```text
Source file
  ->
Parse to Markdown
  ->
Store Markdown artifact
  ->
Split by heading into sections
  ->
Generate caption for each section
  ->
Embed caption
  ->
Index section record
  ->
Search by caption vector
  ->
Return:
  - section_content
  - caption
  - markdown_s3_uri
  - source_s3_uri
  - score
```

### 5.1. Bốn đơn vị trung tâm

- `File`: tài liệu gốc
- `Markdown`: bản chuẩn hóa của file
- `Section`: đơn vị tri thức để retrieve
- `Caption`: đơn vị semantic để embed

### 5.2. Cái gì là canonical artifact

Sau parse, Markdown là dữ liệu nền cho tất cả bước sau:

- split section
- caption
- indexing metadata
- trace, debug, reprocess

File gốc vẫn quan trọng, nhưng không còn là artifact chính để downstream logic làm việc trực tiếp.

### 5.3. Cái gì là retrieval unit

Retrieval unit phải là `section`, không phải `chunk`.

Điều này là quyết định kiến trúc, không phải một tối ưu cục bộ.

### 5.4. Cái gì là embedding unit

Embedding unit phải là `caption`, không phải full `section_content`.

Section content vẫn được lưu và trả về, nhưng vector được sinh từ caption để tăng chất lượng semantic retrieval.

## 6. Target response model phải đồng bộ

VSF cần đổi toàn bộ response contract theo model mới.

### 6.1. Search result chuẩn

```python
@dataclass
class SectionSearchResult:
    section_id: str
    document_id: str
    document_name: str
    caption: str
    section_content: str
    markdown_s3_uri: str
    source_s3_uri: str
    score: float
    heading_path: list[str] | None = None
```

### 6.2. Những field bắt buộc

- `section_content`
  Dùng làm context chính cho LLM hoặc AI layer.

- `caption`
  Dùng để hiểu nhanh nội dung section, hỗ trợ ranking, debug và UI.

- `markdown_s3_uri`
  Dùng để đọc bản đã chuẩn hóa, mở rộng context và debug parser.

- `source_s3_uri`
  Dùng để kiểm tra chéo file gốc khi cần độ chắc chắn cao hơn.

### 6.3. Những field không còn là trung tâm

- `chunk_id`
- `page_number`
- `chunk_count`
- `chunk_text`

Nếu vẫn giữ tạm thời, chúng chỉ nên là field legacy hoặc migration-only.

## 7. Search API contract mới cho VSF

`POST /search` của VSF phải đổi response sang dạng section-centric.

Ví dụ:

```json
{
  "results": [
    {
      "section_id": "uuid",
      "document_id": "uuid",
      "document_name": "travel_policy_2024.pdf",
      "caption": "Section này mô tả mức hoàn tiền tối đa cho chuyến công tác nội địa và quốc tế.",
      "section_content": "## Mục 4. Hoàn tiền\nNhân viên được hoàn tối đa ...",
      "markdown_s3_uri": "s3://rag-derived-bucket/markdown/doc-123.md",
      "source_s3_uri": "s3://raw-docs/hr/travel_policy_2024.pdf",
      "score": 0.91,
      "heading_path": ["Chính sách công tác", "Hoàn tiền"]
    }
  ]
}
```

Search API không chỉ là thay đổi payload. Nó kéo theo thay đổi ở:

- contracts
- metadata schema
- Qdrant payload
- Chat/Agent consumption
- UI hiển thị nguồn

## 8. Data contracts giữa các bước

VSF nên đồng bộ với pipeline mới ở mức data contracts trung gian.

### 8.1. `SourceDocument`

Thông tin tối thiểu:

- `document_id`
- `document_name`
- `source_s3_uri`
- `file_type`
- classification metadata

### 8.2. `MarkdownDocument`

Thông tin tối thiểu:

- `document_id`
- `document_name`
- `source_s3_uri`
- `markdown_content`
- `markdown_s3_uri`
- `parser_version`

### 8.3. `DocumentSection`

Thông tin tối thiểu:

- `section_id`
- `document_id`
- `heading_path`
- `section_content`
- `markdown_s3_uri`
- `source_s3_uri`

### 8.4. `CaptionedSection`

Thông tin tối thiểu:

- toàn bộ field của `DocumentSection`
- `caption`
- `caption_model`

### 8.5. `IndexedSection`

Thông tin tối thiểu:

- toàn bộ field của `CaptionedSection`
- `embedding_model`
- `embedding_vector`

## 9. Kiến trúc module mà VSF cần đồng bộ

### 9.1. Kiến trúc lớp

VSF nên giữ hướng clean architecture, nhưng phải đổi business model và contracts cho đúng retrieval architecture mới.

Đề xuất cấu trúc:

- `domain/`
  - `Document`
  - `MarkdownDocument`
  - `DocumentSection`
  - `SectionSearchResult`
- `application/`
  - `RunIngestJob`
  - `SearchSections`
  - `ApproveDocument`
  - `ScanDocuments`
- `ports/`
  - `DocumentParser`
  - `MarkdownStore`
  - `SectionSplitter`
  - `SectionCaptioner`
  - `EmbeddingProvider`
  - `SectionIndex`
  - `DocumentRepository`
  - `JobLogRepository`
- `infrastructure/`
  - parser adapters
  - markdown store adapters
  - caption adapters
  - embedding adapters
  - Qdrant section index
  - Postgres repositories

### 9.2. Composition root

Wiring dependency phải nằm ở `bootstrap` hoặc container layer, không nằm trực tiếp trong API hay use case.

Điều này giúp:

- thay strategy mà không sửa business flow
- cấu hình local, test, prod rõ ràng
- giữ dependency direction đúng

## 10. Nguyên tắc interface per pipeline step

Mỗi bước gắn vào pipeline phải đi qua một interface ổn định. Đây là nguyên tắc bắt buộc nếu muốn VSF mở rộng tốt về sau.

Mẫu thiết kế:

```text
Pipeline step
  ->
Port / Interface ổn định
  ->
Strategy / Adapter có thể thay đổi
```

### 10.1. Mapping đề xuất

| Pipeline step | Port / Interface | Strategy có thể thay |
|---|---|---|
| Parse | `DocumentParser` | PDF, DOCX, HTML, OCR, image |
| Save markdown | `MarkdownStore` | dedicated bucket, shared prefix, local |
| Split section | `SectionSplitter` | heading splitter, fallback splitter |
| Caption | `SectionCaptioner` | prompt version, provider, batch strategy |
| Embed | `EmbeddingProvider` | model, provider |
| Index | `SectionIndex` | Qdrant hoặc backend khác |
| Search | `SectionSearchService` | ranking, threshold, filter strategy |

### 10.2. Lợi ích

- thêm loại tài liệu mới không sửa pipeline lõi
- đổi provider không sửa use case
- nhiều team làm song song ít đụng nhau
- test theo contract dễ hơn

## 11. SOLID áp dụng cho VSF theo kiến trúc mới

### 11.1. Single Responsibility

Mỗi module chỉ nên có một lý do để thay đổi:

- parser chỉ làm `file -> markdown`
- splitter chỉ làm `markdown -> sections`
- captioner chỉ làm `section -> caption`
- embedder chỉ làm `text -> vector`
- indexer chỉ làm `indexed records -> vector store`

### 11.2. Open/Closed

Muốn thêm định dạng file mới hoặc strategy mới thì thêm implementation mới, không sửa pipeline lõi.

### 11.3. Liskov Substitution

Mọi implementation cùng một port phải trả về cùng semantics, không chỉ cùng kiểu dữ liệu.

### 11.4. Interface Segregation

Không dùng một repository khổng lồ cho mọi use case. Tách nhỏ:

- `DocumentRepository`
- `JobLogRepository`
- `MarkdownStore`
- `SectionIndex`

### 11.5. Dependency Inversion

Use case phụ thuộc vào port, không phụ thuộc vào SDK hoặc vendor code.

## 12. Markdown storage là thành phần bắt buộc

VSF phải coi `MarkdownStore` là first-class component, không phải phần mở rộng tùy chọn.

### 12.1. Vì sao bắt buộc

- cần `markdown_s3_uri` trong search response
- cần artifact ổn định để debug parser output
- cần reprocess từ Markdown
- cần full context đã chuẩn hóa cho AI team

### 12.2. Các mức triển khai

`Option 1 - Optimal`

- bucket hoặc prefix derived artifact do chính team pipeline hoặc RAG sở hữu
- chỉ service của team này được ghi
- hệ thống bên ngoài chỉ được cấp quyền đọc nếu cần

`Option 2 - Acceptable`

- dùng chung bucket nhưng prefix riêng do team này sở hữu
- ngoài team chỉ nên có read-only

`Option 3 - Temporary / Dev`

- local storage hoặc MinIO cho dev và test

### 12.3. Quy tắc vận hành

Core pipeline không được phụ thuộc vào việc đang chạy theo option nào.

Tức là:

- business flow giữ nguyên
- chỉ implementation của `MarkdownStore` thay đổi

## 13. Data schema mới mà VSF cần áp dụng

### 13.1. Document metadata

Bảng `documents` cần có tối thiểu:

- `source_s3_uri`
- `markdown_s3_uri`
- `section_count`
- `parser_version`
- `caption_model`
- `embedding_model`
- `processed_at`

`chunk_count` không còn là field trung tâm của kiến trúc đích.

### 13.2. Qdrant payload

Payload mới cần là section-centric:

```json
{
  "section_id": "uuid",
  "document_id": "uuid",
  "document_name": "string",
  "caption": "string",
  "section_content": "string",
  "heading_path": ["string"],
  "markdown_s3_uri": "string",
  "source_s3_uri": "string",
  "classification": "public | internal | secret | top_secret",
  "allowed_departments": ["HR", "Finance"],
  "allowed_user_ids": ["uuid"],
  "uploaded_by": "uuid",
  "parser_version": "string",
  "caption_model": "string",
  "embedding_model": "string"
}
```

Vector được sinh từ `caption`, không phải từ `section_content`.

## 14. Search flow mới cần được ghi nhận trong VSF

Search flow chuẩn:

1. nhận query
2. embed query
3. search theo caption vectors
4. lấy top section results
5. trả `section_content`, `caption`, `markdown_s3_uri`, `source_s3_uri`

Phía Chat/Agent phải sử dụng response theo thứ tự ưu tiên:

1. đọc `caption` để hiểu nhanh
2. dùng `section_content` làm context chính
3. nếu cần nhiều ngữ cảnh hơn thì fetch `markdown_s3_uri`
4. nếu cần đối chiếu nguồn gốc thì dùng `source_s3_uri`

## 15. Logging và observability bắt buộc

VSF phải đồng bộ với kiến trúc logging mới, vì đây là phần quan trọng để vận hành enterprise.

### 15.1. Lineage bắt buộc

`source_s3_uri -> markdown_s3_uri -> section_id -> caption -> vector -> search result`

### 15.2. Correlation fields tối thiểu

- `job_id`
- `doc_id`
- `section_id`
- `request_id`
- `source_s3_uri`
- `markdown_s3_uri`
- `parser_version`
- `caption_model`
- `embedding_model`

### 15.3. Event tối thiểu

- `ingest.started`
- `parse.completed`
- `markdown.saved`
- `sections.split`
- `captions.generated`
- `embeddings.generated`
- `sections.indexed`
- `search.requested`
- `search.completed`
- `ingest.failed`

Nếu VSF vẫn giữ logging theo mindset chunk-based, debug production sau refactor sẽ thiếu dấu vết đúng.

## 16. Yêu cầu enterprise cho chatbot nội bộ

VSF cần phản ánh đúng các yêu cầu enterprise đã được chốt trong target architecture:

- response phải có căn cứ và truy vết được
- retrieval phải ưu tiên section hoàn chỉnh hơn fragment text
- caller phải có cả bản chuẩn hóa và bản gốc để kiểm tra chéo
- hệ thống phải hỗ trợ access control theo document metadata
- hệ thống phải hỗ trợ audit, logging và reprocess
- thiết kế phải mở rộng được thêm nhiều loại tài liệu và provider mới

Đây không phải yêu cầu phụ. Đây là phần định hình toàn bộ kiến trúc.

## 17. Team boundaries mà VSF cần cập nhật

Boundary giữa RAG và Chat/Agent không còn là:

- chunk content
- score
- page number

Boundary mới phải là:

- `caption`
- `section_content`
- `markdown_s3_uri`
- `source_s3_uri`
- metadata bảo mật liên quan

Điều này cần cập nhật trong [team-ownership.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/team-ownership.md:1).

## 18. Các tài liệu VSF phải sửa để đồng bộ hoàn toàn

### 18.1. Bắt buộc sửa ngay

- [contracts.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/contracts.md:1)
  - đổi `SearchResult` sang section-based
  - bổ sung `MarkdownStore`, `SectionSplitter`, `SectionCaptioner`, `SectionIndex`

- [api-spec.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/api-spec.md:1)
  - đổi response `POST /search`
  - bổ sung `caption`, `section_content`, `markdown_s3_uri`, `source_s3_uri`

- [data-schema.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/data-schema.md:1)
  - đổi schema sang section-centric
  - thay `chunk_count` bằng `section_count` làm field chính
  - bổ sung metadata parser, caption, embedding

- [team-ownership.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/team-ownership.md:1)
  - đổi boundary dữ liệu giữa RAG và Chat/Agent

### 18.2. Nên sửa ngay sau đó

- [architecture.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/architecture.md:1)
  - cập nhật retrieval model, module boundaries, dependency direction

- [roadmap.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/roadmap.md:1)
  - bỏ chunk size hoặc overlap khỏi target architecture
  - thay bằng section split quality, caption quality, retrieval relevance

- [SA_RAG_Chatbot_Final.md](D:/Training/e-commerce events/docs/team-work/DA08-VSF/docs/SA_RAG_Chatbot_Final.md:1)
  - cập nhật solution architecture và end-to-end flow

## 19. Kế hoạch chuyển đổi đề xuất

### Phase 1. Chốt contract mới

- chốt `SectionSearchResult`
- chốt API response mới
- chốt `MarkdownStore`
- chốt Qdrant payload mới

### Phase 2. Chuyển metadata và schema

- thêm `markdown_s3_uri`, `source_s3_uri`, `section_count`
- giảm vai trò của `chunk_count`
- chuẩn hóa metadata parser và model

### Phase 3. Chuyển ingestion model

- parse to Markdown
- save Markdown
- split sections
- caption sections
- embed captions
- index sections

### Phase 4. Chuyển search model

- search theo caption vectors
- trả full section contract mới
- cập nhật Chat/Agent consumption

### Phase 5. Dọn legacy

- đánh dấu chunk retrieval là legacy hoặc migration-only
- loại chunk tuning khỏi docs target
- làm sạch contracts và schema cũ

## 20. Nguyên tắc quyết định cuối cùng

VSF không nên chỉ thêm Markdown lên trên kiến trúc chunk cũ.

VSF phải đồng bộ toàn bộ theo retrieval architecture mới:

- từ `chunk` sang `section`
- từ `embed content` sang `embed caption`
- từ `fragment response` sang `section response`
- từ `single-layer source reference` sang `markdown + raw source references`

Nếu không đổi đồng bộ ở mức:

- product model
- contracts
- API
- schema
- team boundary
- logging lineage

thì VSF sẽ trở thành kiến trúc nửa cũ nửa mới, khó xây dựng, khó mở rộng và khó debug.

## 21. Kiến nghị

Kiến nghị chính thức:

1. Thừa nhận chunk-based retrieval hiện tại trong VSF là legacy design.
2. Chốt `Markdown -> Section -> Caption` là target architecture chung cho VSF và pipeline.
3. Dùng tài liệu này làm chuẩn để cập nhật toàn bộ docs VSF liên quan.
4. Không mở thêm implementation mới trên contract chunk-based, trừ khi phục vụ migration tạm thời.

Khi các tài liệu contracts, API, schema, architecture và ownership đã được cập nhật theo tài liệu này, VSF mới thực sự đồng bộ với toàn bộ kiến trúc mới của pipeline.
