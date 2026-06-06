#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$HOME/DA08-VSF}"

sudo apt-get update
sudo apt-get install -y ca-certificates curl git gnupg lsb-release

if ! command -v docker >/dev/null 2>&1; then
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

sudo usermod -aG docker "$USER" || true

if [ ! -d "$PROJECT_DIR/.git" ]; then
  git clone https://github.com/lehuuhung2001/DA08-VSF "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"
mkdir -p deploy/env

echo "Bootstrap hoàn tất. Hãy:"
echo "1. Điền các file deploy/env/*.env"
echo "2. Sửa <REPO_URL> trong script nếu chưa sửa"
echo "3. Chạy: docker compose up --build -d"

