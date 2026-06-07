# Runbook: test e2e luồng document → NATS → rag-worker → Qdrant → mcp (cloud thật)

Hướng dẫn **tái hiện đúng bài test** đã chạy: `file → document-service → GCS → NATS →
rag-worker → Qdrant → mcp-service search`, với **GCS + Qdrant Cloud + OpenAI THẬT**,
còn Postgres + NATS chạy local docker. Không cần user-service / query-service.

> File `infra/localtest/init-db.sql` **KHÔNG push git** (gitignored) — tự tạo ở local theo
> DDL ở mục [Tạo DB cho document-service](#tạo-db-cho-document-service-2-case). Compose +
> runbook này thì push bình thường.

---

## 0. Cần có
- Docker + Docker Compose.
- Python 3 + `pip install boto3 requests nats-py` (cho script clean/upload nếu chạy ngoài container).
- Mạng ra được: `storage.googleapis.com`, Qdrant Cloud, `api.openai.com`.
- Các secret (GCS HMAC, Qdrant API key + URL, OpenAI key, JWT secret).

## 1. Export secret cho compose interpolation
`docker-compose.localtest.yml` đọc secret từ biến môi trường. Export TRƯỚC mọi lệnh
`docker compose` (cả `build`):

```bash
export OPENAI_API_KEY="sk-proj-..."
export QDRANT_URL="https://<cluster>.gcp.cloud.qdrant.io:6333"   # BẮT BUỘC :6333
export QDRANT_API_KEY="<qdrant key>"
export GCS_HMAC_KEY="GOOG1..."
export GCS_HMAC_SECRET="<hmac secret>"
export JWT_SECRET_KEY="<jwt secret>"
```

## 2. Clean GCS bucket + Qdrant Cloud (chạy trên state SẠCH mới ra bug thật)

```bash
PYTHONIOENCODING=utf-8 python - <<'PY'
import boto3, urllib.request, json
from botocore.client import Config
import os
c=boto3.client("s3",endpoint_url="https://storage.googleapis.com",
  aws_access_key_id=os.environ["GCS_HMAC_KEY"],aws_secret_access_key=os.environ["GCS_HMAC_SECRET"],
  region_name="auto",config=Config(signature_version="s3v4",s3={"addressing_style":"path"}))
b="vsf-rag-chatbot-docs-dev"; r=c.list_objects_v2(Bucket=b)
objs=[{"Key":o["Key"]} for o in r.get("Contents",[])]
if objs: c.delete_objects(Bucket=b,Delete={"Objects":objs})
print("GCS now:", c.list_objects_v2(Bucket=b).get("KeyCount"))
QURL=os.environ["QDRANT_URL"]; KEY=os.environ["QDRANT_API_KEY"]
def req(m,p):
    rq=urllib.request.Request(QURL+p,method=m,headers={"api-key":KEY}); return json.load(urllib.request.urlopen(rq,timeout=30))
for col in [x["name"] for x in req("GET","/collections")["result"]["collections"]]: req("DELETE","/collections/"+col)
print("Qdrant now:", [x["name"] for x in req("GET","/collections")["result"]["collections"]])
PY
```

## Tạo DB cho document-service (2 case)

document-service cần DB `doc_db`. **Cách tạo phụ thuộc service đã có migration auto chưa.**
(rag-worker thì luôn có alembic → service `rag-migrate` trong compose tự `alembic upgrade head`
tạo `rag_db`; phần dưới chỉ nói về **document-service**.)

### Case A — document-service CHƯA có migration auto (hiện tại)

document-service **không** tự `create_all`/alembic → phải tạo **schema + bảng bằng tay**.
Đây là việc của `infra/localtest/init-db.sql` (mount vào `/docker-entrypoint-initdb.d` của
Postgres, chạy 1 lần khi volume rỗng). File này KHÔNG push → tạo ở local bằng nội dung sau:

```sql
-- infra/localtest/init-db.sql
CREATE DATABASE doc_db;
CREATE DATABASE rag_db;

\connect doc_db
CREATE SCHEMA IF NOT EXISTS doc_svc;

CREATE TABLE IF NOT EXISTS doc_svc.documents (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(500) NOT NULL,
    file_type           VARCHAR(20)  NOT NULL,
    gcs_key             VARCHAR(1000) NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'queued',
    uploaded_by         UUID         NOT NULL,
    classification      VARCHAR(20)  NOT NULL DEFAULT 'internal',
    allowed_departments TEXT[]       NOT NULL DEFAULT '{}',
    allowed_user_ids    TEXT[]       NOT NULL DEFAULT '{}',
    chunk_count         INTEGER      NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_doc_status ON doc_svc.documents (status);
CREATE INDEX IF NOT EXISTS ix_doc_uploaded_by ON doc_svc.documents (uploaded_by);

CREATE TABLE IF NOT EXISTS doc_svc.audit_logs (
    id            UUID PRIMARY KEY,
    actor_id      UUID         NOT NULL,
    actor_role    VARCHAR(50)  NOT NULL,
    action        VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id   UUID,
    detail        JSONB,
    ip_address    VARCHAR(45),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON doc_svc.audit_logs (actor_id);
```

> Schema/bảng PHẢI khớp `app/infrastructure/db/models.py` của document-service (`__table_args__
> = {"schema": "doc_svc"}`). Models đổi → cập nhật DDL này.

### Case B — document-service ĐÃ có migration auto (alembic)

Khi document-service bổ sung alembic (giống rag-worker): **bỏ phần tạo schema/bảng tay**.
`init-db.sql` chỉ cần tạo **database rỗng**:

```sql
CREATE DATABASE doc_db;
CREATE DATABASE rag_db;
```

rồi thêm 1 service migrate vào compose để tự dựng schema (mẫu theo `rag-migrate`):

```yaml
  doc-migrate:
    build: { context: ./src/document-service }
    command: ["alembic", "upgrade", "head"]
    working_dir: /app
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/doc_db
    depends_on:
      postgres: { condition: service_healthy }
    restart: "no"
```
và cho `document-service` `depends_on: doc-migrate: { condition: service_completed_successfully }`.
Lúc này không cần DDL tay nữa — schema do migration quản, tránh lệch với models.

## 3. Build + up stack

```bash
docker compose -f docker-compose.localtest.yml up -d --build
```
Thứ tự: postgres → nats → `rag-migrate` (alembic upgrade head) → rag-worker → document-service → mcp-service.

Chờ rag-worker khỏe + tạo collection/contract:
```bash
docker logs da08-vsf-rag-worker-1 2>&1 | grep -E "contract_stamp_written|nats_ingest_started"
```

> ⚠️ **mcp-service phải start SAU khi đã có data collection** (nó verify-contract
> fail-closed). Data collection chỉ được tạo ở **lần ingest đầu**. Nên: upload trước
> (bước 5) rồi mới restart mcp (bước 6). Nếu mcp exit với
> `mcp_contract_verify_failed: Collection ... chưa tồn tại` → đúng dự kiến, restart sau.

## 4. (nếu cần) đảm bảo biến env khi `up` lại từng service
Mỗi lần gọi `docker compose ... up -d <svc>` nhớ đã `export` secret ở bước 1 trong cùng shell.

## 5. Upload toàn bộ validation files qua document-service (tự mint JWT admin)

```bash
PYTHONIOENCODING=utf-8 python - <<'PY'
import os,json,time,hmac,hashlib,base64,uuid,glob,requests
SECRET=os.environ["JWT_SECRET_KEY"]
def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=")
def jwt(p):
    h=b64(b'{"alg":"HS256","typ":"JWT"}'); pl=b64(json.dumps(p,separators=(",",":")).encode())
    s=b64(hmac.new(SECRET.encode(),h+b"."+pl,hashlib.sha256).digest()); return (h+b"."+pl+b"."+s).decode()
hdr={"Authorization":"Bearer "+jwt({"sub":str(uuid.uuid4()),"role":"admin","department":"hr","exp":int(time.time())+3600})}
ALLOWED={"pdf","docx","txt","xlsx","csv","pptx","md"}   # html/png/jpg KHÔNG được phép
files=sorted(f for f in glob.glob("src/rag-worker/eval/validation/*") if os.path.splitext(f)[1].lstrip(".").lower() in ALLOWED)
ok=0
for f in files:
    with open(f,"rb") as fh:
        r=requests.post("http://127.0.0.1:8002/documents/upload",headers=hdr,
            files={"file":(os.path.basename(f),fh)},data={"classification":"public"},timeout=60)
    ok+=r.status_code==202; print(os.path.basename(f), r.status_code)
print(f"Uploaded {ok}/{len(files)}")
PY
```
> Chạy lệnh này ở **thư mục gốc repo** (đường dẫn `src/rag-worker/eval/validation/*`).
> `sub` của JWT phải là UUID (cột `uploaded_by` kiểu UUID).

## 6. Verify ingest + Qdrant, rồi restart mcp

```bash
sleep 25
docker logs da08-vsf-rag-worker-1 2>&1 | grep -c ingest_completed     # mong: 9
docker logs da08-vsf-rag-worker-1 2>&1 | grep -c '"status": "failed"' # mong: 0
docker logs da08-vsf-rag-worker-1 2>&1 | grep -c "400 Bad Request"    # mong: 0

# points trên Qdrant Cloud
PYTHONIOENCODING=utf-8 python - <<'PY'
import os,urllib.request,json
rq=urllib.request.Request(os.environ["QDRANT_URL"]+"/collections/rag_chatbot__te3s__d1536",
    headers={"api-key":os.environ["QDRANT_API_KEY"]})
print("points:", json.load(urllib.request.urlopen(rq,timeout=30))["result"]["points_count"])
PY

# giờ data collection đã có -> mcp verify pass
docker compose -f docker-compose.localtest.yml up -d mcp-service
sleep 8
docker logs da08-vsf-mcp-service-1 2>&1 | grep -E "contract_verified|Uvicorn running"
```

## 7. Search trực tiếp qua MCP HTTP (client MCP chính thức)

```bash
cat > /tmp/mcp_client.py <<'PY'
import asyncio
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
Q=[("how long until the password reset link expires","fifteen"),
   ("how many annual leave days do full-time employees get","twelve"),
   ("how to report a security incident data breach","breach"),
   ("how many days per week can employees work remotely","three"),
   ("what is the daily meal allowance per diem for travel","fifty"),
   ("collect laptop and badge and attend orientation onboarding","orientation")]
async def main():
    async with streamablehttp_client("http://mcp-service:8003/mcp") as (r,w,_):
        async with ClientSession(r,w) as s:
            await s.initialize(); p=0
            for q,kw in Q:
                res=await s.call_tool("rag_search",{"query":q,"top_k":5})
                hits=(res.structuredContent or {}).get("results",[])
                blob=" ".join((h.get('caption','') or '')+" "+(h.get('parent_text','') or '') for h in hits).lower()
                ok=kw in blob; p+=ok
                print(f"{'OK ' if ok else 'MISS'} {q[:46]:46} -> {hits[0].get('document_name','-') if hits else '-'}")
            print(f"PASS {p}/{len(Q)}")
asyncio.run(main())
PY
# chạy trong network compose để resolve được host mcp-service
docker compose -f docker-compose.localtest.yml run --rm -T mcp-service python - < /tmp/mcp_client.py
```
Kỳ vọng: **PASS 6/6**.

## 8. Dọn dẹp
```bash
docker compose -f docker-compose.localtest.yml down -v
```
Qdrant Cloud là THẬT → vector còn lại sau `down`. Muốn sạch: lặp lại bước 2.

---

## Troubleshooting (lỗi đã gặp thật)

| Triệu chứng | Nguyên nhân | Cách xử |
|-------------|-------------|---------|
| Mọi ingest `status=failed`, log `points/scroll 400`, error `Index required but not found for "document_id"` | Qdrant Cloud bắt buộc payload index để filter; collection mới chưa có | Đã fix trong code (tạo index lúc tạo collection) — xem `src/rag-worker/docs/ops/qdrant-payload-index.md`. Phải xóa collection cũ để recreate có index. |
| mcp-service exit `mcp_contract_verify_failed: Collection ... chưa tồn tại` | mcp start trước khi rag-worker ingest (data collection chưa có) | Upload trước, rồi `up -d mcp-service` |
| mcp exit `FastMCP.run() got an unexpected keyword argument 'middleware'` | bản mcp SDK không nhận `middleware` ở `run()` | Đã fix `app/main.py` (streamable_http_app + uvicorn) |
| `required variable X is missing` khi build/up | chưa `export` secret trong shell hiện tại | export lại bước 1 |
| upload trả 401 | JWT sai secret / thiếu role=admin / sub không phải UUID | mint lại đúng JWT_SECRET_KEY |
| Qdrant 401/403 | thiếu `:6333` hoặc thiếu API key | URL phải có `:6333` + set API key |
| document-service không ghi được GCS | thiếu SA JSON | dùng `STORAGE_BACKEND=s3` + HMAC (đã set sẵn trong compose) |
