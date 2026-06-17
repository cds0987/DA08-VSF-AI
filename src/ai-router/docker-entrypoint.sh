#!/bin/sh
# Entrypoint ai-router: OTel auto-instrument CÓ CÔNG TẮC (mặc định TẮT -> hành vi y nguyên).
# Bật: set VSF_OTEL_ENABLED=1 (compose env) SAU khi test staging. Khi đó wrap bằng
# opentelemetry-instrument -> phát trace OTLP về otel-collector (FastAPI server + httpx client
# tới OpenAI/OpenRouter), trace_id xuyên suốt. Tắt -> chạy uvicorn thẳng như cũ.
set -e
if [ "${VSF_OTEL_ENABLED:-0}" = "1" ]; then
  # QUAN TRỌNG: opentelemetry-instrument KHÔNG tương thích uvicorn multi-worker (fork) -> crash.
  # Khi bật OTel ÉP workers=1 (single process). Đã từng gây AiRouterDown khi để --workers 2.
  echo "[entrypoint] OTel ENABLED (workers=1) -> ${OTEL_EXPORTER_OTLP_ENDPOINT:-otel-collector:4317}"
  exec opentelemetry-instrument uvicorn app.main:app --host 0.0.0.0 --port 8010 --workers 1
fi
echo "[entrypoint] OTel disabled (default) -> uvicorn thẳng"
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --workers "${UVICORN_WORKERS:-2}"
