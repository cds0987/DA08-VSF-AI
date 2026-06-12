# ONBOARD — CI/CD & Env (handoff)

> ⚠️ **2026-06-13 di trú hạ tầng** — nguồn sự thật mới: [docs/onboard_cicd.md](docs/onboard_cicd.md).
> Project `vintravel-chatbot`; **1 VM** in-compose (BỎ Cloud SQL → `app-postgres`; BỎ qdrant-base → `qdrant:6333`); GCS keyless (SA `vsf-storage` gắn VM); **CI/CD từ fork `cds0987/DA08-VSF`**; production `http://35.240.193.13`. Deploy CHỈ qua CI, không `docker compose up` tay trên VM.

> File bàn giao để tiếp tục công việc CI/CD ở session khác. Nguồn sự thật chi tiết: [CICD.md](CICD.md) + [.github/workflows/deploy-develop.yml](.github/workflows/deploy-develop.yml).
> Trạng thái tại 2026-06-10, nhánh làm việc: **`nguyendev`**.

---

## 0. TL;DR đang làm gì

Tái cấu trúc env + thêm stage-gate cho CD, để chữa 3 vấn đề: env hardcode rải rác trên VM, env không đồng bộ giữa CI↔CD, và "CI pass nhưng prod fail".

Hai khối thay đổi (đã code xong, đã verify cục bộ, **commit trên `nguyendev`**):
1. **Env tập trung, commit thẳng vào git** (`deploy/env/common.env` + 6 file service, cascade).
2. **CD stage-gate**: smoke luồng-vàng CHỌN-LỌC theo `detect` + **auto-rollback** + query-service torch CPU-only.

---

## 1. Kiến trúc env (đã xong)

- `deploy/env/common.env` = biến dùng chung + **contract-critical** (rag-worker producer == mcp-service consumer): `AI_PROVIDER/OPENAI_API_KEY/EMBED_BASE_URL/EMBED_MODEL/EMBED_DIMENSION/VECTOR_DB_*/QDRANT_*`, cộng `JWT_SECRET_KEY/JWT_ALGORITHM/NATS_URL/REDIS_URL/Langfuse`.
- `deploy/env/<service>.env` = chỉ biến riêng. **`DATABASE_URL` per-service** (db name khác nhau; **driver `postgresql+psycopg`** cho TẤT CẢ — KHÔNG asyncpg, vì VM đang chạy psycopg3). hr dùng `HR_DATABASE_URL`.
- compose `env_file: [common.env, <svc>.env]` — common nạp trước, file service override khi trùng. Quy tắc thêm key: **mặc định để ở service; chỉ nâng lên common khi service thứ 2 cần**; nhóm contract-critical bắt buộc ở common.
- **Commit thẳng vào git** (repo private). `git reset --hard` lúc deploy đồng bộ env cùng code → hết drift. `.gitignore` KHÔNG còn ignore `deploy/env`.
- Giá trị thật đã điền từ container đang chạy trên VM (login/token/key khớp 100%): `JWT_SECRET_KEY`, `OPENAI_API_KEY` (OpenAI direct sk-proj), `MCP_INTERNAL_TOKEN` (mcp==query), `HR_INTERNAL_TOKEN` (hr==mcp), GCS HMAC (rag-worker S3_*), Cloud SQL `***REDACTED-DB-PW***@app-postgres`.
- **Bỏ bẫy cũ**: compose không còn `environment: DATABASE_URL` override (từng đè env_file); hr alembic `migrations/env.py` đọc `HR_DATABASE_URL` (hết split-brain migrate vs runtime); bind-mount SA đổi `/home/<user>/...` → `./deploy/secrets/gcp-sa.json`.

### Việc thủ công đã làm trên VM (KHÔNG trong git)
- SA JSON đã copy: `$APP_DIR/deploy/secrets/gcp-sa.json` (APP_DIR=`/home/TOMAP/DA08-VSF`). Untracked nên `git reset --hard` không xoá. Nếu dựng VM mới phải đặt lại file này.

---

## 2. CD stage-gate + auto-rollback (đã xong)

Trong job `deploy` ([.github/workflows/deploy-develop.yml](.github/workflows/deploy-develop.yml)):
- `trap` rollback đặt đầu script; bước **2b** ghi điểm rollback = image ID đang chạy (trước pull). Gate nào fail → `exit 1` → trap retag image cũ về `:develop` + recreate → **prod giữ bản trước, pipeline đỏ**.
- **Health gate (5)** + **smoke FE/nginx (5b)**: luôn chạy.
- **Smoke luồng-vàng (5c) — CHỌN LỌC theo `detect`** (mô phỏng FE gửi qua nginx, env prod thật + Cloud SQL + Qdrant nội bộ):
  - **DOC** (login + `GET /api/documents`): khi `document-service|user-service` đổi.
  - **RAG** (`query→mcp→rag→qdrant`, **sources>0**, outcome≠ERROR): khi `rag-worker|mcp-service|query-service` đổi.
  - **HR** (`query→mcp→hr_query`, outcome≠ERROR; + `hr-service /health`): khi `hr-service|mcp-hr|mcp-service|query-service` đổi.
  - Không service tầng-dưới đổi (chỉ FE/nginx) → bỏ qua 5c. `workflow_dispatch`/đổi workflow → smoke hết.
  - Creds smoke: `admin@company.com` / `***REDACTED-SEED-ADMIN-PW***` (inline, repo private). Parser SSE ghi ra `/tmp/smoke_parse.py` (Outcome enum: 5=SUCCESS, 6=ERROR).
- query-service `Dockerfile`: cài `torch --index-url .../whl/cpu` TRƯỚC requirements → bỏ CUDA wheels (image nhẹ vài GB; VM không GPU; llm-guard lazy-import, GUARDRAILS_MODE=off).

> Đã cân nhắc "staging stack song song biệt-lập" nhưng BỎ: 1 VM nhỏ (e2-standard-2/8GB), Qdrant không expose host port + service-name collision + cần staging Cloud SQL DB → quá tầm. Rollback đạt cùng mục tiêu (bản hỏng không phục vụ prod). Muốn làm thật cần: expose/tách Qdrant + DB staging + VM lớn hơn.

---

## 3. Quy trình CI/CD tổng (tham chiếu nhanh)

Trigger: push `develop` (bỏ qua docs/**, **.md) | `workflow_dispatch`. Concurrency `deploy-develop`.
`detect` (so commit trước) → validate chọn-lọc theo path (`contract`/`rag-test`/`search-semantic`/`hr-integration`/`e2e-cloud`) → `gate` (fail bất kỳ → chặn) → `build-push` chỉ service đổi → Docker Hub (:develop + :sha) → `deploy` (SSH VM: §2).

- **Validate jobs dùng env RIÊNG inline** (NATS/MinIO/Qdrant docker trong runner) — KHÔNG đụng `deploy/env/*.env`. Nên thay đổi env tập trung KHÔNG ảnh hưởng validate.
- GitHub secrets còn 13 (đã xoá 4 mồ côi `RAG_WORKER_ENV/MCP_SERVICE_ENV/HR_SERVICE_ENV/QUERY_SERVICE_ENV`). Còn lại đều dùng (CI e2e-cloud + build + deploy VM). Liệt kê: `APP_DIR DOCKERHUB_TOKEN DOCKERHUB_USERNAME GCS_HMAC_KEY GCS_HMAC_SECRET JWT_SECRET_KEY OPENAI_API_KEY QDRANT_API_KEY QDRANT_URL VECTOR_DB_BASIC_AUTH VM_HOST VM_SSH_KEY VM_USER`.

---

## 4. Hạ tầng (ghi nhớ vận hành)

- gcloud máy dev mặc định trỏ SAI project → luôn `gcloud config set project vintravel-chatbot` trước.
- VM `vsf-rag-demo-vm` (asia-southeast1-a, 34.158.47.236), SSH qua IAP: `gcloud compute ssh vsf-rag-demo-vm --zone asia-southeast1-a --tunnel-through-iap --command "..."`, cần `sudo docker`. Container prefix `da08-vsf-<svc>-1`. APP_DIR=`/home/TOMAP/DA08-VSF`.
- Cloud SQL `app-postgres` (postgres-18), GCS `vintravel-chatbot-docs-dev`. Qdrant chạy NỘI BỘ compose (`qdrant:6333`) — KHÔNG Qdrant Cloud trên VM.
- Đổi cấu hình vận hành (model/threshold/mode/key) = sửa `deploy/env/*.env` + commit + deploy. KHÔNG sửa code.

---

## 5. CÒN LẠI cần làm (next session)

1. **Merge `nguyendev` → `develop`** để pipeline chạy thật (đây là LẦN ĐẦU chạy với env-in-git + stage-gate; **deploy job auto-deploy PRODUCTION**). Hỏi user trước khi merge.
2. **Theo dõi run đầu tiên**, đặc biệt:
   - `build-push (query-service)`: torch CPU-only — đảm bảo `pip install torch --index-url .../cpu` + `llm-guard` cài được (nếu llm-guard pin torch version không có trên CPU index → build fail → cần pin `torch==<ver llm-guard chấp nhận>`).
   - deploy: `git reset --hard` lần đầu có thể vướng nếu trên VM còn `deploy/env/*.env` UNTRACKED (giờ thành tracked). Nếu git than "untracked would be overwritten" → SSH VM xoá tay `deploy/env/*.env` cũ 1 lần rồi chạy lại (giá trị y hệt, an toàn).
   - smoke 5c: nếu RAG `sources>0` fail do retrieval đổi → cân nhắc nới assert (chấp nhận outcome=SUCCESS). HR có thể NO_INFO nếu admin chưa có dữ liệu HR → đã chỉ assert outcome≠ERROR (OK).
3. Nếu rollback kích hoạt → đọc log job deploy, sửa nguyên nhân, deploy lại.

## 6. Lệnh hữu ích

```bash
# Smoke prod thủ công (giống gate 5c) — đặt PYTHONIOENCODING=utf-8 khi in tiếng Việt:
#  login -> token; POST /api/query/query (SSE) kiểm 'done'/sources; GET /api/documents
# Xem các script mẫu: tmp-ui-check/verify_rag.py, ui_check.py (Playwright FE).

# Liệt kê secrets (chỉ TÊN):
tok=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')
curl -s -H "Authorization: token $tok" https://api.github.com/repos/lehuuhung2001/DA08-VSF/actions/secrets?per_page=100

# Dump env container trên VM (lấy giá trị thật):
gcloud compute ssh vsf-rag-demo-vm --zone asia-southeast1-a --tunnel-through-iap \
  --command "sudo docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' da08-vsf-query-service-1"
```
