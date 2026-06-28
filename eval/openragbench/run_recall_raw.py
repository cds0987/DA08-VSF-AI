"""Combined RAG-worker benchmark: LATENCY/PERF (upload song song N doc) + RECALL@k THẬT.

Khác run_precision: recall chấm qua rag-worker **/api/search TRỰC TIẾP** (embed+vector+RRF,
CHƯA orchestrator) -> đo đúng chất lượng retrieval embedding, KHÔNG bị HR-orchestrator
topic-gate câu hỏi off-domain (academic) -> trả 0 sources (lý do recall qua /api/query = 0).

Vòng đời:
  phase1 (script này): upload SONG SONG corpus (đo accept + e2e latency p50/p95/p99) ->
          poll tới terminal -> ghi uploaded_ids.json + latency.json + recall_input.json.
  phase2 (ngoài VM): docker exec rag-worker -> POST localhost:8000/api/search từng query
          (document_ids = mọi doc đã index = ACL scope) -> ranks.json.
  phase3 (--score ranks.json): doc-level recall@1/3/5/10 / MRR theo gt_doc_id.
  cleanup: tái dùng run_precision.py --cleanup-only (cùng format uploaded_ids.json).

Creds qua ENV CE/CP. KHÔNG hardcode.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from run_precision import BASE, DATA_ROOT, MIME, _login, _norm

KS = (1, 3, 5, 10)


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return round(s[i], 1)


def _upload_one(token: str, fp: Path) -> dict:
    hdr = {"authorization": f"Bearer {token}"}
    t0 = time.time()
    last_err = None
    # retry: tầng upload reset kết nối dưới burst (ConnectionReset 10054) -> backoff + thử lại.
    for attempt in range(4):
        try:
            with open(fp, "rb") as fh:
                r = requests.post(
                    f"{BASE}/api/documents/upload", headers=hdr,
                    files={"file": (fp.name, fh, MIME.get(fp.suffix.lstrip(".").lower(), "application/octet-stream"))},
                    data={"classification": "internal"}, timeout=180,
                )
            dt = time.time() - t0
            if r.status_code in (429, 502, 503, 504):  # tải nặng tạm thời -> retry
                last_err = f"http{r.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if not r.ok:
                return {"name": fp.name, "gt_id": _norm(fp.name), "document_id": None,
                        "status": "upload_fail", "accept_s": round(dt, 3), "http": r.status_code, "t0": t0}
            return {"name": fp.name, "gt_id": _norm(fp.name), "document_id": r.json().get("document_id"),
                    "status": "uploaded", "accept_s": round(dt, 3), "http": r.status_code,
                    "retries": attempt, "t0": t0}
        except Exception as e:  # noqa: BLE001  (ConnectionReset/ConnectionError dưới burst)
            last_err = str(e)[:120]
            time.sleep(1.5 * (attempt + 1))
    return {"name": fp.name, "gt_id": _norm(fp.name), "document_id": None,
            "status": "upload_err", "accept_s": round(time.time() - t0, 3), "err": last_err, "t0": t0}


def _poll_one(token: str, rec: dict) -> dict:
    """Poll 1 doc tới terminal; e2e = từ lúc bắt đầu upload (t0) tới indexed."""
    hdr = {"authorization": f"Bearer {token}"}
    if not rec.get("document_id"):
        return rec
    for _ in range(360):  # 360×5s = 1800s/doc trần
        try:
            r = requests.get(f"{BASE}/api/documents/{rec['document_id']}", headers=hdr, timeout=30)
            if r.ok:
                j = r.json()
                st = j.get("status")
                rec["status"], rec["chunks"] = st, j.get("chunk_count")
                if st in ("indexed", "failed"):
                    rec["e2e_s"] = round(time.time() - rec["t0"], 1)
                    return rec
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    rec["status"] = rec.get("status") or "timeout"
    rec["e2e_s"] = round(time.time() - rec["t0"], 1)
    return rec


def run_phase1(out_dir: Path, concurrency: int, label: str) -> None:
    token = _login(os.environ["CE"], os.environ["CP"])
    corpus = out_dir / "corpus"
    files = sorted(p for p in corpus.iterdir() if p.suffix.lower() in (".pdf", ".docx"))
    print(f"[phase1] upload SONG SONG {len(files)} doc, concurrency={concurrency}")

    t_start = time.time()
    records: list[dict] = []
    state_path = out_dir / "uploaded_ids.json"
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(_upload_one, token, fp) for fp in files]
        for f in as_completed(futs):
            rec = f.result()
            records.append(rec)
            # ghi incremental (main thread, an toàn) -> Monitor thấy tiến độ upload real-time.
            state_path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  upload {rec['name']} -> {rec['status']} ({rec.get('accept_s')}s)")
    upload_window = round(time.time() - t_start, 1)

    accepted = [r for r in records if r.get("document_id")]
    print(f"[phase1] accepted={len(accepted)}/{len(files)} | upload_window={upload_window}s | poll ingest...")

    # poll song song
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(_poll_one, token, r) for r in accepted]
        done = 0
        for f in as_completed(futs):
            f.result(); done += 1
            if done % 10 == 0:
                print(f"  polled {done}/{len(accepted)}")
    total_wall = round(time.time() - t_start, 1)
    (out_dir / "uploaded_ids.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    indexed = [r for r in records if r.get("status") == "indexed"]
    failed = [r for r in records if r.get("status") == "failed"]
    accept_l = [r["accept_s"] for r in accepted]
    e2e_l = [r["e2e_s"] for r in indexed if "e2e_s" in r]

    lat = {
        "label": label, "n": len(files), "concurrency": concurrency,
        "accepted": len(accepted), "indexed": len(indexed), "failed": len(failed),
        "upload_window_s": upload_window, "total_wall_s": total_wall,
        "throughput_doc_s": round(len(indexed) / total_wall, 3) if total_wall else 0,
        "accept_latency": {"p50": _pct(accept_l, 50), "p95": _pct(accept_l, 95), "p99": _pct(accept_l, 99), "max": round(max(accept_l), 1) if accept_l else 0},
        "e2e_latency": {"p50": _pct(e2e_l, 50), "p90": _pct(e2e_l, 90), "p95": _pct(e2e_l, 95), "p99": _pct(e2e_l, 99), "max": round(max(e2e_l), 1) if e2e_l else 0,
                        "avg": round(sum(e2e_l) / len(e2e_l), 1) if e2e_l else 0},
    }
    (out_dir / "latency.json").write_text(json.dumps(lat, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== LATENCY/PERF rag-worker (upload song song) ===")
    print(json.dumps(lat, ensure_ascii=False, indent=2))
    if failed:
        print("failed docs:", [r["name"] for r in failed][:10])

    # recall_input: doc_ids ACL scope (mọi doc index được) + queries từ labels
    labels = [json.loads(l) for l in (out_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    indexed_gt = {_norm(r["gt_id"]) for r in indexed}
    doc_ids = [r["document_id"] for r in indexed]
    qpd = int(os.environ.get("QPD", "2"))
    seen: dict[str, int] = {}
    queries = []
    for lab in labels:
        gt = _norm(lab["gt_doc_id"])
        if gt not in indexed_gt:
            continue
        if seen.get(gt, 0) >= qpd:
            continue
        seen[gt] = seen.get(gt, 0) + 1
        queries.append({"gt_id": gt, "query": lab["query"], "type": lab.get("type", "?")})
    recall_input = {"doc_ids": doc_ids, "queries": queries, "top_k": 10}
    (out_dir / "recall_input.json").write_text(json.dumps(recall_input, ensure_ascii=False), encoding="utf-8")
    print(f"\n[phase1] recall_input: {len(doc_ids)} doc trong ACL scope, {len(queries)} query (eval-doc index={len(indexed_gt & {_norm(l['gt_doc_id']) for l in labels})})")
    print(f"  -> {out_dir/'recall_input.json'}")


def run_score(out_dir: Path, ranks_path: Path) -> None:
    ranks = json.loads(ranks_path.read_text(encoding="utf-8"))
    hits = {k: 0 for k in KS}
    rr = 0.0
    by_type: dict[str, dict] = {}
    for row in ranks:
        gt = _norm(row["gt_id"])
        ranked = [_norm(d) for d in row.get("ranked", [])]
        rank = ranked.index(gt) + 1 if gt in ranked else None
        tp = row.get("type", "?")
        bt = by_type.setdefault(tp, {"n": 0, **{k: 0 for k in KS}})
        bt["n"] += 1
        if rank:
            rr += 1.0 / rank
            for k in KS:
                if rank <= k:
                    hits[k] += 1
                    bt[k] += 1
    n = len(ranks)
    out = {
        "n": n, "mrr": round(rr / n, 3) if n else 0,
        "recall": {f"@{k}": round(hits[k] / n, 3) if n else 0 for k in KS},
        "by_type": {t: {"n": d["n"], **{f"@{k}": round(d[k] / d["n"], 3) if d["n"] else 0 for k in KS}}
                    for t, d in by_type.items()},
    }
    (out_dir / "recall_raw_out.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== RECALL@k RAW (rag-worker /api/search, bypass orchestrator) ===")
    print(json.dumps(out["recall"], ensure_ascii=False))
    print("MRR =", out["mrr"], "| N =", n)
    print("by_type:", json.dumps(out["by_type"], ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="thư mục data/<N> (vd data/38)")
    ap.add_argument("--concurrency", type=int, default=12)  # PDF nặng: 20 làm tầng upload reset ~48%
    ap.add_argument("--label", default="recall_raw")
    ap.add_argument("--score", help="ranks.json từ VM -> chấm recall")
    args = ap.parse_args()
    out_dir = Path(args.dir) if Path(args.dir).is_absolute() else DATA_ROOT / Path(args.dir).name

    if args.score:
        run_score(out_dir, Path(args.score))
    else:
        run_phase1(out_dir, args.concurrency, args.label)


if __name__ == "__main__":
    main()
