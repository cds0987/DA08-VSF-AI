# Hướng dẫn học WebSocket với FastAPI từ nền tảng đến production

Tài liệu này được viết theo hướng "nền tảng trước, production sau": hiểu giao thức, nắm lifecycle, biết các pattern triển khai, tránh lỗi thực chiến và có một bộ cấu hình hoàn chỉnh với FastAPI, Redis và Nginx.

## 1. WebSocket là gì?

### 1.1. Bản chất

WebSocket là giao thức giao tiếp hai chiều, persistent và full-duplex giữa client và server.

Khác với HTTP REST truyền thống:

```text
HTTP REST:
Client gửi request -> Server trả response -> Kết thúc request

WebSocket:
Client mở connection -> Server accept -> Hai bên gửi message qua lại liên tục
```

WebSocket bắt đầu bằng một HTTP request thông thường, sau đó được nâng cấp sang giao thức WebSocket thông qua handshake.

### 1.2. Vì sao WebSocket tồn tại?

Nhiều hệ thống cần server chủ động đẩy dữ liệu xuống client ngay khi có sự kiện:

- Real-time chat
- Live dashboard
- Notification system
- Collaborative editing
- Live trading price
- Multiplayer game
- Realtime monitoring

Nếu chỉ dùng REST, client phải polling liên tục:

```text
Client: Có tin mới chưa?
Server: Chưa.

Client: Có tin mới chưa?
Server: Chưa.

Client: Có tin mới chưa?
Server: Có.
```

Polling gây lãng phí request, tăng latency và tốn tài nguyên mạng. WebSocket giải quyết bằng cách giữ một kết nối mở để server đẩy dữ liệu ngay khi cần.

### 1.3. So sánh REST, WebSocket, SSE và Long Polling

| Tiêu chí | HTTP REST | WebSocket | SSE | Long Polling |
| --- | --- | --- | --- | --- |
| Kiểu kết nối | Request/response | Persistent | Persistent | Request giữ lâu |
| Chiều giao tiếp | Client -> Server | Hai chiều | Server -> Client | Gần real-time |
| Server push | Không tự nhiên | Rất tốt | Rất tốt | Giả lập |
| Dùng cho chat | Không tối ưu | Rất phù hợp | Chỉ nhận tốt | Tạm được |
| Dùng cho notification | Được | Được | Rất phù hợp | Tạm được |
| Dùng cho collaborative editing | Không phù hợp | Rất phù hợp | Không đủ | Không phù hợp |
| Scale ngang | Dễ hơn | Khó hơn | Trung bình | Trung bình |

Quy tắc thực tế:

- Dùng REST cho CRUD và request/response.
- Dùng SSE khi chỉ cần stream một chiều từ server xuống client.
- Dùng WebSocket khi cần tương tác real-time hai chiều.
- Dùng Long Polling khi môi trường không hỗ trợ WebSocket hoặc SSE.

## 2. WebSocket trong FastAPI

FastAPI hỗ trợ WebSocket thông qua decorator:

```python
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("Hello")
```

Về mặt tầng kiến trúc:

```text
FastAPI
  ↓
Starlette
  ↓
ASGI
  ↓
Uvicorn / Hypercorn
  ↓
TCP socket
```

FastAPI cung cấp API dễ dùng, Starlette chịu trách nhiệm phần abstraction WebSocket, còn Uvicorn là ASGI server chạy phía dưới.

### 2.1. Lifecycle của một connection

1. Client gửi HTTP request với `Upgrade: websocket`
2. Server kiểm tra route, auth, origin hoặc protocol
3. Server `accept()` connection
4. Connection chuyển sang trạng thái mở
5. Hai bên gửi và nhận message
6. Một bên đóng connection hoặc gặp lỗi mạng
7. Server cleanup connection khỏi memory

### 2.2. Minimal endpoint

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

## 3. Các khái niệm cốt lõi

### 3.1. Handshake

Client bắt đầu bằng HTTP request:

```http
GET /ws HTTP/1.1
Host: example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: ...
Sec-WebSocket-Version: 13
```

Server đồng ý nâng cấp:

```http
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: ...
```

### 3.2. Connection lifecycle

Có thể hình dung như một cuộc gọi điện:

```text
open    = nhấc máy
message = nói chuyện
close   = cúp máy
error   = mất sóng
```

Ví dụ:

```python
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/lifecycle")
async def lifecycle(websocket: WebSocket):
    await websocket.accept()
    print("OPEN")

    try:
        while True:
            data = await websocket.receive_text()
            print("MESSAGE:", data)
            await websocket.send_text(f"Received: {data}")
    except WebSocketDisconnect:
        print("CLOSE")
    except Exception as exc:
        print("ERROR:", exc)
```

### 3.3. Text message và binary message

Text message phù hợp với JSON, chat hoặc command:

```json
{
  "type": "chat.message",
  "room": "general",
  "text": "hello"
}
```

Binary message phù hợp với audio chunk, protobuf, image hoặc file stream.

### 3.4. Ping/Pong heartbeat

Heartbeat giúp server biết client còn sống hay đã chết ngầm trong các tình huống như:

- Mất mạng
- Browser bị sleep
- Mobile app chạy nền
- Proxy cắt connection
- NAT timeout

Ví dụ heartbeat ở tầng ứng dụng:

```python
import asyncio
from fastapi import WebSocket, WebSocketDisconnect

async def heartbeat(websocket: WebSocket):
    while True:
        await asyncio.sleep(30)
        await websocket.send_json({"type": "ping"})


@app.websocket("/ws/heartbeat")
async def ws_heartbeat(websocket: WebSocket):
    await websocket.accept()
    heartbeat_task = asyncio.create_task(heartbeat(websocket))

    try:
        while True:
            msg = await websocket.receive_json()

            if msg.get("type") == "pong":
                continue

            await websocket.send_json({"type": "echo", "data": msg})
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
```

### 3.5. Connection state management

Nếu không quản lý connection, bạn không thể:

- Broadcast
- Gửi message cho một user cụ thể
- Remove dead connection
- Kiểm soát memory leak
- Theo dõi online/offline

Ví dụ:

```python
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def send_to_all(self, message: str):
        dead = []

        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)
```

### 3.6. Broadcast, unicast và room/channel

| Kiểu | Ý nghĩa |
| --- | --- |
| Broadcast | Gửi cho tất cả client |
| Unicast | Gửi cho một user cụ thể |
| Room / Channel | Gửi cho một nhóm client |

Hình dung thực tế:

- Broadcast = loa phát thanh toàn công ty
- Unicast = gọi riêng một người
- Room = nhóm Slack hoặc Telegram

### 3.7. Authentication trên WebSocket

WebSocket không giống REST ở chỗ không có một vòng request/response riêng cho từng message. Vì vậy auth phải được thiết kế rõ ở thời điểm mở connection hoặc trong protocol message.

Các cách phổ biến:

| Cách | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| Cookie session | Tốt với web app cùng domain | Cần kiểm soát CSRF và origin |
| Query param token | Dễ dùng | Có thể lộ trong log |
| Authorization header | Chuẩn về mặt API | Browser WebSocket API không cho set custom header trực tiếp |
| First-message auth | Linh hoạt | Connection mở trước khi auth xong |
| Subprotocol | Mạnh cho use case nâng cao | Ít phổ biến hơn |

Ví dụ auth bằng query token:

```python
from fastapi import WebSocket, status

VALID_TOKENS = {"secret-token": {"user_id": "u1"}}

async def authenticate_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    user = VALID_TOKENS.get(token)

    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    return user
```

### 3.8. Concurrency model

WebSocket giữ connection lâu, nên handler phải dùng async đúng cách.

Sai:

```python
import time

@app.websocket("/ws/bad")
async def bad(websocket: WebSocket):
    await websocket.accept()

    while True:
        time.sleep(5)
        await websocket.send_text("tick")
```

Đúng:

```python
import asyncio

@app.websocket("/ws/good")
async def good(websocket: WebSocket):
    await websocket.accept()

    while True:
        await asyncio.sleep(5)
        await websocket.send_text("tick")
```

## 4. Các pattern quan trọng

### 4.1. Pattern: Connection Manager

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Set

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []

        for websocket in list(self.connections):
            try:
                await websocket.send_json(message)
            except Exception:
                dead_connections.append(websocket)

        for websocket in dead_connections:
            self.disconnect(websocket)
```

### 4.2. Pattern: Room / Channel

```python
from collections import defaultdict
from typing import DefaultDict, Set
from fastapi import WebSocket

class RoomManager:
    def __init__(self):
        self.rooms: DefaultDict[str, Set[WebSocket]] = defaultdict(set)

    async def join(self, room: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms[room].add(websocket)

    def leave(self, room: str, websocket: WebSocket):
        self.rooms[room].discard(websocket)

        if not self.rooms[room]:
            del self.rooms[room]
```

### 4.3. Pattern: Redis Pub/Sub cho multi-worker

Nếu chạy nhiều worker, state in-memory không còn đủ:

```text
Worker 1 có connection A, B
Worker 2 có connection C, D
```

Nếu A gửi message vào worker 1, worker 2 sẽ không biết gì nếu không có external pub/sub.

Giải pháp:

```text
Client A -> Worker 1 -> Redis channel -> Worker 2 -> Client C/D
```

Ví dụ:

```python
import json
from redis.asyncio import Redis

class RedisPubSub:
    def __init__(self, redis_url: str):
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def publish(self, channel: str, message: dict):
        await self.redis.publish(channel, json.dumps(message))
```

### 4.4. Pattern: Heartbeat

Heartbeat nên có timeout policy rõ ràng. Nếu quá lâu không nhận được `pong`, server nên đóng connection để tránh giữ kết nối chết.

### 4.5. Pattern: Snapshot + delta sau reconnect

WebSocket là stream, không tự đảm bảo replay. Sau reconnect, client có thể bị hụt dữ liệu nếu server không có chiến lược resync.

Mô hình phổ biến:

1. Client gửi `last_seen_event_id`
2. Server gửi snapshot hiện tại
3. Sau đó mới stream các delta tiếp theo

## 5. Các lỗi thực chiến rất hay gặp

### 5.1. Thiếu cleanup trong `finally`

Triệu chứng:

- Memory tăng dần
- Online count sai
- Broadcast lỗi vì còn dead socket

### 5.2. Không bắt `WebSocketDisconnect`

Khi client đóng tab hoặc mất mạng, handler có thể văng lỗi và không dọn dẹp connection.

### 5.3. Dùng blocking I/O trong async handler

Sai:

```python
import requests
```

Đúng:

```python
import httpx
```

Trong async handler, luôn dùng thư viện async-compatible.

### 5.4. Không có heartbeat

Hệ thống có thể giữ các connection chết ngầm quá lâu, đặc biệt sau reverse proxy hoặc mobile network.

### 5.5. Auth thiếu hoặc sai

WebSocket endpoint cần auth riêng. Không nên giả định middleware REST đang tự bảo vệ đủ cho luồng WebSocket.

### 5.6. Đưa token vào query rồi log toàn bộ URL

Điều này dễ làm lộ JWT trong access log, APM log hoặc browser history. Nếu dùng query token, nên kiểm soát TTL và logging rất chặt.

### 5.7. Multi-worker không sync state

`connections = set()` chỉ đúng khi chạy một process. Khi có nhiều worker, phải có Redis, NATS, Kafka hoặc một cơ chế đồng bộ khác.

### 5.8. Không giới hạn message size

Client có thể gửi payload rất lớn, gây spike RAM hoặc làm server chậm.

Ví dụ:

```python
MAX_SIZE = 64 * 1024
```

### 5.9. Không validate message format

Nên dùng Pydantic để kiểm soát contract message và trả lỗi rõ ràng nếu client gửi sai format.

### 5.10. Thiếu reconnect ở client

Nếu server restart hoặc deploy, user sẽ mất realtime cho đến khi reload nếu client không tự kết nối lại.

### 5.11. Race condition khi broadcast và disconnect

Sai:

```python
for ws in connections:
    await ws.send_json(message)
```

Đúng:

```python
for ws in list(connections):
    await ws.send_json(message)
```

### 5.12. Nginx thiếu header Upgrade hoặc timeout

Đây là lỗi hạ tầng rất phổ biến khiến browser báo handshake fail hoặc connection tự đóng sau khoảng thời gian ngắn.

### 5.13. Không handle backpressure

Nếu server gửi nhanh hơn client nhận, queue sẽ phình to và kéo hiệu năng toàn hệ thống đi xuống.

### 5.14. Không resync state sau reconnect

Client reconnect xong nhưng chỉ chờ event mới, dẫn đến dashboard sai số liệu hoặc mất notification cũ.

## 6. Kiến trúc production: FastAPI + Redis + Nginx

### 6.1. Sơ đồ

```text
Browser
  |
  | wss://api.example.com/ws/rooms/general
  v
Nginx
  |
  | proxy_pass http://app:8000
  v
Gunicorn / Uvicorn workers
  |        |        |
Worker 1 Worker 2 Worker 3
  |        |        |
  +--------+--------+
           |
        Redis Pub/Sub
```

### 6.2. Cấu trúc file

```text
app/
  main.py
  redis_pubsub.py
  connection_manager.py
requirements.txt
Dockerfile
docker-compose.yml
nginx.conf
```

### 6.3. `requirements.txt`

```text
fastapi
uvicorn[standard]
gunicorn
redis
pydantic
```

### 6.4. `app/connection_manager.py`

```python
from collections import defaultdict
from typing import DefaultDict, Set
from fastapi import WebSocket

class RoomConnectionManager:
    def __init__(self):
        self.rooms: DefaultDict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, room: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms[room].add(websocket)

    def disconnect(self, room: str, websocket: WebSocket):
        self.rooms[room].discard(websocket)
```

### 6.5. `app/redis_pubsub.py`

```python
import json
from typing import AsyncIterator
from redis.asyncio import Redis

class RedisPubSub:
    def __init__(self, redis_url: str):
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def publish(self, channel: str, message: dict):
        payload = json.dumps(message)
        await self.redis.publish(channel, payload)
```

### 6.6. `app/main.py`

Các điểm quan trọng cần có trong `main.py`:

- Auth cho WebSocket
- Origin check
- Pydantic validation
- Rate limiting
- Heartbeat
- Redis Pub/Sub
- Cleanup trong `finally`

### 6.7. `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["gunicorn", "app.main:app",
     "-k", "uvicorn.workers.UvicornWorker",
     "--bind", "0.0.0.0:8000",
     "--workers", "4",
     "--timeout", "120"]
```

### 6.8. `nginx.conf`

```nginx
events {}

http {
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    upstream fastapi_app {
        server app:8000;
    }

    server {
        listen 80;
        server_name localhost;

        location /ws/ {
            proxy_pass http://fastapi_app;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            proxy_connect_timeout 60s;
            proxy_buffering off;
        }
    }
}
```

### 6.9. Vì sao các dòng Nginx này quan trọng?

- `proxy_http_version 1.1`: WebSocket upgrade cần HTTP/1.1
- `proxy_set_header Upgrade $http_upgrade`: forward yêu cầu upgrade
- `proxy_set_header Connection $connection_upgrade`: forward connection upgrade đúng cách
- `proxy_read_timeout 3600s`: tránh bị cắt connection quá sớm
- `proxy_buffering off`: stream dữ liệu realtime trực tiếp

## 7. Checklist production

### 7.1. Ở tầng ứng dụng

- Có bắt `WebSocketDisconnect`
- Có cleanup trong `finally`
- Có auth riêng cho WebSocket
- Có origin check nếu dùng browser
- Có validate message bằng Pydantic
- Có giới hạn kích thước message
- Có rate limit theo connection hoặc user
- Có heartbeat
- Có reconnect client-side
- Có snapshot hoặc resync sau reconnect
- Không dùng blocking I/O trong async handler
- Không dùng in-memory broadcast nếu chạy multi-worker

### 7.2. Ở tầng hạ tầng

- Nginx có `proxy_http_version 1.1`
- Có `Upgrade` và `Connection`
- Timeout đủ dài
- Dùng `wss://` ở production
- Có Redis, NATS hoặc Kafka nếu cần multi-worker
- Có health check
- Có graceful shutdown
- Có metrics: active connections, messages/sec, disconnect reason, send latency
- Có log nhưng không log token hoặc query string nhạy cảm

## 8. Khi nào chưa nên dùng WebSocket?

Không nên dùng WebSocket chỉ vì "nghe realtime hơn".

Nên cân nhắc REST hoặc SSE nếu:

- Client không cần gửi dữ liệu realtime
- Chỉ cần stream một chiều từ server
- Hệ thống cần scale cực đơn giản
- Use case chủ yếu là CRUD
- Tần suất update thấp, vài chục giây một lần là đủ

Nên dùng WebSocket nếu:

- Cần latency thấp
- Cần giao tiếp hai chiều
- Cần presence hoặc online/offline
- Cần room hoặc channel
- Cần collaborative interaction
- Cần server push ngay lập tức

## 9. Kết luận

WebSocket với FastAPI không khó ở phần "mở connection", mà khó ở phần vận hành lâu dài: auth, cleanup, heartbeat, sync state giữa nhiều worker, reverse proxy và khả năng phục hồi sau reconnect.

Nếu dạy cho người khác, điểm quan trọng nhất cần nhấn mạnh là: một demo chat đơn giản chưa phải production WebSocket. Production bắt đầu từ quản lý lifecycle, giới hạn rủi ro và thiết kế cơ chế phục hồi khi kết nối bị gián đoạn.
