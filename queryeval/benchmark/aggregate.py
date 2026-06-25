# -*- coding: utf-8 -*-
"""Aggregate load_results.jsonl (+ optional trees json) ->
- status/latency distribution under load
- peak concurrency (open-loop queueing)
- fan-out: distinct workers/trace (SPAN rag_search/hr_query/leave_action), % >=2 workers
- stage breakdown (plan/verify/worker)
- latency vs dispatch time (degradation as load builds)
Usage: python aggregate.py [results.jsonl] [trees.json]
"""
import sys, os, json, statistics as st
HERE=os.path.dirname(os.path.abspath(__file__))
RES=sys.argv[1] if len(sys.argv)>1 else os.path.join(HERE,"..","results","load_results.jsonl")
TREES=sys.argv[2] if len(sys.argv)>2 else os.path.join(HERE,"..","results","load_trees.json")
res=[json.loads(l) for l in open(RES,encoding="utf-8") if l.strip()]
def pct(xs,q):
    xs=sorted(xs); return xs[min(len(xs)-1,int(q*(len(xs)-1)))] if xs else 0

ok=[r for r in res if r.get("status_code")==200 and not r.get("error")]
bad=[r for r in res if r.get("status_code")!=200 or r.get("error")]
from collections import Counter
print("=== LOAD RESULTS ===")
print(f"total={len(res)} | 200_ok={len(ok)} | failed={len(bad)}", dict(Counter((str(r.get('status_code')),'err' if r.get('error') else 'ok') for r in bad)))
errs=Counter((r.get('error') or '').split(':')[0] for r in bad if r.get('error'))
if errs: print("error types:", dict(errs))
L=[r["total_latency"] for r in ok]
T=[r["ttft"] for r in ok if r.get("ttft")]
print(f"latency(ok)  p50={pct(L,.5):.1f} p90={pct(L,.9):.1f} p95={pct(L,.95):.1f} p99={pct(L,.99):.1f} max={max(L) if L else 0:.1f} avg={st.mean(L) if L else 0:.1f}")
print(f"TTFT(ok)     p50={pct(T,.5):.1f} p90={pct(T,.9):.1f} max={max(T) if T else 0:.1f}")

# peak concurrency from dispatch/complete
events=[]
for r in res:
    if r.get("dispatch_s") is not None and r.get("complete_s") is not None:
        events.append((r["dispatch_s"],1)); events.append((r["complete_s"],-1))
events.sort()
cur=peak=0
for _,d in events:
    cur+=d; peak=max(peak,cur)
disp=[r["dispatch_s"] for r in res if r.get("dispatch_s") is not None]
if disp: print(f"\narrival window: {min(disp):.1f}-{max(disp):.1f}s | PEAK CONCURRENCY in-flight: {peak}")

# latency vs dispatch bucket (degradation)
if ok:
    print("\nlatency by dispatch-time bucket (degradation as load builds):")
    buckets={}
    for r in ok:
        b=int(r["dispatch_s"]//5)*5
        buckets.setdefault(b,[]).append(r["total_latency"])
    for b in sorted(buckets):
        xs=buckets[b]; print(f"  dispatch {b:3d}-{b+5:3d}s: n={len(xs):3d} lat_p50={pct(xs,.5):6.1f} lat_max={max(xs):6.1f}")

# fan-out + stages from trees
if os.path.exists(TREES):
    trees={t["trace_id"]:t for t in json.load(open(TREES,encoding="utf-8"))}
    WSPAN={"rag_search","hr_query"}  # SPAN entry per worker (+ leave_action)
    wc=[]; stage={}; tot=0; analyzed=0; replan=0
    for r in ok:
        t=trees.get(r.get("trace_id"))
        if not t or t.get("error") or not t.get("nodes"): continue
        analyzed+=1; nodes=t["nodes"]
        workers=sum(1 for n in nodes if n["type"]=="SPAN" and n["name"] in WSPAN) + \
                sum(1 for n in nodes if n["name"]=="leave_action")
        wc.append(workers)
        if sum(1 for n in nodes if n["name"]=="plan")>1 or sum(1 for n in nodes if n["name"]=="verify")>1: replan+=1
        for n in nodes:
            if n.get("dur") is None: continue
            k=n["name"]; k="rag" if k in ("rag_search","rag_retrieve") else ("hr" if k in ("hr_lookup","hr_query") else k)
            stage[k]=stage.get(k,0)+n["dur"]; tot+=n["dur"]
    if analyzed:
        print(f"\n=== FAN-OUT (trees analyzed={analyzed}) ===")
        dist=Counter(wc)
        print("workers/trace distribution:", dict(sorted(dist.items())))
        multi=sum(1 for w in wc if w>=2)
        print(f">=2 workers: {multi}/{analyzed} = {multi/analyzed*100:.0f}%  | avg workers={st.mean(wc):.2f} max={max(wc)}")
        print(f"replan: {replan}/{analyzed} = {replan/analyzed*100:.0f}%")
        print(f"\nstage share (tot={tot:.0f}s):")
        for k,v in sorted(stage.items(),key=lambda x:-x[1]):
            print(f"  {k:12s} {v:8.1f}s {v/tot*100:5.1f}%")
else:
    print("\n(no trees file yet — run scrape_traces.js then re-run)")
