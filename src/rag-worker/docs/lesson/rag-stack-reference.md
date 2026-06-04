# Vector Database, NATS JetStream và WebSocket + FastAPI — Tổng hợp kiến thức chi tiết

Tài liệu tham khảo độc lập, tổng hợp kiến thức cốt lõi của ba mảng: lưu trữ và truy xuất ngữ nghĩa (Vector Database), messaging bền vững (NATS JetStream), và giao tiếp realtime hai chiều (WebSocket + FastAPI). Mỗi phần đứng riêng, đủ chi tiết để tra cứu nhanh khái niệm, cấu hình và bẫy thường gặp.

---

# Phần I — Vector Database

## 1. Bản chất

Vector Database là hệ cơ sở dữ liệu được tối ưu cho việc lưu trữ, lập chỉ mục và truy vấn embedding vector. Embedding là mảng số biểu diễn ý nghĩa ngữ nghĩa của văn bản, hình ảnh, âm thanh, video hoặc một thực thể bất kỳ.

```text
"Cách reset mật khẩu?"        -> [0.12, -0.33, 0.91, ...]
"Quên password thì làm sao?"  -> [0.10, -0.29, 0.88, ...]
```

Hai câu khác từ ngữ nhưng gần nghĩa nên vector của chúng nằm gần nhau trong không gian vector. Đây là nền tảng của semantic search và RAG.

## 2. So với các cách lưu trữ khác

| Nhu cầu | SQL | Elasticsearch/BM25 | Vector DB |
| --- | --- | --- | --- |
| Tìm exact match | Tốt | Tốt | Không phải mục tiêu chính |
| Tìm theo keyword | Kém | Rất tốt | Trung bình nếu không hybrid |
| Tìm theo ngữ nghĩa | Kém | Giới hạn | Rất tốt |
| RAG chatbot | Khó | Thiếu semantic | Rất phù hợp |
| Image similarity | Không phù hợp | Không phù hợp | Rất phù hợp |
| ANN search quy mô lớn | Không native | Có kNN | Là mục tiêu cốt lõi |

## 3. Ba nhóm hay bị nhầm

| Loại | Ví dụ | Bản chất |
| --- | --- | --- |
| Vector Database | Pinecone, Weaviate, Qdrant, Milvus, Chroma, LanceDB | Có storage, index, API, metadata, replication, filtering |
| Vector Index Library | FAISS, Annoy, ScaNN, USearch | Chỉ là thư viện index/search, chưa phải DB hoàn chỉnh |
| Database + Vector Extension | PostgreSQL + pgvector, Elasticsearch kNN, MongoDB Atlas | DB truyền thống có thêm vector search |

## 4. Embedding và dimension

| Loại embedding | Input | Use case |
| --- | --- | --- |
| Text embedding | Câu, đoạn, chunk | RAG, semantic search |
| Image embedding | Ảnh | Image search, duplicate detection |
| Multimodal | Text + image + audio/video | Tìm kiếm đa phương thức |
| Sparse embedding | Term-weight | Hybrid search, keyword-aware |
| Dense embedding | Vector float dày | Similarity search |

`Dimension` là số chiều vector (ví dụ `384`, `768`, `1536`). Dimension lớn hơn không đồng nghĩa tốt hơn; nó ảnh hưởng trực tiếp tới dung lượng và chi phí index:

```text
storage xấp xỉ số_vector × số_chiều × 4 byte (float32)
```

Ví dụ `10M vectors × 1536 dim × float32 ≈ 61.4 GB` dữ liệu thô, chưa tính index, metadata, replication.

## 5. Distance metrics

| Metric | Ý nghĩa | Khi dùng | Lưu ý |
| --- | --- | --- | --- |
| Cosine Similarity | So góc hai vector | Text embedding phổ biến | Thường cần normalize |
| Euclidean / L2 | Khoảng cách hình học | Image, clustering | Nhạy với magnitude |
| Dot / Inner Product | Tích vô hướng | Model train theo dot product | Magnitude ảnh hưởng kết quả |
| Manhattan / L1 | Tổng chênh lệch từng chiều | Bài toán đặc thù | Ít dùng trong RAG |

Quy tắc: dùng metric mà embedding model khuyến nghị, không tự đổi.

## 6. Exact search và ANN

| Loại | Cách làm | Ưu | Nhược |
| --- | --- | --- | --- |
| Exact / brute force | So query với toàn bộ vector | Recall 100% | Chậm khi dữ liệu lớn |
| ANN | Tìm gần đúng qua index | Nhanh hơn nhiều | Recall < 100% |

Tam giác đánh đổi luôn tồn tại trong production:

```text
Recall tăng  -> Latency tăng, Memory tăng
Latency giảm -> Recall có thể giảm
Memory giảm  -> Recall hoặc latency thường xấu đi
```

## 7. Thuật toán index

| Index | Ý tưởng | Ưu | Nhược | Khi dùng |
| --- | --- | --- | --- | --- |
| Flat | Quét toàn bộ | Chính xác nhất | Chậm, tốn CPU | Dataset nhỏ, ground truth |
| IVF | Chia cụm/bucket | Nhanh hơn Flat | Tune `nlist`, `nprobe` | Dataset lớn |
| HNSW | Đồ thị nhiều tầng | Recall/latency rất tốt | Tốn RAM | Mặc định tốt nhiều workload |
| PQ | Nén vector thành mã ngắn | Tiết kiệm RAM/disk | Giảm recall | Dữ liệu rất lớn |
| DiskANN | Giữ index trên SSD | Scale lớn, ít RAM | Phụ thuộc SSD | Hàng trăm triệu đến tỷ vector |
| IVF-PQ | Shortlist + nén | Scale tốt | Giảm recall nếu tune kém | Hệ giới hạn bộ nhớ |

## 8. Khái niệm cốt lõi

| Khái niệm | Giải thích |
| --- | --- |
| Collection | Nhóm vector cùng schema |
| Index | Cấu trúc tăng tốc search (HNSW...) |
| Namespace | Phân vùng logic (mỗi tenant một namespace) |
| Metadata / Payload | Dữ liệu đi kèm vector (`tenant_id`, `doc_id`, `lang`) |
| Pre-filter | Lọc trước khi vector search — tốt khi filter chọn lọc cao |
| Post-filter | Search trước, lọc sau — dễ làm mất kết quả đúng |
| Hybrid search | Kết hợp vector và keyword/BM25 |
| Multi-tenancy | Cô lập dữ liệu nhiều tenant |
| Sharding / Replication | Chia dữ liệu qua node / nhân bản tăng HA |
| Consistency | Strong hoặc eventual |

## 9. So sánh các lựa chọn phổ biến

| Option | Loại | Điểm mạnh | Phù hợp nhất |
| --- | --- | --- | --- |
| Pinecone | Managed | Ít vận hành, scale nhanh | Enterprise RAG |
| Weaviate | OSS + Cloud | Hybrid search tốt, schema rõ | Knowledge base, hybrid RAG |
| Qdrant | OSS + Cloud | Filtering mạnh, payload index | SaaS RAG, metadata-heavy |
| Milvus / Zilliz | OSS distributed | Scale lớn, nhiều loại index | Hệ rất lớn |
| Chroma | OSS + Cloud | Dễ dùng, hợp prototype | MVP, local RAG |
| LanceDB | Embedded / Cloud | Hợp multimodal, lakehouse | Image, multimodal |
| pgvector | PostgreSQL extension | Tận dụng Postgres, ACID, JOIN | App đã dùng Postgres |
| Elasticsearch kNN | Search engine | Keyword search mạnh | Search product, catalog |
| Redis Vector Search | In-memory | Latency thấp | Realtime matching |
| FAISS | Library | Cực mạnh local/research | Custom engine, benchmark |

## 10. Workflow RAG đầy đủ

```text
Documents -> Chunking -> Embedding -> Upsert Vector DB
User Query -> Query Embedding -> Similarity Search Top-K
          -> Metadata Filter -> Reranking -> LLM Prompt -> Answer
```

Ví dụ pipeline tối thiểu (sinh embedding):

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
texts = ["Vector database dùng cho semantic search.",
         "PostgreSQL có extension pgvector."]
vectors = model.encode(texts, normalize_embeddings=True).tolist()
```

Ví dụ truy vấn có filter (Qdrant):

```python
hits = client.search(
    collection_name="docs",
    query_vector=query_vec,
    query_filter=Filter(must=[
        FieldCondition(key="tenant_id", match=MatchValue(value="acme"))
    ]),
    limit=3,
)
```

Ví dụ pgvector (SQL):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384)
);
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

SELECT id, content, 1 - (embedding <=> :q) AS similarity
FROM documents
WHERE tenant_id = :tenant
ORDER BY embedding <=> :q
LIMIT 5;
```

## 11. Lỗi kinh điển

- **Dùng hai embedding model khác nhau** cho index và query → vector ở hai không gian, retrieval sai.
- **Sai dimension** giữa collection và model → insert/query thất bại.
- **Không normalize** khi metric yêu cầu (cosine).
- **Chunk quá lớn/nhỏ** → điểm bắt đầu hợp lý `300-800 tokens`, overlap `50-150`.
- **Quên tenant filter** trong multi-tenant → lộ dữ liệu (rất nguy hiểm).
- **Sai logic filter AND/OR** — phải theo đúng DSL từng hệ.
- **Dùng exact search (FLAT) cho dữ liệu rất lớn** thay vì HNSW.
- **Không đo recall** — cần `recall@k`, `MRR`, `nDCG`, `p95/p99 latency`, `empty result rate`, `tenant leakage test`.
- **Duplicate vector** do sinh ID mới mỗi lần upsert → top-k lặp đoạn giống nhau.
- **Embedding drift** — đổi model mà không reindex; nên lưu metadata model/version.
- **Post-filter gây mất kết quả** — nên lọc trong engine.
- **Không tạo payload/scalar index** cho field hay filter (`tenant_id`, `lang`).

## 12. Nguyên tắc production

1. Version hóa embedding model, lưu `embedding_model`, `dimension`, `metric`, `created_at`.
2. Không search multi-tenant nếu thiếu tenant filter/namespace.
3. Benchmark trên dữ liệu thật, không chỉ synthetic.
4. Theo dõi recall song song với latency.
5. Thiết kế reindex pipeline ngay từ đầu.
6. Batch ingest thay vì insert từng vector.
7. Tạo metadata/payload index cho field hay filter.
8. Không chọn DB chỉ vì benchmark công khai đẹp.
9. Có abstraction layer giảm phụ thuộc SDK vendor.
10. Tính tổng chi phí sở hữu: RAM, disk, replica, backup, rebuild.

---

# Phần II — NATS JetStream

## 1. NATS Core và giới hạn

NATS là messaging system hiệu năng cao, latency thấp, xây quanh pub/sub theo subject. Subject là chuỗi phân cấp ngăn bằng dấu chấm:

```text
orders.us.created      # subject cụ thể
orders.*.created       # * khớp đúng một token
orders.>               # > khớp toàn bộ đuôi còn lại
```

NATS Core là pub/sub "fire-and-forget": cực nhanh, nhưng nếu không có subscriber online tại thời điểm publish thì message biến mất — không lưu trữ, không replay, không đảm bảo delivery. Tốt cho metric/telemetry ephemeral, không đủ cho order/payment/event nghiệp vụ.

## 2. JetStream giải quyết gì

JetStream là lớp persistence và streaming tích hợp sẵn trong NATS server, bổ sung:

- Lưu trữ message bền vững (file hoặc memory).
- Replay theo thời gian hoặc sequence.
- At-least-once và exactly-once delivery.
- Acknowledgement và redelivery khi xử lý thất bại.
- Giới hạn lưu trữ theo dung lượng, số lượng hoặc thời gian.

## 3. So sánh NATS Core / JetStream / Kafka

| Tiêu chí | NATS Core | JetStream | Kafka |
| --- | --- | --- | --- |
| Lưu trữ | Không | Có | Có |
| Replay | Không | Có | Có |
| Delivery | At-most-once | At-least / exactly-once | At-least / exactly-once |
| Độ trễ | Cực thấp | Thấp | Trung bình |
| Vận hành | Rất nhẹ | Nhẹ | Nặng hơn |
| Mô hình | Subject pub/sub | Stream + Consumer | Topic + Partition |
| Phù hợp | Tín hiệu ephemeral | Event nghiệp vụ vừa/nhỏ | Pipeline dữ liệu lớn |

## 4. Stream

Stream là nơi lưu trữ bền vững message từ một hoặc nhiều subject. Một stream định nghĩa: danh sách `subjects`, `storage` (file/memory), `retention` policy, và giới hạn `max_bytes` / `max_msgs` / `max_age`.

```python
from nats.js.api import StreamConfig, RetentionPolicy, StorageType

await js.add_stream(StreamConfig(
    name="ORDERS",
    subjects=["orders.>"],
    storage=StorageType.FILE,
    retention=RetentionPolicy.LIMITS,
    max_msgs=1_000_000,
    max_age=7 * 24 * 3600,
))
```

## 5. Consumer

Consumer là "view" có trạng thái để đọc stream. Nhiều consumer đọc cùng stream độc lập với offset riêng.

| Kiểu | Ý nghĩa |
| --- | --- |
| Push consumer | Server chủ động đẩy message tới subscriber |
| Pull consumer | Client chủ động fetch message theo batch (khuyến nghị) |

Pull consumer được khuyến nghị cho phần lớn backend vì kiểm soát flow control và dễ scale nhiều worker.

```python
sub = await js.pull_subscribe("orders.us.>", durable="order-workers")
while True:
    msgs = await sub.fetch(batch=10, timeout=5)
    for msg in msgs:
        try:
            handle(msg.data)
            await msg.ack()
        except Exception:
            await msg.nak()
```

## 6. Acknowledgement và redelivery

| Loại ack | Ý nghĩa |
| --- | --- |
| `Ack` | Xử lý thành công, không gửi lại |
| `Nak` | Thất bại, yêu cầu gửi lại |
| `Term` | Bỏ hẳn message, không gửi lại |
| `InProgress` | Đang xử lý, reset timer redelivery |

Nếu không ack trong `AckWait`, JetStream redeliver. Vượt `max_deliver` mà chưa ack → phát advisory `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.<stream>.<consumer>` (dùng làm DLQ).

## 7. Delivery semantics

```text
At-most-once   = gửi tối đa một lần, có thể mất (NATS Core)
At-least-once  = không mất, có thể trùng (cần idempotent)
Exactly-once   = không mất, không trùng (dedup theo Msg-Id)
```

Exactly-once phía publish: gán header `Nats-Msg-Id`, server bỏ qua bản trùng trong cửa sổ dedup. Phía consume cần idempotent (ví dụ upsert theo `order_id`).

```python
ack = await js.publish(
    "orders.us.created",
    b'{"order_id": "A1", "amount": 100}',
    headers={"Nats-Msg-Id": "order-A1"},
)
print(ack.stream, ack.seq)
```

## 8. Retention policy

| Policy | Hành vi |
| --- | --- |
| `Limits` | Giữ tới khi chạm bytes/messages/age |
| `WorkQueue` | Mỗi message bị xóa sau khi một consumer ack |
| `Interest` | Giữ khi còn ít nhất một consumer quan tâm |

`WorkQueue` hợp job queue (mỗi việc một worker). Cần fan-out nhiều service thì dùng `Limits` hoặc `Interest`, không dùng `WorkQueue`.

## 9. Pattern quan trọng

- **Work queue**: retention `WorkQueue`, nhiều worker pull cùng durable consumer chia job.
- **Fan-out**: nhiều durable consumer độc lập, mỗi service một consumer, offset riêng.
- **Replay**: `DeliverPolicy` (`ALL`, `LAST`, `NEW`, `BY_START_SEQUENCE`, `BY_START_TIME`) để rebuild state.
- **Exactly-once**: dedup `Nats-Msg-Id` + consumer idempotent.
- **Dead Letter**: subscribe advisory `MAX_DELIVERIES`, chuyển message "độc" sang stream DLQ.

```python
from nats.js.api import DeliverPolicy
ConsumerConfig(
    deliver_policy=DeliverPolicy.BY_START_TIME,
    opt_start_time="2026-06-01T00:00:00Z",
)
```

## 10. Lỗi kinh điển

- **Nhầm `nc.publish()` với `js.publish()`** → message không vào stream, không persistence.
- **Quên ack** → redeliver liên tục sau mỗi `AckWait`.
- **Ack quá sớm** trước khi commit DB rồi chết → mất logic. Luôn ack sau side-effect.
- **Consumer không idempotent** với at-least-once → bản ghi nhân đôi.
- **AckWait quá ngắn** → redeliver khi worker còn chạy; dùng `InProgress` cho job dài.
- **Không giới hạn stream** (`max_bytes`/`max_age`) → phình đầy đĩa.
- **Ephemeral consumer cho việc cần bền vững** → mất offset khi ngắt kết nối.
- **Bỏ qua PubAck** → không biết message đã lưu hay chưa.
- **Hiểu sai WorkQueue** → chỉ một consumer tiêu thụ.
- **Không cấu hình replica** → mất dữ liệu khi node chết; cần `num_replicas=3`.
- **Subject overlap** giữa nhiều stream → nhập nhằng.
- **Không theo dõi consumer lag** (pending) → tụt xa không ai biết.

## 11. Cấu hình cluster production

```conf
# nats-server.conf
server_name: node-1
port: 4222
jetstream {
  store_dir: /data/jetstream
  max_memory_store: 1G
  max_file_store: 50G
}
cluster {
  name: prod-cluster
  port: 6222
  routes: [ nats://node-2:6222, nats://node-3:6222 ]
}
```

```python
await js.add_stream(StreamConfig(
    name="ORDERS",
    subjects=["orders.>"],
    storage=StorageType.FILE,
    num_replicas=3,
    max_bytes=20 * 1024**3,
    max_age=14 * 24 * 3600,
))
```

Checklist: `num_replicas=3` cho stream quan trọng, durable consumer cho luồng cần resume, `max_bytes`/`max_age` cho mọi stream, `store_dir` trên đĩa bền, monitoring pending/redelivery/ack rate/disk/RAFT health, backup/snapshot, alert khi lag vượt ngưỡng.

---

# Phần III — WebSocket + FastAPI

## 1. Bản chất

WebSocket là giao thức giao tiếp hai chiều, persistent, full-duplex giữa client và server. Bắt đầu bằng HTTP request thông thường rồi nâng cấp sang WebSocket qua handshake.

```text
HTTP REST:   Client request -> Server response -> Kết thúc
WebSocket:   Client mở connection -> Server accept -> Hai bên gửi message liên tục
```

Sinh ra để server chủ động đẩy dữ liệu xuống client ngay khi có sự kiện (chat, dashboard, notification, collaborative editing, live price, monitoring), tránh polling lãng phí.

## 2. So sánh REST / WebSocket / SSE / Long Polling

| Tiêu chí | REST | WebSocket | SSE | Long Polling |
| --- | --- | --- | --- | --- |
| Kiểu kết nối | Request/response | Persistent | Persistent | Request giữ lâu |
| Chiều | Client → Server | Hai chiều | Server → Client | Gần real-time |
| Server push | Không tự nhiên | Rất tốt | Rất tốt | Giả lập |
| Chat | Không tối ưu | Rất phù hợp | Chỉ nhận tốt | Tạm được |
| Collaborative editing | Không phù hợp | Rất phù hợp | Không đủ | Không phù hợp |
| Scale ngang | Dễ hơn | Khó hơn | Trung bình | Trung bình |

Quy tắc: REST cho CRUD, SSE cho stream một chiều, WebSocket cho tương tác hai chiều realtime, Long Polling khi môi trường không hỗ trợ WS/SSE.

## 3. WebSocket trong FastAPI

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(f"Echo: {message}")
    except WebSocketDisconnect:
        print("Client disconnected")
```

Tầng kiến trúc: `FastAPI → Starlette → ASGI → Uvicorn/Hypercorn → TCP socket`.

## 4. Lifecycle của một connection

1. Client gửi HTTP request với `Upgrade: websocket`.
2. Server kiểm tra route, auth, origin, protocol.
3. Server `accept()`.
4. Connection mở, hai bên gửi/nhận message.
5. Một bên đóng hoặc gặp lỗi mạng.
6. Server cleanup connection khỏi memory.

Handshake: client gửi `Upgrade: websocket` + `Sec-WebSocket-Key`, server trả `101 Switching Protocols`.

Hình dung như cuộc gọi điện: `open = nhấc máy`, `message = nói chuyện`, `close = cúp máy`, `error = mất sóng`.

## 5. Các khái niệm cốt lõi

- **Text vs binary message**: text hợp JSON/chat/command; binary hợp audio chunk, protobuf, image, file stream.
- **Ping/Pong heartbeat**: phát hiện connection chết ngầm do mất mạng, browser sleep, mobile nền, proxy cắt, NAT timeout. Nên có timeout policy: quá lâu không nhận `pong` thì đóng connection.
- **Connection state management**: cần để broadcast, gửi unicast, remove dead connection, kiểm soát memory leak, theo dõi online/offline.
- **Broadcast / unicast / room**: broadcast (tất cả), unicast (một user), room/channel (một nhóm).
- **Authentication**: WebSocket không có vòng request/response riêng cho mỗi message, auth phải thiết kế rõ lúc mở connection hoặc trong protocol message.
- **Concurrency**: handler giữ connection lâu nên phải async đúng cách — không dùng `time.sleep()` mà dùng `asyncio.sleep()`.

```python
async def heartbeat(websocket: WebSocket):
    while True:
        await asyncio.sleep(30)
        await websocket.send_json({"type": "ping"})
```

## 6. Các cách authentication

| Cách | Ưu | Nhược |
| --- | --- | --- |
| Cookie session | Tốt với web cùng domain | Cần kiểm soát CSRF và origin |
| Query param token | Dễ dùng | Có thể lộ trong log |
| Authorization header | Chuẩn về API | Browser WS API không cho set custom header |
| First-message auth | Linh hoạt | Connection mở trước khi auth xong |
| Subprotocol | Mạnh cho use case nâng cao | Ít phổ biến |

## 7. Pattern quan trọng

- **Connection Manager**: giữ `set` các socket đang mở, phục vụ broadcast và cleanup.
- **Room / Channel**: nhóm client theo ngữ cảnh bằng `defaultdict(set)`.
- **Redis Pub/Sub cho multi-worker**: nhiều worker không thấy connection của nhau; cần external pub/sub để sync.
- **Heartbeat** với timeout policy rõ ràng.
- **Snapshot + delta sau reconnect**: WebSocket là stream, không tự replay; client gửi `last_seen_event_id`, server gửi snapshot rồi mới stream delta tiếp.

```python
class ConnectionManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
```

## 8. Lỗi thực chiến

- **Thiếu cleanup trong `finally`** → memory tăng, online count sai, broadcast vào dead socket.
- **Không bắt `WebSocketDisconnect`** → handler văng lỗi, không dọn state.
- **Blocking I/O trong async handler** (`requests`, `time.sleep`) → chặn event loop, lag toàn bộ client. Dùng `httpx`/`asyncio.sleep`.
- **Không có heartbeat** → giữ connection chết ngầm sau proxy/mobile.
- **Auth thiếu/sai** — không giả định middleware REST đủ bảo vệ luồng WebSocket.
- **Log token trong query string** → lộ JWT trong access log, APM, browser history.
- **Multi-worker không sync state** — `set()` chỉ đúng một process; cần Redis/NATS/Kafka.
- **Không giới hạn message size** → spike RAM (`MAX_SIZE = 64 * 1024`).
- **Không validate message format** — nên dùng Pydantic.
- **Thiếu reconnect ở client** — mất realtime sau deploy/restart.
- **Race condition broadcast/disconnect** — iterate `list(connections)`, không iterate trực tiếp.
- **Nginx thiếu header Upgrade/timeout** → handshake fail hoặc drop connection.
- **Không handle backpressure** — server gửi nhanh hơn client nhận, queue phình.
- **Không resync state sau reconnect** — dashboard sai số liệu.

## 9. Kiến trúc production: FastAPI + Redis + Nginx

```text
Browser --wss--> Nginx --proxy_pass--> Gunicorn/Uvicorn workers
                                       Worker 1 / 2 / 3
                                            |
                                       Redis Pub/Sub (sync giữa worker)
```

Dockerfile (Gunicorn + Uvicorn worker):

```dockerfile
CMD ["gunicorn", "app.main:app",
     "-k", "uvicorn.workers.UvicornWorker",
     "--bind", "0.0.0.0:8000",
     "--workers", "4",
     "--timeout", "120"]
```

Nginx essentials (vì sao quan trọng):

```nginx
location /ws/ {
    proxy_pass http://fastapi_app;
    proxy_http_version 1.1;                       # WebSocket upgrade cần HTTP/1.1
    proxy_set_header Upgrade $http_upgrade;        # forward yêu cầu upgrade
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;                      # tránh cắt connection sớm
    proxy_buffering off;                           # stream realtime trực tiếp
}
```

## 10. Checklist production

**Ứng dụng**: bắt `WebSocketDisconnect`, cleanup trong `finally`, auth riêng, origin check, validate Pydantic, giới hạn message size, rate limit theo connection/user, heartbeat, reconnect client-side, snapshot/resync sau reconnect, không blocking I/O, không in-memory broadcast khi multi-worker.

**Hạ tầng**: Nginx `proxy_http_version 1.1` + `Upgrade`/`Connection`, timeout đủ dài, `wss://` ở production, Redis/NATS/Kafka nếu multi-worker, health check, graceful shutdown, metrics (active connections, messages/sec, disconnect reason, send latency), không log token/query nhạy cảm.

---

# Phụ lục — Bảng đối chiếu nhanh ba mảng

| Tiêu chí | Vector Database | NATS JetStream | WebSocket + FastAPI |
| --- | --- | --- | --- |
| Bài toán | Lưu trữ & tìm kiếm ngữ nghĩa | Messaging bền vững | Giao tiếp realtime hai chiều |
| Mô hình | Collection + ANN Index | Stream + Consumer | Connection + Message frame |
| Đơn vị | Vector + metadata | Message theo subject | Text/binary frame |
| Đảm bảo | Recall (gần đúng) | At-least / exactly-once | Order trong một connection |
| Trạng thái | Bền vững (index) | Bền vững (stream) | Tạm thời (connection sống) |
| Scale ngang | Sharding, replica, HNSW/IVF | Cluster RAFT, num_replicas=3 | Multi-worker + Redis/NATS pub/sub |
| "Anh em họ" dễ nhầm | FAISS (library), pgvector (extension) | NATS Core (ephemeral), Kafka | SSE (một chiều), Long Polling |
| Lỗi nguy hiểm nhất | Quên tenant filter, sai dimension | Quên/ack sớm, không idempotent | Thiếu cleanup, không heartbeat, blocking I/O |
| Mấu chốt khi scale | Replica + reindex pipeline | Cluster + durable consumer | Sync state qua pub/sub ngoài |
