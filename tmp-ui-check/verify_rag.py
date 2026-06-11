import json, urllib.request, base64
IP = "http://34.158.47.236"

def post(path, data, tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    return urllib.request.urlopen(
        urllib.request.Request(IP + path, data=json.dumps(data).encode(), headers=h),
        timeout=90,
    )

tok = json.loads(post("/api/user/auth/login",
                      {"email": "admin@company.com", "password": "***REDACTED-SEED-ADMIN-PW***"}).read())["access_token"]
p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
uid = json.loads(base64.urlsafe_b64decode(p))["user_id"]

def ask(q):
    resp = post("/api/query/query", {"question": q, "user_id": uid}, tok)
    ans = ""; tools = []; done = None
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:].strip())
        except Exception:
            continue
        if d.get("tool"):
            tools.append(d.get("tool"))
        if d.get("token"):
            ans += d["token"]
        if d.get("done"):
            done = d
    src = len(done.get("sources") or []) if done else 0
    names = [s.get("document_name") for s in (done.get("sources") or [])] if done else []
    outcome = done.get("outcome") if done else None
    print(f"\n=== Q: {q}")
    print(f"  tools={tools}  outcome={outcome}  sources={src}  {names}")
    print(f"  ANSWER: {ans[:300]}")

for q in ["số ngày nghỉ phép năm là bao nhiêu", "chính sách nghỉ phép của công ty"]:
    try:
        ask(q)
    except Exception as e:
        print(f"\n=== Q: {q}\n  ERROR: {type(e).__name__}: {e}")
