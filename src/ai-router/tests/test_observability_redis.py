"""Test shared metrics qua Redis (RedisMetricsSink) — nhất quán across nhiều worker.

Chạy: python -m pytest tests/test_observability_redis.py -q

Repo chưa có fakeredis -> dùng fake async redis tối giản (dict-backed) đủ cho sink:
hincrbyfloat / hgetall / expire. Đủ kiểm chứng delta cộng dồn + aggregate 2 worker.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.observability import (
    COUNTERS_HASH,
    HIST_HASH,
    LAT_BUCKETS,
    Metrics,
    RedisMetricsSink,
    render_prometheus,
    render_prometheus_shared,
)


class FakeAsyncRedis:
    """Async Redis tối giản dict-backed: chỉ hash ops + expire (đủ cho RedisMetricsSink)."""

    def __init__(self) -> None:
        self._h: dict[str, dict[str, float]] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def hincrbyfloat(self, key, field, amount):
        h = self._h.setdefault(key, {})
        h[field] = h.get(field, 0.0) + float(amount)
        return h[field]

    async def hgetall(self, key):
        # redis decode_responses=True -> str; ta giữ float, render tự float() lại nên OK.
        return dict(self._h.get(key, {}))

    async def expire(self, key, ttl):
        self.expire_calls.append((key, ttl))
        return True


def test_flush_delta_no_double_count():
    async def run():
        r = FakeAsyncRedis()
        m = Metrics()
        sink = RedisMetricsSink(r)

        m.inc("airouter_calls_total", {"key_id": "oai-1", "status": "ok"})  # =1
        m.observe("airouter_ttfc_seconds", {"key_id": "oai-1"}, 0.4)
        await sink.flush(m)

        # tăng thêm -> flush 2 chỉ đẩy DELTA
        m.inc("airouter_calls_total", {"key_id": "oai-1", "status": "ok"})  # =2
        m.observe("airouter_ttfc_seconds", {"key_id": "oai-1"}, 0.4)
        await sink.flush(m)

        data = await sink.read()
        counters = {(n, tuple(sorted(l.items()))): v for n, l, v in data["counters"]}
        assert counters[("airouter_calls_total",
                         (("key_id", "oai-1"), ("status", "ok")))] == 2.0
        (hname, hlabels, h), = data["hist"]
        assert hname == "airouter_ttfc_seconds"
        assert h["count"] == 2.0
        # cả 2 obs ≤ 0.5 -> bucket le=0.5 (index của 0.5) = 2
        idx = LAT_BUCKETS.index(0.5)
        assert h["b"][idx] == 2.0
        assert abs(h["sum"] - 0.8) < 1e-9
        print("OK flush delta không double-count")
    asyncio.run(run())


def test_two_workers_aggregate():
    async def run():
        r = FakeAsyncRedis()                 # 1 Redis dùng chung
        m1, m2 = Metrics(), Metrics()        # 2 "worker" process riêng
        s1, s2 = RedisMetricsSink(r), RedisMetricsSink(r)

        labels = {"key_id": "oai-1", "status": "ok"}
        for _ in range(3):
            m1.inc("airouter_calls_total", labels)
            m1.observe("airouter_call_latency_seconds", {"m": "x"}, 1.0)
        for _ in range(5):
            m2.inc("airouter_calls_total", labels)
            m2.observe("airouter_call_latency_seconds", {"m": "x"}, 1.0)

        await s1.flush(m1)
        await s2.flush(m2)

        data = await sink_read(r)
        counters = {(n, tuple(sorted(l.items()))): v for n, l, v in data["counters"]}
        assert counters[("airouter_calls_total",
                         (("key_id", "oai-1"), ("status", "ok")))] == 8.0
        (_, _, h), = data["hist"]
        assert h["count"] == 8.0
        idx = LAT_BUCKETS.index(1)
        assert h["b"][idx] == 8.0   # cả 8 obs = 1.0 ≤ 1
        print("OK 2 worker -> Redis tổng đúng (counter 8, hist count 8)")
    asyncio.run(run())


async def sink_read(r):
    return await RedisMetricsSink(r).read()


def test_render_shared_format():
    async def run():
        r = FakeAsyncRedis()
        m = Metrics()
        sink = RedisMetricsSink(r)
        m.inc("airouter_calls_total", {"key_id": "oai-1", "status": "ok"}, 4.0)
        m.observe("airouter_ttfc_seconds", {"key_id": "oai-1"}, 2.0)
        await sink.flush(m)

        snap = {"keys": [{"key_id": "oai-1", "secret_env": "OPENAI_API_KEY_1",
                          "provider": "openai", "used_today": 10}]}
        text = render_prometheus_shared(snap, await sink.read())

        assert "# TYPE airouter_calls_total counter" in text
        assert 'airouter_calls_total{key_id="oai-1",status="ok"} 4.0' in text
        assert "# TYPE airouter_ttfc_seconds histogram" in text
        assert 'airouter_ttfc_seconds_bucket{key_id="oai-1",le="3"}' in text
        assert 'airouter_ttfc_seconds_bucket{key_id="oai-1",le="+Inf"} 1.0' in text
        assert 'airouter_ttfc_seconds_sum{key_id="oai-1"} 2.0' in text
        assert 'airouter_ttfc_seconds_count{key_id="oai-1"} 1.0' in text
        # GAUGE giữ nguyên (nguồn snapshot)
        assert "airouter_key_tokens_today" in text
        print("OK render_shared format giống bản cũ (_bucket/le/_sum/_count/+Inf)")
    asyncio.run(run())


def test_fallback_inprocess_still_works():
    # Không Redis -> render in-process cũ vẫn chạy y nguyên.
    m = Metrics()
    m.inc("airouter_fallback_total", {"capability": "answer", "tier": "free_oai"})
    m.observe("airouter_call_latency_seconds", {"m": "x"}, 5.0)
    text = render_prometheus({"keys": []}, m)
    assert "# TYPE airouter_fallback_total counter" in text
    assert "# TYPE airouter_call_latency_seconds histogram" in text
    assert 'airouter_call_latency_seconds_bucket{m="x",le="+Inf"} 1' in text
    print("OK fallback in-process render nguyên vẹn")


def test_shared_and_inprocess_same_shape():
    # Cùng 1 quan sát -> render_prometheus (in-proc) và render_prometheus_shared phải ra
    # cùng các dòng counter/hist (dashboard không đổi).
    async def run():
        r = FakeAsyncRedis()
        m = Metrics()
        sink = RedisMetricsSink(r)
        m.inc("airouter_calls_total", {"a": "1"}, 2.0)
        m.observe("airouter_ttfc_seconds", {"a": "1"}, 0.3)
        await sink.flush(m)

        snap = {"keys": []}
        inproc = render_prometheus(snap, m)
        shared = render_prometheus_shared(snap, await sink.read())
        # so sánh tập dòng metric (bỏ qua khác biệt float fmt 2 vs 2.0 bằng cách chuẩn hóa)
        import re
        def metric_lines(t):
            # chuẩn hóa value cuối dòng: bỏ '.0' (int vs float) -> so hình dạng, không fmt
            out = set()
            for ln in t.splitlines():
                if ln and not ln.startswith("#"):
                    out.add(re.sub(r"\.0+$", "", ln))
            return out
        assert metric_lines(inproc) == metric_lines(shared)
        print("OK in-process vs shared cùng tập dòng metric")
    asyncio.run(run())


def test_expire_refreshed_on_flush():
    async def run():
        r = FakeAsyncRedis()
        m = Metrics()
        m.inc("x_total", {})
        sink = RedisMetricsSink(r)
        await sink.flush(m)
        assert (COUNTERS_HASH, 93_600) in r.expire_calls
        assert (HIST_HASH, 93_600) in r.expire_calls
        print("OK TTL refresh mỗi flush")
    asyncio.run(run())


if __name__ == "__main__":
    test_flush_delta_no_double_count()
    test_two_workers_aggregate()
    test_render_shared_format()
    test_fallback_inprocess_still_works()
    test_shared_and_inprocess_same_shape()
    test_expire_refreshed_on_flush()
    print("\nALL TESTS PASSED")
