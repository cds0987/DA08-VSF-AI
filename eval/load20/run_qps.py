"""chat-bm0 — load test OPEN-LOOP theo ARRIVAL-RATE (QPS) cố định, đo latency + capacity.

Khác run_load20 (N concurrent / barrier-burst = closed-loop): ở đây cứ mỗi 1/QPS giây bắn 1
query MỚI bất kể query trước xong chưa (open-loop) → mô phỏng đúng "X user/giây tới". Nếu hệ
gánh kịp → in-flight phẳng + latency phẳng; không kịp → in-flight PHÌNH + latency BUNG (tín
hiệu trần thật).

Đo: TTFT(answer) + total latency p50/p95/p99, throughput đạt, peak in-flight, shed/error.
Pool user seeded (common.N_USERS) round-robin né cap 3-SSE/user. Creds qua ENV (common).

Chạy: python eval/load20/seed_users.py   # 1 lần
      LOAD_BASE=.. python eval/load20/run_qps.py --qps 5 --duration 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from common import (
    N_USERS,
    QUERY_API,
    QUESTIONS as _FALLBACK_QUESTIONS,
    USER_API,
    USER_EMAIL,
    USER_PW,
    classify_event,
    parse_sse_line,
)

_INSECURE = False

# Câu hỏi đã VERIFY retrieve (sources>0) trên corpus HIỆN TẠI của Qdrant — tránh
# false-negative khi corpus bị migrate (câu cá-nhân/off-topic ra 0 sources -> đo nhầm
# latency path khác). Sinh bởi đoạn batch-verify; fallback common.QUESTIONS nếu thiếu file.
_VERIFIED = Path(__file__).parent / "hr_questions_verified.json"


def _load_questions() -> list[str]:
    if _VERIFIED.exists():
        qs = json.loads(_VERIFIED.read_text(encoding="utf-8"))
        if qs:
            return qs
    return _FALLBACK_QUESTIONS


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return round(s[i], 3)


async def prelogin(client: httpx.AsyncClient, i: int) -> dict | None:
    try:
        r = await client.post(f"{USER_API}/auth/login",
                              json={"email": USER_EMAIL(i), "password": USER_PW}, timeout=30)
        if r.status_code != 200:
            return None
        token = r.json()["access_token"]
        me = await client.get(f"{USER_API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        uid = me.json().get("id") or me.json().get("user_id")
        return {"idx": i, "token": token, "user_id": uid}
    except Exception:  # noqa: BLE001
        return None


async def one_query(client: httpx.AsyncClient, user: dict, question: str, out: list) -> None:
    t0 = time.perf_counter()
    rec = {"ttft": None, "total": None, "status": "ok", "tokens": 0}
    body = {"user_id": user["user_id"], "question": question, "conversation_id": None}
    h = {"Authorization": f"Bearer {user['token']}"}
    try:
        async with client.stream("POST", f"{QUERY_API}/query", json=body, headers=h,
                                 timeout=httpx.Timeout(180, connect=30)) as r:
            if r.status_code != 200:
                rec["status"] = {429: "rate_limited", 502: "router_error",
                                 503: "unavailable"}.get(r.status_code, f"http_{r.status_code}")
                out.append(rec)
                return
            async for line in r.aiter_lines():
                ev = parse_sse_line(line)
                if ev is None:
                    continue
                kind, text = classify_event(ev)
                if kind == "answer":
                    if rec["ttft"] is None:
                        rec["ttft"] = time.perf_counter() - t0
                    if text:
                        rec["tokens"] += 1
                if ev.get("done"):
                    rec["total"] = time.perf_counter() - t0
                    break
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "error"
        rec["err"] = f"{type(exc).__name__}: {str(exc)[:60]}"
    if rec["total"] is None:
        rec["total"] = time.perf_counter() - t0
    out.append(rec)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qps", type=float, default=5.0, help="arrival rate (query/giây)")
    ap.add_argument("--duration", type=float, default=30.0, help="giây bắn tải")
    ap.add_argument("--label", default="chat_bm0")
    args = ap.parse_args()

    async with httpx.AsyncClient(verify=not _INSECURE) as login_client:
        users = [u for u in await asyncio.gather(*(prelogin(login_client, i) for i in range(1, N_USERS + 1))) if u]
    if not users:
        print("[FATAL] không login được user nào (seed_users chưa chạy?)")
        return
    questions = _load_questions()
    print(f"[chat-bm0] {len(users)} user | {len(questions)} câu HR (đã verify retrieve) | "
          f"qps={args.qps} | duration={args.duration}s | in-flight kỳ vọng ≈ qps×latency")

    results: list = []
    tasks: list = []
    interval = 1.0 / args.qps
    inflight_samples: list[int] = []
    async with httpx.AsyncClient(verify=not _INSECURE,
                                 limits=httpx.Limits(max_connections=None, max_keepalive_connections=None)) as client:
        start = time.perf_counter()
        n = 0
        while time.perf_counter() - start < args.duration:
            user = users[n % len(users)]
            question = questions[n % len(questions)]
            tasks.append(asyncio.create_task(one_query(client, user, question, results)))
            n += 1
            cur_inflight = sum(1 for t in tasks if not t.done())
            inflight_samples.append(cur_inflight)
            await asyncio.sleep(interval)
        sent = n
        send_window = time.perf_counter() - start
        print(f"[chat-bm0] đã bắn {sent} query trong {round(send_window,1)}s, chờ drain...")
        await asyncio.gather(*tasks)
        total_window = time.perf_counter() - start

    ok = [r for r in results if r["status"] == "ok"]
    ttft = [r["ttft"] for r in ok if r["ttft"] is not None]
    total = [r["total"] for r in ok if r["total"] is not None]
    from collections import Counter
    status_counts = Counter(r["status"] for r in results)

    print(f"\n=== chat-bm0 [{args.label}] — open-loop {args.qps} QPS × {args.duration}s ===")
    print(f"sent={sent} | ok={len(ok)} | throughput đạt={round(len(ok)/total_window,2)} q/s "
          f"(mục tiêu {args.qps})")
    print(f"status: {dict(status_counts)}")
    print(f"PEAK in-flight={max(inflight_samples) if inflight_samples else 0} "
          f"(kỳ vọng ≈ {round(args.qps * (statistics.median(total) if total else 0),1)}; "
          f"phình lớn = hệ tụt lại)")
    print(f"TTFT(answer)  p50={_pct(ttft,50)} p95={_pct(ttft,95)} p99={_pct(ttft,99)} max={round(max(ttft),3) if ttft else 0}s")
    print(f"TOTAL latency p50={_pct(total,50)} p95={_pct(total,95)} p99={_pct(total,99)} max={round(max(total),3) if total else 0}s")


if __name__ == "__main__":
    asyncio.run(main())
