#!/usr/bin/env bash
# Render .env (root, compose ${VAR} substitution) + deploy/env/secret.env (env_file)
# trên VM từ biến môi trường do CI forward (appleboy envs:) — GitHub Secrets là NGUỒN
# DUY NHẤT. Tách khỏi inline workflow script để không vượt giới hạn 21000 ký tự.
#
# Dùng: bash deploy/scripts/render-secrets.sh "$APP_DIR"
# Chạy SAU git reset --hard: .env ở root + secret.env gitignored -> không bị reset xoá.
set -euo pipefail

APP_DIR="${1:?thiếu APP_DIR}"

# Bắt buộc có mặt (fail-fast) — tránh render env rỗng gây lỗi âm thầm.
for v in POSTGRES_PASSWORD NEW_RELIC_LICENSE_KEY LANGFUSE_DB_PASSWORD NEXTAUTH_SECRET \
         LANGFUSE_SALT LANGFUSE_ENCRYPTION_KEY LANGFUSE_INIT_USER_PASSWORD \
         LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY OPENAI_API_KEY JWT_SECRET_KEY \
         MCP_INTERNAL_TOKEN HR_INTERNAL_TOKEN GCS_HMAC_KEY GCS_HMAC_SECRET \
         DOCKERHUB_USERNAME; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || { echo "::error::GitHub Secret '$v' THIẾU -> dừng deploy (không render env mồ côi)"; exit 1; }
done
: "${SEED_ADMIN_PASSWORD:=}"   # optional: chỉ dùng khi re-seed admin lần đầu
: "${LANGSMITH_API_KEY:=}"     # optional: thiếu -> langsmith backend tự bỏ (không crash)

umask 077

# root .env: biến compose ${VAR} substitution
cat > "$APP_DIR/.env" <<EOF
DOCKERHUB_USERNAME=${DOCKERHUB_USERNAME}
IMAGE_TAG=develop
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
NEW_RELIC_LICENSE_KEY=${NEW_RELIC_LICENSE_KEY}
SEED_ADMIN_PASSWORD=${SEED_ADMIN_PASSWORD}
LANGFUSE_DB_PASSWORD=${LANGFUSE_DB_PASSWORD}
NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
LANGFUSE_SALT=${LANGFUSE_SALT}
LANGFUSE_ENCRYPTION_KEY=${LANGFUSE_ENCRYPTION_KEY}
LANGFUSE_INIT_USER_PASSWORD=${LANGFUSE_INIT_USER_PASSWORD}
LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
EOF

# deploy/env/secret.env: env_file -> biến container (load CUỐI, override).
# HR_SERVICE_INTERNAL_TOKEN = HR_INTERNAL_TOKEN (1 nguồn, 2 tên — chống drift).
# S3_* = GCS HMAC (không thêm secret riêng).
cat > "$APP_DIR/deploy/env/secret.env" <<EOF
OPENAI_API_KEY=${OPENAI_API_KEY}
JWT_SECRET_KEY=${JWT_SECRET_KEY}
MCP_INTERNAL_TOKEN=${MCP_INTERNAL_TOKEN}
HR_INTERNAL_TOKEN=${HR_INTERNAL_TOKEN}
HR_SERVICE_INTERNAL_TOKEN=${HR_INTERNAL_TOKEN}
S3_ACCESS_KEY_ID=${GCS_HMAC_KEY}
S3_SECRET_ACCESS_KEY=${GCS_HMAC_SECRET}
LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
LANGSMITH_API_KEY=${LANGSMITH_API_KEY}
EOF

chmod 600 "$APP_DIR/.env" "$APP_DIR/deploy/env/secret.env"
echo "  rendered .env ($(grep -c = "$APP_DIR/.env") keys) + secret.env ($(grep -c = "$APP_DIR/deploy/env/secret.env") keys)"
