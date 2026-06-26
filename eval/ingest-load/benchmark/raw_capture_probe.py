# Bắt RESPONSE THÔ của ai-router/embeddings lúc degraded (data rỗng) dưới concurrency cao.
# Dùng raw HTTP (KHÔNG qua OpenAI SDK) -> thấy đúng HTTP status + body thật:
#   - 429/5xx (proper error) HAY 200-với-body-rỗng/error-envelope?
import asyncio, json, urllib.request, urllib.error
from collections import Counter

URL = "http://ai-router:8010/v1/embeddings"

def call(i):
    body = json.dumps({"model": "qwen/qwen3-embedding-4b", "input": [f"row {i}"],
                       "encoding_format": "float", "dimensions": 2560}).encode()
    req = urllib.request.Request(URL, data=body, headers={"content-type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        raw = r.read().decode("utf-8", "replace")
        status = r.status
    except urllib.error.HTTPError as e:
        return ("HTTP_" + str(e.code), e.read().decode("utf-8", "replace")[:400])
    except Exception as e:
        return ("EXC_" + type(e).__name__, str(e)[:200])
    try:
        d = json.loads(raw)
    except Exception:
        return ("BAD_JSON_" + str(status), raw[:400])
    data = d.get("data")
    if isinstance(data, list) and data and isinstance(data[0].get("embedding"), list):
        return ("ok_" + str(status), "")
    # degraded: 200 nhưng data rỗng/thiếu -> DUMP nguyên body
    return ("DEGRADED_" + str(status), raw[:600])

async def main():
    loop = asyncio.get_event_loop()
    for conc in [60, 120, 180]:
        results = await asyncio.gather(*[loop.run_in_executor(None, call, i) for i in range(conc)])
        c = Counter(k for k, _ in results)
        print(f"\n=== conc={conc}: {dict(c)}")
        seen = set()
        for k, body in results:
            if not k.startswith("ok") and k not in seen:
                seen.add(k)
                print(f"   [{k}] body/err: {body}")
        await asyncio.sleep(1)

asyncio.run(main())
