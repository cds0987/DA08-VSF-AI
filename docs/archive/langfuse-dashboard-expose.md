# Expose Langfuse dashboard cho team

Cho cả team xem trace Langfuse tại **https://langfuse.vsfchat.cloud** mà không cần SSH tunnel, không làm FE riêng, không mở thêm port firewall.

> ⚠ Tài liệu này KHÔNG chứa mật khẩu (repo public). Cách lấy credential xem mục [Truy cập](#truy-cập).

## Kiến trúc

```
Browser → https://langfuse.vsfchat.cloud
  → Cloudflare (proxied, TLS tự động, Universal SSL phủ *.vsfchat.cloud)
    → origin VM nginx :80   (Cloudflare Flexible SSL: CF↔origin = HTTP:80; origin 443 đóng)
      → nginx route theo Host → server block `langfuse.vsfchat.cloud`
        → auth_basic (Basic Auth, fail-closed)
          → proxy_pass http://langfuse:3000
```

- **Vì sao subdomain (không subpath):** Langfuse là Next.js, không chạy được dưới sub-path (`/langfuse/` vỡ asset/redirect) → phải đặt ở root của subdomain riêng.
- **Không mở port mới:** tái dùng 80/443 sẵn có (qua Cloudflare) → firewall VM vẫn chỉ 80/443/22.
- **Không ảnh hưởng ingest:** service nội bộ vẫn gửi trace qua `http://langfuse:3000` (mạng compose, `LANGFUSE_HOST` ở `deploy/env/common.env`), KHÔNG qua nginx public → Basic Auth chỉ chắn người xem dashboard.
- **nginx không phụ thuộc langfuse:** block langfuse dùng `resolver 127.0.0.11` + `proxy_pass` qua biến → nginx KHÔNG resolve `langfuse` lúc start; langfuse chết thì subdomain trả 502 nhưng cổng 80 (chat/admin/api) vẫn sống.

## Các thành phần

| Nơi | Nội dung |
|---|---|
| `nginx/nginx.conf` | `server { listen 80; server_name langfuse.vsfchat.cloud; auth_basic ...; proxy_pass http://$langfuse_upstream:3000 }` |
| `docker-compose.yml` (nginx) | mount `./deploy/nginx/.htpasswd:/etc/nginx/.htpasswd:ro` |
| `docker-compose.yml` (langfuse) | `NEXTAUTH_URL: https://langfuse.vsfchat.cloud` (giữ loopback `127.0.0.1:3100` cho `deploy.sh` readiness check) |
| `deploy/scripts/render-secrets.sh` | render `deploy/nginx/.htpasswd` từ GitHub Secret mỗi deploy (rỗng → fail-closed 401) |
| `.github/workflows/deploy-develop.yml` | forward secret `LANGFUSE_BASIC_AUTH_HTPASSWD` |
| `.gitignore` | bỏ qua `deploy/nginx/.htpasswd` |
| GitHub Secret `LANGFUSE_BASIC_AUTH_HTPASSWD` | 1 dòng htpasswd (`user:hash`) — nguồn-duy-nhất, render ra VM, không commit |
| Cloudflare DNS | A record `langfuse` → IP VM (proxied) |

## Truy cập

2 lớp, 2 mật khẩu khác nhau:

1. **Basic Auth (popup nginx):** user `team`. Mật khẩu = giá trị plaintext khi sinh GitHub Secret `LANGFUSE_BASIC_AUTH_HTPASSWD` bằng `htpasswd -nbB team <pass>` (hoặc apr1). VM chỉ giữ HASH → quên thì sinh secret mới + deploy lại.
2. **Login Langfuse:** `admin@company.com`, mật khẩu = GitHub Secret `LANGFUSE_INIT_USER_PASSWORD`. Lấy lại:
   ```bash
   gcloud compute ssh vsf-rag-demo-vm --zone asia-southeast1-a --tunnel-through-iap \
     --command "sudo docker inspect da08-vsf-langfuse-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep LANGFUSE_INIT_USER_PASSWORD"
   ```
   (Chỉ đóng đinh ở lần boot Langfuse ĐẦU; đổi secret không đổi pass đang chạy.)

Mời thêm người: Langfuse → Settings → Members → Invite (mỗi teammate account riêng).

## Sự cố đã gặp: Cloudflare 522 (root cause)

Lúc setup, A-record `langfuse` bị trỏ **IP cũ của VM** trong khi VM đã đổi IP:

- VM dùng **external IP ephemeral** → đổi khi VM **stop/start** (không phải reboot mềm). IP đã đổi `34.158.47.236` → `35.240.193.13`.
- IP cũ trả về pool Google (vẫn ping được nhưng port 80 đóng, không còn nginx).
- Domain chính `vsfchat.cloud` đã trỏ IP mới → sống. A-record `langfuse` (mới thêm) lỡ dùng IP cũ → Cloudflare proxy → bắt tay TCP `IP-cũ:80` (đóng) → **522 (connection timed out to origin)**.
- nginx ở IP mới vẫn serve Host=langfuse → 401 (code đúng). Sửa A-record → IP mới là chạy.

**Bài học:** lấy IP VM từ nguồn chuẩn (GCP `gcloud compute instances describe ... --format="get(networkInterfaces[0].accessConfigs[0].natIP)"`), KHÔNG từ docs (dễ cũ). 522 = DNS proxied OK nhưng IP origin sai/chết.

## Khuyến nghị: promote IP thành static

Tránh tái diễn mỗi lần VM stop/start:
```bash
gcloud compute addresses list                       # xem IP đang ephemeral
gcloud compute addresses create vsf-rag-vm-static \
  --addresses=35.240.193.13 --region=asia-southeast1   # gắn cứng IP đang dùng, không downtime
```
Sau đó IP không đổi nữa; cập nhật cả A-record `vsfchat.cloud` lẫn `langfuse` về IP tĩnh này.

## Hardening (khi có data thật)

- Chuyển Cloudflare sang **Full SSL** + dựng TLS ở origin (hoặc siết origin :80 chỉ nhận dải IP Cloudflare) — hiện Flexible nên CF↔origin là HTTP.
- Cân nhắc **Cloudflare Access** (email OTP) thay/đứng trước Basic Auth.
