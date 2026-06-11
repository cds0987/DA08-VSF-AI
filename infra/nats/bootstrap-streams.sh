#!/bin/sh
# NATS JetStream provisioner — NGUỒN DUY NHẤT tạo/đồng bộ stream theo contract
# infra/nats/subjects.md. Chạy MỘT LẦN lúc deploy (one-shot), TRƯỚC khi các service
# kết nối. Mọi service chạy verify-only -> hết cảnh nhiều app đua add_stream vào
# cùng broker gây "subjects overlap".
#
# Idempotent: chạy lại vô hại (stream đã có -> bỏ qua). Cũng kiêm MIGRATION: xóa
# stream legacy `DOCS` (deviation cũ của rag-worker) đè subject của DOC_EVENTS.
set -eu

NATS_URL="${NATS_URL:-nats://nats:4222}"

echo "==> Chờ NATS sẵn sàng tại $NATS_URL"
i=0
until nats -s "$NATS_URL" stream ls >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "ERROR: NATS không sẵn sàng sau ~120s" >&2
    exit 1
  fi
  sleep 2
done
echo "NATS OK"

# ── MIGRATION: bỏ stream legacy DOCS (đè doc.ingest/doc.status/doc.access của
#    DOC_EVENTS). An toàn vì các subject này được DOC_EVENTS sở hữu lại bên dưới.
if nats -s "$NATS_URL" stream info DOCS >/dev/null 2>&1; then
  echo "==> Migration: xóa stream legacy DOCS (đè subject của DOC_EVENTS)"
  nats -s "$NATS_URL" stream rm DOCS -f
fi

# ── Provision stream chuẩn (idempotent: có rồi thì bỏ qua) ──────────────────────
ensure_stream() {
  name="$1"; subjects="$2"; maxage="$3"
  if nats -s "$NATS_URL" stream info "$name" >/dev/null 2>&1; then
    echo "stream $name đã tồn tại -> giữ nguyên"
    return 0
  fi
  echo "==> Tạo stream $name [$subjects]"
  nats -s "$NATS_URL" stream add "$name" \
    --subjects="$subjects" \
    --storage=file \
    --retention=limits \
    --discard=old \
    --max-age="$maxage" \
    --dupe-window=2m \
    --replicas=1 \
    --defaults
}

# Theo infra/nats/subjects.md (DevOps contract).
ensure_stream DOC_EVENTS    "doc.ingest,doc.status,doc.access"   7d
ensure_stream NOTIFY_EVENTS "notify.doc_new"                     3d
ensure_stream HR_EVENTS     "hr.*,hr.employee_profile.updated"   30d

echo "==> NATS bootstrap DONE"
