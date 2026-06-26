# Khảo sát qwen3-embedding-8b trên OpenRouter: dimension (native + MRL truncate),
# truy cập, multi-provider routing, so 4b. Chạy trong ai-router container (có OPENROUTER key).
import os, json, urllib.request, urllib.error, time

KEY = next((v for k, v in os.environ.items() if k.startswith("OPENROUTER_API_KEY")), None)
print("has_or_key:", bool(KEY))


def emb(model, dim=None, provider_order=None):
    body = {"model": model, "input": ["chinh sach nghi phep cong ty"]}
    if dim:
        body["dimensions"] = dim
    if provider_order:
        body["provider"] = {"order": provider_order}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/embeddings",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {KEY}"},
    )
    t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=40))
        ms = (time.time() - t0) * 1000
        data = d.get("data")
        if not data:
            return f"NO_DATA err={d.get('error')}"
        v = data[0]["embedding"]
        return f"OK dim={len(v)} served={d.get('model')} prov={d.get('provider','?')} {ms:.0f}ms type={type(v).__name__}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()[:160]}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {str(e)[:160]}"


print("8b native     :", emb("qwen/qwen3-embedding-8b"))
print("8b dim=2560   :", emb("qwen/qwen3-embedding-8b", 2560))
print("8b dim=4096   :", emb("qwen/qwen3-embedding-8b", 4096))
print("8b dim=1024   :", emb("qwen/qwen3-embedding-8b", 1024))
print("4b native(so) :", emb("qwen/qwen3-embedding-4b"))

# Burst 40 // để so engine_overloaded 8b vs 4b
import concurrent.futures as cf
def hit(model):
    return emb(model)
for model in ["qwen/qwen3-embedding-8b", "qwen/qwen3-embedding-4b"]:
    with cf.ThreadPoolExecutor(max_workers=40) as ex:
        res = list(ex.map(lambda i: hit(model), range(40)))
    ok = sum(r.startswith("OK") for r in res)
    overloaded = sum("429" in r or "overload" in r.lower() for r in res)
    print(f"BURST40 {model}: ok={ok}/40 overloaded={overloaded} other={40-ok-overloaded}")
