import json, urllib.request, base64
IP="http://34.158.47.236"
def post(path, data, tok=None):
    h={"Content-Type":"application/json"}
    if tok: h["Authorization"]="Bearer "+tok
    return urllib.request.urlopen(urllib.request.Request(IP+path, data=json.dumps(data).encode(), headers=h), timeout=45)
tok=json.loads(post("/api/user/auth/login",{"email":"admin@company.com","password":"***REDACTED-SEED-ADMIN-PW***"}).read())["access_token"]
p=tok.split(".")[1]; p+="="*(-len(p)%4); uid=json.loads(base64.urlsafe_b64decode(p))["user_id"]
for q in ["Chính sách nghỉ phép năm của công ty quy định thế nào?", "Quy trình xin nghỉ phép gồm những bước nào?"]:
    print("\n### Q:", q)
    resp=post("/api/query/query",{"question":q,"user_id":uid}, tok)
    answer=""; route=None; sources=0
    for raw in resp:
        line=raw.decode("utf-8","replace").strip()
        if not line.startswith("data:"): continue
        try: d=json.loads(line[5:].strip())
        except: continue
        if d.get("tool"): route=d.get("tool_args")
        if d.get("token"): answer+=d["token"]
        if d.get("done"): sources=len(d.get("sources") or [])
    print("  route/tool_args:", route)
    print("  sources:", sources)
    print("  answer:", answer[:400])
