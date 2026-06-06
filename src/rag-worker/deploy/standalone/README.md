# rag-worker standalone trên GCE VM + CD độc lập

rag-worker chạy như **server riêng lẻ** trên 1 GCE VM (project `vintravel-chatbot`),
mang theo Qdrant + Postgres. Các service khác nối vào qua 3 ranh giới — **không gọi
HTTP API của rag-worker** (nó chỉ có `/readyz` `/livez`):

| Ranh giới | Ai cấp | Cấu hình |
|-----------|--------|----------|
| **NATS** | TEAM KHÁC (server ngoài VM) | `NATS_URL` trong `rag-worker.env` trỏ ra ngoài |
| **Qdrant** | VM này (expose `6333`) | mcp-service đặt `VECTOR_DB_URL=http://<VM_IP>:6333` |
| **GCS** | managed (global) | HMAC key (S3-interop) trong `rag-worker.env` |

## Files

| File | Vai trò |
|------|---------|
| `docker-compose.standalone.yml` | rag-worker (pull từ Artifact Registry) + Qdrant + Postgres + migrate one-shot |
| `rag-worker.env.example` | template env → copy thành `rag-worker.env` trên VM, điền giá trị thật |
| `../../../../.github/workflows/rag-worker-standalone-deploy.yml` | CD: build → Artifact Registry → SSH pull |

## Luồng CD (nhánh `rag-worker-prod`)

```
push rag-worker-prod (đụng src/rag-worker/**)
  → CI build image
  → push asia-southeast1-docker.pkg.dev/vintravel-chatbot/rag-worker/rag-worker
  → SSH vào VM: git reset + ghi digest vào .env + docker compose pull && up -d
```

Mọi thay đổi DevOps commit vào `rag-worker-prod` sẽ tự động deploy. Image deploy theo
**digest cố định** (immutable), không theo tag mutable.

## Chuẩn bị 1 lần (GCP)

1. **Artifact Registry repo** (đã/đang tạo):
   ```bash
   gcloud artifacts repositories create rag-worker \
     --repository-format=docker --location=asia-southeast1 \
     --project=vintravel-chatbot
   ```
2. **Service account cho CI** (push image):
   ```bash
   gcloud iam service-accounts create rag-worker-ci --project=vintravel-chatbot
   gcloud projects add-iam-policy-binding vintravel-chatbot \
     --member="serviceAccount:rag-worker-ci@vintravel-chatbot.iam.gserviceaccount.com" \
     --role="roles/artifactregistry.writer"
   # tạo key JSON -> đưa vào GitHub secret GCP_SA_KEY (hoặc dùng Workload Identity)
   ```
3. **VM standalone** + SA gắn vào VM có quyền **đọc** Artifact Registry:
   - Bootstrap docker bằng `infra/gcp/gce-setup.sh`.
   - Gán VM 1 service account có role `roles/artifactregistry.reader`.
   - Trên VM: `gcloud auth configure-docker asia-southeast1-docker.pkg.dev` (CD cũng tự chạy).
4. **Firewall** mở `6333` CHỈ cho IP mcp-service (Qdrant không có auth):
   ```bash
   gcloud compute firewall-rules create allow-qdrant-from-mcp \
     --project=vintravel-chatbot --direction=INGRESS --action=ALLOW \
     --rules=tcp:6333 --source-ranges=<MCP_IP>/32 --target-tags=rag-worker
   ```
   (gán network tag `rag-worker` cho VM). KHÔNG mở 6333 cho `0.0.0.0/0`.

## GitHub Secrets cần có

| Secret | Ý nghĩa |
|--------|---------|
| `GCP_SA_KEY` | JSON key của `rag-worker-ci` (Artifact Registry Writer) |
| `RAGW_VM_HOST` | IP/host VM standalone |
| `RAGW_VM_USER` | user SSH |
| `RAGW_VM_SSH_KEY` | private key SSH |
| `RAGW_VM_SSH_PORT` | (tùy chọn, mặc định 22) |
| `RAGW_APP_DIR` | thư mục repo trên VM (vd `/home/ubuntu/DA08-VSF`) |

## Lần đầu trên VM (thủ công)

```bash
cd <RAGW_APP_DIR>/src/rag-worker/deploy/standalone
cp rag-worker.env.example rag-worker.env
#  → điền OPENAI_API_KEY, POSTGRES_PASSWORD, DATABASE_URL, NATS_URL, GCS HMAC, EMBED_DIMENSION
# CD lần kế sẽ tự ghi .env (RAG_WORKER_IMAGE) và up -d.
```

## ⚠️ Lưu ý vận hành (đã biết)

- **EMBED_DIMENSION**: `text-embedding-3-small` chiều gốc **1536**; k8s configmap đang để
  `1024` (lệch). Phải chốt 1 con số và dùng **y hệt** ở mcp-service, nếu không mcp fail-closed.
- **NATS chỉ kết nối lúc startup, không retry nền** → khi NATS team cấp lên/đổi, chạy
  `docker compose -f docker-compose.standalone.yml restart rag-worker`.
- **`/readyz` trả 200 cả khi ingest tắt** (degrade) → theo dõi log `nats_ingest_*` để biết
  ingest có chạy không, đừng chỉ dựa probe.
- **Self-host stateful = SPOF + tự lo backup** (Postgres `pg_dump`, Qdrant snapshot hoặc
  re-ingest). Chỉ hợp giai đoạn bootstrap; end-state nên Cloud SQL / Qdrant Cloud (chỉ đổi env).
