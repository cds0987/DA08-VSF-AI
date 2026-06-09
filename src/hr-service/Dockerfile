FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# New Relic APM: newrelic-admin bootstraps agent rồi exec uvicorn. Cấu hình (license
# key, app name) đọc từ biến môi trường NEW_RELIC_* (set ở docker-compose).
# Lưu ý: hr-migrate dùng chung image nhưng override command=alembic -> KHÔNG bọc agent.
CMD ["newrelic-admin", "run-program", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]

