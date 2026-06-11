import json, urllib.request, base64
IP="http://34.158.47.236"
def post(path, data, tok=None):
    h={"Content-Type":"application/json"}
    if tok: h["Authorization"]="Bearer "+tok
    return urllib.request.urlopen(urllib.request.Request(IP+path, data=json.dumps(data).encode(), headers=h), timeout=60)
tok=json.loads(post("/api/user/auth/login",{"email":"admin@company.com","password":"***REDACTED-SEED-ADMIN-PW***"}).read())["access_token"]
p=tok.split(".")[1]; p+="="*(-len(p)%4); uid=json.loads(base64.urlsafe_b64decode(p))["user_id"]
resp=post("/api/query/query",{"question":"nghỉ phép năm","user_id":uid}, tok)
ans=""; ev=[]
for raw in resp:
    line=raw.decode("utf-8","replace").strip()
    if not line.startswith("data:"): continue
    try: d=json.loads(line[5:].strip())
    except: continue
    if d.get("tool"): ev.append(("tool",d.get("tool"),d.get("tool_args")))
    if d.get("token"): ans+=d["token"]
    if d.get("done"): ev.append(("done","sources",len(d.get("sources") or []),"outcome",d.get("outcome")))
print("EVENTS:",ev)
print("ANSWER:",ans[:400])
