"""Test coalescing embed batcher — TỚI HẠN: split sai = trả nhầm vector cho caller (corruption)."""
import asyncio
import os

import pytest

from ai_router.embed_coalescer import EmbedCoalescer, _split_embeddings, _norm_input


# ───────────────────────── _split_embeddings (PURE, tới hạn) ─────────────────────────
def test_split_basic_offsets():
    merged = [{"index": i, "embedding": [float(i)]} for i in range(5)]
    out = _split_embeddings(merged, [2, 3])             # req A=2 text, req B=3 text
    assert [d["embedding"][0] for d in out[0]] == [0.0, 1.0]          # A nhận 0,1
    assert [d["embedding"][0] for d in out[1]] == [2.0, 3.0, 4.0]     # B nhận 2,3,4
    assert [d["index"] for d in out[0]] == [0, 1]                     # re-index 0..k-1
    assert [d["index"] for d in out[1]] == [0, 1, 2]


def test_split_reorders_out_of_order_index():
    merged = [{"index": 2, "embedding": ["c"]}, {"index": 0, "embedding": ["a"]},
              {"index": 1, "embedding": ["b"]}]
    out = _split_embeddings(merged, [1, 2])
    assert out[0][0]["embedding"] == ["a"]              # phải SORT theo index trước khi cắt
    assert [d["embedding"] for d in out[1]] == [["b"], ["c"]]


def test_split_mismatch_raises():
    with pytest.raises(ValueError):
        _split_embeddings([{"index": 0, "embedding": [1]}], [2, 3])   # 1 ≠ 5


def test_norm_input():
    assert _norm_input(["a", "b"]) == ["a", "b"]
    assert _norm_input("x") == ["x"]
    assert _norm_input(None) == []


# ───────────────────────── Coalescer end-to-end (mapping ĐÚNG caller) ─────────────────────────
def _make_fn(calls):
    """mock router.embeddings: embedding = [len(text)] -> verify mapping đúng. Đếm số call."""
    async def fn(body):
        calls.append(len(body["input"]))
        return {"object": "list", "model": body["model"], "usage": {"prompt_tokens": 1},
                "data": [{"index": i, "embedding": [float(len(t))]} for i, t in enumerate(body["input"])]}
    return fn


@pytest.mark.asyncio
async def test_passthrough_when_disabled():
    os.environ["EMBED_COALESCE_ENABLED"] = "0"
    calls = []
    c = EmbedCoalescer(_make_fn(calls))
    r = await c.embeddings({"model": "qwen", "input": ["abc"]})
    assert r["data"][0]["embedding"] == [3.0] and len(calls) == 1
    await c.aclose()


@pytest.mark.asyncio
async def test_coalesce_maps_each_caller_correctly():
    os.environ["EMBED_COALESCE_ENABLED"] = "1"
    os.environ["EMBED_COALESCE_WINDOW_MS"] = "40"
    calls = []
    c = EmbedCoalescer(_make_fn(calls))
    # 3 request đồng thời CÙNG model -> phải gom thành ÍT call + mỗi caller nhận ĐÚNG embedding của mình
    r1, r2, r3 = await asyncio.gather(
        c.embeddings({"model": "qwen", "input": ["a", "bb"]}),       # len 1,2
        c.embeddings({"model": "qwen", "input": ["ccc"]}),           # len 3
        c.embeddings({"model": "qwen", "input": ["dddd", "e"]}),     # len 4,1
    )
    assert [d["embedding"][0] for d in r1["data"]] == [1.0, 2.0]
    assert [d["embedding"][0] for d in r2["data"]] == [3.0]
    assert [d["embedding"][0] for d in r3["data"]] == [4.0, 1.0]
    assert len(calls) < 3, f"phải GỘP (< 3 call), thực {len(calls)} call"   # demand-driven coalesce
    await c.aclose()


@pytest.mark.asyncio
async def test_diff_model_not_coalesced():
    os.environ["EMBED_COALESCE_ENABLED"] = "1"
    os.environ["EMBED_COALESCE_WINDOW_MS"] = "30"
    calls_meta = []

    async def fn(body):
        calls_meta.append(body["model"])
        return {"object": "list", "model": body["model"],
                "data": [{"index": i, "embedding": [float(len(t))]} for i, t in enumerate(body["input"])]}
    c = EmbedCoalescer(fn)
    r1, r2 = await asyncio.gather(
        c.embeddings({"model": "qwen", "input": ["a"]}),
        c.embeddings({"model": "pplx", "input": ["bb"]}),
    )
    assert r1["data"][0]["embedding"] == [1.0] and r2["data"][0]["embedding"] == [2.0]
    assert set(calls_meta) == {"qwen", "pplx"}          # 2 model -> 2 call riêng (không trộn vector-space)
    await c.aclose()
