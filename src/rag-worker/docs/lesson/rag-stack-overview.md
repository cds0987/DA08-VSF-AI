# Tổng hợp 3 trụ cột của RAG Service: Vector Database, NATS JetStream, WebSocket + FastAPI

Tài liệu này tổng hợp ba bài giảng nền tảng của `rag-service` và ghép chúng thành một bức tranh kiến trúc thống nhất. Mục tiêu là trả lời câu hỏi: ba công nghệ này khác nhau ở đâu, giải quyết tầng nào trong hệ thống, và phối hợp với nhau ra sao để dựng một RAG chatbot realtime ở mức production.

Ba tài liệu chi tiết tương ứng:

- [Vector Database](vectordatabase.md) — lưu trữ và truy xuất theo ngữ nghĩa.
- [NATS JetStream](nats-jetstream.md) — messaging bền vững giữa các service.
- [WebSocket + FastAPI](websocket-fastapi.md) — kênh realtime hai chiều tới client.

## 1. Bức tranh tổng: mỗi công nghệ giải quyết một tầng

Một câu hỏi của người dùng đi xuyên qua cả ba tầng:

```text
                    Client (browser / app)
                          │  ▲
        WebSocket (hai chiều, realtime)  │  │  đẩy token/answer về
                          ▼  │
                  ┌─────────────────┐
                  │   FastAPI app   │  (API + WebSocket endpoint)
                  └─────────────────┘
                     │            ▲
   publish job/event │            │ stream kết quả, tiến độ
       (JetStream)   ▼            │
                  ┌─────────────────┐
                  │  Worker / RAG   │
                  │   pipeline      │
                  └─────────────────┘
                          │  ▲
     query embedding      │  │  top-k chunks + metadata
   (similarity search)    ▼  │
                  ┌─────────────────┐
                  │ Vector Database │  (embedding store + ANN index)
                  └─────────────────┘
```

| Tầng | Công nghệ | Trách nhiệm chính | Nếu thiếu nó |
| --- | --- | --- | --- |
| Lưu trữ & truy xuất | Vector Database | Lưu embedding, tìm top-k theo ngữ nghĩa, filter metadata | Không có "trí nhớ" ngữ nghĩa, RAG không có context |
| Messaging & điều phối | NATS JetStream | Truyền job/event bền vững giữa các service, replay, work queue | Service gọi nhau trực tiếp, mất việc khi worker chết |
| Giao tiếp realtime | WebSocket + FastAPI | Đẩy token/tiến độ về client ngay lập tức, hai chiều | Client phải polling, latency cao, không stream được |

Điểm cốt lõi cần nhớ: **ba công nghệ này không thay thế nhau, chúng nằm ở ba tầng khác nhau.** Vector DB là nơi *biết*, JetStream là cách *truyền*, WebSocket là cách *nói* với người dùng.

## 2. Bản chất từng công nghệ trong một đoạn

### 2.1. Vector Database

Hệ cơ sở dữ liệu tối ưu cho việc lưu, index và truy vấn embedding vector. Thay vì tìm exact match như SQL, nó tìm theo *độ gần ngữ nghĩa* trong không gian vector.

```text
"Cách reset mật khẩu?"     -> [0.12, -0.33, 0.91, ...]
"Quên password thì làm sao?" -> [0.10, -0.29, 0.88, ...]
```

Hai câu khác từ ngữ nhưng gần nghĩa nên vector nằm gần nhau. Đây là nền tảng của semantic search và RAG.

### 2.2. NATS JetStream

Lớp persistence và streaming tích hợp trong NATS server. NATS Core là pub/sub fire-and-forget (cực nhanh nhưng mất message nếu không ai nghe); JetStream bổ sung lưu trữ bền vững, replay, acknowledgement và delivery guarantee.

```text
Producer -> js.publish("rag.jobs.>") -> Stream lưu bền vững -> Worker pull + ack
```

### 2.3. WebSocket + FastAPI

Giao thức hai chiều, persistent, full-duplex giữa client và server. Khác REST request/response, WebSocket giữ một kết nối mở để server đẩy dữ liệu xuống ngay khi có (ví dụ stream từng token của câu trả lời LLM).

```text
Client mở connection -> Server accept -> Hai bên gửi message qua lại liên tục
```

## 3. Ranh giới dễ nhầm: chọn đúng tầng

Mỗi công nghệ đều có một "anh em họ" hay bị nhầm. Nắm đúng ranh giới này là phần khó nhất khi đi dạy.

| Nhầm lẫn phổ biến | Phân biệt đúng |
| --- | --- |
| Vector DB vs Vector Index Library (FAISS) | FAISS chỉ là thư viện index/search; Vector DB có storage, API, metadata, replication, filtering |
| Vector DB vs Database + extension (pgvector) | Extension tận dụng DB sẵn có nhưng đụng giới hạn khi scale ANN lớn |
| NATS Core vs JetStream | Core là at-most-once ephemeral; JetStream mới có persistence và delivery guarantee |
| JetStream vs Kafka | JetStream nhẹ, hợp event vừa và nhỏ; Kafka nặng hơn, hợp pipeline dữ liệu rất lớn |
| WebSocket vs SSE vs Long Polling | SSE chỉ một chiều server→client; WebSocket hai chiều; Long Polling là giả lập khi không hỗ trợ WS |

## 4. Cách ba tầng phối hợp trong một luồng RAG realtime

Luồng end-to-end của một câu hỏi chatbot stream:

```text
1. Client mở WebSocket tới FastAPI, gửi câu hỏi.
2. FastAPI embed câu hỏi, hoặc publish job "rag.query" vào JetStream.
3. Worker pull job từ JetStream (durable consumer, at-least-once).
4. Worker tạo query embedding -> similarity search top-k trong Vector DB
   (kèm tenant filter để cô lập dữ liệu).
5. Worker ghép context + prompt -> gọi LLM -> stream từng token.
6. Mỗi token được publish/đẩy ngược về FastAPI.
7. FastAPI đẩy token qua WebSocket xuống client ngay lập tức.
8. Worker ack message khi xử lý xong (không ack sớm).
```

Vai trò từng tầng trong luồng này:

- **Vector DB** quyết định *chất lượng câu trả lời* (recall, đúng context, đúng tenant).
- **JetStream** quyết định *độ bền và khả năng scale* (job không mất, nhiều worker chia tải, replay được khi lỗi).
- **WebSocket** quyết định *trải nghiệm* (token hiện dần, latency thấp, hai chiều).

### Pipeline ingest (offline, song song với luồng truy vấn)

```text
Documents -> Chunking -> Embedding -> Upsert Vector DB
                                  │
                                  └─ publish "rag.ingested" vào JetStream
                                     để service khác (analytics, audit) cùng biết
```

## 5. Bảng so sánh nhanh ba tầng

| Tiêu chí | Vector Database | NATS JetStream | WebSocket + FastAPI |
| --- | --- | --- | --- |
| Loại bài toán | Lưu trữ & tìm kiếm ngữ nghĩa | Messaging bền vững | Giao tiếp realtime |
| Mô hình | Collection + Index (ANN) | Stream + Consumer | Connection + Message |
| Đơn vị dữ liệu | Vector + metadata | Message theo subject | Text/binary frame |
| Đảm bảo | Recall (gần đúng) | At-least / exactly-once | Order trong một connection |
| Trạng thái | Bền vững (index) | Bền vững (stream) | Tạm thời (connection sống) |
| Khi scale | Sharding, replica, HNSW/IVF | Cluster RAFT, num_replicas=3 | Multi-worker + Redis/NATS pub/sub |
| Lỗi kinh điển | Quên tenant filter, sai dimension | Quên ack, consumer không idempotent | Thiếu cleanup, không heartbeat |

## 6. Lỗi production xuyên suốt cả ba tầng

Gom các lỗi nguy hiểm nhất từ ba bài để nhớ nhanh:

### Vector Database
- Quên `tenant filter` trong hệ multi-tenant → lộ dữ liệu chéo tenant.
- Sai `dimension` hoặc dùng hai embedding model khác nhau cho index và query.
- Không normalize vector khi metric yêu cầu.
- Không đo recall, chỉ nhìn latency.

### NATS JetStream
- Dùng `nc.publish()` thay vì `js.publish()` → message không vào stream.
- Ack quá sớm (trước khi commit) hoặc quên ack → mất dữ liệu hoặc redeliver vô hạn.
- Consumer không idempotent với at-least-once → bản ghi nhân đôi.
- Stream không đặt `max_bytes`/`max_age`, không có `num_replicas` cho HA.

### WebSocket + FastAPI
- Thiếu cleanup trong `finally` → memory leak, dead socket.
- Không bắt `WebSocketDisconnect`, không có heartbeat → giữ connection chết.
- Blocking I/O trong async handler → chặn event loop, lag toàn bộ client.
- Multi-worker dùng `set()` in-memory để broadcast → không sync state giữa worker.

> Một sợi chỉ đỏ nối ba tầng: **state phải được đồng bộ đúng khi scale ngang.** Vector DB cần replica, JetStream cần cluster RAFT, WebSocket cần pub/sub bên ngoài (Redis hoặc chính NATS). In-memory state chỉ đúng khi chạy một process.

## 7. Khi nào cần đủ cả ba, khi nào chưa

| Tình huống | Vector DB | JetStream | WebSocket |
| --- | --- | --- | --- |
| RAG chatbot trả lời streaming, multi-tenant, production | Cần | Nên có | Cần |
| Semantic search trả về một lần (request/response) | Cần | Không bắt buộc | Không cần (REST đủ) |
| Pipeline ingest tài liệu lớn, nhiều worker | Cần | Cần | Không cần |
| Demo/MVP một process, ít tài liệu | Chroma/pgvector | Bỏ qua | Tùy, REST có thể đủ |
| Live dashboard tiến độ ingest cho nhiều người | Tùy | Cần (event) | Cần (push) |

Nguyên tắc: **đừng thêm tầng vì "nghe hiện đại hơn".** Thêm JetStream khi job không được phép mất hoặc cần nhiều worker; thêm WebSocket khi thực sự cần push hai chiều realtime; còn Vector DB là bắt buộc cho bất kỳ RAG nào.
 → Vector DB truy xuất context → WebSocket đẩy answer về.

## 8. Kết luận

Ba công nghệ này tạo thành ba tầng tách bạch của một RAG service production:

- **Vector Database** là nơi hệ thống *biết* — lưu và tìm tri thức theo ngữ nghĩa.
- **NATS JetStream** là cách hệ thống *truyền* — chuyển công việc và sự kiện một cách bền vững, không mất, scale được.
- **WebSocket + FastAPI** là cách hệ thống *nói* với người dùng — đẩy kết quả realtime, hai chiều.