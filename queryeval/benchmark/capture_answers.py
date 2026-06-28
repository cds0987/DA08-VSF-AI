# -*- coding: utf-8 -*-
"""BM6 capture: fire dataset (low-conc -> latency SẠCH) + lưu FULL answer + per-node timing để
Claude tự chấm accuracy. Đo đường PHỨC TẠP (multi-worker) lần đầu (5 vòng queryeval bỏ sót).

Lưu mỗi câu: id/subtype/q/expect/expect_outcome/expect_min_workers + answer(full) + outcome +
n_sources + ttft + total_latency + node_seen (plan/worker/synthesize... -> xác nhận đi full pipeline).
Env: ADMIN_PW LOADTEST_PW. Usage: python capture_answers.py [--conc 3] [--limit 113] [--dataset multiagent_hr]
"""
import sys, os, json, time, base64, uuid, asyncio
import httpx

BASE="https://vsfchat.cloud"
HERE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(HERE,"..","results","bm6_capture.jsonl")
OCNAME={1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS",6:"ERROR"}
_ADMIN=os.environ.get("ADMIN_PW",""); _LOAD=os.environ.get("LOADTEST_PW","")
ACCOUNTS=[("admin@company.com",_ADMIN)]+[(f"loadtest{i:02d}@company.com",_LOAD) for i in range(1,21)]


def uid_of(tok):
    p=tok.split(".")[1]; p+="="*(-len(p)%4)
    d=json.loads(base64.urlsafe_b64decode(p)); return d.get("user_id") or d.get("sub")


async def login(c,email,pw):
    r=await c.post(f"{BASE}/api/user/auth/login",json={"email":email,"password":pw},timeout=30)
    r.raise_for_status(); t=r.json()["access_token"]; return t,uid_of(t)


async def fire(c,tok,uid,q):
    body={"question":q,"user_id":uid,"conversation_id":str(uuid.uuid4())}
    hdr={"Authorization":f"Bearer {tok}","Content-Type":"application/json","Accept":"text/event-stream"}
    t0=time.perf_counter(); ttft=None; ans=[]; nodes=set(); roles=set(); done=None
    try:
        async with c.stream("POST",f"{BASE}/api/query/query",headers=hdr,json=body,timeout=240) as r:
            if r.status_code!=200:
                return {"err":f"HTTP {r.status_code}","total_latency":round(time.perf_counter()-t0,2)}
            async for line in r.aiter_lines():
                if not line.startswith("data:"): continue
                try: ev=json.loads(line[5:].strip())
                except Exception: continue
                if ev.get("node"): nodes.add(ev["node"])
                if ev.get("role"): roles.add(ev["role"])
                tok_v=ev.get("token")
                if tok_v is not None:
                    if ttft is None: ttft=round(time.perf_counter()-t0,2)
                    # answer token (phase generating) — gom để chấm
                    if ev.get("phase")=="generating" or (ev.get("node") in (None,"synthesize","answer")):
                        ans.append(tok_v)
                if ev.get("done"): done=ev; break
    except Exception as e:
        return {"err":f"{type(e).__name__}: {str(e)[:120]}","total_latency":round(time.perf_counter()-t0,2)}
    d=done or {}
    return {"answer":"".join(ans).strip(),"outcome":OCNAME.get(d.get("outcome"),str(d.get("outcome"))),
            "n_sources":len(d.get("sources") or []),"ttft":ttft,"total_latency":round(time.perf_counter()-t0,2),
            "nodes":sorted(nodes),"roles":sorted(roles),"trace_id":d.get("trace_id")}


async def main():
    a=sys.argv
    conc=int(a[a.index("--conc")+1]) if "--conc" in a else 3
    ds=a[a.index("--dataset")+1] if "--dataset" in a else "multiagent_hr"
    items=[json.loads(l) for l in open(os.path.join(HERE,"..","questions",f"labels_{ds}.jsonl"),encoding="utf-8") if l.strip()]
    if "--limit" in a: items=items[:int(a[a.index("--limit")+1])]
    if not _ADMIN or not _LOAD: raise SystemExit("set ADMIN_PW + LOADTEST_PW")
    if os.path.exists(OUT): os.rename(OUT,OUT+f".bak.{int(time.time())}")
    sem=asyncio.Semaphore(conc); done_n=[0]; lock=asyncio.Lock()
    async with httpx.AsyncClient(verify=True) as c:
        sess=[]
        for e,pw in ACCOUNTS:
            try: sess.append(await login(c,e,pw))
            except Exception as ex: print("login fail",e,str(ex)[:60])
        print(f"{len(sess)} accounts · capture {len(items)} câu conc={conc}",flush=True)
        async def work(i,item):
            async with sem:
                tok,uid=sess[i%len(sess)]
                res=await fire(c,tok,uid,item["q"])
                rec={"id":item["id"],"subtype":item.get("subtype"),"q":item["q"],
                     "expect":item.get("expect"),"expect_outcome":OCNAME.get(item.get("expect_outcome")),
                     "expect_min_workers":item.get("expect_min_workers"),**res}
                async with lock:
                    with open(OUT,"a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")
                    done_n[0]+=1
                    print(f"[{done_n[0]:3d}/{len(items)}] {item['id']} {res.get('outcome','?')} "
                          f"{res.get('total_latency','?')}s src={res.get('n_sources','?')} w={len(res.get('roles',[]))}",flush=True)
        await asyncio.gather(*(work(i,it) for i,it in enumerate(items)))
    print("DONE ->",os.path.normpath(OUT),flush=True)

if __name__=="__main__": asyncio.run(main())
