#!/usr/bin/env bash
# Đối chiếu VM log (CHỈ ĐỌC) cho cửa sổ load-test. Không ghi gì lên VM.
#
#   bash eval/load20/pull_vm_logs.sh '<start_utc_iso>' '<end_utc_iso>'
#
# start/end lấy từ output run_load20.py (window_start_utc/window_end_utc).
# SSH dùng OpenSSH native (bypass plink) theo memory vm-ssh-access. Chạy từ MÁY USER (Windows
# git-bash) — egress sandbox Claude chặn port 22; nếu chạy từ sandbox cần IAP tunnel (xem cuối file).
set -uo pipefail

START="${1:-}"; END="${2:-}"
VM_IP="${VM_IP:-35.240.193.13}"          # ⚠ ephemeral — đổi nếu VM restart (xem memory gcp-access)
SSH_USER="${SSH_USER:-nguyentt32}"
KEY="${SSH_KEY:-$HOME/.ssh/google_compute_engine}"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 ${SSH_USER}@${VM_IP}"

if [[ -z "$START" || -z "$END" ]]; then
  echo "Dùng: bash pull_vm_logs.sh '<start_utc_iso>' '<end_utc_iso>'"; exit 1
fi

OUT_DIR="$(dirname "$0")/out/vmlog_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
echo "[*] Cửa sổ: $START → $END"
echo "[*] VM: ${SSH_USER}@${VM_IP}  → lưu $OUT_DIR"

# 1) tìm container ai-router thật (prefix da08-vsf-*)
ROUTER=$($SSH "sudo docker ps --format '{{.Names}}' | grep -i ai-router | head -1" 2>/dev/null)
ROUTER="${ROUTER:-da08-vsf-ai-router-1}"
echo "[*] container ai-router = $ROUTER"

# docker --since/--until nhận RFC3339 (ISO UTC ok)
LOGS_RAW="$OUT_DIR/ai-router.log"
$SSH "sudo docker logs --since '$START' --until '$END' '$ROUTER'" > "$LOGS_RAW" 2>&1
echo "[*] đã kéo $(wc -l < "$LOGS_RAW") dòng log ai-router"

# 2) bóc tín hiệu quan trọng
echo "===== chat_stream_timing (resolve/create/ttfc theo capability) ====="
grep -h "chat_stream_timing" "$LOGS_RAW" | tail -60 | tee "$OUT_DIR/timing.txt"

echo; echo "===== ĐẾM tín hiệu tải ====="
{
  echo "save_mode (degrade gpt-4o-mini):  $(grep -c 'save_mode' "$LOGS_RAW")"
  echo "429 / rate-limit:                 $(grep -ciE '429|rate.?limit|too many' "$LOGS_RAW")"
  echo "error_quota:                      $(grep -c 'error_quota' "$LOGS_RAW")"
  echo "error_rate:                       $(grep -c 'error_rate' "$LOGS_RAW")"
  echo "no_capacity:                      $(grep -c 'no_capacity' "$LOGS_RAW")"
  echo "call_ok:                          $(grep -c 'call_ok' "$LOGS_RAW")"
  echo "call_failed:                      $(grep -c 'call_failed' "$LOGS_RAW")"
} | tee "$OUT_DIR/counts.txt"

# 3) snapshot quota/per-key SAU test (read-only; /metrics bind nội bộ -> exec curl trong container)
echo; echo "===== /metrics airouter per-key (token_today/cooldown) ====="
$SSH "sudo docker exec '$ROUTER' sh -c 'curl -s localhost:8010/metrics 2>/dev/null || python -c \"import urllib.request;print(urllib.request.urlopen(\\\"http://localhost:8010/metrics\\\").read().decode())\"'" 2>/dev/null \
  | grep -E 'airouter_(key|resolve|fallback|save_mode|tokens)' | tee "$OUT_DIR/metrics.txt" | tail -40

echo; echo "[*] Xong. Thư mục: $OUT_DIR"
echo "    → đối chiếu ttfc_ms (router) vs TTFT-answer (client) để biết nghẽn ở router hay ở proxy/graph."

# ── Nếu chạy TỪ sandbox Claude (port 22 bị chặn egress): mở IAP tunnel trước rồi đổi SSH target ──
#   gcloud compute start-iap-tunnel vsf-rag-demo-vm 22 --zone=asia-southeast1-a --local-host-port=localhost:2225 &
#   SSH_USER=ttnguyen1410_gmail_com VM_IP=localhost  (và thêm -p 2225 vào biến SSH)
