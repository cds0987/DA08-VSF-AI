# Onboarding: thao tác GCP & CI/CD từ một PC mới

> Mục tiêu: cầm 1 máy trắng (Windows) là **đăng nhập GCP, SSH vào VM, đụng được Cloud SQL / GCS / Qdrant, và hiểu luồng CI/CD** trong thời gian ngắn nhất, không vướng các bẫy thực tế của project này.

Tài liệu liên quan (đọc kèm khi cần đào sâu):
- [devops-deployment-architecture.md](devops-deployment-architecture.md) — kiến trúc tổng thể.
- [ci-cd-onboarding.md](ci-cd-onboarding.md) — chi tiết pipeline build/deploy.
- [team-infra-access.md](team-infra-access.md) — phân quyền truy cập hạ tầng.
- [devops-runbook.md](devops-runbook.md) — xử lý sự cố vận hành.

---

## 0. Thông số project (tra nhanh)

| Hạng mục | Giá trị |
|---|---|
| GCP Project ID | `vsf-rag-chatbot-dev` |
| Region chính | `asia-southeast1` (Singapore) |
| VM app (compose) | `vsf-rag-demo-vm` — zone `asia-southeast1-a` |
| VM Qdrant | `qdrant-base` — zone `asia-southeast1-c` |
| Cloud SQL (Postgres) | host `34.87.63.152:5432` (6 DB: `user_db`, `doc_db`, `query_db`, `mcp_db`, `hr_db`, `langfuse_db`) |
| GCS bucket tài liệu | `vsf-rag-chatbot-docs-dev` |
| App dir trên VM | `~/DA08-VSF` (của user deploy; `docker-compose.yml` + `deploy/env/`) |
| Git repo | `github.com/lehuuhung2001/DA08-VSF` (private) — branch deploy: `develop` |

> Secret thật (OpenAI key, DB pass, JWT, GCS HMAC, internal token) **không nằm trong git**. Chúng ở **GitHub Secrets** và được ghi ra `deploy/env/*.env` trên VM lúc deploy. Xem mục 6.

---

## 1. Cài công cụ trên máy mới (Windows)

```powershell
# Google Cloud SDK (gcloud)
winget install --id Google.CloudSDK -e

# Git (nếu chưa có)
winget install --id Git.Git -e

# (khuyến nghị) GitHub CLI — máy hiện tại KHÔNG có, nên thao tác CI phải gọi REST trực tiếp (xem mục 7)
winget install --id GitHub.cli -e
```

Mở **PowerShell mới** sau khi cài để PATH cập nhật. Kiểm tra:

```powershell
gcloud version
git --version
```

---

## 2. Đăng nhập Google / GCP

### 2.1 Auth cho người dùng (tương tác — dùng để vận hành tay)

```powershell
gcloud auth login                 # mở browser, đăng nhập tài khoản được cấp quyền
gcloud config set project vsf-rag-chatbot-dev
gcloud config set compute/region asia-southeast1
gcloud config set core/disable_prompts true   # tránh prompt treo trong script/agent
```

Kiểm tra:

```powershell
gcloud auth list          # thấy account active
gcloud config list        # thấy project = vsf-rag-chatbot-dev
```

### 2.2 ⚠️ BẪY SSL sau proxy công ty (rất hay gặp ở môi trường nội bộ)

Triệu chứng:

```
ERROR: ... There was a problem refreshing your current auth tokens:
SSLError(SSLCertVerificationError ... unable to get local issuer certificate)
```

Nguyên nhân: HTTPS thường (Edge/Chrome, `Invoke-RestMethod`) tin **Windows cert store**, nhưng gcloud chạy Python certifi đi kèm nên **không tin CA của proxy công ty**. Cách sửa: export CA từ Windows store ra 1 file PEM rồi trỏ gcloud vào đó.

```powershell
# Tạo bundle PEM từ Windows cert store
$pem = "$env:USERPROFILE\.gcp\win-ca-bundle.pem"
New-Item -ItemType Directory -Force (Split-Path $pem) | Out-Null
$sb = New-Object System.Text.StringBuilder
foreach ($store in 'Root','CA') {
  Get-ChildItem "Cert:\LocalMachine\$store","Cert:\CurrentUser\$store" -ErrorAction SilentlyContinue | ForEach-Object {
    [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
    [void]$sb.AppendLine([Convert]::ToBase64String($_.RawData,'InsertLineBreaks'))
    [void]$sb.AppendLine("-----END CERTIFICATE-----")
  }
}
Set-Content -Path $pem -Value $sb.ToString() -Encoding ascii

# Trỏ gcloud vào bundle
gcloud config set core/custom_ca_certs_file $pem
```

> Lưu ý: cùng máy đó nếu chạy Python/boto3/requests bị lỗi tương tự, set thêm biến môi trường
> `REQUESTS_CA_BUNDLE` và `SSL_CERT_FILE` trỏ về cùng file PEM.

### 2.3 Application Default Credentials (cho code/SDK trên máy chạy local)

Nếu bạn chạy service hoặc script Python đụng GCS/Cloud SQL trên máy:

```powershell
gcloud auth application-default login
# tạo file ADC tại %APPDATA%\gcloud\application_default_credentials.json
```

---

## 3. Tạo & quản lý key

### 3.1 Service Account key (cho app/CI dùng GCP API — KHÔNG dùng tài khoản người)

```powershell
# Liệt kê SA hiện có
gcloud iam service-accounts list

# Tạo key JSON cho 1 SA (ví dụ SA ingest/GCS)
gcloud iam service-accounts keys create gcp-sa.json `
  --iam-account=<SA_NAME>@vsf-rag-chatbot-dev.iam.gserviceaccount.com
```

> File `gcp-sa.json` là **secret** — KHÔNG commit, để ngoài git (đã có trong `.gitignore`).
> Trên VM nó được mount vào container theo `GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-sa.json`.

Nguyên tắc:
- Mỗi key tạo ra phải **xoay/huỷ** khi rời máy: `gcloud iam service-accounts keys delete <KEY_ID> --iam-account=...`.
- Ưu tiên **không tạo key tĩnh** nếu có thể — dùng ADC (mục 2.3) hoặc Workload Identity. Key JSON chỉ tạo khi bắt buộc.

### 3.2 GCS HMAC key (cho boto3 / S3-interop — rag-worker đang dùng)

rag-worker đọc GCS qua giao thức S3 (`S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`). Tạo HMAC:

```powershell
gcloud storage hmac create <SA_NAME>@vsf-rag-chatbot-dev.iam.gserviceaccount.com
# in ra accessId + secret -> đưa vào deploy/env/rag-worker.env (hoặc GitHub Secret)
```

> Bẫy boto3 + GCS: tắt checksum của botocore, set default project cho user-HMAC, và bucket phải bật billing thì PUT mới chạy. (xem ghi chú đội RAG)

### 3.3 SSH key cho VM

gcloud tự sinh & đẩy SSH key vào instance metadata ở lần SSH đầu (mục 4). Không cần tạo tay. Key nằm ở `%USERPROFILE%\.ssh\google_compute_engine`.

---

## 4. Truy cập VM (cách hiệu quả nhất)

Dùng `gcloud compute ssh` — tự lo SSH key + IAM, không cần biết IP, không cần mở firewall SSH public:

```powershell
# SSH tương tác
gcloud compute ssh vsf-rag-demo-vm --zone=asia-southeast1-a

# Chạy 1 lệnh rồi thoát (dùng trong script/agent)
gcloud compute ssh vsf-rag-demo-vm --zone=asia-southeast1-a --quiet `
  --command="docker compose -f ~/DA08-VSF/docker-compose.yml ps"
```

Lần đầu sẽ hỏi cache host key — chọn `y`. Sau đó các lệnh tiếp theo chạy thẳng.

Việc thường làm trên VM:

```bash
cd ~/DA08-VSF
docker compose ps                          # trạng thái service
docker compose logs --tail 80 rag-worker   # log 1 service
docker inspect -f '{{.State.Health.Status}}' da08-vsf-rag-worker-1
sudo ls -la deploy/env/                     # các file env thật (secret)
```

> Lưu ý quyền: `deploy/env/` thuộc user đã deploy. Nếu bạn SSH bằng account khác, đọc bằng
> `sudo cat ~<deploy_user>/DA08-VSF/deploy/env/<file>.env` (không `cd` được vào thư mục của họ).

---

## 5. Truy cập Cloud SQL (Postgres)

Hai cách:

**A. Qua VM (đơn giản nhất — VM đã được whitelist):**
```bash
# trên VM
psql "postgresql://postgres:<PASS>@34.87.63.152:5432/query_db"
```

**B. Từ máy local qua Cloud SQL Auth Proxy (an toàn, không cần mở IP):**
```powershell
gcloud auth application-default login
# tải cloud-sql-proxy.exe, rồi:
.\cloud-sql-proxy.exe vsf-rag-chatbot-dev:asia-southeast1:<INSTANCE> --port 5432
# sau đó psql/DBeaver nối localhost:5432
```

> DB password & connection string thật nằm trong `deploy/env/*.env` trên VM, không có trong git.

---

## 6. Bí mật sống ở đâu (mental model)

```
GitHub Secrets ──(${{ secrets.X }} lúc CI chạy)──┐
                                                 ├─→ ENV của job CI (test/build)
                                                 └─→ ghi ra deploy/env/*.env trên VM lúc deploy
                                                        └─→ docker-compose env_file → container
```

- Xem/sửa secret: **GitHub repo → Settings → Secrets and variables → Actions**.
- 3 secret đặc biệt chứa NGUYÊN file env: `RAG_WORKER_ENV`, `MCP_SERVICE_ENV`, `HR_SERVICE_ENV`.
- Trên VM xem giá trị đang chạy: `sudo cat ~/DA08-VSF/deploy/env/<svc>.env`.
- **Không bao giờ** paste secret thật vào commit, PR, chat, hay doc. Khi nghi lộ → rotate ngay
  (OpenAI key, DB pass, GCS HMAC là ưu tiên rotate cao nhất).

---

## 7. Thao tác CI/CD khi máy KHÔNG có `gh` CLI

Máy team hiện không cài `gh`. Để xem trạng thái Actions, mượn PAT từ git credential rồi gọi REST:

```powershell
# Lấy token git đã lưu (credential manager)
$token = (cmd /c "git credential fill" `
  --% <<< "protocol=https`nhost=github.com`n`n" | Select-String '^password=').ToString().Substring(9)

$headers = @{ Authorization = "token $token"; Accept = "application/vnd.github+json" }

# Danh sách run gần nhất của workflow deploy + thời gian chạy
$runs = Invoke-RestMethod -Headers $headers `
  "https://api.github.com/repos/lehuuhung2001/DA08-VSF/actions/workflows/deploy-develop.yml/runs?per_page=10"
$runs.workflow_runs | ForEach-Object {
  $min = [math]::Round(([datetime]$_.updated_at - [datetime]$_.created_at).TotalMinutes,1)
  [PSCustomObject]@{ Run=$_.run_number; Concl=$_.conclusion; Min=$min; SHA=$_.head_sha.Substring(0,7) }
} | Format-Table -AutoSize

# Xem job của 1 run cụ thể (tìm job nào chậm)
# Invoke-RestMethod -Headers $headers ".../actions/runs/<RUN_ID>/jobs"
```

> Nếu cài được `gh` thì đơn giản hơn nhiều: `gh run list -w deploy-develop.yml`,
> `gh run view <id> --log`. Khuyến nghị cài để vận hành lâu dài.

### Luồng CI/CD tóm tắt
Push lên `develop` → workflow `deploy-develop.yml` 3 phase:
1. **detect** (paths-filter) — chỉ build service có file đổi; sửa workflow → build tất cả.
2. **test** — chỉ khi rag-worker/mcp đổi (parity + unit test).
3. **build-push** — build image service đổi → Docker Hub (`:develop` + `:<sha>`), cache qua GHA.
4. **deploy** — SSH VM: `git reset --hard origin/develop` → ghi env → `docker compose pull && up` → health gate.

Sửa `docs/**` hoặc `**.md` → **không trigger gì** (paths-ignore).

---

## 8. Checklist máy mới (rút gọn)

- [ ] `winget install Google.CloudSDK Git.Git` (+ `GitHub.cli` khuyến nghị)
- [ ] `gcloud auth login` → `gcloud config set project vsf-rag-chatbot-dev`
- [ ] Nếu lỗi SSL: tạo `win-ca-bundle.pem` + `gcloud config set core/custom_ca_certs_file ...` (mục 2.2)
- [ ] `gcloud compute instances list` chạy được (xác nhận auth OK)
- [ ] `gcloud compute ssh vsf-rag-demo-vm --zone=asia-southeast1-a` vào được VM
- [ ] (nếu chạy code local) `gcloud auth application-default login`
- [ ] Xác nhận đọc được `deploy/env/` trên VM (mục 4)
- [ ] Rời máy/đổi máy → **xoá SA key & HMAC** đã tạo, gỡ credential git đã lưu

---

## 9. Vệ sinh bảo mật khi rời máy

```powershell
gcloud auth revoke --all
gcloud auth application-default revoke
# xoá key JSON / HMAC đã tạo cho riêng máy này (mục 3)
# xoá credential GitHub đã lưu nếu là máy dùng chung
```

---

## 10. Kiến thức tích luỹ (đã verify — đừng dò lại)

> Phần này gom các sự thật & bẫy đã tốn nhiều vòng debug, để session/máy sau không phải làm lại từ đầu. Mốc verify: **2026-06-09**. Code có thể đổi → kiểm lại trước khi khẳng định.

### 10.1 Inventory GCP chính xác

| Thành phần | Chi tiết |
|---|---|
| Project | `vsf-rag-chatbot-dev`, **number `538092122679`** |
| Cloud SQL instance | `vsf-rag-postgres-dev`, **POSTGRES_18**, asia-southeast1, IP `34.87.63.152`, superuser `postgres` / pass `***REDACTED-DB-PW***` (URL-encode `%401`) |
| VM app | `vsf-rag-demo-vm` — asia-southeast1-a, e2-standard-2, ext `34.158.47.236` |
| VM Qdrant | `qdrant-base` — asia-southeast1-c, e2-medium, ext `34.87.176.141` |
| GCS | `gs://vsf-rag-chatbot-docs-dev/` |
| Docker Hub | namespace `dadlks08` (`dadlks08/<svc>:develop` + `:<git-sha>`) |
| VM deploy user | `tranhuugiahuynb`, repo `/home/tranhuugiahuynb/DA08-VSF`, compose project `da08-vsf` |

- **KHÔNG có Cloud Run** — dù một số config gợi ý vậy, Cloud Run API chưa bật, mọi service chạy bằng `docker compose` trên VM.
- gcloud bản winget nằm ở `...\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd` (kèm gsutil, bq). Login hiện tại: `ttnguyen1410@gmail.com`.

### 10.2 SSH vào VM — dùng IAP tunnel

Cách ổn định nhất (không phụ thuộc IP public / firewall SSH):

```powershell
gcloud compute ssh vsf-rag-demo-vm --zone=asia-southeast1-a --tunnel-through-iap --quiet `
  --command="docker compose -f ~/DA08-VSF/docker-compose.yml ps"
```

- Lần đầu plink hỏi cache host key → nhập `y`.
- Repo trên VM thuộc `tranhuugiahuynb` → đọc/ghi file của họ phải `sudo`; **không `cd` được** vào thư mục home của họ bằng account khác, dùng `sudo cat <path>` với đường dẫn tuyệt đối.

### 10.3 Qdrant thật của runtime ≠ container "qdrant" rỗng

- Qdrant production = **VM `qdrant-base` (34.87.176.141)**: Qdrant bind `127.0.0.1:6333`, đứng sau **nginx :80 + Basic Auth** (`/etc/nginx/.htpasswd`, user `qdrantteam` / pass `123`).
- **BẪY port:** URL http thiếu port → qdrant-client rớt về `:6333` → connection refused. Phải ghi **rõ `:80`**: `VECTOR_DB_URL=http://34.87.176.141:80` + `VECTOR_DB_BASIC_AUTH=***REDACTED-QDRANT-AUTH***`, để trống `VECTOR_DB_API_KEY`. (SCHEME_FORCED_PORT chỉ ép https→443, không ép http.)
- Trong compose nội bộ thì các service trỏ `http://qdrant:6333` — nhưng **container `qdrant` trên demo VM là RÁC**, runtime thật ăn qdrant-base. Qdrant Cloud (`a0016cd3...`) là endpoint **CŨ** (e2e cleanup từng xoá collection → prod 404). Đừng trỏ env về Qdrant Cloud.
- Code rag-worker: mọi remote client phải qua `VectorStoreConfig.remote_client_kwargs()` (chuẩn hoá `:443` + timeout). Có **2 code-path** build config: `from_env` (env) và `to_vector_store_config` (config.yaml params, dùng ở production APP_ENV) — thêm field mới (vd `basic_auth`) phải map ở **cả hai** + thêm `${VAR}` vào config.yaml, nếu không CI production fail dù local pass.

### 10.4 CI/CD — bẫy đã tốn nhiều vòng debug

- **Repo PRIVATE → VM fetch bằng token ephemeral:** `git fetch https://x-access-token:${{ github.token }}@github.com/<repo>.git develop` + `reset --hard FETCH_HEAD` (cần `permissions: contents: read`). PAT mượn qua git-credential **không có quyền Administration** → không tạo được deploy key (404).
- **Env model:** commit `c48cf9a` xoá `deploy/env/` khỏi git → env files là **untracked trên VM**, sống sót qua `git reset --hard`. 3 secret `RAG_WORKER_ENV`/`MCP_SERVICE_ENV`/`HR_SERVICE_ENV` được workflow ghi lại mỗi lần deploy; còn `user/document/query.env` **nằm sẵn untracked**, workflow KHÔNG provision → đừng xoá tay.
- **Driver DB coupling:** mọi `DATABASE_URL` dùng `postgresql+psycopg://` (psycopg v3). Image phải có `psycopg[binary]`; user/document/query từng chỉ có `asyncpg` → recreate container crash `ModuleNotFoundError: psycopg`. Đổi driver trong env BẮT BUỘC thêm package tương ứng vào image.
- **mcp ↔ hr chung token:** `MCP.HR_SERVICE_INTERNAL_TOKEN` == `HR.HR_INTERNAL_TOKEN`. mcp image cũ (≤`204b989`) thiếu `_contribute_basic_auth` → nginx Qdrant trả 401; fix `git checkout origin/develop -- src/mcp-service` rồi rebuild.
- **Build-push xanh KHÔNG chứng minh env secret đúng** — build chỉ cần source; env chỉ dùng ở phase deploy.
- **Build chậm bất thường (1 service ~9' trong khi service khác ~30''):** do Dockerfile `COPY requirements.txt` (đổi 1 byte là bust cache) + deps không pin version. user-service inline deps thẳng trong Dockerfile nên không bị. → pin version + cân nhắc bỏ `build-essential` nếu chỉ dùng wheel binary.
- **New Relic APM:** cả 6 service bọc `newrelic-admin run-program`, license key EU hardcode trong anchor `x-newrelic` của compose, `NEW_RELIC_APP_NAME=vsf-<svc>`. Agent chỉ log "Reporting to" khi có request đầu tiên — service không traffic (vd mcp) im lặng là bình thường, không phải lỗi.

### 10.5 GCS qua S3-interop (boto3) — bẫy đã gặp

rag-worker đọc GCS bằng giao thức S3 (`S3_ENDPOINT_URL=https://storage.googleapis.com`, region `auto`, creds HMAC). Bẫy:

1. **PutObject `SignatureDoesNotMatch`/`Invalid argument` dù LIST OK** → botocore ≥1.36 tự thêm checksum CRC32 mà GCS không nhận. Fix: `Config(signature_version="s3v4", request_checksum_calculation="when_required", response_checksum_validation="when_required")`. 2 kwarg này **chỉ có ở botocore ≥1.36** → botocore cũ raise `TypeError`, phải `try/except` fallback.
2. **HMAC của user-account cần "Set default project"** ở Cloud Storage → Settings → Interoperability, nếu không bị từ chối.
3. **PutObject lên GCS cần billing account đang hoạt động** — project closed-billing thì LIST free nhưng PUT lỗi `closed billing account`.
4. Collection Qdrant đặt tên `{VECTOR_COLLECTION}__d{dim}` (vd `rag_chatbot__d1536`) khi monitor trực tiếp, không phải tên trần.

### 10.6 Kiểm CI khi không có `gh` (Bash tool)

```bash
TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill 2>/dev/null | grep '^password=' | cut -d= -f2-)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/lehuuhung2001/DA08-VSF/actions/runs?branch=develop&per_page=5"
# run_id -> /actions/runs/$RUN_ID/jobs -> job id -> /actions/jobs/$JID/logs
```

> Máy không có `jq` trong Bash → parse JSON bằng `python -c` hoặc dùng PowerShell `Invoke-RestMethod` + `ConvertFrom-Json` (mục 7). Shell state KHÔNG persist giữa các lần gọi Bash → lấy lại token trong mỗi lệnh. Chỉ GET, không in token.
