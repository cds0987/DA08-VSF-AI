# ---------------------------------------------------------------------------
# Stage price-builder: tải giá model từ HF -> model_prices.json (BUNDLE vào image).
# Tách stage để hf/pyarrow KHÔNG lọt vào image runtime. CI có internet nên fetch ở đây
# thay vì để VM phải gọi HF lúc chạy. HF hụt mạng -> script giữ seed đã commit.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS price-builder
WORKDIR /app
ARG MODEL_PRICE_DATASET_REPO=gunnybd01/openrouter-models-cache
COPY requirements-build.txt ./
RUN pip install --no-cache-dir -r requirements-build.txt
# CHỈ copy phần script cần (price_catalog dùng stdlib thuần + seed json) thay vì cả
# app/ -> layer fetch HF KHÔNG bị bust khi code app khác đổi (cache build nhanh hơn
# nhiều; trước đây COPY app làm fetch chạy lại mỗi lần đổi bất kỳ file app nào).
COPY app/__init__.py ./app/__init__.py
COPY app/infrastructure/__init__.py ./app/infrastructure/__init__.py
COPY app/infrastructure/observability ./app/infrastructure/observability
COPY scripts/build_price_catalog.py ./scripts/build_price_catalog.py
RUN python scripts/build_price_catalog.py \
        app/infrastructure/observability/data/model_prices.json \
        "$MODEL_PRICE_DATASET_REPO"

# ---------------------------------------------------------------------------
# Stage runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY requirements-guard.txt ./
# MẶC ĐỊNH (INSTALL_LLM_GUARD=0): KHÔNG cài torch + llm-guard (prod GUARDRAILS_MODE=off)
# -> build nhanh + image nhẹ vài GB. Bật bằng `--build-arg INSTALL_LLM_GUARD=1` khi cần
# guardrails: lúc đó cài torch CPU-only TRƯỚC (chặn pip kéo CUDA wheels vài GB do llm-guard)
# rồi mới cài requirements-guard. Code import llm_guard đã lazy nên image mặc định vẫn boot.
ARG INSTALL_LLM_GUARD=0
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && if [ "$INSTALL_LLM_GUARD" = "1" ]; then \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
        && pip install --no-cache-dir -r requirements-guard.txt ; \
    fi

COPY app ./app
COPY migrations ./migrations
COPY .env.example ./.env.example
COPY pytest.ini ./pytest.ini

# Ghi đè seed bằng bản giá đã refresh từ HF ở stage price-builder (nếu HF lỗi, builder
# đã giữ nguyên seed nên file luôn hợp lệ). Runtime chỉ đọc JSON này — không hf/pyarrow.
COPY --from=price-builder /app/app/infrastructure/observability/data/model_prices.json \
     ./app/infrastructure/observability/data/model_prices.json

EXPOSE 8001

# New Relic APM: newrelic-admin bootstraps agent rồi exec uvicorn. Cấu hình (license
# key, app name) đọc từ biến môi trường NEW_RELIC_* (set ở docker-compose).
CMD ["newrelic-admin", "run-program", "uvicorn", "app.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8001"]