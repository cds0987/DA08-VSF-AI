"""Baseline TUẦN TỰ (concurrency=1, KHÔNG tải) — performance "sạch" mỗi loại câu.
Gửi 1 câu -> chờ done -> câu kế. Đo ttft + total latency + outcome + sources per-type.
Đây là mốc so cho combined load-test (peak). Creds qua ENV (ADMIN_PW)."""
import os, json, time, uuid, base64, requests, sys, statistics, random, threading
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
BASE="https://vsfchat.cloud"; LOGIN=f"{BASE}/api/user/auth/login"; QUERY=f"{BASE}/api/query/query"
OUTCOME={1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS",6:"ERROR"}

def jwt_uid(tok):
    p=tok.split(".")[1]; p+="="*(-len(p)%4)
    d=json.loads(base64.urlsafe_b64decode(p)); return d.get("user_id") or d.get("sub")

def login(email,pw):
    r=requests.post(LOGIN,json={"email":email,"password":pw},timeout=30); r.raise_for_status()
    t=r.json()["access_token"]; return t,jwt_uid(t)

def run_query(tok,uid,q):
    body={"question":q,"user_id":uid,"conversation_id":str(uuid.uuid4())}
    hdr={"Authorization":f"Bearer {tok}","Content-Type":"application/json","Accept":"text/event-stream"}
    t0=time.perf_counter(); ttft=None; events=0; done=None; sc=None; err=None; ans=[]
    try:
        with requests.post(QUERY,headers=hdr,json=body,stream=True,timeout=240) as r:
            sc=r.status_code
            if sc!=200: err=r.text[:200]
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
                            ans.append(ev["token"])
                        if ev.get("done"): done=ev
    except Exception as e: err=f"{type(e).__name__}: {str(e)[:160]}"
    d=done or {}
    return {"sc":sc,"ttft":round(ttft,2) if ttft else None,"lat":round(time.perf_counter()-t0,2),
            "outcome":OUTCOME.get(d.get("outcome"),str(d.get("outcome"))),"trace_id":d.get("trace_id"),
            "n_sources":len(d.get("sources") or []),"events":events,"answer":"".join(ans)[:500],"err":err}

def pct(xs,q): xs=sorted(xs); return round(xs[min(len(xs)-1,int(q*(len(xs)-1)))],2) if xs else 0
def main():
    random.seed(5)
    rows=[json.loads(l) for l in open("systemeval/query-test/questions/loadtest_queries.jsonl",encoding="utf-8") if l.strip()]
    sample=rows  # FULL 450 (benchmark1 no-load, không sample)
    per_n={t:0 for t in ["simple_rag","multiagent","hr_intent","non_rag"]}
    for r in rows: per_n[r["type"]]=per_n.get(r["type"],0)+1
    RAW="systemeval/query-test/results/seq_baseline_raw.jsonl"
    done_ids=set()
    if os.path.exists(RAW):
        for l in open(RAW,encoding="utf-8"):
            try: done_ids.add(json.loads(l)["id"])
            except Exception: pass
    sample=[it for it in sample if it["id"] not in done_ids]
    tok,uid=login("admin@company.com",os.environ["ADMIN_PW"])
    print(f"login OK uid={uid} | RESUME: {len(done_ids)} xong, còn {len(sample)} (conc={os.getenv('CONC','4')})",flush=True)
    res=[]
    out=open(RAW,"a",encoding="utf-8")
    for i,it in enumerate(sample):
        r=run_query(tok,uid,it["q"]); r["type"]=it["type"]; r["id"]=it["id"]; r["q"]=it["q"][:80]
        res.append(r); out.write(json.dumps(r,ensure_ascii=False)+"\n"); out.flush()
        print(f"[{i+1}/{len(sample)}] {it['type']:11s} ttft={r['ttft']} lat={r['lat']:6.1f}s out={r['outcome']} src={r['n_sources']} {'ERR' if r['err'] else ''}",flush=True)
    out.close()
    print("\n=== BASELINE TUẦN TỰ (no-load) per-type ===")
    print(f"{'type':12s} {'n':>3} {'ttft_p50':>8} {'ttft_p95':>8} {'lat_p50':>8} {'lat_p95':>8} {'err':>4} {'success':>8}")
    for t in per_n:
        g=[r for r in res if r["type"]==t]; ok=[r for r in g if not r["err"]]
        tt=[r["ttft"] for r in ok if r["ttft"]]; la=[r["lat"] for r in ok]
        succ=sum(1 for r in g if r["outcome"]=="SUCCESS")
        print(f"{t:12s} {len(g):>3} {pct(tt,.5):>8} {pct(tt,.95):>8} {pct(la,.5):>8} {pct(la,.95):>8} {sum(1 for r in g if r['err']):>4} {succ:>8}")
    allok=[r for r in res if not r["err"]]
    print(f"\nTỔNG n={len(res)} | err={sum(1 for r in res if r['err'])} | lat p50={pct([r['lat'] for r in allok],.5)} p95={pct([r['lat'] for r in allok],.95)}")
    print("BASELINE_DONE")
if __name__=="__main__": main()
