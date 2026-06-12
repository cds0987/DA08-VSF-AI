# Hướng dẫn chạy Full Luồng Frontend Đầu-đến-Đầu (End-to-End) - LOCAL DEV

> **Mục tiêu:** Cung cấp tài liệu tổng hợp, chi tiết từng bước để một lập trình viên có thể tự cấu hình, khởi động và kiểm thử toàn bộ luồng hoạt động từ Frontend (Admin, Chat) đi qua toàn bộ các service Backend (User, Document, Query, MCP, RAG Worker) và hạ tầng (Postgres, NATS, Redis, Qdrant/GCS).

Tài liệu này tối ưu cho việc **phát triển Frontend** (Hot-reload) kết hợp với **Backend chạy qua Docker Compose** để nhanh chóng có môi trường tích hợp chuẩn production.

---

## 1. Yêu cầu Hệ thống (Prerequisites)

1. **Môi trường:** Docker, Node.js 20+, Python 3.11+.
2. **Khóa API (Secrets):** OpenAI API Key, GCS HMAC (hoặc SA JSON), Qdrant URL.
3. **JWT Secret:** Dùng chung `JWT_SECRET_KEY` cho các service (prod: GitHub Secrets → `deploy/env/secret.env`). Nếu dùng stack E2E, mặc định là:
   `e2e-jwt-secret-shared-across-services-32ch`

---

## 2. Cấu hình Môi trường (Environment Setup)

### 2.1. Copy các file .env
```bash
# Root .env (Dành cho Docker Compose E2E - Chứa API Keys)
cp .env.example .env

# Frontend .env.local
cp src/frontend/chat/.env.local.example   src/frontend/chat/.env.local
cp src/frontend/admin/.env.local.example  src/frontend/admin/.env.local
```

### 2.2. Cấu hình Frontend .env.local
Để giả lập chuẩn Production (tránh lỗi CORS và test đúng routing), nên trỏ Frontend về **Nginx Gateway (Port 80)** thay vì trỏ trực tiếp vào port của từng service.

**File `src/frontend/admin/.env.local` & `src/frontend/chat/.env.local`:**
```ini
NUXT_PUBLIC_API_GATEWAY_URL=http://localhost
VITE_API_GATEWAY_URL=http://localhost

NUXT_PUBLIC_USER_SERVICE_PATH=/api/user
NUXT_PUBLIC_DOCUMENT_SERVICE_PATH=/api/documents
NUXT_PUBLIC_QUERY_SERVICE_PATH=/api/query
NUXT_PUBLIC_HR_SERVICE_PATH=/api/hr
NUXT_PUBLIC_MCP_SERVICE_PATH=/api/mcp
```

---

## 3. Khởi động Backend Stack

Sử dụng Docker Compose để dựng toàn bộ Infra và Backend Services:

```bash
docker compose -f docker-compose.e2e.yml up -d --build
```
*Lưu ý:*
- Lệnh này tự động chạy: Migrations, NATS Bootstrap, và **Seed Admin User**.
- Account mặc định: `admin@company.com` / `***REDACTED-SEED-ADMIN-PW***` (Xem `infra/e2e/seed_user.py`).
- Nếu dùng Qdrant Cloud, hãy đảm bảo `QDRANT_URL` trong `.env` có port (vd: `:80` hoặc `:443`) để tránh timeout.

---

## 4. Cấu hình & Chạy Frontend (Host)

Thực hiện trên máy host để có Hot-reload.

### 4.1. Admin App (Quan trọng: BaseURL)
Vì Admin chạy dưới path `/admin/` qua Nginx, bạn **PHẢI** cấu hình `baseURL` trong `src/frontend/admin/nuxt.config.ts`:

```typescript
export default defineNuxtConfig({
  app: {
    baseURL: '/admin/',
  },
  // ... rest of config
})
```

Chạy Admin:
```bash
cd src/frontend/admin
npm install
npm run dev -- --port 3001 --host 0.0.0.0
```

### 4.2. Chat App
Chạy Chat (mặc định port 3000):
```bash
cd src/frontend/chat
npm install
npm run dev -- --host 0.0.0.0
```

---

## 5. Khởi động Local Nginx Gateway

Để ghép luồng FE host vào Backend Docker, chạy một container Nginx tạm thời dùng host network:

1. **Tạo file config tạm** (Dựa trên `nginx/nginx.conf` nhưng trỏ FE về host):
   ```bash
   cp nginx/nginx.conf nginx/nginx_local.conf
   # Sửa các dòng proxy_pass sang localhost (Dùng port thật của từng service)
   sed -i 's/frontend-admin:3001/localhost:3001/g' nginx/nginx_local.conf
   sed -i 's/frontend-chat:3000/localhost:3000/g' nginx/nginx_local.conf
   sed -i 's/user-service:8000/localhost:8000/g' nginx/nginx_local.conf
   sed -i 's/document-service:8002/localhost:8002/g' nginx/nginx_local.conf
   sed -i 's/query-service:8001/localhost:8001/g' nginx/nginx_local.conf
   sed -i 's/hr-service:8004/localhost:8004/g' nginx/nginx_local.conf
   sed -i 's/mcp-service:8003/localhost:8003/g' nginx/nginx_local.conf
   ```

2. **Chạy Nginx**:
   ```bash
   docker run -d --name rag-nginx --network host \
     -v $(pwd)/nginx/nginx_local.conf:/etc/nginx/conf.d/default.conf:ro \
     nginx:alpine
   ```

Bây giờ bạn có thể truy cập toàn bộ hệ thống tại:
- **Chat**: [http://localhost/](http://localhost/)
- **Admin**: [http://localhost/admin/](http://localhost/admin/)

---

## 6. Kiểm tra Luồng E2E

1. **Login Admin**: Truy cập `/admin/login`, dùng `admin@company.com` / `***REDACTED-SEED-ADMIN-PW***`.
2. **Upload**: Vào **Upload Center**, chọn file `.txt` -> Click **Upload All**.
3. **Verify Ingest**: Đợi trạng thái đổi sang **"indexed"**. Check log `rag-worker` để xem quá trình chunk/embed.
4. **Chat**: Sang [http://localhost/](http://localhost/), login và hỏi nội dung liên quan đến file vừa upload.
5. **Citations**: Kiểm tra xem câu trả lời có kèm nguồn (Citations) và metadata không.

---

## 7. Dọn dẹp (Teardown)

```bash
# Xóa Backend
docker compose -f docker-compose.e2e.yml down -v

# Xóa Nginx Gateway
docker rm -f rag-nginx
```

---

## 8. Các Điểm Thiết Kế Quan Trọng (Constraints)

1. **Security**: FE luôn gọi qua Gateway (Port 80). Không gọi trực tiếp port service trong code (ngoại trừ lúc dev local debug lẻ).
2. **SSE/Streaming**: Chat UI dùng Server-Sent Events. Nginx config đã bọc `proxy_buffering off` để hỗ trợ stream token.
3. **Shared Components**: Cả 2 app dùng chung `frontend/base`. Sửa UI tại `base` sẽ cập nhật cho cả Admin & Chat.
4. **CORS**: Bằng cách dùng Nginx Gateway, chúng ta triệt tiêu lỗi CORS vì cả FE và API đều chung Origin (`localhost:80`).
