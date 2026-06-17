FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# Instrumentation libs liệt kê thẳng trong requirements (không cần opentelemetry-bootstrap).
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

# Build catalog từ OpenRouter /models lúc build (public, không cần key).
# Lỗi mạng -> giữ seed config/model_catalog.json đã commit (script luôn exit 0).
RUN python scripts/build_catalog.py config/model_catalog.json || true

EXPOSE 8010

# Entrypoint chọn uvicorn thẳng (mặc định) hoặc opentelemetry-instrument (VSF_OTEL_ENABLED=1).
CMD ["./docker-entrypoint.sh"]
