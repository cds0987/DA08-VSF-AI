#!/usr/bin/env bash
# Combined load: CHAT mix-200 (100 nặng BM7 + 100 nhẹ) @ ~3.3/s trong 60s + UPLOAD ingest đồng
# thời + docker-stats CPU mỗi service. Mục đích: ĐO TOÀN DIỆN — A2 (ingest scale) có bóp chat
# (search-latency / TTFT) không. Cô lập rag-worker(search) vs rag-ingest-worker(×4).
set -uo pipefail
cd "$(dirname "$0")"
GC="/c/Users/TOMAP/AppData/Local/Google/Cloud SDK/google-cloud-sdk/bin/gcloud"
SC="${SCRATCH:-/tmp}"
ING_COUNT="${ING_COUNT:-30}"
ING_DIR="${ING_DIR:-../../eval/openragbench/data/38}"
STATS="$SC/combined_stats.txt"; : > "$STATS"

echo "== 1) docker-stats collector (90s, mỗi 5s) =="
( "$GC" compute ssh vsf-rag-demo-vm --zone asia-southeast1-a --tunnel-through-iap --quiet --command '
for i in $(seq 1 18); do
  echo "=== t=$((i*5))s ==="
  sudo docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemPerc}}" | grep -iE "rag-worker|rag-ingest|query-service|ai-router|mcp|qdrant|postgres"
  sleep 5
done' 2>/dev/null > "$STATS" ) &
STATS_PID=$!

echo "== 2) INGEST upload $ING_COUNT file (bg) =="
( CE="admin@company.com" CP="$ADMIN_PW" PYTHONUTF8=1 python ../../eval/ingest-load/benchmark/run_ingest_load.py \
    --count "$ING_COUNT" --files-dir "$ING_DIR" --concurrency 20 > "$SC/combined_ingest.log" 2>&1 ) &
ING_PID=$!

echo "== 3) CHAT mix-200 @ 3.33/s (foreground ~60s dispatch + drain) =="
ADMIN_PW="$ADMIN_PW" LOADTEST_PW="$LOADTEST_PW" PYTHONUTF8=1 python run_load.py \
    --dataset mixed200 --rate 3.33 --limit 200 2>&1 | tee "$SC/combined_chat.log"

echo "== chờ ingest + stats xong =="
wait $ING_PID; echo "ingest done"
wait $STATS_PID; echo "stats done"
echo "DONE_COMBINED"
