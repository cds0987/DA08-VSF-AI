import json, urllib.request, base64
IP="http://34.158.47.236"
def post(path, data, tok=None):
    h={"Content-Type":"application/json"}
    if tok: h["Authorization"]="Bearer "+tok
    return urllib.request.urlopen(urllib.request.Request(IP+path, data=json.dumps(data).encode(), headers=h), timeout=50)
tok=json.loads(post("/api/user/auth/login",{"email":"admin@company.com","password":"***REDACTED-SEED-ADMIN-PW***"}).read())["access_token"]
p=tok.split(".")[1]; p+="="*(-len(p)%4); uid=json.loads(base64.urlsafe_b64decode(p))["user_id"]
resp=post("/api/query/query",{"question":"Chính sách nghỉ phép năm của công ty quy định thế nào?","user_id":uid}, tok)
n=0
for raw in resp:
    line=raw.decode("utf-8","replace").rstrip()
    if line: print(line[:200])
    n+=1
    if n>60: break
