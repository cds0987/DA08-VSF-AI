# CI/CD Onboarding — DA08-VSF

> ⚠️ **2026-06-13 di trú hạ tầng** — nguồn sự thật mới: [onboard_cicd.md](onboard_cicd.md).
> Project `vintravel-chatbot`; **1 VM** in-compose (BỎ Cloud SQL → `app-postgres`; Qdrant in-compose `qdrant:6333`); GCS keyless (SA `vsf-storage` gắn VM); **CI/CD từ fork `cds0987/DA08-VSF`**; production `http://35.240.193.13`. Deploy CHỈ qua CI.

Tài liệu cho teammate hiểu nhanh quy trình CI/CD và cách vận hành. Cập nhật: 2026-06-13.

---

## 1. Tổng quan

Mỗi push vào nhánh **`develop`** chạy pipeline (`.github/workflows/deploy-develop.yml`) với
**build CÓ CHỌN LỌC** — chỉ build/deploy phần thay đổi, không phải lúc nào cũng build cả 6:

```
push develop
   │
   ├─ Phase 0  DETECT        dò file thay đổi (paths-filter) → quyết định build/test/deploy gì
   │
   ├─ Phase 1  TEST          CHỈ khi rag-worker|mcp-service đổi → contract parity + unit test
   │                          ↓ pass
   ├─ Phase 2  BUILD+PUSH    build CHỈ service thay đổi → Docker Hub (:develop + :<git-sha>)
   │                          ↓ pushed
   └─ Phase 3  DEPLOY        CHỈ khi rag-worker|mcp|hr|docker-compose đổi
                              SSH VM → compose pull + up --no-build → HEALTH GATE
```

Job nối nhau bằng `needs`: fail phase trước thì phase sau **không chạy**.

> **VM KHÔNG build image**. Image build trên GitHub runner, đẩy Docker Hub, VM chỉ `pull`.
> Nhanh hơn, nhẹ VM, có versioning + rollback theo git-sha.

### Khi nào build lại cái gì? (build chọn lọc)

| File thay đổi trong push | Build image | Test | Deploy |
|--------------------------|-------------|------|--------|
| `src/<svc>/**` (1 service) | chỉ service đó | nếu là rag-worker/mcp | nếu là rag-worker/mcp/hr |
| `src/rag-worker/**` hoặc `src/mcp-service/**` | service đó | ✅ | ✅ |
| `src/user|document|query-service/**` | service đó | ❌ | ❌ (không nằm trong VM deploy) |
| `docker-compose.yml` | (không) | ❌ | ✅ (pull + up lại) |
| `.github/workflows/deploy-develop.yml` | **TẤT CẢ 6** (an toàn) | ✅ | ✅ |
| `docs/**`, `**.md` | **KHÔNG chạy gì** (`paths-ignore`) | — | — |

Phase 0 (`detect`) dùng `dorny/paths-filter` so path đổi với 6 service, xuất ra `services`
(JSON list để làm matrix build), `run_test`, `run_deploy`. Deploy luôn pull tag **`:develop`**
nên service không build lần này vẫn giữ image `:develop` cũ — không vỡ.

---

## 2. Các workflow trong repo

| File | Trigger | Vai trò |
|------|---------|---------|
| `deploy-develop.yml` | push `develop` | **CD 3-phase** (test → Docker Hub → deploy VM) |
| `rag-service-ci.yml` | push `nguyendev` (paths rag-worker/mcp) | CI: test + e2e + search-semantic 2 service |
| `hr-mcp-integration.yml` | push `nguyendev`/`develop`, PR `develop` | CI: integration hr-service ↔ mcp-service (Docker thật) |
| `e2e-cloud.yml` | (xem file) | e2e trên hạ tầng cloud |

Luồng làm việc khuyến nghị: code trên feature branch → CI feature branch xanh → merge vào
`develop` → CD tự deploy lên VM.

---

## 3. Hạ tầng

- **Registry**: Docker Hub, namespace **`dadlks08`** → image `dadlks08/<service>` (6 service:
  `rag-worker`, `mcp-service`, `hr-service`, `user-service`, `document-service`, `query-service`).
- **VM**: GCP `vsf-rag-demo-vm` (project `vintravel-chatbot`, zone `asia-southeast1-a`),
  IP ngoài `34.158.47.236`. App dir: `/home/TOMAP/DA08-VSF`.
- **Compose**: `docker-compose.yml` — 6 service dùng `image: ${DOCKERHUB_USERNAME}/<svc>:${IMAGE_TAG:-develop}`
  (KHÔNG còn `build:`). Hạ tầng kèm: NATS, Redis, **Qdrant nội bộ** (`qdrant:6333`), nginx.
- **DB**: Cloud SQL Postgres `app-postgres` — `rag_db` (rag-worker), `hr_db` (hr-service).
- **Qdrant**: chạy **nội bộ trong compose** (`http://qdrant:6333`), KHÔNG dùng Qdrant Cloud.

---

## 4. GitHub Secrets (bắt buộc)

Repo → Settings → Secrets and variables → Actions. Pipeline cần:

| Secret | Nội dung |
|--------|----------|
| `DOCKERHUB_USERNAME` | `dadlks08` |
| `DOCKERHUB_TOKEN` | Docker Hub access token (Read & Write) |
| `VM_HOST` / `VM_USER` / `VM_SSH_KEY` | IP VM / user (`TOMAP`) / **private key** CI (đủ dòng BEGIN/END) |
| `APP_DIR` | đường dẫn app trên VM |
| `RAG_WORKER_ENV` | **toàn bộ nội dung** file `deploy/env/rag-worker.env` |
| `MCP_SERVICE_ENV` | **toàn bộ nội dung** file `deploy/env/mcp-service.env` |
| `HR_SERVICE_ENV` | **toàn bộ nội dung** file `deploy/env/hr-service.env` |

> 3 secret `*_ENV` = NỘI DUNG file `.env` (không phải đường dẫn). Deploy ghi thẳng ra
> `deploy/env/*.env` trên VM. **Build xanh KHÔNG có nghĩa các secret này đã set** — build chỉ
> cần source code; env chỉ dùng ở phase deploy.

`VM_SSH_KEY`: là **private key** (ed25519) của cặp khóa CI. Public key tương ứng phải nằm trong
VM metadata `ssh-keys` (hoặc `~/.ssh/authorized_keys`) của user `TOMAP`. OS Login đang TẮT.

---

## 5. Quy ước biến môi trường (env) — ĐỌC KỸ

Các điểm hay làm sai khi sửa 3 secret `*_ENV`:

1. **Qdrant phải NỘI BỘ**: `VECTOR_DB_URL=http://qdrant:6333`, `VECTOR_DB_API_KEY=` (rỗng).
   ⚠️ KHÔNG trỏ `*.qdrant.io` (Qdrant Cloud) — endpoint cloud trả **404** làm rag-worker
   startup crash → unhealthy → restart loop → deploy FAIL.
2. **rag-worker và mcp-service phải khớp contract**: cùng `EMBED_MODEL`, `EMBED_DIMENSION`,
   `VECTOR_DB_PROVIDER`, `VECTOR_COLLECTION`, cùng Qdrant URL. Lệch → mcp verify fail-closed.
3. **Token nội bộ hr ↔ mcp phải giống nhau**: `MCP_SERVICE_ENV.HR_SERVICE_INTERNAL_TOKEN`
   == `HR_SERVICE_ENV.HR_INTERNAL_TOKEN`.
4. **DB**: `HR_DATABASE_URL` trỏ `hr_db`, `RAG_DATABASE_URL` (root .env / compose) trỏ `rag_db`.
   Driver bắt buộc `postgresql+psycopg://` (KHÔNG asyncpg cho rag-worker/hr migrate).

Template: xem `deploy/env/*.env.example` trên nhánh `nguyendev`/`DevOps`. Biến thật mcp đọc nằm
trong `src/mcp-service/config.yaml` (dạng `${VAR:-default}`), KHÔNG phải file example (đã cũ).

---

## 6. Cách deploy / vận hành

### Deploy bình thường
Merge code vào `develop` rồi push → pipeline tự chạy. Theo dõi ở tab **Actions**.

```bash
git checkout develop
git merge <feature-branch>
git push origin develop
```

### Rollback về 1 commit cũ
Image có tag `:<git-sha>` cho **những lần thực sự build** service đó (build chọn lọc). Chọn
sha có đủ tag cho service cần rollback. SSH vào VM và up lại với tag cũ:

```bash
cd /home/TOMAP/DA08-VSF
export DOCKERHUB_USERNAME=dadlks08
export IMAGE_TAG=<git-sha-muốn-rollback>
docker compose pull rag-worker mcp-service hr-service
docker compose up -d --no-build rag-worker mcp-service hr-service
```

### Kiểm tra health trên VM
```bash
sudo docker compose -f /home/TOMAP/DA08-VSF/docker-compose.yml ps
sudo docker compose -f .../docker-compose.yml logs --tail 60 rag-worker
```
Health gate của deploy chờ: `rag-worker=healthy`, `hr-service=healthy`,
`mcp-service=running` (restarts ≤ 2). Không đạt trong ~5 phút → job FAIL + dump log container.

---

## 7. Troubleshoot nhanh (theo lỗi thật đã gặp)

| Triệu chứng trong log deploy | Nguyên nhân | Cách sửa |
|------------------------------|-------------|----------|
| `ssh: no key found` / `handshake failed` | `VM_SSH_KEY` rỗng/sai định dạng | Dán lại private key đầy đủ (cả BEGIN/END); public key phải ở VM metadata |
| `could not read Username for 'https://github.com'` | Repo private, VM remote HTTPS | Đã xử lý: deploy fetch bằng `GITHUB_TOKEN` (cần `permissions: contents: read`) |
| `printf '%s\n' ""` → env rỗng | Secret `*_ENV` chưa set | Set 3 secret env (nội dung file) |
| rag-worker `404 Not Found` từ `*.qdrant.io` → unhealthy | env trỏ Qdrant Cloud | Đổi `VECTOR_DB_URL=http://qdrant:6333`, bỏ API key |
| `dependency rag-worker failed to start ... unhealthy` | rag-worker startup crash (xem log nó) | Soi `docker logs rag-worker`; thường do Qdrant/DB |

---

## 8. Lần đầu setup môi trường mới (checklist)

1. Tạo Docker Hub account + access token (Read & Write).
2. Set 8 secret ở mục 4.
3. Tạo cặp khóa CI (ed25519); public key → VM metadata `ssh-keys` user deploy; private key → `VM_SSH_KEY`.
4. Tạo sẵn DB `rag_db` + `hr_db` trên Cloud SQL, mở mạng VM → Cloud SQL.
5. Push `develop` → kiểm Actions: test → build-push (6 image) → deploy đều xanh.
6. Sau deploy, Qdrant nội bộ rỗng → chạy ingest corpus để search có dữ liệu.
