# DevOps Deployment Architecture

## Mục tiêu

Thiết lập **1 môi trường dev/demo** trên GCP để khi code được merge vào branch `develop`, GitHub Actions tự động deploy phiên bản mới lên server demo.

Môi trường này ưu tiên:
- đơn giản để team mới vận hành được
- bám sát docs hiện có của repo
- đủ để backend/RAG connect và demo được flow chính

---

## Kiến trúc được chọn

### Thành phần chạy trên GCP VM (self-host)
- `nginx`
- `user-service`
- `document-service`
- `query-service`
- `rag-worker`
- `mcp-service`
- `nats` (JetStream enabled)
- `redis`

### Thành phần managed / external
- **GCP Cloud Storage (GCS)**: lưu file tài liệu gốc
- **Qdrant Cloud**: vector database
- **Cloud SQL PostgreSQL**: 4–5 databases riêng cho services
- **GitHub Actions**: CI/CD trigger từ branch `develop`

> Frontend hiện chưa đủ code trong repo để containerize hoàn chỉnh, nên môi trường demo trước mắt tập trung vào backend/API. Khi frontend hoàn thiện, chỉ cần thêm container và route Nginx.

---

## Sơ đồ kết nối

```text
GitHub (branch develop)
  -> GitHub Actions
  -> SSH vào GCP VM
  -> docker compose up --build -d

User / Team
  -> Nginx :80
     -> /api/user/*       -> user-service:8000
     -> /api/documents/*  -> document-service:8002
     -> /api/query/*      -> query-service:8001
     -> /api/mcp/*        -> mcp-service:8003

Services nội bộ
  - document-service <-> NATS JetStream
  - rag-worker       <-> NATS JetStream
  - query-service    <-> NATS JetStream
  - mcp-service      <-> NATS request-reply
  - query-service    <-> Redis
  - document-service <-> GCS
  - rag-worker       <-> GCS
  - rag-worker       <-> Qdrant Cloud
  - mcp-service      <-> Qdrant Cloud
  - user/document/query/mcp-service <-> Cloud SQL PostgreSQL
```

---

## Vì sao chọn kiến trúc này

### Không chọn GKE
- Quá nặng cho giai đoạn demo
- Team chưa có kinh nghiệm Kubernetes
- Tăng thời gian setup và debug

### Không chọn Cloud Run ngay
- NATS và stack nhiều service stateful sẽ khó hơn cho team mới
- Docker Compose trên VM bám docs hiện tại tốt hơn

### Chọn VM + Docker Compose
- Đơn giản nhất để có demo
- Dễ debug bằng SSH
- Phù hợp với yêu cầu "merge develop là tự deploy"

---

## Môi trường hiện tại

Chỉ tạo **1 môi trường dev/demo**:
- branch deploy: `develop`
- mục tiêu: để team tích hợp và demo nội bộ

Khi dự án ổn hơn có thể mở rộng:
- `develop` -> `dev/staging`
- `main` -> `production`

---

## Trách nhiệm DevOps trong repo này

1. Tạo và quản lý hạ tầng GCP
2. Viết Dockerfile còn thiếu
3. Viết `docker-compose.yml`
4. Viết `nginx/nginx.conf`
5. Cấu hình GitHub Actions deploy từ `develop`
6. Cung cấp thông tin kết nối cho team:
   - `GCS_BUCKET`
   - `QDRANT_URL`, `QDRANT_API_KEY`
   - `NATS_URL`
   - mẫu file `.env`
7. Viết tài liệu vận hành/deploy cho team

---

## Các file DevOps đã thêm trong repo

- `docker-compose.yml`
- `nginx/nginx.conf`
- `src/user-service/Dockerfile`
- `src/document-service/Dockerfile`
- `src/query-service/Dockerfile`
- `src/mcp-service/Dockerfile`
- `.github/workflows/deploy-develop.yml`
- `infra/gcp/gce-setup.sh`
- `deploy/env/*.env.example`
- `docs/devops-deployment-architecture.md`
- `docs/devops-runbook.md`
- `docs/team-infra-access.md`

---

## Lưu ý quan trọng

- `docker-compose.yml` hiện là bản **backend-first demo**. Frontend chưa được đưa vào vì repo chưa có app code hoàn chỉnh để containerize.
- Qdrant được chọn là **Qdrant Cloud**, không self-host trên VM.
- Storage được chọn là **GCS** theo docs, không dùng AWS S3.
- NATS được self-host trên VM để đơn giản hóa hạ tầng.