# Reproduce embed dưới concurrency cao — ĐÚNG đường OpenAI SDK của rag-worker
# (không set encoding_format -> SDK gửi base64 ngầm + tự decode; router ép float).
# Soi: exception type lúc parse, data=None, embedding=None/str. Ramp 30->60->120.
import asyncio, traceback
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="http://ai-router:8010/v1", api_key="x", max_retries=0, timeout=60)

async def one(i):
    try:
        res = await client.embeddings.create(
            model="qwen/qwen3-embedding-4b", input=[f"row {i} chinh sach nghi phep"], dimensions=2560
        )
        data = res.data
        if data is None:
            return ("data_none", f"{i}: res.data=None")
        emb = data[0].embedding
        if emb is None:
            return ("emb_none", f"{i}: embedding=None")
        if not isinstance(emb, list):
            return ("emb_str", f"{i}: embedding type={type(emb).__name__}")
        return ("ok", "")
    except Exception as e:
        return (type(e).__name__, f"{i}: {type(e).__name__}: {str(e)[:120]}\n{traceback.format_exc().splitlines()[-3] if traceback.format_exc() else ''}")

async def main():
    from collections import Counter
    for conc in [30, 60, 120]:
        res = await asyncio.gather(*[one(i) for i in range(conc)])
        c = Counter(k for k, _ in res)
        print(f"=== conc={conc}: {dict(c)}")
        for k, msg in res:
            if k != "ok":
                print("   ", msg)
        await asyncio.sleep(1)

asyncio.run(main())
