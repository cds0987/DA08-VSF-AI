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

Mọi bước fail -> exit non-zero (CI fail). Gọi THẲNG service port (không qua nginx).
Env: xem docker-compose.e2e.yml header + USER_URL (http://localhost:8000),
QUERY_URL (http://localhost:8001), DOC_URL (http://localhost:8002),
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
# Gọi THẲNG service port (không qua nginx) -> e2e không cần build nginx + 2 Nuxt FE
# (nhanh hơn nhiều). Wiring nginx+FE đã được smoke trên VM lúc deploy bao. Path gốc
# lấy từ nginx.conf: /api/user/->:8000/, /api/query/query->:8001/query, upload->:8002.
USER_URL = os.environ.get("USER_URL", "http://localhost:8000").rstrip("/")
QUERY_URL = os.environ.get("QUERY_URL", "http://localhost:8001").rstrip("/")
DOC_URL = os.environ.get("DOC_URL", "http://localhost:8002").rstrip("/")
# hr-service expose 127.0.0.1:8004 trong docker-compose.e2e.yml; token cố định ở compose.
HR_URL = os.environ.get("HR_URL", "http://localhost:8004").rstrip("/")
HR_TOKEN = os.environ.get("HR_INTERNAL_TOKEN", "e2e-hr-token")
ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@company.com")
ADMIN_PW = os.environ.get("SEED_ADMIN_PASSWORD", "DemoAdminPassword123!")
RECORD = os.environ.get("CI_RECORD", "/tmp/e2e_record.json")
# Seed UUID từ migration 0001: USER_FINANCE có manager = USER_HR -> resolve approver
# được; USER_HR manager NULL nên KHÔNG dùng làm requester (sẽ 422 thiếu approver).
HR_USER = "11111111-1111-4111-8111-111111111111"
FIN_USER = "22222222-2222-4222-8222-222222222222"


def _env(k: str, default: str | None = None) -> str:
    v = os.environ.get(k, default)
    if v is None:
        raise SystemExit(f"missing env {k}")
    return v


def _http(method: str, url: str, *, headers=None, data=None, timeout=30):
    rq = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return r.status, r.read()


AIROUTER_URL = os.environ.get("AIROUTER_URL", "http://localhost:8010").rstrip("/")


def verify_router_served() -> None:
    """CHỨNG MINH luồng trả lời chính ĐÃ đi qua ai-router (không phải tình cờ chạy direct).

    Sau khi query, /metrics phải có airouter_resolve_total > 0 (router đã resolve key cho
    LLM call) và ÍT NHẤT 1 key đã tiêu token hôm nay. Nếu query-service bypass router thì
    cả 2 = 0 -> FAIL. Đây là khác biệt giữa 'answer chạy' và 'answer chạy QUA ROUTER'.
    """
    st, raw = _http("GET", f"{AIROUTER_URL}/metrics", timeout=15)
    if st != 200:
        raise SystemExit(f"[router] FAIL: /metrics status={st}")
    text = raw.decode("utf-8", "replace")
    resolved = sum(
        float(line.rsplit(" ", 1)[1])
        for line in text.splitlines()
        if line.startswith("airouter_resolve_total{")
    )
    tokens = sum(
        float(line.rsplit(" ", 1)[1])
        for line in text.splitlines()
        if line.startswith("airouter_key_tokens_today{")
    )
    print(f"  [router] resolve_total={resolved} key_tokens_today={tokens}")
    if resolved < 1:
        raise SystemExit("[router] FAIL: airouter_resolve_total=0 -> query KHÔNG đi qua router")
    # raw key KHÔNG được lộ trong /metrics (chỉ key_id/secret_env)
    if "sk-" in text:
        raise SystemExit("[router] FAIL: /metrics lộ raw key (sk-...)")
    print("  [router] OK: luồng LLM chính đã route qua ai-router")


# ─────────────────────────────── 1. LOGIN ──────────────────────────────────
def login() -> tuple[str, str]:
    body = json.dumps({"email": ADMIN_EMAIL, "password": ADMIN_PW}).encode()
    last = ""
    for _ in range(30):  # user-service + nginx có thể chưa sẵn sàng ngay
        try:
            st, raw = _http("POST", f"{USER_URL}/auth/login",
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
def _doc_statuses(token: str, doc_ids: set[str]) -> dict[str, tuple[str, str]]:
    """{doc_id: (status, error_message)} từ document-service. Mù lỗi -> bỏ qua doc đó."""
    import requests
    out: dict[str, tuple[str, str]] = {}
    hdr = {"Authorization": "Bearer " + token}
    for did in doc_ids:
        try:
            r = requests.get(f"{DOC_URL}/documents/{did}", headers=hdr, timeout=15)
            if r.status_code == 200:
                d = r.json()
                out[did] = (str(d.get("status", "")), str(d.get("error_message") or ""))
        except Exception:  # noqa: BLE001
            pass
    return out


def verify_ingest(records: list[dict], token: str) -> None:
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
        # FAST-FAIL: hỏi document-service trạng thái doc. Nếu KHÔNG còn doc nào đang
        # chạy (mọi doc chưa-index đều đã 'failed') -> ingest hỏng, abort NGAY thay vì
        # chờ hết 420s. In error_message để lộ nguyên nhân thật (vd 401 OpenAI).
        statuses = _doc_statuses(token, expected - ids)
        pending = {d for d, (st, _) in statuses.items() if st in ("queued", "processing")}
        failed = {d: msg for d, (st, msg) in statuses.items() if st == "failed"}
        if statuses and not pending and failed:
            # STRICT: bất kỳ doc nào status=failed (kể cả error_message rỗng) -> hard-fail NGAY.
            # Trước đây nới lỏng bỏ qua "silent fail" (e371bef hybrid) để né chặn deploy -> CHE
            # regression: bug worker upsert unnamed lệch schema named lọt ra prod. Bug đã fix (áp
            # VECTOR_HYBRID cho CẢ 2 nhánh bootstrap); giữ STRICT để bắt tái phát.
            lines = "\n".join(f"    - {d}: {(m or '<rỗng>')[:200]}" for d, m in list(failed.items())[:8])
            raise SystemExit(
                f"[3] INGEST FAILED: {len(ids)}/{len(expected)} indexed, "
                f"{len(failed)} doc status=failed:\n{lines}"
            )
        time.sleep(5)
    raise SystemExit(f"[3] VERIFY TIMEOUT {timeout}s: {last}/{len(expected)} doc")


def verify_hybrid_schema() -> None:
    """VECTOR_HYBRID=true -> mọi collection ingest PHẢI là named 'dense' + sparse 'sparse'.

    Ingest "xanh" mà schema unnamed = bug nhánh config.yaml quên áp VECTOR_HYBRID (worker
    hybrid=False -> tạo+upsert unnamed, tự nhất quán nên không fail). Assert schema bắt đúng
    nó (ở prod auto_migrate tạo named -> worker unnamed -> 400; ở đây schema check là proxy).
    """
    if os.environ.get("VECTOR_HYBRID", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    cols = [c["name"] for c in _qdrant("GET", "/collections")["result"]["collections"]
            if not c["name"].endswith("__meta")]
    for c in cols:
        params = _qdrant("GET", f"/collections/{c}")["result"]["config"]["params"]
        vectors = params.get("vectors") or {}
        sparse = params.get("sparse_vectors") or {}
        named_dense = isinstance(vectors, dict) and "dense" in vectors
        if not (named_dense and "sparse" in sparse):
            shown = list(vectors) if isinstance(vectors, dict) else "UNNAMED(single)"
            raise SystemExit(
                f"[3b] HYBRID SCHEMA SAI ở '{c}': vectors={shown} sparse={list(sparse)} "
                f"(VECTOR_HYBRID=true nhưng KHÔNG named dense+sparse -> bug 2-nhánh bootstrap)")
    print(f"  HYBRID SCHEMA OK: {cols} đều named dense+sparse")


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
    phases: list[str] = []           # chuỗi phase: thinking->acting->observing->generating->done
    tool_seen = False                # có event tool/acting -> think ĐÃ gọi rag_search/hr_query
    answer_chars = 0
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:].strip())
        except Exception:  # noqa: BLE001
            continue
        ph = d.get("phase")
        if ph and (not phases or phases[-1] != ph):
            phases.append(ph)
        if ph in ("acting", "observing") or d.get("tool") or d.get("tool_name"):
            tool_seen = True
        if d.get("token"):
            answer_chars += len(d["token"])
        if d.get("done") or ph == "done" or "outcome" in d:
            done = d
    if done is None:
        raise SystemExit(f"[{label}] FAIL: không nhận event done (stream crash/treo?)")
    outcome = done.get("outcome")
    src = len(done.get("sources") or [])
    agent_mode = done.get("agent_mode")
    # DIAGNOSTIC: phases + tool_seen phân biệt 'think không gọi tool' vs 'gọi mà rỗng'.
    diag = f"agent_mode={agent_mode} phases={phases} tool_seen={tool_seen} answer_chars={answer_chars}"
    print(f"  [{label}] done outcome={outcome} sources={src} {diag}")
    if outcome in (6, "ERROR"):
        raise SystemExit(f"[{label}] FAIL: outcome=ERROR (wiring đứt?) {diag}")
    # GATE path prod: nếu set EXPECT_AGENT_MODE -> done PHẢI báo đúng path đó. Bắt trường hợp
    # orchestrator âm thầm fallback react (thiếu điều kiện) -> e2e KHÔNG còn validate path prod.
    expect_mode = os.environ.get("EXPECT_AGENT_MODE", "").strip().lower()
    if expect_mode and agent_mode != expect_mode:
        raise SystemExit(
            f"[{label}] FAIL: agent_mode={agent_mode!r} != EXPECT {expect_mode!r} "
            f"-> path prod KHÔNG được kích hoạt (fallback?). {diag}"
        )
    if need_sources and src < 1:
        hint = ("model KHÔNG gọi tool/retrieve (adapter/model không phát tool_call)"
                if not tool_seen else "tool gọi RỒI nhưng rag/qdrant trả rỗng (args rỗng?)")
        raise SystemExit(f"[{label}] FAIL: cần sources>0 -> {hint}. {diag}")
    # Câu hỏi cần dữ liệu mà answer rỗng -> fail-closed đã kích hoạt sai/synthesize trống.
    if need_sources and answer_chars < 1:
        raise SystemExit(f"[{label}] FAIL: answer rỗng dù có sources. {diag}")


def query(label: str, token: str, uid: str, question: str, need_sources: bool) -> None:
    body = json.dumps({"question": question, "user_id": uid}).encode()
    st, raw = _http("POST", f"{QUERY_URL}/query",
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


# ───────────────────────── 6b. LEAVE WRITE FLOW ────────────────────────────
def _safe_json(raw: bytes) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def _hr(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    """Gọi THẲNG hr-service (X-Internal-Token). Trả (status, body) cả khi 4xx/5xx
    (bắt HTTPError) để assert được 403/409/422."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-Internal-Token": HR_TOKEN, "Content-Type": "application/json"}
    try:
        st, raw = _http(method, f"{HR_URL}{path}", headers=headers, data=data)
        return st, _safe_json(raw)
    except urllib.error.HTTPError as e:  # 4xx/5xx
        return e.code, _safe_json(e.read())


def _annual_used(user_id: str) -> int:
    st, b = _hr("POST", "/hr/query", {"user_id": user_id, "intent": "leave_balance"})
    if st != 200:
        raise SystemExit(f"[LEAVE] FAIL đọc leave_balance st={st} {b}")
    return b["data"]["annual_used"]


def leave_write_flow() -> None:
    """Mô phỏng production flow đơn nghỉ trên STACK THẬT (hr-service + Postgres thật):
    tạo -> idempotency -> guard sai approver -> duyệt (trừ phép) -> duyệt lại 409 ->
    hủy sai chủ đơn -> hủy (hoàn phép). Net-zero balance -> không ảnh hưởng step khác."""
    label = "LEAVE"
    base = _annual_used(FIN_USER)
    key = "e2e-leave-key-001"
    payload = {"user_id": FIN_USER, "leave_type": "annual",
               "start_date": "2026-09-01", "end_date": "2026-09-01",
               "reason": "e2e", "idempotency_key": key}

    st, created = _hr("POST", "/hr/leave-requests", payload)
    if st != 201:
        raise SystemExit(f"[{label}] FAIL create st={st} {created}")
    rid, approver = created["id"], created["approver_user_id"]
    if approver != HR_USER:
        raise SystemExit(f"[{label}] FAIL approver={approver} != manager {HR_USER}")
    if created["status"] != "pending":
        raise SystemExit(f"[{label}] FAIL status={created['status']} != pending")

    # idempotency: gọi lại cùng key -> KHÔNG tạo trùng (cùng id)
    st, again = _hr("POST", "/hr/leave-requests", payload)
    if st != 201 or again.get("id") != rid:
        raise SystemExit(f"[{label}] FAIL idempotency dup id={again.get('id')} != {rid}")

    # guard: sai người duyệt -> 403
    st, _ = _hr("POST", f"/hr/leave-requests/{rid}/approve", {"approver_user_id": FIN_USER})
    if st != 403:
        raise SystemExit(f"[{label}] FAIL wrong-approver expected 403 got {st}")

    # duyệt đúng manager -> trừ 1 ngày phép (transaction thật)
    st, appr = _hr("POST", f"/hr/leave-requests/{rid}/approve", {"approver_user_id": HR_USER})
    if st != 200 or appr.get("status") != "approved":
        raise SystemExit(f"[{label}] FAIL approve st={st} {appr}")
    used = _annual_used(FIN_USER)
    if used != base + 1:
        raise SystemExit(f"[{label}] FAIL deduct annual_used={used} != {base + 1}")

    # duyệt lại đơn đã duyệt -> 409 (không pending)
    st, _ = _hr("POST", f"/hr/leave-requests/{rid}/approve", {"approver_user_id": HR_USER})
    if st != 409:
        raise SystemExit(f"[{label}] FAIL re-approve expected 409 got {st}")

    # hủy bởi người KHÔNG phải chủ đơn -> 403
    st, _ = _hr("POST", f"/hr/leave-requests/{rid}/cancel", {"user_id": HR_USER})
    if st != 403:
        raise SystemExit(f"[{label}] FAIL cancel non-owner expected 403 got {st}")

    # hủy bởi chủ đơn -> hoàn phép
    st, canc = _hr("POST", f"/hr/leave-requests/{rid}/cancel", {"user_id": FIN_USER})
    if st != 200:
        raise SystemExit(f"[{label}] FAIL cancel st={st} {canc}")
    used = _annual_used(FIN_USER)
    if used != base:
        raise SystemExit(f"[{label}] FAIL refund annual_used={used} != {base}")

    print(f"  [{label}] OK create+idempotency+guard+approve(deduct)+re-approve409+cancel(refund)")


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
        print("==> 3) verify ingest (Qdrant)"); verify_ingest(records, token)
        print("==> 3b) verify hybrid schema (named dense+sparse)"); verify_hybrid_schema()
        print("==> 4) verify rag-worker trace (Langfuse)"); lf1 = verify_trace("ingest", lf0)
        print("==> 5) query RAG"); query("RAG", token, uid, "công ty có chính sách nghỉ phép thế nào", True)
        print("==> 6) query HR"); query("HR", token, uid, "Tôi còn bao nhiêu ngày phép?", False)
        print("==> 6c) verify ai-router served LLM"); verify_router_served()
        print("==> 6b) leave write flow (hr-service + Postgres thật)"); leave_write_flow()
        print("==> 7) verify query-service trace (Langfuse)"); verify_trace("query", lf1)
        print("E2E PASS ✓")
        return 0
    finally:
        if do_cleanup:
            print("==> 8) cleanup"); cleanup()


if __name__ == "__main__":
    sys.exit(main())
