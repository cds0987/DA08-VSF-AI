FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build catalog từ OpenRouter /models lúc build (public, không cần key).
# Lỗi mạng -> giữ seed config/model_catalog.json đã commit (script luôn exit 0).
RUN python scripts/build_catalog.py config/model_catalog.json || true

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]
