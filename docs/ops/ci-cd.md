# CI/CD — DA08-VSF (RAG Chatbot)

> Tài liệu ghi nhớ toàn bộ luồng CI/CD của project. Nguồn sự thật: [.github/workflows/deploy.yml](.github/workflows/deploy.yml).
> **Một pipeline hợp nhất duy nhất** — validate + build + deploy nằm chung 1 file.

---

## 1. Trigger & nguyên tắc

- **Khi nào chạy**: `push` vào nhánh `main`, hoặc `workflow_dispatch` (chạy tay).
- **Bỏ qua hoàn toàn**: thay đổi chỉ `docs/**` hoặc `**.md` → KHÔNG chạy gì (`paths-ignore`).
- **Concurrency**: `group: deploy-main`, `cancel-in-progress: false` → 2 merge sát nhau **xếp hàng**, không deploy chồng, không đụng cloud e2e dùng chung.
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

> **FORCE chạy TẤT CẢ** khi: `workflow_dispatch`, hoặc khi chính file workflow này (`.github/workflows/deploy.yml`) bị đổi.

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

Chỉ chạy khi `gate.result == 'success'`. Mỗi image **2 tag**: `:main` + `:<git-sha>`. Push lên Docker Hub user `${{ secrets.DOCKERHUB_USERNAME }}` (= `dadlks08`).

| Job | Điều kiện | Build gì |
|---|---|---|
| **build-push** | `services != '[]'` | Matrix = **CHỈ** backend service thay đổi (`context: ./src/<service>`). |
| **build-push-frontend** | `run_frontend` | 2 app Nuxt matrix `[admin, chat]`, image `frontend-<app>` (`context: ./src/frontend/<app>`). |
| **build-push-nginx** | `run_deploy` | nginx config **nướng vào image** (`nginx/Dockerfile` COPY nginx.conf), build MỖI lần deploy → image `:main` luôn tồn tại + khớp git. Bỏ bind-mount → chống sửa tay trên VM. |

Cache: `type=gha,scope=<service>,mode=max`.

---

## 6. Phase 4 — DEPLOY (job `deploy`)

Chạy khi: gate success **&&** `run_deploy=true` **&&** build-push(+frontend) success/skipped **&&** build-push-nginx success.

SSH vào VM (`appleboy/ssh-action@v1.2.0`, `command_timeout: 20m`). Deploy dùng tag `:main` — service không build lần này vẫn giữ image cũ.

**STAGE-GATE + AUTO-ROLLBACK** (mục tiêu: bản hỏng KHÔNG phục vụ production). Ngay đầu script đặt `trap` rollback; **2b** ghi điểm rollback = image ID đang chạy (trước khi pull). BẤT KỲ gate nào (health/FE/luồng-vàng) fail → `exit 1` → trap **tự retag image cũ về `:main` + recreate** → production giữ bản trước đang chạy được, pipeline = đỏ. (Fail TRƯỚC khi pull/up → chưa có điểm rollback → prod chưa bị đụng.)

Các bước script trên VM:

1. **Sync code = origin/main**: `git reset --hard FETCH_HEAD` → ghi đè mọi sửa tay trên VM (gồm `deploy/env/*.env`).
2. **Env đến TỪ git** (không provision từ secret). FAIL-FAST đủ 7 file env. Xem [§8](#8-kiến-trúc-env-common--per-service). `deploy/secrets/gcp-sa.json` đặt 1 lần trên VM.
3. **Login Docker Hub + `docker compose pull`** (KHÔNG build trên VM).
4. **`up -d --no-build`** + nginx `--force-recreate`.
5. **HEALTH GATE** (luôn): `docker inspect` health/restart-count rag-worker/hr=healthy, mcp/FE=running (restarts≤2). Fail → rollback.
6. **SMOKE nginx/FE** (luôn): GET `/healthz` `/` `/admin/` — check 2xx + markup Nuxt (`__NUXT`/`/_nuxt/`), không còn placeholder cũ. Fail → rollback.
7. **SMOKE LUỒNG-VÀNG — CHỌN LỌC theo `detect` (KHÔNG test hết mỗi lần)**, mô phỏng FE gửi qua nginx (env prod thật + Cloud SQL + Qdrant nội bộ — phần CI local-docker không đụng):

   | Smoke | Chạy KHI service đổi | Kiểm |
   |---|---|---|
   | **DOC** | document-service \| user-service | login + `GET /api/documents` 2xx |
   | **RAG** | rag-worker \| mcp-service \| query-service | `POST /api/query/query` → query→mcp→rag→qdrant, **sources>0**, outcome≠ERROR |
   | **HR** | hr-service \| mcp-hr \| mcp-service \| query-service | query→mcp→hr_query (outcome≠ERROR) + `hr-service /health` 2xx |

   Login chạy khi có ≥1 trong DOC/RAG/HR. Không service tầng-dưới nào đổi (chỉ FE/nginx) → **bỏ qua bước 7**. `workflow_dispatch` / đổi workflow → detect FORCE → smoke hết. Fail bất kỳ → rollback.
8. `docker image prune -f` (chỉ khi mọi gate pass; trước đó set `DEPLOY_OK=1` để trap không rollback).

---

## 7. Hạ tầng & quy ước môi trường (ghi nhớ vận hành)

- **VM**: `vsf-rag-demo-vm` (35.240.193.13). SSH qua gcloud IAP tunnel, cần `sudo docker`. Project GCP `vsf-rag-chatbot-dev` chạy trên **VM (KHÔNG Cloud Run)**, Cloud SQL postgres-18, GCS bucket.
- **Container naming trên VM**: prefix `da08-vsf-<service>-1` (ví dụ `da08-vsf-rag-worker-1`).
- **Env Qdrant nội bộ**: trên VM phải trỏ `qdrant:6333` (nội bộ compose), KHÔNG phải Qdrant cloud — trỏ cloud gây 404 crash. (e2e-cloud trong CI mới dùng Qdrant Cloud thật.)
- **Đổi cấu hình vận hành** (model LLM, threshold, mode, key...) = sửa `deploy/env/*.env` (hoặc `common.env`) + commit + deploy. KHÔNG sửa code (default trong code chỉ phục vụ local). Git là nguồn duy nhất.
- **CI secrets** (e2e-cloud: `OPENAI_API_KEY`, `QDRANT_*`, `GCS_HMAC_*`...) vẫn set qua PyNaCl encrypt API (máy dev không có `gh` CLI). Đây là secret cho JOB CI, KHÁC với env runtime (đã nằm trong git).
- **Cảnh báo smoke test**: trước đây smoke chỉ check 2xx nên pass giả; bản hiện tại đã thêm check nội dung Nuxt/placeholder để bắt FE chưa serve.

---

## 8. Kiến trúc env (common + per-service)

**Nguyên tắc: một nguồn sự thật = git.** `deploy/env/*.env` commit thẳng (repo private). Mỗi service load **2 file** theo thứ tự (file sau ĐÈ file trước):

```yaml
env_file:
  - ./deploy/env/common.env      # biến dùng chung — cascade
  - ./deploy/env/<service>.env    # chỉ phần riêng (override khi cần)
```

- **`common.env`**: biến nhiều service dùng + **contract-critical** (rag-worker producer == mcp-service consumer): `AI_PROVIDER`, `OPENAI_API_KEY`, `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_DIMENSION`, `VECTOR_DB_PROVIDER`, `VECTOR_COLLECTION`, `VECTOR_DB_URL`. Để chung 1 chỗ → **không service nào lệch** → mcp không fail-closed do drift. Ngoài ra: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `CORS_ORIGINS`, `QDRANT_URL/COLLECTION` (alias query đọc), `NATS_URL`, `REDIS_URL`, Langfuse.
- **Per-service `.env`**: chỉ biến riêng. `DATABASE_URL` per-service (db name + driver KHÁC nhau: rag/hr = `psycopg` sync, còn lại = `asyncpg`). mcp giữ reranker/retrieval; rag giữ parser/S3/caption; query giữ mode/agent; v.v.

**Bỏ bẫy cũ:** compose không còn `environment: DATABASE_URL` override (khối `environment` đè `env_file`, từng gây "sửa .env không ăn"). hr-service: alembic + runtime cùng đọc `HR_DATABASE_URL` (hết split-brain). Bind-mount SA đổi `/home/<user>/...` → `./deploy/secrets/gcp-sa.json`.

**Cần điền `<FILL_...>` trong env** (key/token thật): `JWT_SECRET_KEY`, `CORS_ORIGINS`, `OPENAI_API_KEY` (common); `MCP_INTERNAL_TOKEN` (mcp+query phải khớp); `HR_INTERNAL_TOKEN` (hr+mcp phải khớp); `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` GCS HMAC (rag-worker). Và đặt `deploy/secrets/gcp-sa.json` 1 lần trên VM.

---

## 9. Tóm tắt 1 dòng

**detect (so commit trước) → validate chọn lọc theo path → gate chặn nếu fail → build chỉ phần đổi lên Docker Hub (2 tag) → SSH VM: reset hard origin/main (kéo cả env) + ghi điểm rollback + pull + up + health gate + smoke FE + smoke luồng-vàng CHỌN LỌC theo detect (RAG/HR/DOC) → fail bất kỳ = AUTO-ROLLBACK về image trước, prod không hỏng.**
