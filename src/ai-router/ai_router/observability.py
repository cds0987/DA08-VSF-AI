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
        self._lock = Lock()

    def inc(self, name: str, labels: dict[str, object] | None = None, amount: float = 1.0) -> None:
        key = (name, tuple(sorted((k, str(v)) for k, v in (labels or {}).items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def snapshot(self) -> list[tuple[str, dict[str, str], float]]:
        with self._lock:
            return [(name, dict(lbls), val) for (name, lbls), val in self._counters.items()]


def render_prometheus(snapshot: dict, metrics: Metrics) -> str:
    """Sinh text exposition (version 0.0.4) từ snapshot quota + counter leading-indicator."""
    out: list[str] = []

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
    ]
    for k in snapshot.get("keys", []):
        # secret_env: định danh GitHub secret (oai-3 -> OPENAI_API_KEY_3) cho devops.
        lbl = {
            "key_id": k.get("key_id", ""),
            "secret_env": k.get("secret_env", ""),
            "provider": k.get("provider", ""),
            "tier": k.get("tier", ""),
        }
        out.append(_line("airouter_key_tokens_today", lbl, k.get("used_today", 0) or 0))
        if k.get("remaining") is not None:
            out.append(_line("airouter_key_remaining", lbl, k.get("remaining")))
        out.append(_line("airouter_key_cost_month_usd", lbl, k.get("cost_month", 0.0) or 0.0))
        out.append(_line("airouter_key_rpm", lbl, k.get("rpm_now", 0) or 0))
        out.append(_line("airouter_key_cooldown", lbl, 1 if k.get("cooldown") else 0))
        out.append(_line("airouter_key_limit", lbl, k.get("limit", 0) or 0))

    # ── Meta gauge ────────────────────────────────────────────────────────────
    out += [
        "# HELP airouter_keys_total Tổng số key đang đăng ký (auto-discover từ secret).",
        "# TYPE airouter_keys_total gauge",
        _line("airouter_keys_total", None, len(snapshot.get("keys", []))),
    ]

    # ── Leading-indicator COUNTER (nguồn: in-process Metrics) ─────────────────
    # Tách HELP/TYPE theo tên metric (1 lần), rồi liệt kê series.
    series = metrics.snapshot()
    seen_help: set[str] = set()
    for name, labels, value in sorted(series, key=lambda s: s[0]):
        if name not in seen_help:
            out.append(f"# TYPE {name} counter")
            seen_help.add(name)
        out.append(_line(name, labels, value))

    return "\n".join(out) + "\n"
