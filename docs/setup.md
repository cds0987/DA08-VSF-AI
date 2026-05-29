# Setup Guide — RAG Chatbot Local Development

## Prerequisites

| Tool | Version | Cài đặt |
|------|---------|---------|
| Python | 3.11+ | python.org |
| Node.js | 18+ | nodejs.org |
| Docker Desktop | Latest | docker.com |
| Git | Latest | git-scm.com |

---

## 1. Clone repo

```bash
git clone <repo-url>
cd rag-chatbot
```

---

## 2. Backend setup

```bash
cd app

# Tạo virtual environment
python -m venv venv

# Activate
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Cài dependencies
pip install -r requirements.txt
```

---

## 3. Environment variables

Copy file `.env.example` thành `.env` và điền giá trị:

```bash
cp .env.example .env
```

Nội dung `.env.example`:
```env
# OpenAI
OPENAI_API_KEY=sk-...

# Gemini
GEMINI_API_KEY=...

# Qdrant Cloud
QDRANT_URL=https://xxx.qdrant.io
QDRANT_API_KEY=...
QDRANT_COLLECTION=rag_chatbot

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/rag_chatbot

# AWS S3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET=rag-chatbot-docs
AWS_REGION=ap-southeast-1

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# Langfuse (observability)
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```

---

## 4. Chạy PostgreSQL local (Docker)

```bash
docker run -d \
  --name rag-postgres \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=rag_chatbot \
  -p 5432:5432 \
  postgres:15
```

---

## 5. Chạy backend

```bash
cd app
uvicorn interfaces.api.main:app --reload --port 8000
```

API docs tự động tại: http://localhost:8000/docs

---

## 6. Frontend setup

```bash
cd frontend

npm install

# Copy env
cp .env.local.example .env.local
# Điền NEXT_PUBLIC_API_URL=http://localhost:8000

npm run dev
```

Frontend tại: http://localhost:3000

---

## 7. Chạy tests

```bash
cd app

# Tất cả tests
pytest

# Một module cụ thể
pytest tests/use_cases/test_query.py -v

# Với coverage
pytest --cov=app tests/
```

---

## 8. Docker Compose (chạy toàn bộ stack)

```bash
# Build + start tất cả services
docker compose up --build

# Chỉ start (đã build rồi)
docker compose up

# Stop
docker compose down
```

---

## Troubleshooting

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `Connection refused 5432` | PostgreSQL chưa chạy | Chạy lại docker run postgres |
| `Invalid API Key` | `.env` chưa điền đúng | Kiểm tra lại `.env` |
| `ModuleNotFoundError` | Chưa activate venv | `venv\Scripts\activate` |
| `QDRANT_URL not set` | Thiếu env var | Kiểm tra `.env` có QDRANT_URL chưa |
