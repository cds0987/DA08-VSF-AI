# DevOps Runbook

## 1. Chuẩn bị local

- Có quyền push repo GitHub
- Có quyền thêm GitHub Secrets
- Có tài khoản GCP và quyền Owner/Editor project
- Có SSH key local

---

## 2. Chuẩn bị file env

Copy các file ví dụ trong `deploy/env/`:

- `user-service.env.example` -> `user-service.env`
- `document-service.env.example` -> `document-service.env`
- `query-service.env.example` -> `query-service.env`
- `rag-worker.env.example` -> `rag-worker.env`
- `mcp-service.env.example` -> `mcp-service.env`

Điền giá trị thật trước khi chạy deploy.

---

## 3. Chạy local bằng Docker Compose

```bash
docker compose up --build -d
```

Xem log:

```bash
docker compose logs -f user-service
docker compose logs -f document-service
docker compose logs -f query-service
docker compose logs -f rag-worker
docker compose logs -f mcp-service
```

Dừng:

```bash
docker compose down
```

---

## 4. Healthcheck sau deploy

- `GET /healthz` trên Nginx
- `GET /api/user/health`
- `GET /api/documents/health`
- `GET /api/query/health`
- `GET /health` của rag-worker nếu cần expose trực tiếp ở nội bộ

---

## 5. Flow GitHub Actions deploy

Workflow: `.github/workflows/deploy-develop.yml`

Trigger:
- push vào branch `develop`

Deploy script trên VM sẽ:
1. `git fetch`
2. `git checkout develop`
3. `git reset --hard origin/develop`
4. `docker compose up --build -d`
5. `docker image prune -f`

---

## 6. Rollback tạm thời

Nếu deploy lỗi:

```bash
cd <APP_DIR>
git log --oneline -n 5
git reset --hard <COMMIT_CU>
docker compose up --build -d
```

---

## 7. Thông tin cần giao cho backend team

### Document + RAG team
- `GCS_BUCKET`
- `GCP_PROJECT_ID`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `QDRANT_COLLECTION`
- `NATS_URL`

### Query team
- `NATS_URL`
- `REDIS_URL`
- `MCP_SERVICE_URL`
- `OPENAI_API_KEY`

### User/Document/Query/MCP DB teams
- `DATABASE_URL` tương ứng từng service
- `JWT_SECRET_KEY` shared

---

## 8. Việc cần làm sau khi frontend hoàn thiện

- thêm Dockerfile cho `src/frontend/chat`
- thêm Dockerfile cho `src/frontend/admin`
- cập nhật `docker-compose.yml`
- cập nhật Nginx route `/` và `/admin`

---

## 9. Cảnh báo hiện tại

- Repo hiện chưa có frontend hoàn chỉnh để deploy full stack
- Chưa có migration orchestration thống nhất cho mọi service
- Chưa có HTTPS/domain trong cấu hình hiện tại
- Chưa có production/staging split