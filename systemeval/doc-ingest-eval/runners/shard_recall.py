import json,urllib.request,time
EXTS=(".pdf",".docx",".doc",".txt",".md",".markdown",".pptx",".xlsx",".html",".htm")
def norm(s):
    s=(s or "").strip().lower()
    for e in EXTS:
        if s.endswith(e): return s[:-len(e)]
    return s
cols=["qwen3emb8b__d4096__s2","bgem3__d1024__s2","te3s__d1536__s2","pplxembed__d1024__s2"]
ids=set()
for c in cols:
    n=f"rag_chatbot__{c}";off=None
    while True:
        b={"limit":200,"with_payload":["document_id"]}
        if off:b["offset"]=off
        r=urllib.request.Request(f"http://qdrant:6333/collections/{n}/points/scroll",data=json.dumps(b).encode(),headers={"Content-Type":"application/json"},method="POST")
        res=json.load(urllib.request.urlopen(r))["result"]
        for p in res["points"]: ids.add(p["payload"]["document_id"])
        off=res.get("next_page_offset")
        if not off:break
doc_ids=list(ids)
labels=[json.loads(l) for l in open("/tmp/labels.jsonl",encoding="utf-8") if l.strip()]
KS=(1,3,5,10);hits={k:0 for k in KS};rr=0.0;lat=[]
for lab in labels:
    gt=norm(lab["gt_doc_id"]);q=lab["query"]
    body=json.dumps({"query":q,"document_ids":doc_ids,"top_k":10}).encode()
    req=urllib.request.Request("http://localhost:8000/api/search",data=body,headers={"Content-Type":"application/json"},method="POST")
    t0=time.perf_counter()
    cands=json.load(urllib.request.urlopen(req,timeout=60))["candidates"]
    lat.append((time.perf_counter()-t0)*1000)
    ranked=[];seen=set()
    for c in cands:
        d=norm(c["document_name"])
        if d and d not in seen: seen.add(d);ranked.append(d)
    rank=ranked.index(gt)+1 if gt in ranked else None
    if rank:
        rr+=1/rank
        for k in KS:
            if rank<=k:hits[k]+=1
n=len(labels);lat.sort()
print(f"SHARD-READ RECALL: n={n} docs_acl={len(doc_ids)}")
print("  recall@1={:.3f} @3={:.3f} @5={:.3f} @10={:.3f} MRR={:.3f}".format(hits[1]/n,hits[3]/n,hits[5]/n,hits[10]/n,rr/n))
print("  search latency p50={:.0f}ms p95={:.0f}ms".format(lat[len(lat)//2],lat[int(len(lat)*0.95)]))
