"""PEAK load: 450 câu/60s (base ~5/s + burst ~14/s), multi-account open-loop, mô phỏng 800-1200 user.
Đo TTFT/latency/outcome/error per-query + per-type. Agent per-capability pull từ ai-router log riêng.
Creds ENV: ADMIN_PW, LOADTEST_PW."""
import os,json,time,uuid,base64,requests,threading,random
from concurrent.futures import ThreadPoolExecutor
BASE="https://vsfchat.cloud"; LOGIN=f"{BASE}/api/user/auth/login"; QUERY=f"{BASE}/api/query/query"
OUTCOME={1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS",6:"ERROR"}
def jwt_uid(t): p=t.split(".")[1]; p+="="*(-len(p)%4); d=json.loads(base64.urlsafe_b64decode(p)); return d.get("user_id") or d.get("sub")
def login(e,pw): r=requests.post(LOGIN,json={"email":e,"password":pw},timeout=30); r.raise_for_status(); t=r.json()["access_token"]; return t,jwt_uid(t)
def run_query(tok,uid,q):
    body={"question":q,"user_id":uid,"conversation_id":str(uuid.uuid4())}
    hdr={"Authorization":f"Bearer {tok}","Content-Type":"application/json","Accept":"text/event-stream"}
    t0=time.perf_counter(); ttft=None; ev_n=0; done=None; sc=None; err=None
    try:
        with requests.post(QUERY,headers=hdr,json=body,stream=True,timeout=300) as r:
            sc=r.status_code
            if sc!=200: err=r.text[:150]
            else:
                buf=""
                for ch in r.iter_content(chunk_size=None,decode_unicode=True):
                    if not ch: continue
                    buf+=ch
                    while "\n\n" in buf:
                        pkt,buf=buf.split("\n\n",1); ln=pkt.strip()
                        if not ln.startswith("data:"): continue
                        try: e=json.loads(ln[5:].strip())
                        except: continue
                        ev_n+=1
                        if e.get("token") is not None and ttft is None: ttft=time.perf_counter()-t0
                        if e.get("done"): done=e
    except Exception as ex: err=f"{type(ex).__name__}:{str(ex)[:120]}"
    d=done or {}
    return {"sc":sc,"ttft":round(ttft,2) if ttft else None,"lat":round(time.perf_counter()-t0,2),
            "outcome":OUTCOME.get(d.get("outcome"),str(d.get("outcome"))),"n_sources":len(d.get("sources") or []),"err":err}
def main():
    random.seed(9)
    rows=[json.loads(l) for l in open("systemeval/query-test/questions/loadtest_queries.jsonl",encoding="utf-8") if l.strip()]
    random.shuffle(rows)
    accts=[("admin@company.com",os.environ["ADMIN_PW"])]+[(f"loadtest{i:02d}@company.com",os.environ["LOADTEST_PW"]) for i in range(1,21)]
    sess=[]
    for e,pw in accts:
        try: sess.append(login(e,pw))
        except Exception as ex: print("login fail",e,str(ex)[:50])
    print(f"sess={len(sess)} accounts | fire {len(rows)} câu/60s burst",flush=True)
    # schedule offsets: base 5.3/s + 3 burst windows 14/s
    bursts=[(12,5),(30,5),(48,5)]; offs=[]; t=0.0
    while len(offs)<len(rows):
        inb=any(bs<=t<bs+d for bs,d in bursts); offs.append(t); t+=1.0/(14 if inb else 5.3)
    sc=60.0/offs[-1] if offs[-1]>60 else 1.0; offs=[o*sc for o in offs]  # ép vào ~60s
    res=[]; lock=threading.Lock(); t0=time.perf_counter()
    out=open("systemeval/query-test/results/peak_chat.jsonl","w",encoding="utf-8")
    ex=ThreadPoolExecutor(max_workers=300)
    def fire(it,si):
        tok,uid=sess[si%len(sess)]; r=run_query(tok,uid,it["q"]); r.update(type=it["type"],id=it["id"],disp=round(time.perf_counter()-t0,1))
        with lock: res.append(r); out.write(json.dumps(r,ensure_ascii=False)+"\n"); out.flush()
    for i,it in enumerate(rows):
        nowt=time.perf_counter()-t0
        if offs[i]>nowt: time.sleep(offs[i]-nowt)
        ex.submit(fire,it,i)
    disp_end=time.perf_counter()-t0; print(f"dispatched {len(rows)} trong {disp_end:.1f}s, chờ drain...",flush=True)
    ex.shutdown(wait=True)
    def pct(xs,q): xs=sorted(xs); return round(xs[min(len(xs)-1,int(q*(len(xs)-1)))],2) if xs else 0
    ok=[r for r in res if r["sc"]==200 and not r["err"]]; bad=[r for r in res if r not in ok]
    la=[r["lat"] for r in ok]; tt=[r["ttft"] for r in ok if r["ttft"]]
    print(f"\n=== PEAK (dispatch {disp_end:.0f}s, {len(rows)} câu) ===")
    print(f"OK {len(ok)}/{len(res)} | err/non200 {len(bad)} | TTFT p50={pct(tt,.5)} p95={pct(tt,.95)} | LAT p50={pct(la,.5)} p95={pct(la,.95)} p99={pct(la,.99)} max={max(la) if la else 0}")
    import collections
    print("outcome:",dict(collections.Counter(r["outcome"] for r in res)))
    print("errors:",dict(collections.Counter((r['err'] or '')[:30] for r in bad)))
    for t in ["simple_rag","multiagent","hr_intent","non_rag"]:
        g=[r for r in res if r["type"]==t]; gok=[r for r in g if r["sc"]==200 and not r["err"]]
        gla=[r["lat"] for r in gok]
        print(f"  {t:12s} n={len(g):3d} ok={len(gok):3d} lat_p50={pct(gla,.5):6} p95={pct(gla,.95):6} success={sum(1 for r in g if r['outcome']=='SUCCESS')}")
    print("PEAK_DONE")
if __name__=="__main__": main()
