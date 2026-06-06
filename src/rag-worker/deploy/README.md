# Deploy artifacts — rag-worker

Artifact deploy do service `rag-worker` tự sở hữu.

> Hạ tầng (VM, Cloud SQL, Qdrant Cloud, GCS, NATS) do **Terraform** quản lý (DevOps).
> Thư mục này chỉ chứa cách **chạy rag-worker** trên hạ tầng đó.
> CI/CD pipeline + sự cố/bài học (vd dependency wheel cho Python 3.13): xem [`CI-CD.md`](./CI-CD.md).

## Cách deploy: docker trên GCE VM

Xem [`standalone/README.md`](./standalone/README.md). Có **2 lựa chọn compose**:

| File | Khi nào dùng |
|------|--------------|
| [`standalone/docker-compose.standalone.yml`](./standalone/docker-compose.standalone.yml) | **Bootstrap**: Postgres + Qdrant chạy **in-VM** (khi hạ tầng managed chưa sẵn). |
| [`standalone/docker-compose.cloud.yml`](./standalone/docker-compose.cloud.yml) | **End-state managed**: GCS (S3-interop) + Qdrant Cloud + Cloud SQL. Đã verify e2e — xem [`docs/e2e-cloud-ingest-search-test.md`](../../../docs/e2e-cloud-ingest-search-test.md). |

Cả hai dùng chung `rag-worker.env` (copy từ [`standalone/rag-worker.env.example`](./standalone/rag-worker.env.example), **gitignored**, điền giá trị thật trên VM).

## Rollout verify

1. `cp standalone/rag-worker.env.example standalone/rag-worker.env` rồi điền secret thật.
2. `docker compose -f standalone/docker-compose.<mode>.yml up -d --build` (migrate `alembic upgrade head` chạy trước qua service `migrate`).
3. Verify `GET /readyz` trả `200` (`curl 127.0.0.1:8000/readyz`).
4. Verify log có `vectorstore_contract_stamp_written` (đã đóng dấu contract lên Qdrant).
5. Verify `nats_ingest_started` (consumer ingest đã bật).

## Lưu ý

- **EMBED_DIMENSION** phải khớp tuyệt đối giữa rag-worker và mcp-service (`text-embedding-3-small` = **1536**), nếu không mcp-service fail-closed.
- Qdrant Cloud bắt buộc `:6333` + `https` + `VECTOR_DB_API_KEY`.
- DATABASE_URL của rag-worker dùng driver **psycopg v3** (`postgresql+psycopg://`), KHÔNG asyncpg.
