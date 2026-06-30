# DevOps Deployment Architecture

## Mục tiêu

Thiết lập deploy tự động trên GCP: khi code được merge/push vào branch `main`, GitHub Actions tự động deploy phiên bản mới lên production (`vsfchat.cloud`). `develop` là nhánh tích hợp/dev; merge `develop → main` để phát hành.

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
- `hr-service` (internal only, không route public qua Nginx)
- `nats` (JetStream enabled)
- `redis`

### Thành phần managed / external
- **GCP Cloud Storage (GCS)**: lưu file tài liệu gốc
- **Qdrant Cloud**: vector database
- **Cloud SQL PostgreSQL**: 6 databases riêng cho services (`user_db`, `doc_db`, `query_db`, `mcp_db`, `hr_db`, `langfuse_db`)
- **GitHub Actions**: CI/CD trigger từ branch `main`

> Frontend hiện chưa đủ code trong repo để containerize hoàn chỉnh, nên môi trường demo trước mắt tập trung vào backend/API. Khi frontend hoàn thiện, chỉ cần thêm container và route Nginx.

---

## Sơ đồ kết nối

```text
GitHub (branch main)
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
  - mcp-service      <-> hr-service (internal HTTP/gRPC)
  - hr-service       -> NATS JetStream (`hr.employee_profile.updated`)
  - query-service    <-> Redis
  - document-service <-> GCS
  - rag-worker       <-> GCS
  - rag-worker       <-> Qdrant Cloud
  - mcp-service      <-> Qdrant Cloud
  - user/document/query/mcp/hr-service <-> Cloud SQL PostgreSQL
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
- Phù hợp với yêu cầu "merge main là tự deploy"

---

## Môi trường hiện tại

Chỉ tạo **1 môi trường dev/demo**:
- branch deploy: `main`
- mục tiêu: để team tích hợp và demo nội bộ

- `main` -> production (`vsfchat.cloud`)
- `develop` -> nhánh tích hợp/dev (không tự deploy)

---

## Trách nhiệm DevOps trong repo này

1. Tạo và quản lý hạ tầng GCP
2. Viết Dockerfile còn thiếu
3. Viết `docker-compose.yml`
4. Viết `nginx/nginx.conf`
5. Cấu hình GitHub Actions deploy từ `main`
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
- `src/hr-service/Dockerfile`
- `.github/workflows/deploy.yml`
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
