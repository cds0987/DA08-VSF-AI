"""Load-test 20 concurrent user — đo CHẤT LƯỢNG THẬT người dùng cảm nhận:

  • TTFT-thought : bao lâu thấy "đang suy nghĩ" (reasoning panel hiện)
  • TTFT-answer  : bao lâu token CÂU TRẢ LỜI đầu tiên xuất hiện (cái user chờ)
  • Độ đều token : khoảng cách giữa các token answer (gap p50/p95 + stall lớn nhất = giật/khựng)
  • Công bằng    : chênh lệch TTFT giữa các user (ai bị bỏ đói khi 1 event-loop gánh hết SSE?)
  • Degrade/lỗi  : 429 (rate/concurrent) · 502 (router) · save_mode (gpt-4o-mini) · stream đứt

Hybrid: N_BROWSERS trình duyệt Playwright THẬT (đo cadence wire-level qua Cloudflare + screenshot)
chạy SONG SONG với (N - N_BROWSERS) phiên SSE-HTTP nhẹ. TẤT CẢ bắn /query CÙNG LÚC (asyncio.Barrier).

Chạy:  python eval/load20/run_load20.py
(Cần đã seed user: python eval/load20/seed_users.py)
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import requests

from common import (BASE, N_BROWSERS, N_USERS, QUERY_API, QUESTIONS, USER_API,
                    USER_EMAIL, USER_PW, classify_event, now, parse_sse_line)

OUT = Path(__file__).parent / "out"
STREAM_TIMEOUT = 240
# Máy test sau proxy công ty (SSL MITM) -> python certifi fail verify (curl OK qua CA hệ thống).
# LOAD_INSECURE=1 bỏ verify để KẾT NỐI ĐƯỢC; client-side latency lúc này KHÔNG đáng tin (proxy buffer
# SSE) -> ĐO SERVER-SIDE (orchestrator_preplan_timing). Xem memory proxy-domain-blocks-sse.
_INSECURE = __import__("os").environ.get("LOAD_INSECURE") == "1"
if _INSECURE:
    import urllib3
    urllib3.disable_warnings()


# ───────────────────────── pre-login (ngoài vùng đo) ─────────────────────────
def prelogin(i: int) -> dict | None:
    """Login + lấy user_id cho user i. Làm TRƯỚC barrier để latency login không lẫn vào đo."""
    s = requests.Session()
    if _INSECURE:
        s.verify = False
    try:
        r = s.post(f"{USER_API}/auth/login",
                   json={"email": USER_EMAIL(i), "password": USER_PW}, timeout=30)
        if r.status_code != 200:
            print(f"  [login FAIL] {USER_EMAIL(i)}: HTTP {r.status_code}")
            return None
        token = r.json()["access_token"]
        me = s.get(f"{USER_API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        uid = me.json().get("id") or me.json().get("user_id")
        return {"idx": i, "email": USER_EMAIL(i), "token": token, "user_id": uid,
                "question": QUESTIONS[(i - 1) % len(QUESTIONS)]}
    except Exception as exc:
        print(f"  [login ERR] {USER_EMAIL(i)}: {exc}")
        return None


# ───────────────────────── SSE-HTTP user ─────────────────────────
async def sse_user(u: dict, barrier: asyncio.Barrier) -> dict:
    rec = _blank(u, "sse")
    # LOAD_FRESH_CONV=1 -> conversation_id MỚI mỗi query (uuid) -> load_context rỗng -> route HEAVY
    # (tránh memory pollution do test lặp khiến câu hỏi thành follow-up -> route light, không rag).
    import os as _os, uuid as _uuid
    _conv = str(_uuid.uuid4()) if _os.environ.get("LOAD_FRESH_CONV") == "1" else None
    body = {"user_id": u["user_id"], "question": u["question"],
            "conversation_id": _conv}
    h = {"Authorization": f"Bearer {u['token']}"}
    try:
        await barrier.wait()  # ── tất cả user bắn cùng lúc ──
    except Exception:
        pass
    t0 = now()
    rec["t_send"] = t0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(STREAM_TIMEOUT, connect=30),
                                     verify=not _INSECURE) as client:
            async with client.stream("POST", f"{QUERY_API}/query", json=body, headers=h) as r:
                rec["http_status"] = r.status_code
                if r.status_code != 200:
                    rec["error"] = f"HTTP {r.status_code}"
                    rec["status"] = _status_from_http(r.status_code)
                    return rec
                async for line in r.aiter_lines():
                    ev = parse_sse_line(line)
                    if ev is None:
                        continue
                    _consume(rec, ev, t0)
                    if rec["done"]:
                        break
        _finalize(rec, t0)
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["status"] = "error"
        _finalize(rec, t0)
    return rec


# ───────────────────────── Playwright browser user ─────────────────────────
async def browser_user(u: dict, barrier: asyncio.Barrier, pw) -> dict:
    """Trình duyệt THẬT: login UI -> CHỜ barrier -> gõ câu hỏi + Enter. CDP bắt
    Network.dataReceived = nhịp gói tới qua Cloudflare/nginx (bắt buffering proxy thật).
    SSE app-level không thấy buffering tầng proxy -> đây là tín hiệu UI-quality quan trọng."""
    rec = _blank(u, "browser")
    OUT.mkdir(parents=True, exist_ok=True)
    browser = await pw.chromium.launch(headless=True)
    try:
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        await cdp.send("Network.enable")

        state = {"qid": None, "t0": None, "events": []}  # (t_rel, bytes)

        def on_req(ev):
            url = ev.get("request", {}).get("url", "")
            if url.endswith("/api/query/query"):
                state["qid"] = ev["requestId"]
                state["t0"] = now()
        cdp.on("Network.requestWillBeSent", on_req)

        def on_data(ev):
            if ev.get("requestId") == state["qid"] and state["t0"]:
                state["events"].append((round(now() - state["t0"], 3), ev.get("dataLength", 0)))
        cdp.on("Network.dataReceived", on_data)

        # ── setup: login UI + sẵn sàng ô nhập (ngoài vùng đo) ──
        await page.goto(f"{BASE}/chat", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)
        if await page.query_selector('input[type="email"]'):
            await page.fill('input[type="email"]', u["email"])
            await page.fill('input[type="password"]', USER_PW)
            await page.click('button[type="submit"]')
            await page.wait_for_url("**/chat**", timeout=60000)
        ta = await page.wait_for_selector("textarea", timeout=30000)
        await ta.click()
        await ta.fill(u["question"])

        try:
            await barrier.wait()  # ── đồng loạt với mọi user ──
        except Exception:
            pass
        t0 = now()
        rec["t_send"] = t0
        await page.keyboard.press("Enter")

        # chờ stream xong: dataReceived ngừng > 8s hoặc hết deadline
        deadline = now() + STREAM_TIMEOUT
        last_n, idle = 0, 0
        while now() < deadline:
            await page.wait_for_timeout(1500)
            if len(state["events"]) == last_n:
                idle += 1
                if idle >= 6 and last_n > 0:
                    break
            else:
                idle = 0
            last_n = len(state["events"])

        evs = state["events"]
        if evs:
            rec["ttft_answer"] = evs[0][0]          # gói wire đầu (qua proxy) ~ token thấy được
            rec["n_answer_tokens"] = len(evs)
            gaps = [round(evs[k][0] - evs[k - 1][0], 3) for k in range(1, len(evs))]
            rec["answer_gaps"] = gaps
            rec["total_latency"] = evs[-1][0]
            rec["wire_bytes"] = sum(b for _, b in evs)
            rec["status"] = "ok"
        else:
            rec["status"] = "error"
            rec["error"] = "no data chunks"
        shot = OUT / f"browser_user{u['idx']:02d}.png"
        try:
            await page.screenshot(path=str(shot), full_page=True)
            rec["screenshot"] = shot.name
            rec["answer_text"] = (await page.inner_text("body"))[-1200:]
        except Exception:
            pass
    except Exception as exc:
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await browser.close()
    return rec


# ───────────────────────── helpers ─────────────────────────
def _blank(u: dict, kind: str) -> dict:
    return {"idx": u["idx"], "email": u["email"], "kind": kind, "question": u["question"],
            "status": "pending", "http_status": None, "error": None,
            "t_send": None, "ttft_thought": None, "ttft_answer": None,
            "n_answer_tokens": 0, "answer_gaps": [], "total_latency": None,
            "model_used": [], "sources": 0, "trace_id": None, "done": False,
            "_last_ans_t": None, "timeline": [], "_last_ev_t": 0.0}


def _consume(rec: dict, ev: dict, t0: float) -> None:
    kind, val = classify_event(ev)
    t = now() - t0
    # LIVENESS: ghi MỌI event có nhãn (t, kind, phase, node) + gap kể từ event trước
    # -> đo graph có "sống" liên tục không, im lặng ở chuyển stage nào.
    rec["timeline"].append({"t": round(t, 3), "kind": kind,
                            "phase": ev.get("phase"), "node": ev.get("node"),
                            "tool": ev.get("tool"), "gap": round(t - rec["_last_ev_t"], 3)})
    rec["_last_ev_t"] = t
    if kind == "thought" and rec["ttft_thought"] is None:
        rec["ttft_thought"] = round(t, 3)
    elif kind == "answer":
        if rec["ttft_answer"] is None:
            rec["ttft_answer"] = round(t, 3)
        else:
            rec["answer_gaps"].append(round(t - rec["_last_ans_t"], 3))
        rec["_last_ans_t"] = t
        rec["n_answer_tokens"] += 1
    elif kind == "model" and val:
        if val not in rec["model_used"]:
            rec["model_used"].append(val)
    elif kind == "done":
        rec["done"] = True
        rec["sources"] = len(ev.get("sources") or [])
        rec["trace_id"] = ev.get("trace_id")


def _finalize(rec: dict, t0: float) -> None:
    rec["total_latency"] = round(now() - t0, 3)
    if rec["status"] in ("pending",):
        rec["status"] = "ok" if rec["done"] and rec["n_answer_tokens"] > 0 else (
            "empty" if rec["done"] else "truncated")


def _status_from_http(code: int) -> str:
    return {429: "rate_limited", 503: "unavailable", 502: "router_error"}.get(code, f"http_{code}")


def _pct(xs: list[float], p: float):
    if not xs:
        return None
    xs = sorted(xs)
    k = min(len(xs) - 1, int(p / 100 * len(xs)))
    return round(xs[k], 3)


def _stats(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(min(xs), 3), "p50": _pct(xs, 50), "p90": _pct(xs, 90),
            "p95": _pct(xs, 95), "p99": _pct(xs, 99), "max": round(max(xs), 3),
            "mean": round(statistics.mean(xs), 3)}


# ───────────────────────── orchestrate ─────────────────────────
async def run(users: list[dict]) -> dict:
    n_browser = min(N_BROWSERS, len(users))
    barrier = asyncio.Barrier(len(users))
    started = datetime.now(timezone.utc)

    async def _spawn(pw) -> list:
        tasks = []
        for k, u in enumerate(users):
            if k < n_browser:
                tasks.append(asyncio.create_task(browser_user(u, barrier, pw)))
            else:
                tasks.append(asyncio.create_task(sse_user(u, barrier)))
        return await asyncio.gather(*tasks, return_exceptions=True)

    # Playwright (greenlet) CHỈ cần khi có browser-session -> N_BROWSERS=0 chạy thuần SSE-HTTP,
    # KHÔNG import playwright (máy thiếu VC++ runtime vẫn đo được).
    if n_browser > 0:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            results = await _spawn(pw)
    else:
        results = await _spawn(None)

    ended = datetime.now(timezone.utc)
    recs = []
    for r in results:
        if isinstance(r, Exception):
            recs.append({"status": "crash", "error": f"{type(r).__name__}: {r}",
                         "kind": "?", "answer_gaps": [], "model_used": []})
        else:
            recs.append(r)
    return {"window_start_utc": started.isoformat(), "window_end_utc": ended.isoformat(),
            "records": recs}


# ───────────────────────── report ─────────────────────────
def build_report(data: dict) -> str:
    recs = data["records"]
    ok = [r for r in recs if r.get("status") == "ok"]
    L = []
    L.append(f"# Load-test {len(recs)} concurrent user — {BASE}")
    L.append("")
    L.append(f"- Cửa sổ (UTC): `{data['window_start_utc']}` → `{data['window_end_utc']}`")
    L.append(f"  (dùng cho VM log: `--since`/`--until`)")
    L.append(f"- Thành công: **{len(ok)}/{len(recs)}**  ·  browser: "
             f"{sum(1 for r in recs if r.get('kind') == 'browser')}  ·  "
             f"sse: {sum(1 for r in recs if r.get('kind') == 'sse')}")
    L.append("")

    # phân loại status
    by_status: dict[str, int] = {}
    for r in recs:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
    L.append("## Kết cục mỗi user")
    L.append("| status | số user | nghĩa |")
    L.append("|---|---|---|")
    meaning = {"ok": "stream đủ + có answer", "rate_limited": "429 rate/concurrent",
               "router_error": "502 ai-router", "unavailable": "503", "truncated": "stream đứt giữa chừng",
               "empty": "done nhưng 0 token answer", "error": "exception client", "crash": "task chết"}
    for st, n in sorted(by_status.items(), key=lambda x: -x[1]):
        L.append(f"| {st} | {n} | {meaning.get(st, '')} |")
    L.append("")

    # degrade save_mode
    degraded = [r for r in ok if any("4o-mini" in str(m) or "save" in str(m).lower()
                                     for m in r.get("model_used", []))]
    L.append("## Chất lượng cảm nhận (chỉ tính user OK)")
    tt_ans = _stats([r["ttft_answer"] for r in ok if r.get("ttft_answer") is not None])
    tt_tho = _stats([r["ttft_thought"] for r in ok if r.get("ttft_thought") is not None])
    L.append("")
    L.append("**TTFT — answer (giây): thời gian tới TOKEN TRẢ LỜI đầu tiên** (cái user thật sự chờ)")
    L.append(_fmt_stat(tt_ans))
    L.append("")
    L.append("**TTFT — thought (giây): tới lúc thấy 'đang suy nghĩ'** (đỡ dead-air)")
    L.append(_fmt_stat(tt_tho))
    L.append("")

    # độ đều token
    all_gaps = [g for r in ok for g in r.get("answer_gaps", [])]
    gstat = _stats(all_gaps)
    max_stall = [round(max(r["answer_gaps"]), 2) for r in ok if r.get("answer_gaps")]
    L.append("**Độ đều token answer (giây giữa 2 token liên tiếp)** — gap lớn = giật/khựng")
    L.append(_fmt_stat(gstat))
    if max_stall:
        L.append(f"- Stall lớn nhất / user: p50={_pct(max_stall, 50)}s  p95={_pct(max_stall, 95)}s  "
                 f"max={max(max_stall)}s  (số user có stall>2s: "
                 f"{sum(1 for s in max_stall if s > 2)})")
    L.append("")

    # công bằng giữa user
    ttfts = [r["ttft_answer"] for r in ok if r.get("ttft_answer") is not None]
    if len(ttfts) >= 2:
        spread = round(max(ttfts) - min(ttfts), 2)
        cv = round(statistics.pstdev(ttfts) / statistics.mean(ttfts), 3) if statistics.mean(ttfts) else 0
        L.append(f"**Công bằng giữa user:** TTFT-answer chênh max−min = **{spread}s** · "
                 f"hệ số biến thiên CV = **{cv}** (càng nhỏ càng đều; >0.5 = có user bị bỏ đói)")
    L.append("")
    L.append(f"**Degrade save_mode (gpt-4o-mini):** {len(degraded)}/{len(ok)} user "
             f"{'⚠️ pool deepseek cạn dưới tải' if degraded else '— không có (pool đủ)'}")
    L.append("")

    # bảng per-user
    L.append("## Chi tiết từng user")
    L.append("| # | kind | status | TTFT-ans | TTFT-tho | #tok | gap p95 | maxstall | total | model | src |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(recs, key=lambda x: (x.get("idx", 999))):
        g95 = _pct(r.get("answer_gaps", []), 95)
        mstall = round(max(r["answer_gaps"]), 2) if r.get("answer_gaps") else None
        models = ",".join(str(m).split("/")[-1] for m in r.get("model_used", [])) or "-"
        L.append(f"| {r.get('idx','?')} | {r.get('kind','?')[:3]} | {r.get('status','?')} | "
                 f"{r.get('ttft_answer','-')} | {r.get('ttft_thought','-')} | {r.get('n_answer_tokens',0)} | "
                 f"{g95 if g95 is not None else '-'} | {mstall if mstall is not None else '-'} | "
                 f"{r.get('total_latency','-')} | {models} | {r.get('sources',0)} |")
    errs = [r for r in recs if r.get("error")]
    if errs:
        L.append("")
        L.append("## Lỗi")
        for r in errs:
            L.append(f"- user {r.get('idx','?')} ({r.get('kind','?')}): {r['error']}")
    return "\n".join(L)


def _ev_label(e: dict) -> str:
    base = e.get("phase") or e.get("kind") or "?"
    if e.get("node"):
        base += f"/{e['node']}"
    if e.get("tool"):
        base += f":{e['tool']}"
    return base


def build_liveness(data: dict, gap_thr: float = 2.0) -> str:
    """LIVENESS = graph có 'sống' liên tục không. User chịu chờ NẾU thấy hoạt động;
    kẻ thù là khoảng LẶNG (không event nào) khiến tưởng treo. Đo:
      • dead-air đầu  : tới event ĐẦU TIÊN (bao lâu màn hình trống hoàn toàn)
      • dead-air max  : khoảng lặng dài nhất giữa 2 event bất kỳ
      • % thời gian im : tổng gap>1s / tổng thời gian (bao nhiêu phần là chết)
      • mật độ hoạt động: % số giây có ≥1 event (heartbeat)
      • chỗ im lặng    : chuyển stage nào ôm khoảng lặng (prev→next)
    """
    recs = [r for r in data["records"] if r.get("timeline")]
    L = ["", "## LIVENESS — SSE có rải đều suốt graph không (cái user thật sự cần)", ""]
    if not recs:
        return "\n".join(L + ["(không có timeline — chạy với SSE user)"])

    first_air, max_gaps, silent_frac, density = [], [], [], []
    trans: dict[str, list[float]] = {}
    for r in recs:
        tl = r["timeline"]
        first_air.append(tl[0]["t"])               # dead-air đầu (gap event #0 = t - 0)
        gaps = [e["gap"] for e in tl]
        mg = max(gaps) if gaps else 0
        max_gaps.append(round(mg, 2))
        total = r.get("total_latency") or (tl[-1]["t"] if tl else 1)
        silent = sum(g for g in gaps if g > 1.0)
        silent_frac.append(round(100 * silent / total, 1) if total else 0)
        secs = {int(e["t"]) for e in tl}
        density.append(round(100 * len(secs) / max(1, int(total) + 1), 1))
        for i, e in enumerate(tl):
            if e["gap"] > gap_thr:
                prev = _ev_label(tl[i - 1]) if i > 0 else "START"
                trans.setdefault(f"{prev} → {_ev_label(e)}", []).append(round(e["gap"], 2))

    L.append(f"**Dead-air ĐẦU (tới event đầu tiên, s):** {_fmt_stat(_stats(first_air))}")
    L.append(f"- → màn hình TRỐNG HOÀN TOÀN trung vị {_pct(first_air,50)}s trước khi thấy bất kỳ dấu hiệu sống.")
    L.append("")
    L.append(f"**Dead-air MAX / user (khoảng lặng dài nhất, s):** {_fmt_stat(_stats(max_gaps))}")
    L.append(f"- số user có khoảng lặng >{gap_thr}s: {sum(1 for m in max_gaps if m > gap_thr)}/{len(recs)}"
             f"  ·  >5s: {sum(1 for m in max_gaps if m > 5)}/{len(recs)}")
    L.append("")
    L.append(f"**% thời gian IM LẶNG (gap>1s / tổng):** {_fmt_stat(_stats(silent_frac))}")
    L.append(f"**Mật độ hoạt động (% giây có ≥1 event):** {_fmt_stat(_stats(density))}")
    L.append(f"- mật độ cao = heartbeat đều (cảm giác sống); thấp = nhiều giây trống.")
    L.append("")
    L.append(f"### Khoảng lặng >{gap_thr}s nằm ở CHUYỂN STAGE nào (prev → next)")
    L.append("| chuyển tiếp | số lần | gap trung vị | gap max |")
    L.append("|---|---|---|---|")
    for k, v in sorted(trans.items(), key=lambda x: -sum(x[1])):
        L.append(f"| {k} | {len(v)} | {round(statistics.median(v),2)}s | {max(v)}s |")
    L.append("")
    # 1 timeline mẫu (user có dead-air max lớn nhất) để thấy hình dạng
    worst = max(recs, key=lambda r: max((e["gap"] for e in r["timeline"]), default=0))
    L.append(f"### Timeline mẫu — user {worst['idx']} (dead-air xấu nhất)")
    L.append("```")
    for e in worst["timeline"]:
        mark = "  <<< IM" if e["gap"] > gap_thr else ""
        if e["kind"] == "answer" and e["gap"] <= gap_thr:
            continue  # gọn: bỏ token answer chảy đều, chỉ giữ mốc stage + chỗ im
        L.append(f"  t={e['t']:7.2f}s  gap={e['gap']:6.2f}s  {_ev_label(e)}{mark}")
    L.append("```")
    return "\n".join(L)


def _fmt_stat(s: dict) -> str:
    if not s.get("n"):
        return "- (không có dữ liệu)"
    return (f"- n={s['n']}  min={s['min']}  **p50={s['p50']}**  p90={s['p90']}  "
            f"**p95={s['p95']}**  p99={s['p99']}  max={s['max']}  mean={s['mean']}")


# ───────────────────────── main ─────────────────────────
def main() -> int:
    print(f"[1/3] Pre-login {N_USERS} user...")
    users = []
    for i in range(1, N_USERS + 1):
        u = prelogin(i)
        if u:
            users.append(u)
    print(f"      login OK: {len(users)}/{N_USERS}")
    if len(users) < 2:
        print("[FATAL] không đủ user đăng nhập — chạy seed_users.py trước.")
        return 1

    print(f"[2/3] Bắn {len(users)} /query ĐỒNG THỜI ({min(N_BROWSERS,len(users))} browser thật)...")
    data = asyncio.run(run(users))

    print("[3/3] Tổng hợp report...")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = OUT / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = build_report(data) + "\n" + build_liveness(data)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    # move screenshots vào run_dir
    for png in OUT.glob("browser_user*.png"):
        try:
            png.rename(run_dir / png.name)
        except Exception:
            pass
    print("\n" + report)
    print(f"\nĐã lưu: {run_dir}")
    print(f"\n>>> Đối chiếu VM log (read-only):")
    print(f"    bash eval/load20/pull_vm_logs.sh '{data['window_start_utc']}' '{data['window_end_utc']}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
