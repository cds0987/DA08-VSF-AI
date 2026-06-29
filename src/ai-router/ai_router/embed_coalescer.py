"""Demand-driven coalescing batcher cho /v1/embeddings (gateway-side).

Vì sao: embed KHÔNG scale ngang (3 provider OpenRouter + AIMD cap concurrency) -> lever đúng là
gom theo CHIỀU DỌC. ai-router là điểm DUY NHẤT mọi request embed hội tụ (ingest-doc + chat-intent +
mcp-search) -> đo được DEMAND THẬT (queue-depth) rồi size batch theo đó, KHÔNG "gửi mù chờ 429".

Cơ chế: mỗi request enqueue (texts + future). Dispatcher/key (model+dims+encoding) gom các request
đang chờ trong CỬA SỔ ngắn (W ms) tới max_batch text -> 1 upstream call (router.embeddings) -> tách
embedding-array trả về đúng từng future theo offset.

AN TOÀN: opt-in (EMBED_COALESCE_ENABLED=0 mặc định -> passthrough). Logic merge/split TÁCH thành
hàm thuần (_split_embeddings) để test kỹ — sai split = trả nhầm vector cho caller.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable


def _norm_input(inp: Any) -> list[str]:
    if isinstance(inp, list):
        return [x for x in inp]
    return [inp] if inp is not None else []


def _split_embeddings(merged_data: list[dict], sizes: list[int]) -> list[list[dict]]:
    """Tách `data` (embedding của batch gộp, mỗi item có 'index' + 'embedding') về từng request theo
    `sizes` (số text mỗi request, đúng thứ tự enqueue). Re-index mỗi slice về 0..k-1 (caller mong index
    khớp input CỦA NÓ). PURE -> test kỹ. Đảm bảo data sort theo index trước khi cắt."""
    ordered = sorted(merged_data, key=lambda d: d.get("index", 0))
    total = sum(sizes)
    if len(ordered) != total:
        raise ValueError(f"coalesce split mismatch: got {len(ordered)} embeddings, expect {total}")
    out: list[list[dict]] = []
    off = 0
    for k in sizes:
        sl = ordered[off:off + k]
        out.append([{"object": "embedding", "index": i, "embedding": sl[i]["embedding"]}
                    for i in range(k)])
        off += k
    return out


class _Pending:
    __slots__ = ("texts", "future")

    def __init__(self, texts: list[str], future: asyncio.Future):
        self.texts = texts
        self.future = future


class EmbedCoalescer:
    """Gom request embed theo (model, dimensions, encoding_format). enabled qua env."""

    def __init__(self, embed_fn: Callable[[dict], Awaitable[dict]]):
        self._embed = embed_fn                      # router.embeddings
        self.enabled = _truthy(os.getenv("EMBED_COALESCE_ENABLED", "0"))
        self.window = max(1, int(os.getenv("EMBED_COALESCE_WINDOW_MS", "15"))) / 1000.0
        self.max_batch = max(1, int(os.getenv("EMBED_COALESCE_MAX_BATCH", "256")))
        self._queues: dict[tuple, asyncio.Queue] = {}
        self._tasks: dict[tuple, asyncio.Task] = {}

    async def embeddings(self, body: dict) -> dict:
        texts = _norm_input(body.get("input"))
        if not self.enabled or len(texts) >= self.max_batch:
            return await self._embed(body)          # off / request đã đầy -> passthrough (không gom)
        key = (body.get("model") or "embed", body.get("dimensions"), body.get("encoding_format"))
        q = self._queues.get(key)
        if q is None:
            q = asyncio.Queue()
            self._queues[key] = q
            self._tasks[key] = asyncio.create_task(self._dispatch(key, q, body))
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        await q.put(_Pending(texts, fut))
        return await fut

    async def aclose(self) -> None:
        """Cancel dispatcher tasks (test teardown / shutdown). Prod: app sống lâu, ít gọi."""
        for t in self._tasks.values():
            t.cancel()
        for t in list(self._tasks.values()):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        self._queues.clear()

    async def _dispatch(self, key: tuple, q: asyncio.Queue, sample_body: dict) -> None:
        model, dims, enc = key
        while True:
            first: _Pending = await q.get()                  # chặn tới khi có request
            batch = [first]
            n = len(first.texts)
            deadline = asyncio.get_event_loop().time() + self.window
            while n < self.max_batch:
                timeout = deadline - asyncio.get_event_loop().time()
                if timeout <= 0:
                    break
                try:
                    item: _Pending = await asyncio.wait_for(q.get(), timeout)
                except asyncio.TimeoutError:
                    break
                if n + len(item.texts) > self.max_batch:
                    q.put_nowait(item)                        # không nhét được -> để batch sau
                    break
                batch.append(item)
                n += len(item.texts)
            await self._flush(batch, model, dims, enc)

    async def _flush(self, batch: list[_Pending], model, dims, enc) -> None:
        merged: list[str] = []
        sizes: list[int] = []
        for it in batch:
            merged.extend(it.texts)
            sizes.append(len(it.texts))
        req = {"model": model, "input": merged}
        if dims is not None:
            req["dimensions"] = dims
        if enc is not None:
            req["encoding_format"] = enc
        try:
            resp = await self._embed(req)
            slices = _split_embeddings(resp.get("data") or [], sizes)
            usage = resp.get("usage") or {}
            for it, sl in zip(batch, slices):
                if not it.future.done():
                    it.future.set_result({"object": "list", "data": sl, "model": resp.get("model"),
                                          "usage": usage, "_router": resp.get("_router")})
        except Exception as exc:                              # 1 call gộp lỗi -> mọi future nhận lỗi (caller tự retry)
            for it in batch:
                if not it.future.done():
                    it.future.set_exception(exc)


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")
