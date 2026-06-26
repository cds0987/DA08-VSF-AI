# Probe AI Router /v1/embeddings: base64 vs float vs default (SDK) — soi res.data/embedding.
import json, urllib.request, sys

URL = "http://ai-router:8010/v1/embeddings"

def probe(label, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(URL, data=body, headers={"content-type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        d = json.load(r)
    except Exception as e:
        print(f"[{label}] HTTP-ERROR {type(e).__name__}: {str(e)[:160]}")
        return
    data = d.get("data")
    print(f"[{label}] data_type={type(data).__name__} len={len(data) if isinstance(data,list) else data}")
    if isinstance(data, list) and data:
        emb = data[0].get("embedding")
        print(f"        embedding_type={type(emb).__name__} sample={str(emb)[:48]}")
    else:
        print(f"        RAW(first 300)={json.dumps(d)[:300]}")

base = {"model": "qwen/qwen3-embedding-4b", "input": ["hello world"], "dimensions": 2560}
probe("base64", {**base, "encoding_format": "base64"})
probe("float", {**base, "encoding_format": "float"})
probe("default(no encoding_format = SDK gửi base64 ngầm)", dict(base))

# Bắn 10 call //song song để thử reproduce degraded dưới concurrency
import concurrent.futures as cf
print("\n=== 10 concurrent (base64) — soi None/str ===")
def one(i):
    body = json.dumps({**base, "encoding_format": "base64", "input": [f"row {i}"]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"content-type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=30))
        data = d.get("data")
        if not isinstance(data, list) or not data:
            return f"i={i} DEGRADED data={data!r} raw={json.dumps(d)[:120]}"
        return f"i={i} ok emb={type(data[0].get('embedding')).__name__}"
    except Exception as e:
        return f"i={i} ERR {type(e).__name__}:{str(e)[:80]}"
with cf.ThreadPoolExecutor(max_workers=10) as ex:
    for r in ex.map(one, range(10)):
        print("  ", r)
