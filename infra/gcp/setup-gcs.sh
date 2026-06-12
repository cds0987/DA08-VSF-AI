#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Setup GCS cho DA08-VSF: bucket + service account + HMAC key (S3 API) + SA JSON.
#
# GCS độc lập VM — chỉ cần 1 project có billing. Chạy xong là e2e (CI fork) qua
# được phần storage, KHÔNG cần đợi dựng VM.
#
# Sinh ra:
#   - bucket gs://$BUCKET
#   - service account $SA_NAME
#   - HMAC key -> GCS_HMAC_KEY / GCS_HMAC_SECRET (cho S3 API: e2e + rag-worker)
#   - deploy/secrets/gcp-sa.json (cho document-service prod, native GCS)
#
# YÊU CẦU: project đã tồn tại + đã gắn billing OPEN. Nếu chưa có project, chạy
# infra/gcp/dev-provision.sh trước (nó tạo project + bucket), rồi chạy script này
# để bổ sung SA + HMAC + JSON.
#
# ⚠ Script này SINH CREDENTIAL thật. Tự chạy khi đã sẵn sàng; HMAC secret + JSON
#   key chỉ hiện 1 lần -> lưu kỹ.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ============================ CONFIG — SỬA Ở ĐÂY =============================
PROJECT_ID="vintravel-chatbot"           # Project đã có billing. Đổi cho khớp.
REGION="asia-southeast1"
BUCKET="vintravel-chatbot-docs-dev"          # PHẢI duy nhất toàn GCS.
SA_NAME="vsf-storage"                        # Tên service account (phần trước @).
SA_JSON_OUT="deploy/secrets/gcp-sa.json"     # Nơi ghi SA key JSON (cho document-service).
# ============================================================================

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"

echo "==> 1) Bật API storage + iam"
gcloud services enable storage.googleapis.com iam.googleapis.com --project="$PROJECT_ID"

echo "==> 2) Tạo bucket gs://$BUCKET (nếu chưa có)"
if gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo "   bucket đã có — bỏ qua."
else
  gcloud storage buckets create "gs://$BUCKET" \
    --project="$PROJECT_ID" --location="$REGION" --uniform-bucket-level-access
fi

echo "==> 3) Tạo service account $SA_EMAIL (nếu chưa có)"
if gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  echo "   SA đã có — bỏ qua."
else
  gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_ID" --display-name="VSF storage SA"
fi

echo "==> 4) Cấp quyền objectAdmin trên bucket cho SA"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin >/dev/null
echo "   OK."

echo "==> 5) Tạo HMAC key (S3 API) cho SA"
HMAC_OUT=$(gcloud storage hmac create "$SA_EMAIL" --project="$PROJECT_ID" --format="value(metadata.accessId,secret)")
HMAC_KEY=$(echo "$HMAC_OUT" | awk '{print $1}')
HMAC_SECRET=$(echo "$HMAC_OUT" | awk '{print $2}')

echo "==> 6) Tạo SA JSON key -> $SA_JSON_OUT (cho document-service prod)"
mkdir -p "$(dirname "$SA_JSON_OUT")"
gcloud iam service-accounts keys create "$SA_JSON_OUT" --iam-account="$SA_EMAIL"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " GCS SETUP XONG. Cập nhật các nơi sau:"
echo ""
echo " 1) Secret trên fork CI (cds0987/DA08-VSF):"
echo "      gh secret set GCS_HMAC_KEY    --repo cds0987/DA08-VSF --body '$HMAC_KEY'"
echo "      gh secret set GCS_HMAC_SECRET --repo cds0987/DA08-VSF --body '$HMAC_SECRET'"
echo ""
echo " 2) GCS_BUCKET trong .github/workflows/deploy-develop.yml (đang hardcode bucket cũ):"
echo "      đổi 'vsf-rag-chatbot-docs-dev' -> '$BUCKET'"
echo ""
echo " 3) deploy/env/*.env (S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY / bucket) nếu deploy VM:"
echo "      S3_ACCESS_KEY_ID=$HMAC_KEY"
echo "      S3_SECRET_ACCESS_KEY=$HMAC_SECRET"
echo ""
echo " 4) $SA_JSON_OUT đã tạo — KHÔNG commit (đặt trực tiếp trên VM khi deploy)."
echo "════════════════════════════════════════════════════════════════════"
echo "HMAC_KEY=$HMAC_KEY"
echo "HMAC_SECRET=$HMAC_SECRET"
