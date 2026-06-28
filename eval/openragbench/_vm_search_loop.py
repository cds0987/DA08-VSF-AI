"""Chạy BÊN TRONG container rag-worker (qua: docker exec -e RB64=<b64> -i rag-worker python < this).
Đọc recall_input (doc_ids ACL + queries) -> POST localhost:8000/api/search từng query ->
dedupe candidate về doc-level (document_name) -> in ranks JSON ra stdout (dòng RANKS=)."""
import base64
import json
import os
import urllib.request

EXTS = (".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".pptx", ".xlsx", ".html", ".htm")


def norm(name):
    s = (name or "").strip().lower()
    for ext in EXTS:
        if s.endswith(ext):
            return s[: -len(ext)]
    return s


def main():
    data = json.loads(base64.b64decode(os.environ["RB64"]))
    doc_ids = data["doc_ids"]
    queries = data["queries"]
    top_k = int(data.get("top_k", 10))
    out = []
    for q in queries:
        body = json.dumps({"query": q["query"], "document_ids": doc_ids, "top_k": top_k}).encode()
        req = urllib.request.Request(
            "http://localhost:8000/api/search", data=body,
            headers={"content-type": "application/json"},
        )
        try:
            r = json.load(urllib.request.urlopen(req, timeout=90))
            cands = r.get("candidates", [])
        except Exception as e:  # noqa: BLE001
            out.append({"gt_id": q["gt_id"], "type": q.get("type"), "ranked": [], "err": str(e)[:120]})
            continue
        ranked, seen = [], set()
        for c in cands:
            d = norm(c.get("document_name"))
            if d and d not in seen:
                seen.add(d)
                ranked.append(d)
        out.append({"gt_id": q["gt_id"], "type": q.get("type"), "ranked": ranked[:top_k],
                    "n_cands": len(cands)})
    print("RANKS=" + json.dumps(out, ensure_ascii=False))


main()
