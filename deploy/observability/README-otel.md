# OTel instrumentation — bật & verify (golden path: ai-router)

> Image ai-router đã **OTel-ready** nhưng **TẮT mặc định** (`VSF_OTEL_ENABLED=0` → uvicorn chạy
> y như cũ). Bật theo các bước dưới SAU khi test staging. Backend (otel-collector/Tempo/Loki)
> đã chạy sẵn trong monitor stack.

## Bật — QUA CI/CD (KHÔNG đụng tay VM)
1. Repo **Settings → Secrets and variables → Actions → Variables** → tạo/sửa
   **`VSF_OTEL_ENABLED` = `1`** (đây là Variable, không phải Secret).
2. Chạy lại workflow **deploy-develop** (push 1 commit, hoặc Actions → Run workflow).
3. Pipeline render `.env` (VSF_OTEL_ENABLED=1) → `docker compose up -d ai-router` TỰ recreate
   ai-router với entrypoint `opentelemetry-instrument` → phát trace OTLP về `otel-collector:4317`.

## Verify (qua Grafana, không cần SSH)
- Sinh 1 request LLM (hỏi chatbot 1 câu qua app).
- Grafana (`grafana.vsfchat.cloud`) → **Explore** → datasource **Tempo** → tìm trace gần nhất
  → thấy trace `ai-router` (span FastAPI + httpx tới OpenAI/OpenRouter).
- Dashboard ai-router vẫn xanh (health 200) = không crash.

## Rollback — cũng qua CI/CD
- Đổi Variable **`VSF_OTEL_ENABLED` = `0`** → chạy lại deploy → ai-router về uvicorn thẳng.
- ai-router KHÔNG ai depends_on → kể cả lỗi cũng không kéo sập app (+ kill-switch LLM_MODEL_ADAPTER).

## Lưu ý kỹ thuật
- **Multi-worker**: ai-router chạy `--workers 2`. Auto-instrumentation qua `opentelemetry-instrument`
  với uvicorn multi-worker có thể chỉ áp 1 phần. Nếu trace thiếu, test với `UVICORN_WORKERS=1`
  trước, hoặc dùng post-fork hook. **Đây là lý do bật trên staging trước.**
- Collector down → exporter drop trace, **KHÔNG chặn request** (non-blocking).

## Fan-out service khác (Phase 2b/2c)
Cùng khuôn: thêm 2 dep OTel + `opentelemetry-bootstrap` + entrypoint công tắc + env OTEL_*.
Service đã có `newrelic-admin`: chain `opentelemetry-instrument newrelic-admin run-program uvicorn ...`
(test kỹ vì double-wrapper). nginx sinh trace_id gốc (W3C traceparent) → truyền xuống.
