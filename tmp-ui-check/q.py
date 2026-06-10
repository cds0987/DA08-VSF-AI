import json, urllib.request
IP="http://34.158.47.236"
def post(path, data, tok=None):
    h={"Content-Type":"application/json"}
    if tok: h["Authorization"]="Bearer "+tok
    req=urllib.request.Request(IP+path, data=json.dumps(data).encode(), headers=h)
    return urllib.request.urlopen(req, timeout=40)
tok=json.loads(post("/api/user/auth/login",{"email":"admin@company.com","password":"***REDACTED-SEED-ADMIN-PW***"}).read())["access_token"]
import base64
p=tok.split(".")[1]; p+="="*(-len(p)%4)
uid=json.loads(base64.urlsafe_b64decode(p))["user_id"]
print("user_id=",uid)
print("=== SSE stream ===")
resp=post("/api/query/query",{"question":"Nhân viên được bao nhiêu ngày phép năm?","user_id":uid}, tok)
import sys
n=0
for raw in resp:
    line=raw.decode("utf-8","replace").rstrip()
    if line: print(line)
    n+=1
    if n>120: break
