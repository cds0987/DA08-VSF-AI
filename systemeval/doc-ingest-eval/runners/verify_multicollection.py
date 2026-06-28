import urllib.request,json,math,os
from collections import Counter
tok=os.environ["AIROUTER_INTERNAL_TOKEN"]
EXTS=(".pdf",".docx",".doc",".txt",".md",".pptx",".xlsx",".html",".htm")
def norm(s):
    s=(s or "").strip().lower()
    for e in EXTS:
        if s.endswith(e): return s[:-len(e)]
    return s
def emb(model,text):
    b=json.dumps({"model":model,"input":text}).encode()
    r=urllib.request.Request("http://ai-router:8010/v1/embeddings",data=b,headers={"Content-Type":"application/json","X-Internal-Token":tok},method="POST")
    return json.load(urllib.request.urlopen(r,timeout=40))["data"][0]["embedding"]
def cos(a,b):
    n=min(len(a),len(b));a,b=a[:n],b[:n]
    return sum(x*y for x,y in zip(a,b))/(math.sqrt(sum(x*x for x in a))*math.sqrt(sum(y*y for y in b))+1e-9)
def scroll(coll,fields,vec=False):
    out=[];off=None
    while True:
        bd={"limit":200,"with_payload":fields,"with_vector":vec}
        if off: bd["offset"]=off
        r=urllib.request.Request(f"http://qdrant:6333/collections/rag_chatbot__{coll}/points/scroll",data=json.dumps(bd).encode(),headers={"Content-Type":"application/json"},method="POST")
        res=json.load(urllib.request.urlopen(r))["result"]
        out+=res["points"];off=res.get("next_page_offset")
        if not off: break
    return out
cols={"qwen3emb8b__d4096__s2":"qwen/qwen3-embedding-8b","bgem3__d1024__s2":"baai/bge-m3",
      "te3s__d1536__s2":"openai/text-embedding-3-small","pplxembed__d1024__s2":"perplexity/pplx-embed-v1-0.6b"}
print("=== 1. XÁC THỰC VECTOR: mỗi collection lưu model THẬT của nó? ===")
print("   (cos(stored, model-NÓ) ~1.0 = thật | cos(stored, qwen8b) thấp = KHÁC qwen8b)")
for coll,model in cols.items():
    p=scroll(coll,["child_text"],vec=True)[0]
    text=p["payload"]["child_text"];stored=p["vector"]["dense"]
    c_real=cos(stored,emb(model,text));c_qw=cos(stored,emb("qwen/qwen3-embedding-8b",text))
    tag="✓THẬT" if c_real>0.95 else "✗SAI"
    print(f"   {model:38s} dim={len(stored):5d} cos(self)={c_real:.3f} cos(qwen8b)={c_qw:.3f} {tag}")
print("\n=== 2. SHARD-READ phủ CẢ 4 collection? (doc gt nằm collection nào -> tìm thấy không) ===")
doc2coll={}
for coll in cols:
    for p in scroll(coll,["document_name"]): doc2coll[norm(p["payload"]["document_name"])]=coll
allids=list({p["payload"]["document_id"] for coll in cols for p in scroll(coll,["document_id"])})
labels=[json.loads(l) for l in open("/tmp/labels.jsonl",encoding="utf-8") if l.strip()]
hit=Counter();tot=Counter()
for lab in labels:
    gt=norm(lab["gt_doc_id"]);gc=doc2coll.get(gt,"?");tot[gc]+=1
    b=json.dumps({"query":lab["query"],"document_ids":allids,"top_k":5}).encode()
    r=urllib.request.Request("http://localhost:8000/api/search",data=b,headers={"Content-Type":"application/json"},method="POST")
    cands=json.load(urllib.request.urlopen(r,timeout=60))["candidates"]
    ranked=[norm(c["document_name"]) for c in cands]
    if gt in ranked: hit[gc]+=1
print("   collection (model)         | gt-docs | recall@5 (tìm thấy/tổng)")
for coll in cols:
    if tot[coll]: print(f"   {cols[coll]:38s} {tot[coll]:3d}q   {hit[coll]}/{tot[coll]} = {hit[coll]/tot[coll]:.2f}")
print(f"   -> shard-read tìm thấy doc từ {sum(1 for c in cols if hit[c]>0)}/4 collection = MERGE THẬT")
print("VERIFY_DONE")
