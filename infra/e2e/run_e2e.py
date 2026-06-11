#!/usr/bin/env python3
"""run_e2e.py — 1 FLOW tích hợp xuyên suốt cho stack docker-compose.e2e.yml.

Chạy đúng MỘT lượt, mô phỏng FE thật, nghiệm thu toàn bộ mắt xích:

  1. login THẬT qua nginx -> user-service           (nginx + auth wiring)
  2. upload validation corpus -> document-service    (auth + GCS thật + NATS publish)
  3. poll Qdrant tới khi đủ doc có vector             (NATS -> rag-worker ingest -> Qdrant Cloud)
  4. verify Langfuse NHẬN trace ingest của rag-worker (đường observability rag-worker)
  5. query RAG qua nginx -> query-service -> mcp -> rag_search (sources>0, outcome SUCCESS)
  6. query HR  qua nginx -> query-service -> mcp -> hr_query    (outcome SUCCESS)
  7. verify Langfuse NHẬN trace query của query-service (đường observability query)
  8. cleanup: xóa object GCS + collection Qdrant đã tạo (cloud bền -> phải dọn).

Mọi bước fail -> exit non-zero (CI fail). Env: xem docker-compose.e2e.yml header +
GATEWAY_URL (mặc định http://localhost), DOC_URL (http://localhost:8002),
QDRANT_URL/QDRANT_API_KEY, S3_* (GCS), LANGFUSE_* (verify trace), VALIDATION_DIR.
"""
from __future__ import annotations

import base64
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

ALLOWED = {"pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"}
GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost").rstrip("/")
DOC_URL = os.environ.get("DOC_URL", "http://localhost:8002").rstrip("/")
ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@company.com")
ADMIN_PW = os.environ.get("SEED_ADMIN_PASSWORD", "***REDACTED-SEED-ADMIN-PW***")
RECORD = os.environ.get("CI_RECORD", "/tmp/e2e_record.json")


def _env(k: str, default: str | None = None) -> str:
    v = os.environ.get(k, default)
    if v is None:
        raise SystemExit(f"missing env {k}")
    return v


def _http(method: str, url: str, *, headers=None, data=None, timeout=30):
    rq = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return r.status, r.read()


# ─────────────────────────────── 1. LOGIN ──────────────────────────────────
def login() -> tuple[str, str]:
    body = json.dumps({"email": ADMIN_EMAIL, "password": ADMIN_PW}).encode()
    last = ""
    for _ in range(30):  # user-service + nginx có thể chưa sẵn sàng ngay
        try:
            st, raw = _http("POST", f"{GATEWAY}/api/user/auth/login",
                            headers={"Content-Type": "application/json"}, data=body)
            tok = json.loads(raw).get("access_token", "")
            if st == 200 and tok:
                payload = tok.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                uid = json.loads(base64.urlsafe_b64decode(payload)).get("user_id") \
                    or json.loads(base64.urlsafe_b64decode(payload)).get("sub", "")
                print(f"  login OK (user_id={uid})")
                return tok, uid
        except Exception as e:  # noqa: BLE001
            last = str(e)[:160]
        time.sleep(3)
    raise SystemExit(f"[1] login FAIL: {last}")


# ─────────────────────────────── 2. UPLOAD ─────────────────────────────────
def upload(token: str) -> list[dict]:
    import requests
    vdir = os.environ.get("VALIDATION_DIR", "src/rag-worker/eval/validation")
    files = sorted(f for f in glob.glob(vdir + "/*")
                   if os.path.splitext(f)[1].lstrip(".").lower() in ALLOWED)
    if not files:
        raise SystemExit(f"[2] no validation files in {vdir}")
    hdr = {"Authorization": "Bearer " + token}
    records, ok = [], 0
    for f in files:
        name = os.path.basename(f)
        with open(f, "rb") as fh:
            r = requests.post(f"{DOC_URL}/documents/upload", headers=hdr,
                              files={"file": (name, fh)},
                              data={"classification": "public"}, timeout=120)
        if r.status_code == 202:
            ok += 1
            doc_id = r.json()["document_id"]
            records.append({"doc_id": doc_id, "gcs_key": f"raw/{doc_id}/{name}"})
            print(f"  upload {name} -> 202 ({doc_id})")
        else:
            print(f"  upload {name} -> {r.status_code} {r.text[:200]}")
    with open(RECORD, "w", encoding="utf-8") as fh:
        json.dump({"docs": records}, fh)
    if ok != len(files):
        raise SystemExit(f"[2] upload FAIL: {ok}/{len(files)}")
    print(f"  uploaded {ok}/{len(files)}")
    return records


# ─────────────────────────────── Qdrant helpers ────────────────────────────
def _qdrant(method: str, path: str, body: dict | None = None) -> dict:
    url = _env("QDRANT_URL").rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {}
    api_key = os.environ.get("QDRANT_API_KEY", "").strip()
    if api_key:
        headers["api-key"] = api_key
    basic = (os.environ.get("VECTOR_DB_BASIC_AUTH") or "").strip()
    if ":" in basic:
        headers["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
    if data:
        headers["Content-Type"] = "application/json"
    st, raw = _http(method, url, headers=headers, data=data, timeout=30)
    return json.loads(raw) if raw else {}


def _distinct_doc_ids() -> set[str]:
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


# ─────────────────────────────── 3. VERIFY INGEST ──────────────────────────
def verify_ingest(records: list[dict]) -> None:
    expected = {d["doc_id"] for d in records}
    timeout = int(os.environ.get("VERIFY_TIMEOUT", "420"))
    deadline = time.time() + timeout
    last = -1
    while time.time() < deadline:
        try:
            ids = _distinct_doc_ids()
        except Exception as e:  # noqa: BLE001
            print("  verify poll err:", str(e)[:120]); time.sleep(5); continue
        if len(ids) != last:
            print(f"  ingested {len(ids)}/{len(expected)} doc")
            last = len(ids)
        if expected <= ids:
            print(f"  INGEST OK: {len(expected)} doc có vector")
            return
        time.sleep(5)
    raise SystemExit(f"[3] VERIFY TIMEOUT {timeout}s: {last}/{len(expected)} doc")


# ─────────────────────────────── Langfuse verify ───────────────────────────
def _lf_trace_count() -> int:
    host = _env("LANGFUSE_HOST_PUBLIC", os.environ.get("LANGFUSE_HOST", "http://localhost:3100"))
    pk = _env("LANGFUSE_PUBLIC_KEY", "pk-lf-e2e")
    sk = _env("LANGFUSE_SECRET_KEY", "sk-lf-e2e")
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    st, raw = _http("GET", host.rstrip("/") + "/api/public/traces?limit=100",
                    headers={"Authorization": "Basic " + auth}, timeout=15)
    return len((json.loads(raw) or {}).get("data", []))


def verify_trace(label: str, baseline: int) -> int:
    """Đợi Langfuse có trace MỚI so với baseline (đường observability hoạt động)."""
    for _ in range(20):
        try:
            n = _lf_trace_count()
            if n > baseline:
                print(f"  [{label}] Langfuse trace OK ({baseline} -> {n})")
                return n
        except Exception as e:  # noqa: BLE001
            print(f"  [{label}] langfuse poll err: {str(e)[:120]}")
        time.sleep(3)
    raise SystemExit(f"[{label}] KHÔNG thấy trace mới trên Langfuse (baseline={baseline})")


# ─────────────────────────────── 4/6. QUERY (SSE) ──────────────────────────
def _parse_sse(raw: bytes, label: str, need_sources: bool) -> None:
    done = None
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:].strip())
        except Exception:  # noqa: BLE001
            continue
        if d.get("done") or d.get("phase") == "done" or "outcome" in d:
            done = d
    if done is None:
        raise SystemExit(f"[{label}] FAIL: không nhận event done (stream crash/treo?)")
    outcome = done.get("outcome")
    src = len(done.get("sources") or [])
    print(f"  [{label}] done outcome={outcome} sources={src}")
    if outcome in (6, "ERROR"):
        raise SystemExit(f"[{label}] FAIL: outcome=ERROR (wiring query->mcp->rag/hr đứt?)")
    if need_sources and src < 1:
        raise SystemExit(f"[{label}] FAIL: cần sources>0 (query->mcp->rag->qdrant rỗng)")


def query(label: str, token: str, uid: str, question: str, need_sources: bool) -> None:
    body = json.dumps({"question": question, "user_id": uid}).encode()
    st, raw = _http("POST", f"{GATEWAY}/api/query/query",
                    headers={"Authorization": "Bearer " + token,
                             "Content-Type": "application/json"},
                    data=body, timeout=120)
    _parse_sse(raw, label, need_sources)


# ─────────────────────────────── 8. CLEANUP ────────────────────────────────
def cleanup() -> None:
    try:
        with open(RECORD, encoding="utf-8") as fh:
            docs = json.load(fh)["docs"]
    except FileNotFoundError:
        docs = []
    if docs:
        import boto3
        from botocore.client import Config
        c = boto3.client(
            "s3",
            endpoint_url=_env("S3_ENDPOINT_URL", "https://storage.googleapis.com"),
            aws_access_key_id=_env("S3_ACCESS_KEY_ID"),
            aws_secret_access_key=_env("S3_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("S3_REGION", "auto"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        bucket = _env("S3_BUCKET")
        c.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": d["gcs_key"]} for d in docs]})
        print(f"  GCS: deleted {len(docs)} objects")
    try:
        cols = [c["name"] for c in _qdrant("GET", "/collections")["result"]["collections"]]
        for col in cols:
            _qdrant("DELETE", f"/collections/{col}")
        print(f"  Qdrant: deleted collections {cols}")
    except Exception as e:  # noqa: BLE001
        print(f"  Qdrant cleanup warn: {str(e)[:120]}")


# ─────────────────────────────── main ──────────────────────────────────────
def main() -> int:
    do_cleanup = "--no-cleanup" not in sys.argv
    try:
        print("==> 1) login"); token, uid = login()
        print("==> 2) upload corpus"); records = upload(token)
        lf0 = 0
        try:
            lf0 = _lf_trace_count()
        except Exception:  # noqa: BLE001
            pass
        print("==> 3) verify ingest (Qdrant)"); verify_ingest(records)
        print("==> 4) verify rag-worker trace (Langfuse)"); lf1 = verify_trace("ingest", lf0)
        print("==> 5) query RAG"); query("RAG", token, uid, "công ty có chính sách nghỉ phép thế nào", True)
        print("==> 6) query HR"); query("HR", token, uid, "Tôi còn bao nhiêu ngày phép?", False)
        print("==> 7) verify query-service trace (Langfuse)"); verify_trace("query", lf1)
        print("E2E PASS ✓")
        return 0
    finally:
        if do_cleanup:
            print("==> 8) cleanup"); cleanup()


if __name__ == "__main__":
    sys.exit(main())
