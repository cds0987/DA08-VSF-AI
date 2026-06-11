import json, urllib.request, base64
IP = "http://34.158.47.236"

def post(path, data, tok=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    return urllib.request.urlopen(
        urllib.request.Request(IP + path, data=json.dumps(data).encode(), headers=h),
        timeout=120,
    )

tok = json.loads(post("/api/user/auth/login",
                      {"email": "admin@company.com", "password": "***REDACTED-SEED-ADMIN-PW***"}).read())["access_token"]
p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
uid = json.loads(base64.urlsafe_b64decode(p))["user_id"]

def ask(q):
    print(f"\n========== Q: {q}")
    resp = post("/api/query/query", {"question": q, "user_id": uid}, tok)
    ans = ""
    last_done = None
    nevents = 0
    keys_seen = set()
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:].strip())
        except Exception:
            continue
        nevents += 1
        keys_seen |= set(d.keys())
        if d.get("token"):
            ans += d["token"]
        # print non-token events verbatim (tool lifecycle, phase, done)
        if not d.get("token"):
            compact = {k: v for k, v in d.items() if k not in ("sources",)}
            if "sources" in d:
                compact["sources_n"] = len(d.get("sources") or [])
            print("  EVT:", json.dumps(compact, ensure_ascii=False)[:300])
        if d.get("done"):
            last_done = d
    print(f"  -- events={nevents} keys={sorted(keys_seen)}")
    if last_done:
        srcs = last_done.get("sources") or []
        print(f"  -- FINAL outcome={last_done.get('outcome')} sources={len(srcs)} names={[s.get('document_name') for s in srcs]}")
    print(f"  -- ANSWER: {ans[:400]}")

for q in ["chính sách nghỉ phép của công ty như thế nào", "công ty có bao nhiêu ngày nghỉ phép năm"]:
    try:
        ask(q)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
