# Hướng dẫn học NATS JetStream từ nền tảng đến production

Tài liệu này được viết theo hướng "nền tảng trước, production sau": hiểu NATS core, nắm vì sao cần JetStream, biết các khái niệm stream/consumer, các pattern triển khai, tránh lỗi thực chiến và có một bộ cấu hình hoàn chỉnh để chạy persistent messaging.

## 1. NATS là gì?

### 1.1. Bản chất

NATS là một messaging system hiệu năng cao, độ trễ thấp, xây quanh mô hình publish/subscribe theo subject.

Khác với gọi API trực tiếp giữa các service:

```text
Gọi trực tiếp (HTTP/gRPC):
Service A gọi thẳng Service B -> A phải biết địa chỉ B -> B chết thì A lỗi

NATS:
Service A publish vào subject -> NATS định tuyến -> Bất kỳ subscriber nào cũng nhận
```

NATS tách rời (decouple) bên gửi và bên nhận: producer chỉ cần biết subject, không cần biết ai đang lắng nghe hay có bao nhiêu consumer.

### 1.2. Subject và wildcard

Subject là chuỗi phân cấp ngăn cách bằng dấu chấm, ví dụ `orders.us.created`.

```text
orders.us.created      # subject cụ thể
orders.*.created       # * khớp đúng một token
orders.>               # > khớp tất cả token còn lại
```

- `*` khớp đúng một token tại vị trí đó.
- `>` khớp toàn bộ phần đuôi còn lại, chỉ dùng ở cuối.

### 1.3. NATS Core và giới hạn của nó

NATS Core là pub/sub thuần "fire-and-forget":

- Cực nhanh, latency thấp.
- Nếu không có subscriber nào đang online tại thời điểm publish, message biến mất.
- Không lưu trữ, không replay, không đảm bảo delivery.

Điều này tốt cho metric, telemetry hoặc tín hiệu ephemeral, nhưng không đủ cho dữ liệu không được phép mất như order, payment hoặc event nghiệp vụ.

## 2. Vì sao JetStream tồn tại?

### 2.1. Vấn đề JetStream giải quyết

JetStream là lớp persistence và streaming được tích hợp sẵn trong NATS server, bổ sung những thứ NATS Core thiếu:

- Lưu trữ message bền vững (file hoặc memory).
- Replay lại message theo thời gian hoặc theo sequence.
- At-least-once và exactly-once delivery.
- Acknowledgement và redelivery khi consumer xử lý thất bại.
- Giới hạn lưu trữ theo dung lượng, số lượng hoặc thời gian.

### 2.2. So sánh NATS Core, JetStream và Kafka

| Tiêu chí | NATS Core | JetStream | Kafka |
| --- | --- | --- | --- |
| Lưu trữ | Không | Có | Có |
| Replay | Không | Có | Có |
| Delivery guarantee | At-most-once | At-least-once / exactly-once | At-least-once / exactly-once |
| Độ trễ | Cực thấp | Thấp | Trung bình |
| Vận hành | Rất nhẹ | Nhẹ | Nặng hơn |
| Mô hình | Subject pub/sub | Stream + Consumer | Topic + Partition |
| Phù hợp | Tín hiệu ephemeral | Event nghiệp vụ vừa và nhỏ | Pipeline dữ liệu lớn |

Quy tắc thực tế:

- Dùng NATS Core khi mất message không sao và cần latency tối thiểu.
- Dùng JetStream khi cần persistence và replay nhưng muốn vận hành nhẹ.
- Cân nhắc Kafka khi cần throughput cực lớn với hệ sinh thái stream processing trưởng thành.

## 3. Các khái niệm cốt lõi của JetStream

### 3.1. Stream

Stream là nơi lưu trữ bền vững các message được publish vào một hoặc nhiều subject.

```text
Subject: orders.>
        |
        v
   +-----------+
   |  Stream   |  ORDERS  (lưu message theo thứ tự, có sequence number)
   +-----------+
```

Một stream định nghĩa:

- Danh sách subject mà nó "bắt" (subjects).
- Storage là file hay memory.
- Retention policy: giữ message bao lâu hoặc bao nhiêu.
- Giới hạn: max bytes, max messages, max age.

### 3.2. Consumer

Consumer là "view" có trạng thái để đọc message từ stream. Nhiều consumer có thể đọc cùng một stream độc lập với nhau.

Hai kiểu chính:

| Kiểu | Ý nghĩa |
| --- | --- |
| Push consumer | Server chủ động đẩy message tới subscriber |
| Pull consumer | Client chủ động kéo (fetch) message theo batch |

Pull consumer được khuyến nghị cho phần lớn use case backend vì kiểm soát được flow control và dễ scale ngang nhiều worker.

### 3.3. Acknowledgement

Mỗi message cần được ack để JetStream biết đã xử lý xong.

| Loại ack | Ý nghĩa |
| --- | --- |
| `Ack` | Xử lý thành công, không gửi lại |
| `Nak` | Xử lý thất bại, yêu cầu gửi lại |
| `Term` | Bỏ hẳn message, không gửi lại |
| `InProgress` | Đang xử lý, reset timer redelivery |

Nếu consumer không ack trong khoảng `AckWait`, JetStream sẽ redeliver message đó.

### 3.4. Delivery semantics

```text
At-most-once   = gửi tối đa một lần, có thể mất (NATS Core)
At-least-once  = không mất, nhưng có thể trùng (cần idempotent)
Exactly-once   = không mất, không trùng (dùng dedup theo Msg-Id)
```

JetStream hỗ trợ exactly-once phía publish bằng message deduplication: gán header `Nats-Msg-Id`, server bỏ qua bản trùng trong cửa sổ dedup.

### 3.5. Retention policy

| Policy | Hành vi |
| --- | --- |
| `Limits` | Giữ message tới khi chạm giới hạn bytes/messages/age |
| `WorkQueue` | Mỗi message bị xóa sau khi được một consumer ack |
| `Interest` | Giữ message khi còn ít nhất một consumer quan tâm |

`WorkQueue` rất hợp cho job queue: mỗi việc chỉ một worker xử lý rồi message biến mất.

### 3.6. Subject mapping giữa stream và consumer

Một stream bắt nhiều subject, còn consumer có thể lọc tiếp bằng `FilterSubject`:

```text
Stream ORDERS  bắt:  orders.>
Consumer A     lọc:  orders.us.>
Consumer B     lọc:  orders.eu.>
```

Nhờ đó nhiều consumer chia nhau xử lý các phần khác nhau của cùng một stream.

## 4. JetStream trong code (Python - nats-py)

### 4.1. Kết nối và lấy JetStream context

```python
import asyncio
import nats

async def main():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    # ... dùng js ở đây
    await nc.drain()

asyncio.run(main())
```

### 4.2. Tạo stream

```python
from nats.js.api import StreamConfig, RetentionPolicy, StorageType

await js.add_stream(
    StreamConfig(
        name="ORDERS",
        subjects=["orders.>"],
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        max_msgs=1_000_000,
        max_age=7 * 24 * 3600,  # giữ 7 ngày
    )
)
```

### 4.3. Publish có xác nhận

```python
ack = await js.publish(
    "orders.us.created",
    b'{"order_id": "A1", "amount": 100}',
    headers={"Nats-Msg-Id": "order-A1"},  # dedup exactly-once
)
print(ack.stream, ack.seq)  # ORDERS, sequence number
```

### 4.4. Pull consumer (khuyến nghị)

```python
from nats.js.api import ConsumerConfig, AckPolicy

# Tạo durable consumer
await js.add_consumer(
    "ORDERS",
    ConsumerConfig(
        durable_name="order-workers",
        filter_subject="orders.us.>",
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=30,          # giây
        max_deliver=5,        # tối đa 5 lần redeliver
    ),
)

sub = await js.pull_subscribe(
    "orders.us.>",
    durable="order-workers",
)

while True:
    msgs = await sub.fetch(batch=10, timeout=5)
    for msg in msgs:
        try:
            handle(msg.data)
            await msg.ack()
        except Exception:
            await msg.nak()
```

### 4.5. Push consumer

```python
async def cb(msg):
    handle(msg.data)
    await msg.ack()

await js.subscribe(
    "orders.us.>",
    durable="push-workers",
    cb=cb,
    manual_ack=True,
)
```

## 5. Các pattern quan trọng

### 5.1. Pattern: Work queue (mỗi job một worker)

```python
from nats.js.api import StreamConfig, RetentionPolicy

await js.add_stream(
    StreamConfig(
        name="JOBS",
        subjects=["jobs.>"],
        retention=RetentionPolicy.WORK_QUEUE,
    )
)
```

Nhiều worker cùng pull một durable consumer sẽ chia nhau job; mỗi message chỉ được xử lý một lần rồi xóa khỏi stream sau khi ack.

### 5.2. Pattern: Fan-out nhiều consumer độc lập

Cùng một stream, nhiều durable consumer khác nhau (mỗi service một consumer) đọc độc lập với offset riêng:

```text
            +--> Consumer "billing"    (đọc từ đầu)
Stream ----+
            +--> Consumer "analytics"  (đọc từ now)
```

Mỗi consumer giữ vị trí đọc riêng, không ảnh hưởng nhau.

### 5.3. Pattern: Replay theo thời gian hoặc sequence

```python
from nats.js.api import ConsumerConfig, DeliverPolicy

ConsumerConfig(
    deliver_policy=DeliverPolicy.BY_START_TIME,
    opt_start_time="2026-06-01T00:00:00Z",
)
```

`DeliverPolicy` cho phép đọc lại: `ALL`, `LAST`, `NEW`, `BY_START_SEQUENCE`, `BY_START_TIME`. Rất hữu ích khi rebuild state hoặc khắc phục sự cố.

### 5.4. Pattern: Exactly-once bằng dedup + idempotent consumer

- Phía publish: gán `Nats-Msg-Id` để server loại bản trùng.
- Phía consume: xử lý idempotent (ví dụ upsert theo `order_id`) để chịu được redeliver.

Hai lớp này kết hợp mới cho hành vi exactly-once thực sự ở mức nghiệp vụ.

### 5.5. Pattern: Dead Letter qua max_deliver

Khi message vượt `max_deliver` mà vẫn chưa ack, JetStream phát một advisory. Bạn có thể subscribe advisory đó để chuyển message "độc" sang stream DLQ riêng để điều tra.

```text
$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.<stream>.<consumer>
```

## 6. Các lỗi thực chiến rất hay gặp

### 6.1. Nhầm NATS Core với JetStream

Dùng `nc.publish()` thay vì `js.publish()` thì message không được lưu vào stream, không có persistence dù bạn đã tạo stream.

### 6.2. Quên ack message

Nếu không ack, JetStream sẽ liên tục redeliver sau mỗi `AckWait`, gây xử lý lặp và tải tăng vọt.

### 6.3. Ack quá sớm trước khi xử lý xong

Nếu ack trước khi commit DB rồi process chết, message coi như đã xử lý nhưng thực tế bị mất logic. Luôn ack sau khi side-effect hoàn tất.

### 6.4. Consumer không idempotent với at-least-once

At-least-once nghĩa là có thể trùng. Nếu handler không idempotent, một message redeliver sẽ tạo bản ghi nhân đôi.

### 6.5. Đặt AckWait quá ngắn

Nếu `AckWait` ngắn hơn thời gian xử lý thực tế, message bị redeliver trong khi worker vẫn đang chạy, gây xử lý song song ngoài ý muốn. Dùng `InProgress` cho job dài.

### 6.6. Không đặt giới hạn cho stream

Stream không có `max_bytes`/`max_age` sẽ phình to vô hạn và làm đầy đĩa server.

### 6.7. Dùng ephemeral consumer cho việc cần bền vững

Ephemeral consumer biến mất khi client ngắt kết nối, mất offset đã đọc. Việc cần resume sau restart phải dùng durable consumer.

### 6.8. Publish không kiểm tra PubAck

`js.publish()` trả về `PubAck`. Nếu bỏ qua và không xử lý lỗi/timeout, bạn không biết message đã thực sự được lưu hay chưa.

### 6.9. Hiểu sai retention WorkQueue

Với `WorkQueue`, một message chỉ được tiêu thụ bởi một consumer. Nếu cần fan-out nhiều service, dùng `Limits` hoặc `Interest`, không dùng `WorkQueue`.

### 6.10. Không cấu hình replica khi cần HA

Stream một replica sẽ mất dữ liệu nếu node đó chết. Production cần `num_replicas=3` trên cluster để chịu lỗi.

### 6.11. Subject overlap giữa nhiều stream

Hai stream cùng bắt một subject sẽ gây nhập nhằng message đi vào đâu. Subject của các stream nên tách bạch rõ.

### 6.12. Không theo dõi consumer lag

Nếu không giám sát số message tồn đọng (pending), consumer có thể tụt lại rất xa mà không ai biết cho tới khi trễ nghiêm trọng.

## 7. Kiến trúc production: JetStream cluster

### 7.1. Sơ đồ

```text
Producers
   |
   | js.publish("orders.>")
   v
+--------------------------------------+
|        NATS JetStream Cluster        |
|   node-1     node-2     node-3       |
|   (RAFT replication, num_replicas=3) |
+--------------------------------------+
   |                    |
   | pull/fetch         | pull/fetch
   v                    v
Worker pool A       Worker pool B
(durable: billing)  (durable: analytics)
```

### 7.2. Bật JetStream trên server

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
  routes: [
    nats://node-2:6222
    nats://node-3:6222
  ]
}
```

### 7.3. Tạo stream HA

```python
from nats.js.api import StreamConfig, StorageType

await js.add_stream(
    StreamConfig(
        name="ORDERS",
        subjects=["orders.>"],
        storage=StorageType.FILE,
        num_replicas=3,        # chịu lỗi 1 node
        max_bytes=20 * 1024**3,
        max_age=14 * 24 * 3600,
    )
)
```

### 7.4. Những điểm quan trọng cần có

- `num_replicas=3` cho stream nghiệp vụ quan trọng.
- Durable consumer cho mọi luồng cần resume sau restart.
- `max_bytes` và `max_age` để khống chế dung lượng.
- Idempotent consumer + `Nats-Msg-Id` cho exactly-once.
- Giám sát pending messages, redelivery và disk usage.
- DLQ qua advisory `MAX_DELIVERIES`.

## 8. Checklist production

### 8.1. Ở tầng ứng dụng

- Dùng `js.publish()` chứ không phải `nc.publish()` cho dữ liệu cần lưu.
- Kiểm tra `PubAck` và xử lý timeout khi publish.
- Dùng durable consumer cho luồng cần resume.
- Ack sau khi xử lý xong, không ack sớm.
- Handler idempotent để chịu redeliver.
- Đặt `AckWait` phù hợp thời gian xử lý, dùng `InProgress` cho job dài.
- Giới hạn `max_deliver` và có chiến lược DLQ.
- Dùng `Nats-Msg-Id` nếu cần exactly-once publish.

### 8.2. Ở tầng hạ tầng

- JetStream chạy cluster, không single node cho production.
- Stream quan trọng đặt `num_replicas=3`.
- Cấu hình `max_bytes`, `max_age` cho mọi stream.
- `store_dir` nằm trên đĩa bền và đủ dung lượng.
- Có monitoring: pending, redelivery, ack rate, disk, RAFT health.
- Có backup/snapshot stream nếu dữ liệu quan trọng.
- Có alert khi consumer lag vượt ngưỡng.

## 9. Khi nào chưa nên dùng JetStream?

Không nên dùng JetStream chỉ vì "nghe persistent hơn".

Nên cân nhắc NATS Core hoặc giải pháp khác nếu:

- Message ephemeral, mất không sao (metric, heartbeat, telemetry).
- Chỉ cần request/reply đơn giản, latency là ưu tiên tuyệt đối.
- Không cần replay hay delivery guarantee.

Nên dùng JetStream nếu:

- Dữ liệu không được phép mất.
- Cần replay lại lịch sử event.
- Cần work queue chia job cho nhiều worker.
- Cần fan-out nhiều consumer độc lập.
- Cần at-least-once hoặc exactly-once.
- Muốn persistence nhưng không muốn vận hành nặng như Kafka.

## 10. Kết luận

JetStream không khó ở phần "publish và subscribe", mà khó ở phần thiết kế đúng semantics: chọn retention policy, đặt ack đúng chỗ, làm consumer idempotent, cấu hình replica và giám sát lag.

Nếu dạy cho người khác, điểm quan trọng nhất cần nhấn mạnh là: NATS Core và JetStream là hai thứ khác nhau. NATS Core là pub/sub fire-and-forget; JetStream mới là nơi bắt đầu của persistence, replay và delivery guarantee. Production bắt đầu từ việc chọn đúng delivery semantics và thiết kế consumer chịu được redeliver.
