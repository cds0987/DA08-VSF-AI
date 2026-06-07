"""CI e2e helper: drive luồng document-service -> NATS -> rag-worker -> Qdrant -> mcp
trên hạ tầng cloud THẬT (GCS + Qdrant Cloud + OpenAI), rồi DỌN SẠCH những gì đã tạo.

Subcommands:
  upload   mint JWT admin, upload toàn bộ validation files qua document-service,
           ghi lại (doc_id, gcs_key) vào record file để cleanup.
  verify   poll Qdrant tới khi có đủ points (ingest xong) hoặc timeout -> fail.
  search   chạy golden queries qua MCP HTTP; sai -> exit non-zero.
  cleanup  XÓA object đã upload trên GCS + XÓA mọi collection trên Qdrant Cloud.

Env cần có:
  DOC_URL (mặc định http://localhost:8002), MCP_URL (http://localhost:8003/mcp)
  JWT_SECRET_KEY
  QDRANT_URL (có :6333), QDRANT_API_KEY
  S3_ENDPOINT_URL (https://storage.googleapis.com), S3_BUCKET, S3_ACCESS_KEY_ID,
  S3_SECRET_ACCESS_KEY, S3_REGION
  CI_RECORD (mặc định /tmp/ci_e2e_record.json), VALIDATION_DIR
"""
from __future__ import annotations

import base64
import glob
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import uuid

ALLOWED = {"pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"}
GOLDEN = [
    ("how long until the password reset link expires", "fifteen"),
    ("how many annual leave days do full-time employees get", "twelve"),
    ("how to report a security incident data breach", "breach"),
    ("how many days per week can employees work remotely", "three"),
    ("what is the daily meal allowance per diem for travel", "fifty"),
    ("collect laptop and badge and attend orientation onboarding", "orientation"),
]


def _env(k: str, default: str | None = None) -> str:
    v = os.environ.get(k, default)
    if v is None:
        raise SystemExit(f"missing env {k}")
    return v


def _record_path() -> str:
    return os.environ.get("CI_RECORD", "/tmp/ci_e2e_record.json")


def _doc_url() -> str:
    return os.environ.get("DOC_URL", "http://localhost:8002").rstrip("/")


def _mint_jwt() -> str:
    secret = _env("JWT_SECRET_KEY")
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    head = b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64(json.dumps({
        "sub": str(uuid.uuid4()), "role": "admin", "department": "hr",
        "exp": int(time.time()) + 3600,
    }, separators=(",", ":")).encode())
    sig = b64(hmac.new(secret.encode(), head + b"." + payload, hashlib.sha256).digest())
    return (head + b"." + payload + b"." + sig).decode()


def _s3_client():
    import boto3
    from botocore.client import Config
    return boto3.client(
        "s3",
        endpoint_url=_env("S3_ENDPOINT_URL", "https://storage.googleapis.com"),
        aws_access_key_id=_env("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("S3_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("S3_REGION", "auto"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _qdrant(method: str, path: str, body: dict | None = None) -> dict:
    url = _env("QDRANT_URL").rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"api-key": _env("QDRANT_API_KEY")}
    if data:
        headers["Content-Type"] = "application/json"
    rq = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(rq, timeout=30) as r:
        return json.load(r)


# --------------------------------------------------------------------------- #
def cmd_upload() -> int:
    import requests
    vdir = os.environ.get("VALIDATION_DIR", "src/rag-worker/eval/validation")
    files = sorted(f for f in glob.glob(vdir + "/*")
                   if os.path.splitext(f)[1].lstrip(".").lower() in ALLOWED)
    if not files:
        raise SystemExit(f"no validation files in {vdir}")
    hdr = {"Authorization": "Bearer " + _mint_jwt()}
    records, ok = [], 0
    for f in files:
        name = os.path.basename(f)
        with open(f, "rb") as fh:
            r = requests.post(f"{_doc_url()}/documents/upload", headers=hdr,
                              files={"file": (name, fh)},
                              data={"classification": "public"}, timeout=120)
        if r.status_code == 202:
            ok += 1
            doc_id = r.json()["document_id"]
            records.append({"doc_id": doc_id, "gcs_key": f"raw/{doc_id}/{name}"})
            print(f"  upload {name} -> 202 ({doc_id})")
        else:
            print(f"  upload {name} -> {r.status_code} {r.text[:200]}")
    with open(_record_path(), "w", encoding="utf-8") as fh:
        json.dump({"docs": records}, fh)
    print(f"uploaded {ok}/{len(files)} (record: {_record_path()})")
    return 0 if ok == len(files) else 1


def _distinct_doc_ids() -> set[str]:
    """Đếm document_id RIÊNG BIỆT đã có vector (mỗi doc ingest xong = có >=1 chunk).
    Dùng cái này thay vì tổng points: points = số chunk, 1 doc nhiều chunk -> ngưỡng
    theo points đạt sớm khi doc chậm (pdf/pptx vision OCR) chưa xong -> search MISS.
    """
    cols = [c["name"] for c in _qdrant("GET", "/collections")["result"]["collections"]]
    ids: set[str] = set()
    for c in cols:
        if c.endswith("__meta"):
            continue
        offset = None
        while True:
            body: dict = {"limit": 256, "with_payload": ["document_id"], "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            res = _qdrant("POST", f"/collections/{c}/points/scroll", body)["result"]
            for p in res.get("points", []):
                did = (p.get("payload") or {}).get("document_id")
                if did:
                    ids.add(did)
            offset = res.get("next_page_offset")
            if not offset:
                break
    return ids


def cmd_verify() -> int:
    with open(_record_path(), encoding="utf-8") as fh:
        expected = {d["doc_id"] for d in json.load(fh)["docs"]}
    timeout = int(os.environ.get("VERIFY_TIMEOUT", "360"))
    deadline = time.time() + timeout
    last = -1
    while time.time() < deadline:
        try:
            ids = _distinct_doc_ids()
        except Exception as e:  # noqa: BLE001 - transient cloud errors
            print("  verify poll err:", str(e)[:120]); time.sleep(5); continue
        if len(ids) != last:
            missing = sorted(expected - ids)
            print(f"  ingested docs: {len(ids)}/{len(expected)}; còn thiếu: {len(missing)}")
            last = len(ids)
        if expected <= ids:
            print(f"INGEST OK: tất cả {len(expected)} doc đã có vector")
            return 0
        time.sleep(5)
    print(f"VERIFY TIMEOUT sau {timeout}s: mới {last}/{len(expected)} doc có vector")
    return 1


def cmd_search() -> int:
    import asyncio
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    url = os.environ.get("MCP_URL", "http://localhost:8003/mcp")

    async def run() -> int:
        async with streamablehttp_client(url) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                passed = 0
                for q, kw in GOLDEN:
                    res = await s.call_tool("rag_search", {"query": q, "top_k": 5})
                    hits = (res.structuredContent or {}).get("results", [])
                    blob = " ".join((h.get("caption", "") or "") + " " +
                                    (h.get("parent_text", "") or "") for h in hits).lower()
                    ok = kw in blob
                    passed += ok
                    top = hits[0].get("document_name", "-") if hits else "-"
                    print(f"  {'OK ' if ok else 'MISS'} {q[:46]:46} -> {top}")
                print(f"PASS {passed}/{len(GOLDEN)}")
                return 0 if passed == len(GOLDEN) else 1

    return asyncio.run(run())


def _psycopg_dsn(url: str) -> str:
    """SQLAlchemy URL (postgresql+psycopg:// | postgresql+asyncpg://) -> DSN thuần cho psycopg.connect."""
    return (
        url.replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )


def _db_cleanup(doc_ids: list[str]) -> None:
    """Dọn data test trên Cloud SQL theo đúng doc_id đã tạo (không nuke cả bảng).

    Guard bằng env: không set RAG_DATABASE_URL/DOC_DATABASE_URL -> no-op (CI dùng
    postgres local throwaway không cần dọn vì `down -v` xóa hết). Chỉ chạy khi test
    trỏ Cloud SQL THẬT (verify tích hợp Cloud SQL) -> phải dọn để không lẫn data.
    """
    rag_url = os.environ.get("RAG_DATABASE_URL")
    doc_url = os.environ.get("DOC_DATABASE_URL")
    if not rag_url and not doc_url:
        print("DB: no RAG_DATABASE_URL/DOC_DATABASE_URL, skip (postgres local sẽ bị down -v)")
        return
    if not doc_ids:
        print("DB: record rỗng, skip")
        return
    try:
        import psycopg
    except ImportError:
        print("DB: thiếu psycopg, skip (pip install 'psycopg[binary]')")
        return
    if rag_url:
        with psycopg.connect(_psycopg_dsn(rag_url)) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM job_logs WHERE document_id::text = ANY(%s)", (doc_ids,))
            cur.execute("DELETE FROM ingest_jobs WHERE document_id::text = ANY(%s)", (doc_ids,))
            cur.execute("DELETE FROM documents WHERE id::text = ANY(%s)", (doc_ids,))
            conn.commit()
        print(f"rag_db: cleaned {len(doc_ids)} docs (documents/ingest_jobs/job_logs)")
    if doc_url:
        with psycopg.connect(_psycopg_dsn(doc_url)) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM doc_svc.documents WHERE id::text = ANY(%s)", (doc_ids,))
            conn.commit()
        print(f"doc_db: cleaned {len(doc_ids)} docs (doc_svc.documents)")


def cmd_cleanup() -> int:
    # 1. GCS: xóa đúng object đã upload (ghi trong record).
    try:
        with open(_record_path(), encoding="utf-8") as fh:
            docs = json.load(fh)["docs"]
    except FileNotFoundError:
        docs = []
    if docs:
        c = _s3_client()
        bucket = _env("S3_BUCKET")
        objs = [{"Key": d["gcs_key"]} for d in docs]
        c.delete_objects(Bucket=bucket, Delete={"Objects": objs})
        print(f"GCS: deleted {len(objs)} objects from {bucket}")
    else:
        print("GCS: no record, skip")
    # 2. Qdrant: xóa MỌI collection (cluster chuyên cho test này).
    cols = [c["name"] for c in _qdrant("GET", "/collections")["result"]["collections"]]
    for col in cols:
        _qdrant("DELETE", f"/collections/{col}")
    print(f"Qdrant: deleted collections {cols}")
    # 3. Cloud SQL: dọn data test (no-op nếu test dùng postgres local).
    _db_cleanup([d["doc_id"] for d in docs])
    return 0


def main() -> int:
    cmds = {"upload": cmd_upload, "verify": cmd_verify, "search": cmd_search, "cleanup": cmd_cleanup}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        raise SystemExit(f"usage: ci_e2e.py [{'|'.join(cmds)}]")
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
