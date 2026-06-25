# -*- coding: utf-8 -*-
"""Closed-loop RAMP: giữ ĐÚNG C request đồng thời (request xong mới bắn tiếp) -> KHÔNG pile-up.
Tăng C theo bậc, cooldown giữa bậc cho embed hồi. Đo latency + src=0 theo từng mức tải.
Creds qua ENV: ADMIN_PW, LOADTEST_PW.
"""
import os, json, time, base64, uuid, threading
from concurrent.futures import ThreadPoolExecutor
import requests
BASE="https://vsfchat.cloud"; LOGIN=f"{BASE}/api/user/auth/login"; QUERY=f"{BASE}/api/query/query"
HERE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(HERE,"..","results","ramp_results.jsonl")
LABELS=os.path.join(HERE,"..","questions","labels_multiagent.jsonl")
OUTCOME={1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS",6:"ERROR"}
ADMIN_PW=os.environ.get("ADMIN_PW",""); LOAD_PW=os.environ.get("LOADTEST_PW","")
ACCOUNTS=[("admin@company.com",ADMIN_PW)]+[(f"loadtest{i:02d}@company.com",LOAD_PW) for i in range(1,21)]
LEVELS=[3,6,10,14,18]; PER_LEVEL=16; COOLDOWN=12

def uid(t):
    p=t.split(".")[1]; p+="="*(-len(p)%4); d=json.loads(base64.urlsafe_b64decode(p)); return d.get("user_id") or d.get("sub")
def login(e,pw):
    r=requests.post(LOGIN,json={"email":e,"password":pw},timeout=30); r.raise_for_status(); t=r.json()["access_token"]; return t,uid(t)
def run_query(tok,u,q):
    body={"question":q,"user_id":u,"conversation_id":str(uuid.uuid4())}
    hdr={"Authorization":f"Bearer {tok}","Content-Type":"application/json","Accept":"text/event-stream"}
    t0=time.perf_counter(); ttft=None; done=None; sc=None; err=None
    try:
        with requests.post(QUERY,headers=hdr,json=body,stream=True,timeout=240) as r:
            sc=r.status_code
            if sc!=200: err=r.text[:200]
            else:
                buf=""
                for ch in r.iter_content(chunk_size=None,decode_unicode=True):
                    if not ch: continue
                    buf+=ch
                    while "\n\n" in buf:
                        pkt,buf=buf.split("\n\n",1); ln=pkt.strip()
                        if not ln.startswith("data:"): continue
                        try: ev=json.loads(ln[5:].strip())
                        except: continue
                        if ev.get("token") is not None and ttft is None: ttft=time.perf_counter()-t0
                        if ev.get("done"): done=ev
    except Exception as e: err=f"{type(e).__name__}: {str(e)[:160]}"
    d=done or {}
    return {"status_code":sc,"ttft":ttft,"total_latency":round(time.perf_counter()-t0,2),
            "outcome":OUTCOME.get(d.get("outcome"),str(d.get("outcome"))),"trace_id":d.get("trace_id"),
            "n_sources":len(d.get("sources") or []),"error":err}

_lock=threading.Lock()
def write(rec):
    with _lock:
        with open(OUT,"a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")

def main():
    if not ADMIN_PW or not LOAD_PW: raise SystemExit("set ADMIN_PW and LOADTEST_PW env")
    items=[json.loads(l) for l in open(LABELS,encoding="utf-8") if l.strip()]
    if os.path.exists(OUT): os.rename(OUT,OUT+f".bak.{int(time.time())}")
    sess=[]
    for e,pw in ACCOUNTS:
        try: t,u=login(e,pw); sess.append((e,t,u))
        except Exception as ex: print("login fail",e,str(ex)[:60])
    print(f"{len(sess)} accounts | RAMP levels={LEVELS} x{PER_LEVEL}/level")
    idx=0; t_run=time.perf_counter()
    for C in LEVELS:
        batch=[items[(idx+k)%len(items)] for k in range(PER_LEVEL)]; idx+=PER_LEVEL
        lvl_lat=[]; lvl_z=0; t_lvl=time.perf_counter(); cnt=[0]
        def work(item,a):
            email,tok,u=sess[a%len(sess)]
            res=run_query(tok,u,item["q"])
            rec={"level_concurrency":C,"id":item["id"],"subtype":item.get("subtype"),"account":email,
                 "t_lvl":round(time.perf_counter()-t_lvl,2),**res}
            write(rec)
            with _lock:
                lvl_lat.append(res["total_latency"]); cnt[0]+=1
                if res["status_code"]==200 and res["n_sources"]==0:
                    nonlocal_z[0]+=1
        nonlocal_z=[0]
        def work2(args):
            item,a=args; email,tok,u=sess[a%len(sess)]
            res=run_query(tok,u,item["q"])
            rec={"level_concurrency":C,"id":item["id"],"subtype":item.get("subtype"),"account":email,
                 "t_lvl":round(time.perf_counter()-t_lvl,2),**res}
            write(rec)
            with _lock:
                lvl_lat.append(res["total_latency"])
                if res["status_code"]==200 and res["n_sources"]==0: nonlocal_z[0]+=1
            return res
        with ThreadPoolExecutor(max_workers=C) as ex:
            list(ex.map(work2,[(batch[k],idx+k) for k in range(PER_LEVEL)]))
        dur=time.perf_counter()-t_lvl
        lat=sorted(lvl_lat); p50=lat[len(lat)//2]; p95=lat[min(len(lat)-1,int(0.95*(len(lat)-1)))]
        thru=PER_LEVEL/dur
        print(f"[C={C:2d}] n={PER_LEVEL} dur={dur:5.1f}s throughput={thru:.2f}req/s "
              f"lat_p50={p50:5.1f} lat_p95={p95:6.1f} src0={nonlocal_z[0]}/{PER_LEVEL} "
              f"({nonlocal_z[0]/PER_LEVEL*100:.0f}%)",flush=True)
        time.sleep(COOLDOWN)
    print("DONE ->",OUT)

if __name__=="__main__": main()
