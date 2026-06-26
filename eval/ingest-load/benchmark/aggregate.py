# -*- coding: utf-8 -*-
"""Aggregate ingest_results.jsonl ->
- accept latency (document-service nhận 202)
- e2e ingest latency dist p50/p90/p95/p99 (dispatch -> indexed)  <- chỉ số chính
- throughput (doc/s), drain window, peak in-flight (đang queued/processing)
- degradation theo dispatch-bucket + breakdown theo loại file
Usage: python aggregate.py [results.jsonl]
"""
import sys, os, json, statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "results", "ingest_results.jsonl")
res = [json.loads(l) for l in open(RES, encoding="utf-8") if l.strip()]


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1)))] if xs else 0


acc = [r for r in res if r.get("doc_id")]
indexed = [r for r in res if r.get("final_status") == "indexed"]
failed = [r for r in res if r.get("final_status") == "failed"]
timeout = [r for r in res if r.get("final_status") == "timeout"]

print(f"=== INGEST-LOAD ({res[0].get('label','?') if res else '?'}) — N={len(res)} ===")
print(f"accepted(202)={len(acc)} | indexed={len(indexed)} | failed={len(failed)} | timeout={len(timeout)}")
up_http = Counter(r.get("http") for r in res)
print(f"upload http: {dict(up_http)}")

AL = [r["accept_latency"] for r in res if r.get("accept_latency") is not None]
print(f"\naccept_latency (202)  p50={pct(AL,.5):.2f} p95={pct(AL,.95):.2f} p99={pct(AL,.99):.2f} max={max(AL) if AL else 0:.2f}s")

E = [r["e2e_latency"] for r in indexed + failed if r.get("e2e_latency") is not None]
print(f"e2e_latency (->idx)   p50={pct(E,.5):.1f} p90={pct(E,.9):.1f} p95={pct(E,.95):.1f} "
      f"p99={pct(E,.99):.1f} max={max(E) if E else 0:.1f} avg={st.mean(E) if E else 0:.1f}s   <<< CHỈ SỐ CHÍNH")

# throughput + drain window
disp = [r["dispatch_s"] for r in res if r.get("dispatch_s") is not None]
idx_s = [r["indexed_s"] for r in indexed + failed if r.get("indexed_s") is not None]
if disp and idx_s:
    window = max(idx_s) - min(disp)
    print(f"\nupload window: {min(disp):.1f}-{max(r['accept_s'] for r in res if r.get('accept_s') is not None):.1f}s | "
          f"drain end: {max(idx_s):.1f}s | total wall: {window:.1f}s | throughput: {len(idx_s)/window:.2f} doc/s")

# peak in-flight (accepted nhưng chưa indexed)
events = []
for r in res:
    if r.get("accept_s") is not None and r.get("indexed_s") is not None:
        events.append((r["accept_s"], 1)); events.append((r["indexed_s"], -1))
events.sort()
cur = peak = 0
for _, d in events:
    cur += d; peak = max(peak, cur)
print(f"PEAK in-flight (queued+processing): {peak}")

# degradation: e2e theo dispatch bucket (doc đến sau chờ queue lâu hơn?)
if E:
    print("\ne2e_latency theo dispatch-bucket (queue build-up):")
    buckets = defaultdict(list)
    for r in indexed + failed:
        if r.get("e2e_latency") is not None:
            buckets[int(r["dispatch_s"] // 5) * 5].append(r["e2e_latency"])
    for b in sorted(buckets):
        xs = buckets[b]
        print(f"  dispatch {b:3d}-{b+5:3d}s: n={len(xs):3d} e2e_p50={pct(xs,.5):6.1f} e2e_max={max(xs):6.1f}")

# breakdown theo loại file
print("\ntheo loại file (e2e p50/p95):")
byext = defaultdict(list)
for r in indexed + failed:
    if r.get("e2e_latency") is not None:
        ext = os.path.splitext(r["name"])[1].lower()
        byext[ext].append(r["e2e_latency"])
for ext in sorted(byext, key=lambda e: -pct(byext[e], .5)):
    xs = byext[ext]
    print(f"  {ext:6s} n={len(xs):3d} p50={pct(xs,.5):6.1f} p95={pct(xs,.95):6.1f} max={max(xs):6.1f}")

if failed:
    print(f"\nFAILED ({len(failed)}):")
    for r in failed[:10]:
        print(f"  {r['name'][:55]} doc={r.get('doc_id')}")
