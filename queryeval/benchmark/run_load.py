# -*- coding: utf-8 -*-
"""Open-loop load runner: fire N queries at a fixed arrival RATE (default 10 req/s),
round-robin qua nhiều account. Đo hành vi prod dưới tải (queueing, 429/5xx, latency
degradation) + tỉ lệ fan-out >1 worker. KHÔNG đợi request trước xong (open-loop) ->
đo đúng saturation. Mỗi request 1 thread, conversation_id mới (context sạch).

Usage: PYTHONUTF8=1 python run_load.py [--rate 10] [--limit 145] [--dataset multiagent]
"""
import sys, os, json, time, threading, base64, uuid
from datetime import datetime, timezone
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "https://vsfchat.cloud"
LOGIN = f"{BASE}/api/user/auth/login"
QUERY = f"{BASE}/api/query/query"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "load_results.jsonl")
OUTCOME = {1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS",6:"ERROR"}
# Creds qua ENV (KHÔNG hardcode). ADMIN_PW, LOADTEST_PW; emails purpose-built test accounts.
_ADMIN_PW = os.environ.get("ADMIN_PW", "")
_LOAD_PW = os.environ.get("LOADTEST_PW", "")
ACCOUNTS = [("admin@company.com", _ADMIN_PW)] + \
           [(f"loadtest{i:02d}@company.com", _LOAD_PW) for i in range(1, 21)]  # 21 total

def jwt_uid(tok):
    p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p)).get("user_id") or json.loads(base64.urlsafe_b64decode(p)).get("sub")

def login(email, pw):
    r = requests.post(LOGIN, json={"email":email,"password":pw}, timeout=30); r.raise_for_status()
    t = r.json()["access_token"]; return t, jwt_uid(t)

def run_query(tok, uid, q):
    body={"question":q,"user_id":uid,"conversation_id":str(uuid.uuid4())}
    hdr={"Authorization":f"Bearer {tok}","Content-Type":"application/json","Accept":"text/event-stream"}
    t0=time.perf_counter(); ttft=None; ans=[]; events=0; done=None; sc=None; err=None
    try:
        with requests.post(QUERY,headers=hdr,json=body,stream=True,timeout=240) as r:
            sc=r.status_code
            if sc!=200: err=r.text[:300]
            else:
                buf=""
                for chunk in r.iter_content(chunk_size=None,decode_unicode=True):
                    if not chunk: continue
                    buf+=chunk
                    while "\n\n" in buf:
                        pkt,buf=buf.split("\n\n",1); line=pkt.strip()
                        if not line.startswith("data:"): continue
                        try: ev=json.loads(line[5:].strip())
                        except Exception: continue
                        events+=1
                        if ev.get("token") is not None:
                            if ttft is None: ttft=time.perf_counter()-t0
                        if ev.get("done"): done=ev
    except Exception as e:
        err=f"{type(e).__name__}: {str(e)[:200]}"
    d=done or {}
    return {"status_code":sc,"ttft":ttft,"total_latency":round(time.perf_counter()-t0,2),
            "outcome":OUTCOME.get(d.get("outcome"),str(d.get("outcome"))),"trace_id":d.get("trace_id"),
            "n_sources":len(d.get("sources") or []),"n_events":events,"error":err}

_lock=threading.Lock()
def write(rec):
    with _lock:
        with open(OUT,"a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")

def main():
    args=sys.argv
    rate=float(args[args.index("--rate")+1]) if "--rate" in args else 10.0
    ds=args[args.index("--dataset")+1] if "--dataset" in args else "multiagent"
    path=os.path.join(HERE,"..","questions",f"labels_{ds}.jsonl")
    items=[json.loads(l) for l in open(path,encoding="utf-8") if l.strip()]
    if "--limit" in args: items=items[:int(args[args.index("--limit")+1])]
    if not _ADMIN_PW or not _LOAD_PW:
        raise SystemExit("set ADMIN_PW and LOADTEST_PW env (creds không hardcode)")
    if os.path.exists(OUT): os.rename(OUT, OUT+f".bak.{int(time.time())}")
    print(f"Login {len(ACCOUNTS)} accounts...")
    sess=[]
    for e,pw in ACCOUNTS:
        try: t,u=login(e,pw); sess.append((e,t,u))
        except Exception as ex: print("FAIL",e,str(ex)[:80])
    print(f"OK {len(sess)} accounts | firing {len(items)} reqs @ {rate}/s open-loop")
    interval=1.0/rate
    results=[]; counter=[0]; t_start=time.perf_counter()
    def worker(idx,item,email,tok,uid,t_disp):
        res=run_query(tok,uid,item["q"])
        rec={"id":item["id"],"subtype":item.get("subtype"),"account":email,
             "dispatch_s":round(t_disp,2),"complete_s":round(time.perf_counter()-t_start,2),
             "question":item["q"][:120],"expect_min_workers":item.get("expect_min_workers"),**res}
        write(rec); results.append(rec)
        with _lock:
            counter[0]+=1
            tag="OK" if res["status_code"]==200 else f"!{res['status_code']}"
            print(f"[{counter[0]:3d}/{len(items)}] {item['id']} {tag} {res['total_latency']:6.1f}s "
                  f"{res['outcome']} src={res['n_sources']} tid={str(res['trace_id'])[:8]}"
                  +(f" ERR {res['error'][:50]}" if res['error'] else ""),flush=True)
    threads=[]
    for i,item in enumerate(items):
        email,tok,uid=sess[i%len(sess)]
        t_disp=time.perf_counter()-t_start
        th=threading.Thread(target=worker,args=(i,item,email,tok,uid,t_disp)); th.start(); threads.append(th)
        time.sleep(interval)  # open-loop arrival pacing
    print(f"[dispatch] all {len(items)} fired in {time.perf_counter()-t_start:.1f}s; waiting for completions...")
    for th in threads: th.join()
    # summary
    n=len(results); ok=[r for r in results if r["status_code"]==200]
    bad=[r for r in results if r["status_code"]!=200]
    lats=sorted(r["total_latency"] for r in ok)
    def pct(q): return lats[min(len(lats)-1,int(q*(len(lats)-1)))] if lats else 0
    from collections import Counter
    print("\n=== LOAD SUMMARY ===")
    print(f"dispatched {n} @ {rate}/s | 200 OK: {len(ok)} | non-200/err: {len(bad)} "+str(dict(Counter(str(r['status_code']) for r in bad))))
    print(f"successful latency p50={pct(.5):.1f} p90={pct(.9):.1f} p95={pct(.95):.1f} max={lats[-1] if lats else 0:.1f}s")
    print("DONE ->", os.path.normpath(OUT))

if __name__=="__main__": main()
