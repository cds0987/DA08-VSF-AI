"""Ramp 20→30→40→50 concurrent — TRỌNG TÂM: TTFT-plan (dấu hiệu sống ĐẦU TIÊN).

Khoảng lặng nguy hiểm nhất = lúc ĐẦU: màn hình trống hoàn toàn trước khi plan phun token đầu.
User chịu chờ NẾU thấy hệ thống chạy — nhưng dead-air đầu mà tăng theo tải thì hỏng trải nghiệm.
Đo TTFT-plan (= timeline[0].t, dấu hiệu sống đầu) + dead-air max ở mỗi mốc.

Toàn SSE (nhãn phase/node, nhẹ -> chịu được 50). Pre-login 1 LẦN, tái dùng token qua các mốc.
Mỗi mốc cách nhau để né per-IP 60/min. Ghi kết quả tăng dần -> ramp_<ts>.json.

Chạy:  LOAD_N_BROWSERS=0 python eval/load20/ramp.py
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from common import N_USERS
from run_load20 import OUT, _pct, _stats, prelogin, run

LEVELS = [int(x) for x in __import__("os").environ.get("LOAD_LEVELS", "20,30,40,50").split(",")]
GAP_THR = 2.0


def _level_metrics(data: dict) -> dict:
    recs = data["records"]
    ok = [r for r in recs if r.get("status") == "ok" and r.get("timeline")]
    first_sign = [r["timeline"][0]["t"] for r in ok]              # TTFT-plan (dấu hiệu sống đầu)
    ttft_ans = [r["ttft_answer"] for r in ok if r.get("ttft_answer") is not None]
    max_gaps = [round(max(e["gap"] for e in r["timeline"]), 2) for r in ok]
    # đếm kết cục
    status: dict[str, int] = {}
    for r in recs:
        status[r.get("status", "?")] = status.get(r.get("status", "?"), 0) + 1
    return {
        "n": len(recs), "n_ok": len(ok), "status": status,
        "window_start_utc": data["window_start_utc"], "window_end_utc": data["window_end_utc"],
        "ttft_plan": _stats(first_sign),          # ← chỉ số CHÍNH
        "ttft_answer": _stats(ttft_ans),
        "deadair_max": _stats(max_gaps),
        "deadair_gt5": sum(1 for m in max_gaps if m > 5),
    }


def main() -> int:
    maxn = max(LEVELS)
    print(f"[*] Pre-login {maxn} user (1 lần, tái dùng)...")
    users = []
    for i in range(1, maxn + 1):
        u = prelogin(i)
        if u:
            users.append(u)
    print(f"    login OK: {len(users)}/{maxn}")
    if len(users) < min(LEVELS):
        print("[FATAL] không đủ user — chạy seed_users.py (LOAD_N_USERS=50).")
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    res_path = OUT / f"ramp_{ts}.json"
    results = []
    for lvl in LEVELS:
        if len(users) < lvl:
            print(f"[skip] mốc {lvl}: chỉ có {len(users)} user")
            continue
        sub = users[:lvl]
        print(f"\n[*] === MỐC {lvl} concurrent — bắn đồng loạt ===")
        data = asyncio.run(run(sub))
        m = _level_metrics(data)
        m["level"] = lvl
        results.append(m)
        tp, da = m["ttft_plan"], m["deadair_max"]
        print(f"    OK {m['n_ok']}/{m['n']} · TTFT-plan p50={tp.get('p50')}s p95={tp.get('p95')}s "
              f"max={tp.get('max')}s · dead-air max p95={da.get('p95')}s · status={m['status']}")
        res_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if lvl != LEVELS[-1]:
            time.sleep(25)  # né per-IP 60/min giữa các mốc

    # bảng so sánh
    print("\n" + "=" * 78)
    print("RAMP — TTFT-plan (dấu hiệu sống đầu) theo tải concurrent")
    print("=" * 78)
    print(f"{'lvl':>4} {'ok':>6} {'TTFTplan p50':>13} {'p95':>7} {'max':>7} "
          f"{'TTFTans p50':>12} {'deadairMax p95':>15} {'>5s':>4}")
    for m in results:
        tp, ta, da = m["ttft_plan"], m["ttft_answer"], m["deadair_max"]
        print(f"{m['level']:>4} {m['n_ok']}/{m['n']:<4} {tp.get('p50','-'):>13} {tp.get('p95','-'):>7} "
              f"{tp.get('max','-'):>7} {ta.get('p50','-'):>12} {da.get('p95','-'):>15} {m['deadair_gt5']:>4}")
    md = _markdown(results)
    (OUT / f"ramp_{ts}.md").write_text(md, encoding="utf-8")
    print(f"\nĐã lưu: {res_path}  +  ramp_{ts}.md")
    print("\nWindows (để pull VM log mốc 50):")
    if results:
        last = results[-1]
        print(f"  bash eval/load20/pull_vm_logs.sh '{last['window_start_utc']}' '{last['window_end_utc']}'")
    return 0


def _markdown(results: list) -> str:
    L = ["# Ramp 20→50 concurrent — TTFT-plan (dấu hiệu sống đầu)", "",
         "TTFT-plan = thời gian màn hình TRỐNG trước event đầu tiên (plan/thinking). Chỉ số quan trọng",
         "nhất: bước đầu, user chưa thấy gì. Nếu nó phình theo tải ⇒ trải nghiệm hỏng dù answer vẫn ra.", "",
         "| concurrent | OK | TTFT-plan p50 | p95 | max | TTFT-ans p50 | dead-air max p95 | #user >5s | kết cục |",
         "|---|---|---|---|---|---|---|---|---|"]
    for m in results:
        tp, ta, da = m["ttft_plan"], m["ttft_answer"], m["deadair_max"]
        st = ", ".join(f"{k}={v}" for k, v in m["status"].items())
        L.append(f"| {m['level']} | {m['n_ok']}/{m['n']} | **{tp.get('p50','-')}s** | {tp.get('p95','-')}s | "
                 f"{tp.get('max','-')}s | {ta.get('p50','-')}s | {da.get('p95','-')}s | {m['deadair_gt5']} | {st} |")
    L += ["", "## Đọc",
          "- **TTFT-plan p95 tăng mạnh theo tải** ⇒ bước plan bị xếp hàng (deepseek/OpenRouter mở stream "
          "chậm khi đông) → cần plan model nhanh hơn / off-OR, hoặc phát 'đang xử lý' tức thì (t<1s) để chặn dead-air đầu.",
          "- **dead-air max p95 >5s** ⇒ còn khoảng lặng giữa stage (sau rag_search) cần filler.",
          "- Nếu OK < n ở mốc cao ⇒ bắt đầu 429/save_mode → đối chiếu VM log."]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
