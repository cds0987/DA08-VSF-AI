# Hướng dẫn chạy Full Luồng Frontend Đầu-đến-Đầu (End-to-End)

> ⚠️ **LƯU Ý (2026-06-12):** `docker-compose.localtest.yml`/`docker-compose.local.yml` đã bị xóa.
> Stack tích hợp chuẩn giờ là **`docker-compose.e2e.yml`** (xem [`infra/e2e/README.md`](../../infra/e2e/README.md)).
> Các lệnh `docker compose -f docker-compose.localtest.yml ...` dưới đây cần thay bằng
> `docker-compose.e2e.yml` (e2e KHÔNG build frontend/nginx — dựng FE riêng để dev UI).

> **Mục tiêu:** Cung cấp tài liệu tổng hợp, chi tiết từng bước để một lập trình viên có thể tự cấu hình, khởi động và kiểm thử toàn bộ luồng hoạt động từ Frontend (Admin, Chat) đi qua toàn bộ các service Backend (User, Document, Query, MCP, RAG Worker) và hạ tầng (Qdrant Cloud, GCS, PostgreSQL, NATS).

Tài liệu này được tổng hợp từ các file integration contract hiện có (`document-service`, `query-service`, `mcp-service`, `rag-worker`) và các báo cáo kiến trúc của Nuxt Frontend.

---

## 1. Yêu cầu Hệ thống (Prerequisites)

Để chạy được toàn bộ luồng này ở máy local, bạn cần chuẩn bị:

1. **Môi trường:**
   - Docker & Docker Compose.
   - Node.js 20+ và `npm`.
   - Python 3.11+.
2. **Khóa API (Secrets):**
   - OpenAI API Key.
   - Thông tin xác thực GCS (HMAC Access Key & Secret).
   - Qdrant Cloud URL (`http://34.87.176.141:80`) và Basic Auth (`***REDACTED-QDRANT-AUTH***`).
   - Một chuỗi JWT Secret ngẫu nhiên dùng chung cho tất cả các service nội bộ.

---

## 2. Luồng Dữ liệu Tổng thể (The End-to-End Flow)

Quá trình hoạt động của hệ thống chia làm 2 pha chính (Ingestion và Retrieval):

**Pha 1: Tải tài liệu (Ingestion)**
1. **Admin Frontend (Port 3001)**: Admin đăng nhập và tải tài liệu (kèm metadata phân quyền ACL) thông qua API của **Document Service**.
2. **Document Service (Port 8002)**: Lưu file gốc lên **GCS**, lưu record vào database và bắn event `doc.ingest` qua **NATS**.
3. **RAG Worker (Port 8010)**: Bắt event, tải file từ GCS, chia nhỏ (chunk), nhúng (embed qua OpenAI) và lưu vector lên **Qdrant Cloud**. Cuối cùng bắn event `doc.status (indexed)`.
4. **Document Service**: Nhận status `indexed`, cập nhật DB và bắn event `doc.access` (phân quyền) & `notify.doc_new`.

**Pha 2: Truy vấn & Hội thoại (Retrieval)**
5. **Query Service (Port 8001)**: Nhận event phân quyền, cập nhật DB nội bộ. Nhận thông báo và đẩy qua kênh **SSE** cho User.
6. **Chat Frontend (Port 3000)**: Người dùng thường đăng nhập. Giao diện nhận thông báo tài liệu mới qua SSE. Người dùng đặt câu hỏi.
7. **Query Service**: Xác thực JWT, lấy danh sách ID tài liệu được phép (ACL) và gọi **MCP Service**.
8. **MCP Service (Port 8003)**: Tìm kiếm trên **Qdrant Cloud** (có filter theo ID tài liệu) và trả về các đoạn text liên quan (chunks).
9. **Query Service**: Gọi LLM (OpenAI) để tổng hợp câu trả lời dựa trên chunks, sau đó stream (truyền) kết quả từng phần (token) về Chat Frontend qua **SSE**, kết thúc bằng event `done` chứa thông tin trích dẫn (Citations).

---

## 3. Cấu hình Môi trường (Environment Setup)

### 3.1. Các Service Python Backend
Tạo một file `.env` chung ở thư mục gốc của project (DA08-VSF) để chứa các secret:

```env
# .env (Gốc)
OPENAI_API_KEY=sk-proj-...
GCS_HMAC_KEY=GOOG1...
GCS_HMAC_SECRET=TaUs...
JWT_SECRET_KEY=***REDACTED-JWT-SECRET***
QDRANT_URL=http://34.87.176.141:80
VECTOR_DB_BASIC_AUTH=***REDACTED-QDRANT-AUTH***
S3_ENDPOINT_URL=https://storage.googleapis.com
S3_BUCKET=vsf-rag-chatbot-docs-dev
```

Mỗi service trong `src/` đã được cấu hình trỏ tới các biến này trong docker compose hoặc bạn có thể chạy bash script để export chúng ra terminal nếu chạy chay.

### 3.2. Cấu hình Frontend
Tạo file `.env` cho hai ứng dụng Frontend.

**Tại `src/frontend/admin/.env`**:
```env
NUXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000
NUXT_PUBLIC_DOCUMENT_SERVICE_URL=http://localhost:8002
NUXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001
```

**Tại `src/frontend/chat/.env`**:
```env
NUXT_PUBLIC_USER_SERVICE_URL=http://localhost:8000
NUXT_PUBLIC_QUERY_SERVICE_URL=http://localhost:8001
```

---

## 4. Khởi động Hệ thống (Startup Sequence)

### Bước 1: Khởi động Hạ tầng Local
Bật PostgreSQL và NATS:
```bash
# Trong thư mục gốc DA08-VSF
docker compose -f docker-compose.localtest.yml up -d postgres nats
```
*Đợi khoảng 10 giây để DB và Queue sẵn sàng.*

### Bước 2: Chạy các Backend Services
Vì hệ thống khá nặng, tốt nhất nên dùng tính năng auto-build của Docker Compose để gom các dịch vụ:
```bash
docker compose -f docker-compose.localtest.yml up -d --build
```
Kiểm tra xem `rag-worker` đã chạy chưa:
```bash
curl -fsS http://localhost:8000/readyz
```

**LƯU Ý QUAN TRỌNG VỀ MCP SERVICE:**
MCP Service áp dụng nguyên tắc "fail-closed" - Nó sẽ crash ngay lúc khởi động nếu Qdrant chưa có bất kỳ Collection nào.
=> Do đó, bạn sẽ phải thực hiện Bước 3 (Upload 1 file) để tạo Collection TRƯỚC, sau đó mới restart lại MCP Service.

### Bước 3: Tải tài liệu qua Admin Frontend
Bật terminal mới, chạy Admin App:
```bash
cd src/frontend/admin
npm install
npm run dev
```
1. Mở trình duyệt tại: `http://localhost:3001`
2. Đăng nhập bằng tài khoản admin.
3. Vào trang Quản lý Tài liệu. Tải lên một tệp `.txt` hoặc `.md` và chọn phân loại `Internal` (Nội bộ).
4. Quan sát UI: Trạng thái ban đầu sẽ là `Queued`. Frontend sẽ tự động Polling ngầm mỗi 4 giây.
5. Sau vài giây, trạng thái sẽ đổi thành `Indexed` (Đã lập chỉ mục).

Lúc này Qdrant Cloud đã có dữ liệu!

### Bước 4: Khởi động lại MCP Service
Quay lại terminal backend:
```bash
docker compose -f docker-compose.localtest.yml up -d mcp-service
```
Đảm bảo MCP Service khởi động thành công (Không bị exit code 1).

### Bước 5: Truy vấn qua Chat Frontend
Bật terminal mới, chạy Chat App:
```bash
cd src/frontend/chat
npm install
npm run dev
```
1. Mở trình duyệt tại: `http://localhost:3000`
2. Đăng nhập bằng tài khoản User (không phải Admin).
3. Đặt một câu hỏi có nội dung nằm trong file bạn vừa tải lên.
4. Quan sát UI:
   - Giao diện sẽ hiển thị chữ nhấp nháy theo hiệu ứng **Streaming (SSE)** do Query Service trả về.
   - Khi hoàn tất, một dải **Citations (Trích dẫn)** sẽ hiện ra bên dưới câu trả lời, cho phép bạn click xem nguồn.
   - Các nút **Feedback (Thumbs Up/Down)** sẽ xuất hiện. Thử click một nút.

### Bước 6: Kiểm tra Thông báo (SSE Notifications)
1. Giữ tab Chat của User mở.
2. Quay lại tab Admin (Port 3001). Tải lên thêm 1 tệp mới (Nhớ chọn phân quyền sao cho User kia xem được, ví dụ `Internal`).
3. Ngay khi tệp chuyển sang trạng thái `Indexed`, tab Chat của User sẽ nhận được thông báo thời gian thực thông qua cơ chế Server-Sent Events (SSE), huy hiệu (badge) thông báo sẽ tăng lên.

---

## 5. Dọn dẹp (Teardown & Cleanup)

Vì bạn đang test với Qdrant Cloud và GCS thật, hãy dọn rác sau khi test xong bằng tool tích hợp sẵn trong repo:

```bash
# Export các biến S3 và Qdrant
source .env
export S3_ACCESS_KEY_ID=$GCS_HMAC_KEY
export S3_SECRET_ACCESS_KEY=$GCS_HMAC_SECRET

# Xoá vector trên Cloud và file trên GCS
src/query-service/.venv/bin/python infra/localtest/ci_e2e.py cleanup

# Tắt toàn bộ hệ thống local Docker
docker compose -f docker-compose.localtest.yml down -v --remove-orphans
```

---

## 6. Các Điểm Thiết Kế Quan Trọng của Frontend (Design Constraints)

Dành cho AI Agents và Frontend Developers khi chỉnh sửa code:

1. **Bảo mật tuyệt đối ranh giới (Boundary):** Trình duyệt chỉ được gọi đến `User Service`, `Document Service` và `Query Service`. TUYỆT ĐỐI KHÔNG chứa cấu hình, token hay gọi trực tiếp tới `RAG Worker`, `MCP Service`, Qdrant, NATS hay GCS trong mã nguồn Frontend.
2. **Không tạo URL Signed ở Client:** Giao diện xem/tải tài liệu không được lưu trữ URL cứng của GCS. Luôn phải gọi API `GET /documents/{id}/file` để lấy URL có thời hạn (Signed URL) 5 phút một lần.
3. **Cơ chế Streaming (SSE):** Không dùng `Axios` cho API Streaming vì nó chỉ bắt dữ liệu một cục khi kết thúc. Phải sử dụng `EventSource` (hoặc thư viện tương đương như `@microsoft/fetch-event-source`) để đọc từng token chữ và hiển thị mượt mà. Đợi đến khi nhận block JSON `{"done": true}` mới được coi là kết thúc session.
4. **Hệ thống Layer của Nuxt:** 
   - `src/frontend/base` chứa UI shadcn, auth logic và thư viện chung. Không sửa nghiệp vụ cụ thể ở đây.
   - Tính năng dành riêng cho quản trị chỉ code ở `src/frontend/admin`.
   - Tính năng trò chuyện chỉ code ở `src/frontend/chat`.
5. **Cơ chế Refresh Token:** Axios Interceptor ở Base Layer đã được cấu hình tự động. Developer không cần quan tâm token hết hạn khi gọi API, chỉ cần gọi như bình thường.
