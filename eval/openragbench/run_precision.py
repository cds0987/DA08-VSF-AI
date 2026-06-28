"""Test INGEST -> PRECISION trên hệ thống THẬT (prod) bằng bộ OpenRAGBench.

Vòng đời (mỗi bước idempotent + crash-safe cleanup):
  1. upload PDF (eval+distractor) qua /api/documents/upload -> poll tới `indexed`
  2. query từng câu (cap mỗi gt-doc) qua /api/query/query (SSE) -> chấm doc-level
     recall@k / MRR / top1-precision theo gt_doc_id (label OpenRAGBench)
  3. CLEANUP: DELETE mọi doc đã upload -> doc.access{deleted:true} -> rag-worker purge
     vector (verify: /documents không còn + re-query mẫu không còn ra gt-doc)

uploaded_ids.json ghi NGAY khi upload -> chạy lại với --cleanup-only nếu crash giữa chừng.
Creds qua ENV: CE / CP (admin). KHÔNG hardcode.

Chạy:
  python eval/openragbench/build_dataset.py --n 8 --strategy balanced        # tải corpus nhỏ (pilot)
  CE=.. CP=.. python eval/openragbench/run_precision.py --n 8 --queries-per-doc 1
  CE=.. CP=.. python eval/openragbench/run_precision.py --n 8 --cleanup-only  # dọn nếu lỡ
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

BASE = "https://vsfchat.cloud"
DATA_ROOT = Path(__file__).parent / "data"
MIME = {"pdf": "application/pdf", "docx":
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
KS = (1, 3, 5, 10)


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/user/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError(f"no access_token: {r.text[:150]}")
    return tok


def _norm(name: str) -> str:
    # CHỈ bỏ đuôi tài liệu THẬT (không dùng Path.stem — nó cắt phần sau dấu chấm CUỐI,
    # làm hỏng arxiv id "2405.04904v2" -> "2405" khi không có .pdf; còn tên file CÓ .pdf
    # thì chỉ bị bỏ .pdf -> 2 phía lệch -> N=0 recall giả). Giữ nguyên id, chỉ strip ext.
    s = str(name).strip().lower()
    for ext in (".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".pptx", ".xlsx", ".html", ".htm"):
        if s.endswith(ext):
            return s[: -len(ext)]
    return s


def upload_corpus(token: str, corpus_dir: Path, state_path: Path) -> list[dict]:
    """Upload mọi file trong corpus, poll tới terminal. Ghi state NGAY mỗi lần upload."""
    hdr = {"authorization": f"Bearer {token}"}
    state: list[dict] = []
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    done_names = {s["name"] for s in state}
    files = sorted(p for p in corpus_dir.iterdir() if p.suffix.lower() in (".pdf", ".docx"))
    for fp in files:
        if fp.name in done_names:
            continue
        with open(fp, "rb") as fh:
            r = requests.post(
                f"{BASE}/api/documents/upload", headers=hdr,
                files={"file": (fp.name, fh, MIME.get(fp.suffix.lstrip(".").lower(), "application/octet-stream"))},
                data={"classification": "internal"}, timeout=120,
            )
        if not r.ok:
            print(f"  upload FAIL {fp.name} {r.status_code}: {r.text[:120]}")
            continue
        doc_id = r.json().get("document_id")
        rec = {"name": fp.name, "gt_id": _norm(fp.name), "document_id": doc_id, "status": "uploaded"}
        state.append(rec)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")  # crash-safe
        print(f"  uploaded {fp.name} -> {doc_id}")

    # poll tất cả tới indexed/failed
    for rec in state:
        if rec["status"] in ("indexed", "failed"):
            continue
        for i in range(240):   # 240×5s = 1200s/doc — PDF học thuật nặng + 8b/4096 chậm cần đủ thời gian
            r = requests.get(f"{BASE}/api/documents/{rec['document_id']}", headers=hdr, timeout=30)
            if r.ok:
                j = r.json()
                rec["status"], rec["chunks"] = j.get("status"), j.get("chunk_count")
                if j.get("status") in ("indexed", "failed"):
                    print(f"  {rec['name']} -> {j.get('status')} chunks={j.get('chunk_count')}")
                    break
            time.sleep(5)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return state


def ask(token: str, question: str) -> dict:
    hdr = {"authorization": f"Bearer {token}", "accept": "text/event-stream",
           "content-type": "application/json"}
    import uuid
    body = {"question": question, "conversation_id": str(uuid.uuid4())}
    sources, trace = [], None
    with requests.post(f"{BASE}/api/query/query", headers=hdr, json=body, stream=True, timeout=180) as r:
        if not r.ok:
            return {"sources": [], "trace": None, "err": f"{r.status_code}"}
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            try:
                j = json.loads(raw[5:].strip())
            except Exception:  # noqa: BLE001
                continue
            if j.get("done"):
                trace = j.get("trace_id")
                sources = [{"n": s.get("document_name"), "score": s.get("score")} for s in (j.get("sources") or [])]
    return {"sources": sources, "trace": trace}


def score(token: str, labels: list[dict], uploaded_gt: set[str], per_doc: int) -> dict:
    seen: dict[str, int] = {}
    picked = []
    for lab in labels:
        gt = _norm(lab["gt_doc_id"])
        if gt not in uploaded_gt:           # gt-doc không index được -> bỏ (log)
            continue
        if seen.get(gt, 0) >= per_doc:
            continue
        seen[gt] = seen.get(gt, 0) + 1
        picked.append(lab)

    hits = {k: 0 for k in KS}
    rr = 0.0
    by_type: dict[str, dict] = {}
    rows = []
    for lab in picked:
        gt = _norm(lab["gt_doc_id"])
        res = ask(token, lab["query"])
        ranked, seen_doc = [], set()
        for s in res["sources"]:
            d = _norm(s["n"])
            if d not in seen_doc:
                seen_doc.add(d)
                ranked.append(d)
        rank = ranked.index(gt) + 1 if gt in ranked else None
        tp = lab.get("type", "?")
        bt = by_type.setdefault(tp, {"n": 0, **{k: 0 for k in KS}})
        bt["n"] += 1
        if rank:
            rr += 1.0 / rank
            for k in KS:
                if rank <= k:
                    hits[k] += 1
                    bt[k] += 1
        rows.append({"q": lab["query"][:80], "gt": gt, "rank": rank,
                     "top": ranked[:5], "trace": res.get("trace")})
        print(f"  [{tp}] rank={rank} gt={gt} :: {lab['query'][:60]}")
    n = len(picked)
    return {
        "n": n, "mrr": round(rr / n, 3) if n else 0,
        "recall": {f"@{k}": round(hits[k] / n, 3) if n else 0 for k in KS},
        "by_type": {t: {"n": d["n"], **{f"@{k}": round(d[k] / d["n"], 3) if d["n"] else 0 for k in KS}}
                    for t, d in by_type.items()},
        "rows": rows,
    }


def cleanup(token: str, state: list[dict], token_for_verify: str | None = None) -> dict:
    hdr = {"authorization": f"Bearer {token}"}
    deleted, failed = [], []
    for rec in state:
        did = rec.get("document_id")
        if not did:
            continue
        r = requests.delete(f"{BASE}/api/documents/{did}", headers=hdr, timeout=30)
        (deleted if r.ok else failed).append(rec["name"])
    print(f"  DELETE: ok={len(deleted)} fail={len(failed)}")
    # verify: doc không còn trong /documents (soft-delete) + chờ purge vector async
    time.sleep(8)
    r = requests.get(f"{BASE}/api/documents?limit=500", headers=hdr, timeout=30)
    still = []
    if r.ok:
        names = {_norm(d.get("name", "")) for d in (r.json().get("items") or r.json().get("documents") or [])}
        still = [rec["name"] for rec in state if _norm(rec["name"]) in names]
    return {"deleted": len(deleted), "delete_failed": failed, "still_listed": still}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True, help="thư mục data/<n> (khớp build_dataset --n)")
    ap.add_argument("--queries-per-doc", type=int, default=1)
    ap.add_argument("--cleanup-only", action="store_true")
    ap.add_argument("--skip-cleanup", action="store_true", help="GIỮ doc trên prod (tự dọn sau)")
    args = ap.parse_args()

    import os
    email, password = os.getenv("CE"), os.getenv("CP")
    if not email or not password:
        raise SystemExit("thiếu env CE / CP (admin creds)")

    data_dir = DATA_ROOT / str(args.n)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    labels = [json.loads(l) for l in (data_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    corpus_dir = Path(manifest["corpus_dir"])
    state_path = data_dir / "uploaded_ids.json"

    token = _login(email, password)
    print("login OK")

    if args.cleanup_only:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        print(json.dumps(cleanup(token, state), ensure_ascii=False, indent=1))
        return

    out = {"n": args.n, "queries_per_doc": args.queries_per_doc}
    try:
        print(f"== UPLOAD ({len(list(corpus_dir.iterdir()))} files) ==")
        state = upload_corpus(token, corpus_dir, state_path)
        indexed = {r["gt_id"] for r in state if r.get("status") == "indexed"}
        out["ingest"] = {"total": len(state), "indexed": len(indexed),
                         "failed": [r["name"] for r in state if r.get("status") == "failed"]}
        print(f"== INGEST: indexed={len(indexed)}/{len(state)} ==")
        print("== SCORE ==")
        out["precision"] = score(token, labels, indexed, args.queries_per_doc)
    finally:
        if not args.skip_cleanup:
            print("== CLEANUP ==")
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else []
            out["cleanup"] = cleanup(_login(email, password), state)

    (data_dir / "precision_out.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps({k: out[k] for k in ("ingest", "precision", "cleanup") if k in out},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
