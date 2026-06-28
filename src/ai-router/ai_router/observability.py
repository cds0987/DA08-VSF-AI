"""Observability — Prometheus /metrics cho automation monitor (PLAN §giám sát).

Thiết kế MỞ RỘNG:
  - `Metrics`: registry counter in-process (1 instance ai-router). Thêm 1 chỉ số = 1 lời
    gọi `inc()`, KHÔNG sửa core. Dùng cho LEADING INDICATOR (fallback, resolve-fail) — rẻ,
    real-time, không đụng Redis hot-path.
  - Per-key GAUGE (token/cost/quota/cooldown) lấy từ `Router.snapshot()` (Redis) lúc render
    -> số CHÍNH XÁC, không phải đếm lại.
  - `key_id` = định danh theo GitHub secret (`oai-3` ↔ OPENAI_API_KEY_3). KHÔNG bao giờ raw key.

Automation: scrape /metrics -> Prometheus -> alert rule (fallback_rate, paid cost, quota burndown).
Thêm metric mới: chỉ cần `router.metrics.inc("ten_moi", {...})` ở chỗ phát sinh — tự render ra.
"""
from __future__ import annotations

from threading import Lock

# Bucket giây cho histogram latency/ttfc (dải LLM call 0.25-55s). Cumulative theo chuẩn Prometheus
# -> Grafana histogram_quantile() tính p50/p95/p99; avg = rate(_sum)/rate(_count).
# (Nuôi metric airouter_ttfc_seconds + airouter_call_latency_seconds cho bảng 'Trải nghiệm user'.)
# (re-deploy: deploy trước fail do gcloud ssh 255 transient, không phải code.)
LAT_BUCKETS: tuple[float, ...] = (0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144)


def _esc(v: str) -> str:
    """Escape label value theo chuẩn Prometheus text exposition."""
    return str(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _line(name: str, labels: dict[str, object] | None, value: float) -> str:
    if labels:
        inner = ",".join(f'{k}="{_esc(str(v))}"' for k, v in labels.items())
        return f"{name}{{{inner}}} {value}"
    return f"{name} {value}"


class Metrics:
    """Counter cộng dồn in-process (monotonic) cho leading indicator. Thread-safe.

    Mở rộng = gọi inc(name, labels). Không cần khai báo trước. HELP/TYPE auto = counter.
    """

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        # histogram: key -> {"b": [count/bucket], "sum": float, "count": int}
        self._hist: dict[tuple[str, tuple[tuple[str, str], ...]], dict] = {}
        self._lock = Lock()

    def inc(self, name: str, labels: dict[str, object] | None = None, amount: float = 1.0) -> None:
        key = (name, tuple(sorted((k, str(v)) for k, v in (labels or {}).items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def observe(self, name: str, labels: dict[str, object] | None, value: float) -> None:
        """Ghi 1 quan sát latency/ttfc (giây) vào histogram. Bucket cumulative -> p95/p99 ở Grafana."""
        key = (name, tuple(sorted((k, str(v)) for k, v in (labels or {}).items())))
        with self._lock:
            h = self._hist.get(key)
            if h is None:
                h = {"b": [0] * len(LAT_BUCKETS), "sum": 0.0, "count": 0}
                self._hist[key] = h
            for i, le in enumerate(LAT_BUCKETS):
                if value <= le:
                    h["b"][i] += 1          # cumulative: obs ≤ le[i] tăng bucket i
            h["sum"] += float(value)
            h["count"] += 1

    def snapshot(self) -> list[tuple[str, dict[str, str], float]]:
        with self._lock:
            return [(name, dict(lbls), val) for (name, lbls), val in self._counters.items()]

    def hist_snapshot(self) -> list[tuple[str, dict[str, str], dict]]:
        with self._lock:
            return [(name, dict(lbls), {"b": list(h["b"]), "sum": h["sum"], "count": h["count"]})
                    for (name, lbls), h in self._hist.items()]


# --------------------------------------------------------------------------- #
# Shared metrics qua Redis (nhiều worker/replica) — PERIODIC-FLUSH delta.
#
# Vấn đề: `Metrics` in-process -> mỗi uvicorn worker đếm RIÊNG; /metrics đọc 1 worker
# -> số phân mảnh, dashboard sai. Giải: định kỳ flush DELTA (phần TĂNG so với lần
# trước) sang 2 Redis hash dùng chung; render đọc từ Redis -> tổng across workers.
#
# Vì counter monotonic + histogram bucket cumulative => DELTA luôn ≥ 0, cộng dồn bằng
# HINCRBY{,FLOAT} ở Redis = đúng tổng. last-snapshot giữ trong sink (per-worker) để
# flush lần sau chỉ đẩy phần mới (KHÔNG double-count).
# --------------------------------------------------------------------------- #
_US = "\x1f"   # unit separator — ngăn cách name / labels / phần hist trong field
COUNTERS_HASH = "airouter:metrics:counters"
HIST_HASH = "airouter:metrics:hist"
METRICS_TTL = 93_600   # 26h — refresh mỗi flush; metric của worker chết tự rụng


def _ser_labels(labels: dict[str, str]) -> str:
    """Serialize labels ổn định (sorted) -> 'k1=v1,k2=v2'. Đảo lại được khi render."""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


def _deser_labels(s: str) -> dict[str, str]:
    if not s:
        return {}
    out: dict[str, str] = {}
    for part in s.split(","):
        k, _, v = part.partition("=")
        out[k] = v
    return out


class RedisMetricsSink:
    """Flush DELTA counter+histogram của 1 `Metrics` (in-process) sang Redis hash dùng chung.

    Schema:
      hash COUNTERS_HASH  field = f"{name}{US}{labels_ser}"                 -> float (cộng dồn)
      hash HIST_HASH      field = f"{name}{US}{labels_ser}{US}b{i}"        -> float (bucket cumulative)
                          field = f"{name}{US}{labels_ser}{US}sum"         -> float
                          field = f"{name}{US}{labels_ser}{US}count"       -> float
    """

    def __init__(self, client) -> None:
        self._r = client
        # last-snapshot đã flush (per-worker) -> chỉ đẩy phần TĂNG.
        self._last_counters: dict[str, float] = {}
        self._last_hist: dict[str, float] = {}   # field hist -> giá trị đã flush

    async def flush(self, metrics: Metrics) -> None:
        # ── COUNTER delta ─────────────────────────────────────────────────────
        for name, labels, val in metrics.snapshot():
            field = f"{name}{_US}{_ser_labels(labels)}"
            delta = val - self._last_counters.get(field, 0.0)
            if delta:
                await self._r.hincrbyfloat(COUNTERS_HASH, field, delta)
                self._last_counters[field] = val
        # ── HISTOGRAM delta (mỗi bucket + sum + count) ────────────────────────
        for name, labels, h in metrics.hist_snapshot():
            base = f"{name}{_US}{_ser_labels(labels)}"
            cur: dict[str, float] = {}
            for i in range(len(LAT_BUCKETS)):
                cur[f"{base}{_US}b{i}"] = float(h["b"][i])
            cur[f"{base}{_US}sum"] = float(h["sum"])
            cur[f"{base}{_US}count"] = float(h["count"])
            for field, v in cur.items():
                delta = v - self._last_hist.get(field, 0.0)
                if delta:
                    await self._r.hincrbyfloat(HIST_HASH, field, delta)
                    self._last_hist[field] = v
        await self._r.expire(COUNTERS_HASH, METRICS_TTL)
        await self._r.expire(HIST_HASH, METRICS_TTL)

    async def read(self) -> dict:
        """HGETALL 2 hash -> cấu trúc render: {counters:[(name,labels,val)], hist:[(name,labels,h)]}."""
        craw = await self._r.hgetall(COUNTERS_HASH) or {}
        hraw = await self._r.hgetall(HIST_HASH) or {}
        counters: list[tuple[str, dict[str, str], float]] = []
        for field, val in craw.items():
            name, _, labels_ser = field.partition(_US)
            counters.append((name, _deser_labels(labels_ser), float(val)))
        # gom hist theo (name,labels) -> dựng lại b[]/sum/count
        agg: dict[tuple[str, str], dict] = {}
        for field, val in hraw.items():
            name, _, rest = field.partition(_US)
            labels_ser, _, part = rest.rpartition(_US)
            entry = agg.setdefault((name, labels_ser),
                                   {"b": [0.0] * len(LAT_BUCKETS), "sum": 0.0, "count": 0.0})
            if part.startswith("b"):
                entry["b"][int(part[1:])] = float(val)
            else:
                entry[part] = float(val)
        hist = [(name, _deser_labels(ls), h) for (name, ls), h in agg.items()]
        return {"counters": counters, "hist": hist}


def _render_gauges(snapshot: dict, out: list[str]) -> None:
    """Per-key GAUGE từ Redis snapshot (GIỮ NGUYÊN — số chính xác, không phân mảnh)."""

    # ── Per-key GAUGE (nguồn: Redis qua snapshot) ─────────────────────────────
    out += [
        "# HELP airouter_key_tokens_today Token/requests dùng hôm nay theo key (theo limit_kind).",
        "# TYPE airouter_key_tokens_today gauge",
        "# HELP airouter_key_remaining Quota còn lại hôm nay theo key (null limit -> bỏ qua).",
        "# TYPE airouter_key_remaining gauge",
        "# HELP airouter_key_cost_month_usd Cost USD tháng này theo key.",
        "# TYPE airouter_key_cost_month_usd gauge",
        "# HELP airouter_key_rpm Requests phút hiện tại theo key.",
        "# TYPE airouter_key_rpm gauge",
        "# HELP airouter_key_cooldown Key đang cooldown (circuit-breaker) = 1.",
        "# TYPE airouter_key_cooldown gauge",
        "# HELP airouter_key_limit Trần quota/ngày theo key.",
        "# TYPE airouter_key_limit gauge",
        "# HELP airouter_key_tokens_real_today Token THẬT dùng hôm nay theo key (MỌI tier, gồm paid).",
        "# TYPE airouter_key_tokens_real_today gauge",
        "# HELP airouter_key_inflight Request đang in-flight theo key (concurrency — bắt nghẽn).",
        "# TYPE airouter_key_inflight gauge",
        "# HELP airouter_key_aimd_limit Trần AIMD inflight hiện tại theo key (OpenRouter, dò động).",
        "# TYPE airouter_key_aimd_limit gauge",
    ]
    for k in snapshot.get("keys", []):
        # Nhãn theo PROVIDER (KHÔNG còn 'free_*' tier gây hiểu lầm: 1 key phục vụ cả free lẫn paid).
        # secret_env: định danh GitHub secret (oai-3 -> OPENAI_API_KEY_3) cho devops.
        lbl = {
            "key_id": k.get("key_id", ""),
            "secret_env": k.get("secret_env", ""),
            "provider": k.get("provider", ""),
        }
        out.append(_line("airouter_key_tokens_today", lbl, k.get("used_today", 0) or 0))
        out.append(_line("airouter_key_tokens_real_today", lbl, k.get("tokens_real", 0) or 0))
        if k.get("remaining") is not None:
            out.append(_line("airouter_key_remaining", lbl, k.get("remaining")))
        out.append(_line("airouter_key_cost_month_usd", lbl, k.get("cost_month", 0.0) or 0.0))
        out.append(_line("airouter_key_rpm", lbl, k.get("rpm_now", 0) or 0))
        out.append(_line("airouter_key_inflight", lbl, k.get("inflight", 0) or 0))
        if k.get("aimd_limit") is not None:
            out.append(_line("airouter_key_aimd_limit", lbl, k.get("aimd_limit")))
        out.append(_line("airouter_key_cooldown", lbl, 1 if k.get("cooldown") else 0))
        out.append(_line("airouter_key_limit", lbl, k.get("limit", 0) or 0))

    # ── Meta gauge ────────────────────────────────────────────────────────────
    out += [
        "# HELP airouter_keys_total Tổng số key đang đăng ký (auto-discover từ secret).",
        "# TYPE airouter_keys_total gauge",
        _line("airouter_keys_total", None, len(snapshot.get("keys", []))),
    ]


def _render_counters(series: list[tuple[str, dict, float]], out: list[str]) -> None:
    """Leading-indicator COUNTER. `series` = [(name, labels, value)] (in-process HOẶC Redis)."""
    seen_help: set[str] = set()
    for name, labels, value in sorted(series, key=lambda s: s[0]):
        if name not in seen_help:
            out.append(f"# TYPE {name} counter")
            seen_help.add(name)
        out.append(_line(name, labels, value))


def _render_hist(hist: list[tuple[str, dict, dict]], out: list[str]) -> None:
    """Histogram latency/ttfc -> p95/p99/avg ở Grafana. `hist` = [(name, labels, {b,sum,count})]."""
    seen_h: set[str] = set()
    for name, labels, h in sorted(hist, key=lambda s: s[0]):
        if name not in seen_h:
            out.append(f"# HELP {name} Latency giây (histogram).")
            out.append(f"# TYPE {name} histogram")
            seen_h.add(name)
        for i, le in enumerate(LAT_BUCKETS):
            out.append(_line(f"{name}_bucket", {**labels, "le": str(le)}, h["b"][i]))
        out.append(_line(f"{name}_bucket", {**labels, "le": "+Inf"}, h["count"]))
        out.append(_line(f"{name}_sum", labels, h["sum"]))
        out.append(_line(f"{name}_count", labels, h["count"]))


def render_prometheus(snapshot: dict, metrics: Metrics) -> str:
    """Sinh text exposition (0.0.4) từ snapshot quota + counter/hist IN-PROCESS (dev/single)."""
    out: list[str] = []
    _render_gauges(snapshot, out)
    _render_counters(metrics.snapshot(), out)
    _render_hist(metrics.hist_snapshot(), out)
    return "\n".join(out) + "\n"


def render_prometheus_shared(snapshot: dict, sink_data: dict) -> str:
    """Như render_prometheus nhưng counter/hist lấy từ Redis (sink.read()) -> tổng across workers.

    GAUGE giữ nguyên nguồn snapshot (đã shared). Output GIỐNG HỆT định dạng bản in-process
    (cùng tên metric, label, _bucket{le=...}, _sum, _count, +Inf) -> dashboard không đổi.
    """
    out: list[str] = []
    _render_gauges(snapshot, out)
    _render_counters(sink_data.get("counters", []), out)
    _render_hist(sink_data.get("hist", []), out)
    return "\n".join(out) + "\n"
