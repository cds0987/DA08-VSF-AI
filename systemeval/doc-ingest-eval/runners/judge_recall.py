"""Chấm RELEVANCE recall multi-collection bằng LLM-judge ("chấm tay" ở quy mô 100-150 câu).

Khác gt-match (doc-level binary): judge đọc (query + chunk hệ THẬT trả về qua shard-read merge) rồi
phán *chunk có chứa câu trả lời không* -> đo "tỉ lệ câu được trả lời đúng", sát user cuối hơn.

2 PHASE (container không có internet ra OpenRouter; tách retrieval khỏi judging):

  PHASE A — retrieve (CHẠY TRONG container rag-worker, có /api/search + Qdrant):
      docker exec -e LABELS=/tmp/labels.jsonl rag-worker python /tmp/judge_recall.py --retrieve
      -> POST localhost:8000/api/search từng query (document_ids = mọi doc index) -> top_k chunk
      -> ghi /tmp/retrieved.jsonl {query, gt, chunks:[{doc,text}]}

  PHASE B — judge (CHẠY LOCAL, có OR_KEY):
      OR_KEY=... python judge_recall.py --judge retrieved.jsonl
      -> mỗi câu: LLM đọc query+chunk -> relevant@1/@3/@5 -> in tổng hợp + ghi verdicts.jsonl
"""
from __future__ import annotations

import json
import math  # noqa: F401 (giữ cho tiện mở rộng metric)
import os
import re
import sys
import urllib.request

EXTS = (".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".xlsx", ".html", ".htm")


def _norm(s: str | None) -> str:
    s = (s or "").strip().lower()
    for e in EXTS:
        if s.endswith(e):
            return s[: -len(e)]
    return s


# ───────────────────────── PHASE A: retrieve (trong container) ─────────────────────────
def retrieve() -> None:
    labels_path = os.getenv("LABELS", "/tmp/labels.jsonl")
    top_k = int(os.getenv("TOP_K", "5"))
    cols = os.getenv("COLLECTIONS",
                     "qwen3emb8b__d4096__s2,bgem3__d1024__s2,te3s__d1536__s2,pplxembed__d1024__s2").split(",")
    # doc_ids = ACL scope = mọi doc đã index (đủ N collection)
    ids: set[str] = set()
    for c in cols:
        off = None
        while True:
            body = {"limit": 200, "with_payload": ["document_id"]}
            if off:
                body["offset"] = off
            req = urllib.request.Request(
                f"http://qdrant:6333/collections/rag_chatbot__{c.strip()}/points/scroll",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
            res = json.load(urllib.request.urlopen(req))["result"]
            for p in res["points"]:
                ids.add(p["payload"]["document_id"])
            off = res.get("next_page_offset")
            if not off:
                break
    doc_ids = list(ids)
    labels = [json.loads(line) for line in open(labels_path, encoding="utf-8") if line.strip()]
    out = open("/tmp/retrieved.jsonl", "w", encoding="utf-8")
    for lab in labels:
        body = {"query": lab["query"], "document_ids": doc_ids, "top_k": top_k}
        req = urllib.request.Request("http://localhost:8000/api/search", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        cands = json.load(urllib.request.urlopen(req, timeout=60))["candidates"]
        chunks = [{"doc": c["document_name"], "text": (c.get("child_text") or c.get("parent_text") or "")[:450]}
                  for c in cands]
        out.write(json.dumps({"query": lab["query"], "gt": lab.get("gt_doc_id"), "ref_answer": lab.get("ref_answer"), "chunks": chunks},
                             ensure_ascii=False) + "\n")
    out.close()
    print(f"[retrieve] {len(labels)} query, {len(doc_ids)} doc ACL, top_k={top_k} -> /tmp/retrieved.jsonl")


# ───────────────────────── PHASE B: judge (local, OpenRouter) ─────────────────────────
_JUDGE_MODEL = os.getenv("JUDGE_MODEL", "google/gemini-2.5-flash")


def _judge_one(query: str, chunks: list[dict]) -> dict:
    listing = "\n".join(f"[{i+1}] (doc: {c['doc'][:40]}) {c['text']}" for i, c in enumerate(chunks))
    prompt = (
        "Bạn là giám khảo đánh giá hệ truy hồi tài liệu HR. Cho CÂU HỎI và các ĐOẠN hệ trả về (xếp hạng). "
        "Phán: đoạn nào CHỨA thông tin trả lời được câu hỏi (relevant)? Trả JSON: "
        '{"relevant_ranks":[các số thứ tự đoạn relevant], "answered": true/false}. '
        "answered=true nếu CÓ ÍT NHẤT 1 đoạn trả lời được.\n\n"
        f"CÂU HỎI: {query}\n\nĐOẠN:\n{listing}")
    body = json.dumps({"model": _JUDGE_MODEL, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.0}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {os.environ['OR_KEY']}",
                                          "Content-Type": "application/json"})
    txt = json.load(urllib.request.urlopen(req, timeout=90))["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {"relevant_ranks": [], "answered": False}


def judge(path: str) -> None:
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    ks = (1, 3, 5)
    hit = {k: 0 for k in ks}
    answered = 0
    out = open("verdicts.jsonl", "w", encoding="utf-8")
    for i, r in enumerate(rows):
        try:
            v = _judge_one(r["query"], r["chunks"])
        except Exception as exc:  # noqa: BLE001
            print(f"  judge err q{i}: {str(exc)[:60]}")
            continue
        ranks = [x for x in v.get("relevant_ranks", []) if isinstance(x, int)]
        best = min(ranks) if ranks else 99
        for k in ks:
            if best <= k:
                hit[k] += 1
        if v.get("answered"):
            answered += 1
        out.write(json.dumps({**r, "verdict": v}, ensure_ascii=False) + "\n")
        if (i + 1) % 20 == 0:
            print(f"  judged {i+1}/{len(rows)}", flush=True)
    out.close()
    n = len(rows)
    print(f"\n=== JUDGE-RELEVANCE RECALL (n={n}, judge={_JUDGE_MODEL}) ===")
    print(f"  answered (≥1 đoạn trả lời được): {answered}/{n} = {answered/n:.3f}")
    for k in ks:
        print(f"  relevant@{k}: {hit[k]}/{n} = {hit[k]/n:.3f}")
    print("  -> verdicts.jsonl (xem từng câu để review tay)")


if __name__ == "__main__":
    if "--retrieve" in sys.argv:
        retrieve()
    elif "--judge" in sys.argv:
        judge(sys.argv[sys.argv.index("--judge") + 1])
    else:
        print(__doc__)
