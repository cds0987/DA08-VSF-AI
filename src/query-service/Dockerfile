FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY .env.example ./.env.example
COPY pytest.ini ./pytest.ini

EXPOSE 8001

# New Relic APM: newrelic-admin bootstraps agent rồi exec uvicorn. Cấu hình (license
# key, app name) đọc từ biến môi trường NEW_RELIC_* (set ở docker-compose).
CMD ["newrelic-admin", "run-program", "uvicorn", "app.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8001"]