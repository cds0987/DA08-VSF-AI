# -*- coding: utf-8 -*-
"""Aggregate combined-load: CHAT (tách nặng/nhẹ) + INGEST (p50/p99) + CPU peak/service.
So sánh để biết A2 (ingest scale) có bóp chat không. Usage: PYTHONUTF8=1 python agg_combined.py [stats_file]"""
import sys, os, json, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1)))] if xs else 0


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


# id -> weight (nặng/nhẹ) từ dataset
wmap = {}
for l in open(os.path.join(HERE, "..", "questions", "labels_mixed200.jsonl"), encoding="utf-8"):
    if l.strip():
        d = json.loads(l); wmap[d["id"]] = d.get("weight", "?")

chat = load(os.path.join(HERE, "..", "results", "load_results.jsonl"))
print(f"=== CHAT (n={len(chat)}) ===")
for w in ("heavy", "light"):
    g = [r for r in chat if wmap.get(r["id"]) == w and r.get("status_code") == 200]
    lat = [r["total_latency"] for r in g if r.get("total_latency")]
    ttft = [r["ttft"] for r in g if r.get("ttft")]
    oc = {}
    for r in g:
        oc[r.get("outcome")] = oc.get(r.get("outcome"), 0) + 1
    print(f"[{w:5s}] n={len(g)} | latency p50={pct(lat,.5):.1f} p95={pct(lat,.95):.1f} max={max(lat) if lat else 0:.1f}s "
          f"| TTFT p50={pct(ttft,.5):.1f}s | outcome={oc}")
bad = [r for r in chat if r.get("status_code") != 200]
print(f"non-200/err: {len(bad)}")

ing = load(os.path.join(HERE, "..", "results", "ingest_results.jsonl"))
e2e = [r["e2e_latency"] for r in ing if r.get("e2e_latency")]
done = [r for r in ing if r.get("status") in ("indexed", "completed")]
print(f"\n=== INGEST (n={len(ing)}, indexed={len(done)}) ===")
if e2e:
    print(f"e2e p50={pct(e2e,.5):.0f} p95={pct(e2e,.95):.0f} p99={pct(e2e,.99):.0f} max={max(e2e):.0f}s")

# CPU peak per service từ stats file
sf = sys.argv[1] if len(sys.argv) > 1 else None
if sf and os.path.exists(sf):
    peak = {}
    for line in open(sf, encoding="utf-8", errors="ignore"):
        parts = line.split()
        if len(parts) >= 2 and "%" in parts[1]:
            name = parts[0]
            try:
                cpu = float(parts[1].rstrip("%"))
            except ValueError:
                continue
            key = "rag-ingest" if "ingest" in name else ("rag-worker" if "rag-worker" in name else
                  next((s for s in ("query-service", "ai-router", "mcp", "qdrant", "postgres") if s in name), name))
            peak[key] = max(peak.get(key, 0), cpu)
    print("\n=== CPU PEAK %/service (combined) ===")
    for k, v in sorted(peak.items(), key=lambda x: -x[1]):
        print(f"  {k:16s} {v:6.0f}%")
