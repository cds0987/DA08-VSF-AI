#!/usr/bin/env bash
# Remote deploy entrypoint — chạy TRÊN VM dưới user TOMAP qua IAP SSH (CI gọi).
#
# CI (deploy-develop.yml) auth bằng Workload Identity Federation -> impersonate
# github-deploy@ -> `gcloud compute ssh --tunnel-through-iap` -> `sudo -u TOMAP bash -s`.
# Secrets được CI export sẵn vào MÔI TRƯỜNG (printf %q qua stdin, mã hóa qua IAP)
# TRƯỚC khi exec file này — nên ở đây chỉ việc dùng, KHÔNG nội suy secret vào text.
#
# Vì sao chạy dưới TOMAP: OS Login cho login là sa_*/ttnguyen..., còn /home/TOMAP/DA08-VSF
# + group docker thuộc TOMAP. sudo -u TOMAP -> giữ nguyên môi trường deploy như trước.
#
# LƯU Ý bootstrap: git fetch/reset develop được làm Ở PAYLOAD (CI) TRƯỚC khi gọi file
# này — để lần cutover đầu tiên (khi VM chưa có remote-entry.sh) vẫn chạy được. Tới đây
# code đã = origin/develop, nên file này chỉ render secret + deploy + seed.
set -euo pipefail

export APP_DIR="/home/TOMAP/DA08-VSF"
export IMAGE_TAG="develop"
cd "$APP_DIR"

echo "==> 1b) RENDER secret tu GitHub Secrets (nguon DUY NHAT) -> .env + secret.env"
bash deploy/scripts/render-secrets.sh "$APP_DIR"

echo "==> 2..6) Deploy + healthcheck + smoke (logic o deploy/scripts/deploy.sh)"
bash deploy/scripts/deploy.sh

echo "==> 7) Seed users (admin + nhanvien@ + sep@) — idempotent"
docker compose run --rm seed-user || echo "::warning::seed-user failed (idempotent; retry next deploy)"
