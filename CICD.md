# CI/CD — DA08-VSF (RAG Chatbot)

> Tài liệu ghi nhớ toàn bộ luồng CI/CD của project. Nguồn sự thật: [.github/workflows/deploy-develop.yml](.github/workflows/deploy-develop.yml).
> **Một pipeline hợp nhất duy nhất** — validate + build + deploy nằm chung 1 file.

---

## 1. Trigger & nguyên tắc

- **Khi nào chạy**: `push` vào nhánh `develop`, hoặc `workflow_dispatch` (chạy tay).
- **Bỏ qua hoàn toàn**: thay đổi chỉ `docs/**` hoặc `**.md` → KHÔNG chạy gì (`paths-ignore`).
- **Concurrency**: `group: deploy-develop`, `cancel-in-progress: false` → 2 merge sát nhau **xếp hàng**, không deploy chồng, không đụng cloud e2e dùng chung.
- **Bỏ qua validate (giữ build + deploy)**:
  - `workflow_dispatch` tick `skip_tests=true`, **hoặc**
  - nhét `[skip-tests]` vào commit message.

---

## 2. Phase 0 — DETECT (job `detect`)

Dùng `dorny/paths-filter@v3`, **so với commit TRƯỚC của push** (`github.event.before`, KHÔNG so `main`) → detect đúng file thực đổi. Push chỉ-FE / chỉ-nginx tự skip toàn bộ backend validate.

Xuất các cờ output:

| Output | Ý nghĩa |
|---|---|
| `services` | JSON list backend service cần build (giao 6 service với path đổi) |
| `run_rag` | `rag-worker` hoặc `mcp-service` đổi → chạy contract / rag-test / search-semantic |
| `run_hr` | `hr-service` hoặc mcp `hr_query.py`/`config.yaml` đổi → hr-integration |
| `run_e2e_cloud` | `rag-worker` / `mcp-service` / `document-service` / localtest đổi → e2e-cloud |
| `run_frontend` | `src/frontend/**` đổi → build FE |
| `run_deploy` | 1 trong 6 service hoặc `docker-compose.yml` đổi → deploy |

> **FORCE chạy TẤT CẢ** khi: `workflow_dispatch`, hoặc khi chính file workflow này (`.github/workflows/deploy-develop.yml`) bị đổi.

6 backend service: `rag-worker`, `mcp-service`, `hr-service`, `user-service`, `document-service`, `query-service`.

---

## 3. Phase 1 — VALIDATE (chọn lọc theo path)

| Job | Điều kiện | Mô tả |
|---|---|---|
| **contract** | `run_rag` | Parity contract vectorstore: rag-worker (producer) vs mcp-service (consumer). KHÔNG cần hạ tầng. Chạy `src/mcp-service/scripts/check_vectorstore_contract.py`. |
| **rag-test** | `run_rag` | rag-worker unit (infra off, `AI_PROVIDER=offline`) + **e2e protocol thật** với NATS(JetStream `-js`) + MinIO(S3) + Qdrant docker. |
| **search-semantic** | `run_rag` | rag-worker ingest TOÀN BỘ validation corpus qua NATS+MinIO → Qdrant; mcp-service semantic search lại trên CÙNG Qdrant. Drift (model lệch) **phải fail-closed**. |
| **hr-integration** | `run_hr` | hr-service (:8004) → Postgres thật; mcp-service (:8003) → hr-service HTTP. Cả hai build từ Dockerfile thật, cùng Docker network `hr-net`, nói HTTP thật. Có Alembic migrate + seed. |
| **e2e-cloud** | `run_e2e_cloud` | Full flow: document-service → NATS → rag-worker → Qdrant → mcp search, trên **GCS + Qdrant Cloud THẬT**. Postgres+NATS = container runner. Dọn sạch GCS+Qdrant sau mỗi run (`if: always()`). |

Secrets cloud cho e2e-cloud: `OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `VECTOR_DB_BASIC_AUTH`, `GCS_HMAC_KEY`, `GCS_HMAC_SECRET`, `JWT_SECRET_KEY`. Bucket: `vsf-rag-chatbot-docs-dev`.

---

## 4. Phase 2 — GATE (job `gate`)

- `needs: [contract, rag-test, search-semantic, hr-integration, e2e-cloud]`, `if: always()`.
- **Fail nếu BẤT KỲ validate nào = `failure` hoặc `cancelled`** → chặn build + deploy.
- Job `skipped` (do path không khớp) coi như **pass**.
- build-push + deploy đều `needs gate` → không qua gate = dừng.

---

## 5. Phase 3 — BUILD + PUSH (Docker Hub)

Chỉ chạy khi `gate.result == 'success'`. Mỗi image **2 tag**: `:develop` + `:<git-sha>`. Push lên Docker Hub user `${{ secrets.DOCKERHUB_USERNAME }}` (= `dadlks08`).

| Job | Điều kiện | Build gì |
|---|---|---|
| **build-push** | `services != '[]'` | Matrix = **CHỈ** backend service thay đổi (`context: ./src/<service>`). |
| **build-push-frontend** | `run_frontend` | 2 app Nuxt matrix `[admin, chat]`, image `frontend-<app>` (`context: ./src/frontend/<app>`). |
| **build-push-nginx** | `run_deploy` | nginx config **nướng vào image** (`nginx/Dockerfile` COPY nginx.conf), build MỖI lần deploy → image `:develop` luôn tồn tại + khớp git. Bỏ bind-mount → chống sửa tay trên VM. |

Cache: `type=gha,scope=<service>,mode=max`.

---

## 6. Phase 4 — DEPLOY (job `deploy`)

Chạy khi: gate success **&&** `run_deploy=true` **&&** build-push(+frontend) success/skipped **&&** build-push-nginx success.

SSH vào VM (`appleboy/ssh-action@v1.2.0`, `command_timeout: 20m`). Deploy dùng tag `:develop` — service không build lần này vẫn giữ image cũ.

Các bước script trên VM:

1. **Sync code = origin/develop**: `git fetch ... develop` + `git reset --hard FETCH_HEAD` → production phản ánh đúng git, **ghi đè mọi sửa tay trên VM**.
2. **Provision env** từ GitHub Secrets vào `deploy/env/*.env`: `rag-worker.env`, `mcp-service.env`, `hr-service.env`. Riêng **`query-service.env` CHỈ ghi đè khi secret `QUERY_SERVICE_ENV` có nội dung** (guard chống wipe config DB/auth/redis khiến service không boot).
3. **Login Docker Hub + `docker compose pull`** (KHÔNG build trên VM).
4. **`up -d --no-build`** tất cả service (deps: nats, rag-migrate, hr-migrate one-shot alembic); nginx `--force-recreate` để lấy image mới.
5. **HEALTH GATE**: poll tối đa 60 lần (`sleep 5`), `docker inspect` health/restart-count: `rag-worker`=healthy, `hr-service`=healthy, `mcp-service`=running (restarts≤2), `frontend-chat`/`frontend-admin`=running (restarts≤2). Fail → dump logs + `exit 1`.
6. **SMOKE qua nginx**: GET `/healthz`, `/`, `/admin/`. Không chỉ check 2xx/3xx mà còn **check nội dung**: không chứa placeholder cũ ("chưa được containerize") + phải có markup Nuxt (`__NUXT`/`/_nuxt/`/`/admin/_nuxt/`). Tránh pass giả khi nginx về placeholder cũ.
7. `docker image prune -f` dọn rác.

---

## 7. Hạ tầng & quy ước môi trường (ghi nhớ vận hành)

- **VM**: `vsf-rag-demo-vm` (34.158.47.236). SSH qua gcloud IAP tunnel, cần `sudo docker`. Project GCP `vsf-rag-chatbot-dev` chạy trên **VM (KHÔNG Cloud Run)**, Cloud SQL postgres-18, GCS bucket.
- **Container naming trên VM**: prefix `da08-vsf-<service>-1` (ví dụ `da08-vsf-rag-worker-1`).
- **Env Qdrant nội bộ**: trên VM phải trỏ `qdrant:6333` (nội bộ compose), KHÔNG phải Qdrant cloud — trỏ cloud gây 404 crash. (e2e-cloud trong CI mới dùng Qdrant Cloud thật.)
- **Đổi model LLM của query-service** = sửa GitHub Secret `QUERY_SERVICE_ENV` + deploy lại, KHÔNG sửa code.
- **CI secrets** set qua PyNaCl encrypt API (máy dev không có `gh` CLI). Kiểm Actions bằng `git credential fill` (mượn PAT) + curl REST.
- **Cảnh báo smoke test**: trước đây smoke chỉ check 2xx nên pass giả; bản hiện tại đã thêm check nội dung Nuxt/placeholder để bắt FE chưa serve.

---

## 8. Tóm tắt 1 dòng

**detect (so commit trước) → validate chọn lọc theo path → gate chặn nếu fail → build chỉ phần đổi lên Docker Hub (2 tag) → SSH VM: reset hard origin/develop + provision env từ secret + pull + up + health gate + smoke nội dung.**
