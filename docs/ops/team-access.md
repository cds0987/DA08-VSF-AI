# Team Infra Access Guide

File này dùng để DevOps điền thông tin thật sau khi dựng hạ tầng, rồi gửi cho team backend/RAG.

---

## 1. GCP Project

- `GCP_PROJECT_ID=`
- `GCP_REGION=`
- `GCP_ZONE=`

---

## 2. Cloud Storage (GCS)

- `GCS_BUCKET=`
- Quyền truy cập: service account / instance service account
- Mục đích:
  - document-service upload file gốc
  - rag-worker đọc file để ingest

Env liên quan:

```env
GCS_BUCKET=
GCP_PROJECT_ID=
GOOGLE_APPLICATION_CREDENTIALS=
```

---

## 3. Qdrant Cloud

- `QDRANT_URL=`
- `QDRANT_API_KEY=`
- `QDRANT_COLLECTION=rag_chatbot`

Dùng cho:
- rag-worker ingest/search
- mcp-service search
- query-service semantic cache logic nếu cần

---

## 4. NATS JetStream

- `NATS_URL=`
- JetStream: enabled
- Monitoring URL (nếu mở nội bộ):
- Config file: `infra/nats/jetstream.conf`
- Subject contract: `infra/nats/subjects.md`

Dùng cho:
- `doc.ingest`
- `doc.status`
- `doc.access`
- `notify.doc_new`
- `rag.search`

---

## 5. Redis

- `REDIS_URL=redis://redis:6379/0` (nội bộ docker)
- Nếu external thì điền endpoint thật

Dùng cho:
- rate limit
- semantic cache
- blacklist JWT (theo docs)

---

## 6. PostgreSQL / Cloud SQL

Điền riêng cho từng service:

```env
USER_DATABASE_URL=
DOCUMENT_DATABASE_URL=
QUERY_DATABASE_URL=
MCP_DATABASE_URL=
LANGFUSE_DATABASE_URL=
```

---

## 7. Shared JWT

```env
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
```

Lưu ý: `JWT_SECRET_KEY` phải giống nhau ở các service verify token.

---

## 8. OpenAI / Gemini / Langfuse

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
```

---

## 9. Cách dùng cho từng team

### User service
- cần `DATABASE_URL`
- cần `JWT_SECRET_KEY`

### Document service
- cần `DATABASE_URL`
- cần `JWT_SECRET_KEY`
- cần `NATS_URL`
- cần `GCS_BUCKET`

### Query service
- cần `DATABASE_URL`
- cần `JWT_SECRET_KEY`
- cần `REDIS_URL`
- cần `NATS_URL`
- cần `MCP_SERVICE_URL`
- cần `OPENAI_API_KEY`

### RAG worker
- cần `NATS_URL`
- cần `QDRANT_URL`
- cần `GCS_BUCKET`
- cần `OPENAI_API_KEY`
- cần `GEMINI_API_KEY`

### MCP service
- cần `DATABASE_URL`
- cần `NATS_URL`
- cần `QDRANT_URL` nếu service thực tế có dùng trực tiếp
- cần `OPENAI_API_KEY`

---

## 10. Ghi chú DevOps

- Không gửi secret raw qua chat nhóm nếu không cần.
- Nên chia sẻ qua password manager / private note / GitHub Secrets / Secret Manager.
- Nếu team chỉ cần chạy local, có thể gửi `.env.example` + giá trị placeholder thay vì secret thật.