"""Harvest timing per-trace từ Langfuse (loadtest users) -> khoanh dead-air.

Mỗi trace: tổng latency + per-generation (plan/worker/answer) TTFT + latency. So với client
TTFT (8-16s) để thấy bao nhiêu nằm NGOÀI trace (pre-plan/graph/proxy) vs trong planner.

Login 2 lớp: nginx basic auth (http_credentials) + Langfuse form. Creds user cung cấp.
"""
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://langfuse.vsfchat.cloud"
BASIC = {"username": "team", "password": "2EG4sxyGBGybDVVZ"}
LF_EMAIL = "admin@company.com"
LF_PW = "e00015033a465bf1933b6e120b527d1f7198"
OUT = Path(__file__).parent / "out" / "langfuse"
OUT.mkdir(parents=True, exist_ok=True)


def login(pg):
    pg.goto(f"{BASE}/auth/sign-in", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector("input", timeout=30000)
    time.sleep(1)
    pg.locator('input[name="email"]').first.fill(LF_EMAIL)
    pg.locator('input[name="password"]').first.fill(LF_PW)
    time.sleep(0.3)
    pg.get_by_role("button", name="Sign in", exact=True).click()
    pg.wait_for_url("**/", timeout=30000)
    time.sleep(3)


def discover_project(pg) -> str | None:
    pg.goto(BASE, wait_until="networkidle", timeout=60000)
    time.sleep(3)
    m = re.search(r"/project/([^/?#]+)", pg.url)
    if m:
        return m.group(1)
    # thử click vào project đầu nếu landing ở org
    href = pg.eval_on_selector_all(
        'a[href*="/project/"]',
        "els=>els.map(e=>e.getAttribute('href'))[0] || ''",
    )
    m = re.search(r"/project/([^/?#]+)", href or "")
    return m.group(1) if m else None


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 1200}, http_credentials=BASIC)
        pg = ctx.new_page()
        login(pg)
        proj = discover_project(pg)
        print("project_id =", proj, "| url =", pg.url)
        if not proj:
            pg.screenshot(path=str(OUT / "00_no_project.png"))
            print("KHÔNG tìm thấy project id — xem screenshot")
            b.close()
            return

        # traces list mới nhất (mặc định sort theo time desc)
        pg.goto(f"{BASE}/project/{proj}/traces", wait_until="networkidle", timeout=60000)
        time.sleep(5)
        pg.screenshot(path=str(OUT / "01_traces_list.png"))
        hrefs = pg.eval_on_selector_all(
            'a[href*="/traces/"]', "els=>els.map(e=>e.getAttribute('href'))"
        )
        ids = []
        for h in hrefs:
            m = re.search(r"/traces/([0-9a-f\-]{20,})", h or "")
            if m and m.group(1) not in ids:
                ids.append(m.group(1))
        print(f"traces tìm thấy (trang đầu): {len(ids)}")

        rows = []
        for tid in ids[:12]:
            pg.goto(f"{BASE}/project/{proj}/traces/{tid}",
                    wait_until="domcontentloaded", timeout=60000)
            body = ""
            for _ in range(12):
                time.sleep(1.2)
                body = pg.inner_text("body")
                if len(body) > 800 and "loading" not in body.lower()[:200]:
                    break
            # chỉ quan tâm trace của loadtest user
            user = ""
            mu = re.search(r"User ID:\s*(\S+)", body)
            if mu:
                user = mu.group(1)
            if "loadtest" not in user:
                continue
            # tổng latency trace + các badge TTFT/Latency của generation hiện
            ttfts = re.findall(r"Time to first token:\s*([\d.]+)s", body)
            lats = re.findall(r"Latency:\s*([\d.]+)s", body)
            # các node generation trong cây (tên + latency) — click từng node lấy badge
            node_info = []
            for node in ["preplan.get_context", "preplan.load_context",
                         "preplan.save_user_message", "preplan.get_allowed_doc_ids",
                         "plan", "rag_retrieve", "verify", "answer"]:
                try:
                    loc = pg.get_by_text(node, exact=True)
                    if loc.count() == 0:
                        continue
                    loc.first.click()
                    time.sleep(1.0)
                    nb = pg.inner_text("body")
                    t = re.search(r"Time to first token:\s*([\d.]+)s", nb)
                    l = re.search(r"Latency:\s*([\d.]+)s", nb)
                    node_info.append((node, t.group(1) if t else "-", l.group(1) if l else "-"))
                except Exception:
                    pass
            ts = ""
            mts = re.search(r"(\d{1,2}/\d{1,2}/\d{4},\s*[\d:]+\s*[AP]M)", body)
            if mts:
                ts = mts.group(1)
            rows.append({"tid": tid, "user": user, "ts": ts,
                         "trace_ttft": ttfts[:1], "trace_lat": lats[:1], "nodes": node_info})
            print(f"\n{tid[:8]} | {user} | {ts}")
            print(f"   trace TTFT={ttfts[:1]} Latency={lats[:1]}")
            for n in node_info:
                print(f"   node {n[0]:14s} TTFT={n[1]}s Latency={n[2]}s")
            pg.screenshot(path=str(OUT / f"trace_{tid[:8]}.png"))

        import json
        (OUT / "trace_timing.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã lưu {len(rows)} trace loadtest -> {OUT/'trace_timing.json'}")
        b.close()


if __name__ == "__main__":
    main()
