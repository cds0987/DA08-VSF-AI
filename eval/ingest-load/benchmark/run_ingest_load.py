# -*- coding: utf-8 -*-
"""Ingest-load runner: đập N file vào /api/documents/upload (open-loop, RATE cố định
hoặc burst concurrency), rồi POLL từng doc tới terminal (indexed/failed) — đo latency
END-TO-END ingest (dispatch -> indexed) dưới tải. Tương đương run_load.py của queryeval
nhưng cho đường INGEST (document-service nhận + rag-worker drain) thay vì query.

Vì sao tách 2 pha: POST /upload trả 202 NGAY (chỉ store+publish NATS), tải thật nằm ở
rag-worker drain queue — nên phải poll status để biết khi nào doc THỰC SỰ indexed.

Mỗi record JSONL: dispatch_s (lúc gửi POST), accept_s (lúc 202), accept_latency,
indexed_s (lúc thấy terminal), e2e_latency = indexed_s - dispatch_s, status, chunks, doc_id.

Creds qua ENV: CE / CP (admin). KHÔNG hardcode.
Usage:
  CE=.. CP=.. PYTHONUTF8=1 python run_ingest_load.py --count 100 --files-dir <dir> [--rate 5] [--concurrency 20]
  CE=.. CP=.. python run_ingest_load.py --cleanup results/ingest_results.jsonl
"""
import sys, os, json, time, threading, uuid, argparse, mimetypes
from concurrent.futures import ThreadPoolExecutor
import requests

BASE = os.environ.get("BASE", "https://vsfchat.cloud")
LOGIN = f"{BASE}/api/user/auth/login"
UPLOAD = f"{BASE}/api/documents/upload"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "ingest_results.jsonl")
POLL_INTERVAL = 4.0
POLL_TIMEOUT = 1800.0  # 30 min — 1 worker drain 100 file có thể lâu

_lock = threading.Lock()


def login(email, pw):
    r = requests.post(LOGIN, json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def pick_files(files_dir, count):
    exts = (".pdf", ".docx", ".xlsx", ".html", ".md", ".txt", ".jpg", ".jpeg", ".webp", ".png", ".csv", ".pptx")
    pool = sorted(p for p in os.listdir(files_dir)
                  if os.path.isfile(os.path.join(files_dir, p)) and os.path.splitext(p)[1].lower() in exts)
    if not pool:
        raise SystemExit(f"no files in {files_dir}")
    return [os.path.join(files_dir, pool[i % len(pool)]) for i in range(count)]


def upload_one(tok, path, idx, t0):
    """POST /upload (multipart). Trả record với dispatch/accept timing + doc_id."""
    hdr = {"authorization": f"Bearer {tok}"}
    name = f"loadtest_{idx:03d}_{os.path.basename(path)}"
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    dispatch_s = round(time.perf_counter() - t0, 3)
    try:
        with open(path, "rb") as fh:
            r = requests.post(UPLOAD, headers=hdr,
                              files={"file": (name, fh, mime)},
                              data={"classification": "internal"}, timeout=120)
        accept_s = round(time.perf_counter() - t0, 3)
        ok = r.status_code in (200, 202)
        doc_id = r.json().get("document_id") if ok else None
        return {"idx": idx, "name": name, "dispatch_s": dispatch_s, "accept_s": accept_s,
                "accept_latency": round(accept_s - dispatch_s, 3), "http": r.status_code,
                "doc_id": doc_id, "err": None if ok else r.text[:200]}
    except Exception as e:
        accept_s = round(time.perf_counter() - t0, 3)
        return {"idx": idx, "name": name, "dispatch_s": dispatch_s, "accept_s": accept_s,
                "accept_latency": round(accept_s - dispatch_s, 3), "http": 0,
                "doc_id": None, "err": f"{type(e).__name__}: {str(e)[:150]}"}


def poll_until_terminal(tok, records, t0):
    """Poll mọi doc_id tới indexed/failed; gán indexed_s + e2e_latency."""
    hdr = {"authorization": f"Bearer {tok}"}
    pending = {rec["doc_id"]: rec for rec in records if rec.get("doc_id")}
    deadline = time.perf_counter() + POLL_TIMEOUT
    while pending and time.perf_counter() < deadline:
        for did in list(pending.keys()):
            try:
                r = requests.get(f"{BASE}/api/documents/{did}", headers=hdr, timeout=30)
                if r.ok:
                    j = r.json()
                    st = j.get("status")
                    if st in ("indexed", "failed"):
                        rec = pending.pop(did)
                        rec["indexed_s"] = round(time.perf_counter() - t0, 3)
                        rec["e2e_latency"] = round(rec["indexed_s"] - rec["dispatch_s"], 3)
                        rec["final_status"] = st
                        rec["chunks"] = j.get("chunk_count")
                        print(f"  [{len(records)-len(pending)}/{len(records)}] {st} chunks={j.get('chunk_count')} "
                              f"e2e={rec['e2e_latency']}s :: {rec['name'][:50]}")
            except Exception:
                pass
        if pending:
            time.sleep(POLL_INTERVAL)
    for rec in pending.values():  # timeout
        rec["indexed_s"] = None; rec["e2e_latency"] = None; rec["final_status"] = "timeout"


def cleanup(path):
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    ids = [r["doc_id"] for r in recs if r.get("doc_id")]
    tok = login(os.environ["CE"], os.environ["CP"])
    # bulk-delete theo lô 200
    for i in range(0, len(ids), 200):
        chunk = ids[i:i+200]
        r = requests.post(f"{BASE}/api/documents/bulk-delete",
                          headers={"authorization": f"Bearer {tok}", "content-type": "application/json"},
                          json={"document_ids": chunk}, timeout=120)
        print(f"bulk-delete {len(chunk)} -> {r.status_code} {r.text[:160]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--files-dir")
    ap.add_argument("--rate", type=float, help="open-loop arrival rate (req/s). Bỏ qua = burst.")
    ap.add_argument("--concurrency", type=int, default=20, help="số luồng upload song song (burst mode)")
    ap.add_argument("--cleanup", metavar="RESULTS_JSONL", help="bulk-delete doc_id trong file kết quả rồi thoát")
    ap.add_argument("--label", default="baseline")
    args = ap.parse_args()

    if args.cleanup:
        cleanup(args.cleanup)
        return

    email, pw = os.environ.get("CE"), os.environ.get("CP")
    if not email or not pw:
        raise SystemExit("thiếu env CE / CP (admin creds)")
    tok = login(email, pw)
    print(f"login OK | base={BASE} | count={args.count} | mode={'rate '+str(args.rate) if args.rate else 'burst c='+str(args.concurrency)}")

    files = pick_files(args.files_dir, args.count)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    t0 = time.perf_counter()
    records = [None] * args.count

    # PHA 1: upload (open-loop rate hoặc burst concurrency)
    print("== PHA 1: UPLOAD ==")
    if args.rate:
        interval = 1.0 / args.rate
        futs = []
        with ThreadPoolExecutor(max_workers=max(8, int(args.rate * 4))) as ex:
            for i, path in enumerate(files):
                futs.append(ex.submit(upload_one, tok, path, i, t0))
                time.sleep(interval)
            for i, f in enumerate(futs):
                records[i] = f.result()
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {ex.submit(upload_one, tok, p, i, t0): i for i, p in enumerate(files)}
            for f in futs:
                i = futs[f]; records[i] = f.result()
    accepted = [r for r in records if r and r.get("doc_id")]
    up_window = max((r["accept_s"] for r in records if r), default=0)
    print(f"accepted {len(accepted)}/{args.count} | upload window {up_window:.1f}s | "
          f"accept_lat avg={sum(r['accept_latency'] for r in records)/len(records):.2f}s")

    # PHA 2: poll tới terminal
    print("== PHA 2: POLL tới indexed/failed ==")
    poll_until_terminal(tok, records, t0)

    with _lock, open(OUT, "w", encoding="utf-8") as fh:
        for r in records:
            r["label"] = args.label
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    done = [r for r in records if r.get("final_status") in ("indexed", "failed")]
    print(f"\nDONE: {len(done)}/{args.count} terminal | wrote {OUT}")
    print(f"  -> aggregate: python {os.path.join('benchmark','aggregate.py')} {OUT}")
    print(f"  -> cleanup:   CE=.. CP=.. python benchmark/run_ingest_load.py --cleanup {OUT}")


if __name__ == "__main__":
    main()
