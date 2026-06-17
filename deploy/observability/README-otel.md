# OTel instrumentation — bật & verify (golden path: ai-router)

> Image ai-router đã **OTel-ready** nhưng **TẮT mặc định** (`VSF_OTEL_ENABLED=0` → uvicorn chạy
> y như cũ). Bật theo các bước dưới SAU khi test staging. Backend (otel-collector/Tempo/Loki)
> đã chạy sẵn trong monitor stack.

## Bật (sau khi test staging)
1. Set env trên VM (hoặc CI secret forward): `VSF_OTEL_ENABLED=1`.
2. Recreate ai-router: `docker compose up -d --force-recreate ai-router`.
3. Entrypoint sẽ chạy `opentelemetry-instrument uvicorn ...` → phát trace OTLP về `otel-collector:4317`.

## Verify
- Log ai-router: `docker compose logs ai-router | grep entrypoint` → thấy `OTel ENABLED`.
- Sinh traffic (1 request LLM qua ai-router).
- Grafana → Explore → datasource **Tempo** → query gần nhất → thấy trace `ai-router` (span FastAPI + httpx tới OpenAI/OpenRouter).
- Health ai-router vẫn `200 /health` (không crash).

## Rollback tức thì
- `VSF_OTEL_ENABLED=0` + `docker compose up -d --force-recreate ai-router` → về uvicorn thẳng.
- ai-router KHÔNG ai depends_on → kể cả lỗi cũng không kéo sập app (và có kill-switch LLM_MODEL_ADAPTER).

## Lưu ý kỹ thuật
- **Multi-worker**: ai-router chạy `--workers 2`. Auto-instrumentation qua `opentelemetry-instrument`
  với uvicorn multi-worker có thể chỉ áp 1 phần. Nếu trace thiếu, test với `UVICORN_WORKERS=1`
  trước, hoặc dùng post-fork hook. **Đây là lý do bật trên staging trước.**
- Collector down → exporter drop trace, **KHÔNG chặn request** (non-blocking).

## Fan-out service khác (Phase 2b/2c)
Cùng khuôn: thêm 2 dep OTel + `opentelemetry-bootstrap` + entrypoint công tắc + env OTEL_*.
Service đã có `newrelic-admin`: chain `opentelemetry-instrument newrelic-admin run-program uvicorn ...`
(test kỹ vì double-wrapper). nginx sinh trace_id gốc (W3C traceparent) → truyền xuống.
