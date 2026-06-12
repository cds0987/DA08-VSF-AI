#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Provision project GCP DEV cho DA08-VSF VỚI GUARDRAIL CHI PHÍ (~$30/tháng).
#
# 🔒 NGUYÊN TẮC 1-VM: TUYỆT ĐỐI không host service nào ngoài VM. TẤT CẢ service +
#    Postgres + Qdrant + Langfuse chạy in-compose TRÊN 1 VM duy nhất. KHÔNG Cloud SQL.
#    Ngoại lệ DUY NHẤT: GCS bucket (object storage, user chốt giữ — không phải compute).
#
# Tái dựng inventory project cũ vsf-rag-chatbot-dev (đã bị xóa 2026-06) NHƯNG:
#   - 1 VM duy nhất (bỏ VM qdrant-base riêng VÀ bỏ Cloud SQL -> Postgres in-compose).
#   - Auto-shutdown theo lịch (KHÔNG chạy 24/7) — đòn giảm tiền mạnh nhất cho dev.
#   - Quota CPU/GPU thấp -> không thể lỡ tay bật máy to.
#   - Budget alert $30 (chỉ cảnh báo, không tự tắt — giữ uptime).
#
# ⚠ Bài học project cũ: nó chết vì gắn billing TRIAL (đã hết credit -> account đóng
#   -> GCP suspend -> xóa). Script này BẮT BUỘC dùng billing account OPEN trả tiền.
#
# CÁCH DÙNG:
#   1. Sửa các biến CONFIG bên dưới (nhất là PROJECT_ID phải DUY NHẤT toàn GCP).
#   2. bash infra/gcp/dev-provision.sh
#   3. Sau khi xong: SSH vào VM, chạy infra/gcp/gce-setup.sh để cài Docker + clone repo.
#
# Idempotent: chạy lại an toàn (lệnh tạo đã-tồn-tại sẽ bỏ qua, không lỗi fatal).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ============================ CONFIG — SỬA Ở ĐÂY =============================
PROJECT_ID="vintravel-chatbot"          # PHẢI duy nhất toàn GCP. Đổi nếu trùng.
PROJECT_NAME="VSF RAG Chatbot Dev"
BILLING_ACCOUNT="01BDC1-965FBC-F241D6"     # Account OPEN (trả tiền). KHÔNG dùng trial đã đóng.
REGION="asia-southeast1"                    # Giữ vùng cũ (gần VN).
ZONE="asia-southeast1-a"

# --- VM (chạy TOÀN BỘ stack in-compose: 6 service + 2 FE + nginx + nats + redis
#        + qdrant + langfuse + langfuse-db + app-postgres). KHÔNG có gì ngoài VM. ---
VM_NAME="vsf-rag-demo-vm"
VM_MACHINE="e2-standard-4"                  # 4 vCPU / 16GB. Tăng từ 8GB vì nay Postgres
                                            # app + Qdrant + Langfuse ĐỀU chạy trên VM này.
                                            # Muốn rẻ: hạ về e2-standard-2 (8GB) + thêm swap,
                                            # nhưng dễ OOM khi ingest nặng.
VM_DISK_GB="40"                             # Trần disk boot (chứa cả Postgres data + Qdrant).
VM_DISK_TYPE="pd-balanced"
USE_SPOT="false"                            # true = Spot (~1/3 giá) NHƯNG có thể bị preempt.
                                            # Dev gián đoạn chịu được -> cân nhắc bật để rẻ hơn.

# --- GCS (object storage cho file tài liệu — ngoại lệ DUY NHẤT ngoài VM) ---
GCS_BUCKET="vintravel-chatbot-docs-dev"      # PHẢI duy nhất toàn GCS. Đổi nếu trùng.

# --- Budget ---
BUDGET_AMOUNT="30"                          # USD/tháng. Alert 50/90/100%.

# --- Auto-shutdown VM: dừng 20:00, khởi 08:00, T2-T6 (giờ asia-southeast1) ---
SCHEDULE_TZ="Asia/Ho_Chi_Minh"
START_CRON="0 8 * * 1-5"
STOP_CRON="0 20 * * 1-5"
# ============================================================================

echo "==> 0) Project đang tồn tại?"
if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  echo "   project $PROJECT_ID đã có — bỏ qua tạo."
else
  echo "==> 1) Tạo project $PROJECT_ID"
  gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME"
fi

echo "==> 2) Gắn billing account OPEN $BILLING_ACCOUNT"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"

gcloud config set project "$PROJECT_ID"

echo "==> 3) Bật API cần thiết (KHÔNG bật sqladmin — không dùng Cloud SQL)"
gcloud services enable \
  compute.googleapis.com \
  storage.googleapis.com \
  cloudbilling.googleapis.com \
  billingbudgets.googleapis.com \
  --project="$PROJECT_ID"

echo "==> 4) GUARDRAIL — Firewall tối thiểu (chỉ 22/80/443; KHÔNG mở tùm lum)"
gcloud compute firewall-rules create allow-web-ssh \
  --project="$PROJECT_ID" --network=default --direction=INGRESS --action=ALLOW \
  --rules=tcp:22,tcp:80,tcp:443 --source-ranges=0.0.0.0/0 2>/dev/null \
  || echo "   firewall allow-web-ssh đã có — bỏ qua."

echo "==> 5) Tạo VM $VM_NAME ($VM_MACHINE, ${VM_DISK_GB}GB, KHÔNG GPU)"
SPOT_FLAGS=()
if [ "$USE_SPOT" = "true" ]; then
  SPOT_FLAGS=(--provisioning-model=SPOT --instance-termination-action=STOP)
fi
if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" >/dev/null 2>&1; then
  echo "   VM $VM_NAME đã có — bỏ qua tạo."
else
  gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT_ID" --zone="$ZONE" \
    --machine-type="$VM_MACHINE" \
    --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
    --boot-disk-size="${VM_DISK_GB}GB" --boot-disk-type="$VM_DISK_TYPE" \
    --no-restart-on-failure \
    "${SPOT_FLAGS[@]}"
fi

echo "==> 6) GUARDRAIL — Lịch tự bật/tắt VM (T2-T6, 08:00-20:00 $SCHEDULE_TZ)"
if gcloud compute resource-policies describe vm-dev-schedule --region="$REGION" >/dev/null 2>&1; then
  echo "   resource-policy vm-dev-schedule đã có — bỏ qua."
else
  gcloud compute resource-policies create instance-schedule vm-dev-schedule \
    --project="$PROJECT_ID" --region="$REGION" \
    --vm-start-schedule="$START_CRON" \
    --vm-stop-schedule="$STOP_CRON" \
    --timezone="$SCHEDULE_TZ"
fi
gcloud compute instances add-resource-policies "$VM_NAME" \
  --project="$PROJECT_ID" --zone="$ZONE" \
  --resource-policies=vm-dev-schedule 2>/dev/null \
  || echo "   schedule đã gắn vào VM — bỏ qua."

echo "==> 7) (BỎ Cloud SQL) — Postgres app chạy IN-COMPOSE trên VM. Không tạo gì ở GCP."

echo "==> 8) GCS bucket $GCS_BUCKET (single-region, lifecycle xóa file >90 ngày)"
if gcloud storage buckets describe "gs://$GCS_BUCKET" >/dev/null 2>&1; then
  echo "   bucket đã có — bỏ qua tạo."
else
  gcloud storage buckets create "gs://$GCS_BUCKET" \
    --project="$PROJECT_ID" --location="$REGION" --uniform-bucket-level-access
fi
cat > /tmp/gcs-lifecycle.json <<'JSON'
{ "rule": [ { "action": {"type": "Delete"}, "condition": {"age": 90} } ] }
JSON
gcloud storage buckets update "gs://$GCS_BUCKET" --lifecycle-file=/tmp/gcs-lifecycle.json || true

echo "==> 9) GUARDRAIL — Budget alert \$$BUDGET_AMOUNT/tháng (50/90/100%)"
gcloud billing budgets create \
  --billing-account="$BILLING_ACCOUNT" \
  --display-name="dev-$PROJECT_ID-budget" \
  --budget-amount="${BUDGET_AMOUNT}USD" \
  --filter-projects="projects/$PROJECT_ID" \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0 \
  2>/dev/null || echo "   budget có thể đã tồn tại / cần quyền Billing Admin — kiểm tra tay."

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " XONG. Tiếp theo:"
echo "  1. gcloud compute ssh $VM_NAME --zone=$ZONE"
echo "  2. Trên VM: chạy infra/gcp/gce-setup.sh (cài Docker + clone repo)"
echo "  3. Đặt deploy/secrets/gcp-sa.json + điền deploy/env/*.env"
echo "  4. docker compose up -d"
echo ""
echo " GUARDRAIL THỦ CÔNG còn lại (làm 1 lần trên Console, script không tự set được):"
echo "  - IAM & Admin > Quotas: đặt 'Compute Engine CPUs' (vùng $REGION) = 4,"
echo "    'GPUs (all regions)' = 0  -> chặn lỡ tay bật máy to / GPU."
echo "════════════════════════════════════════════════════════════════════"
