  FROM python:3.11-slim

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1

  WORKDIR /app

  RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      && rm -rf /var/lib/apt/lists/*

  RUN pip install --no-cache-dir --upgrade pip && \
      pip install --no-cache-dir \
      fastapi \
      "uvicorn[standard]" \
      sqlalchemy \
      asyncpg \
      "psycopg[binary]" \
      python-dotenv \
      python-jose \
      python-multipart \
      pydantic \
      bcrypt \
      passlib \
      email-validator \
      "alembic>=1.13" \
      "nats-py>=2.6" \
      newrelic

  COPY app ./app
  COPY migrations ./migrations
  COPY scripts ./scripts
  COPY alembic.ini ./alembic.ini

  EXPOSE 8000

  # New Relic APM: newrelic-admin bootstraps agent rồi exec uvicorn. Cấu hình (license
  # key, app name) đọc từ biến môi trường NEW_RELIC_* (set ở docker-compose).
  CMD ["newrelic-admin", "run-program", "uvicorn", "app.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
