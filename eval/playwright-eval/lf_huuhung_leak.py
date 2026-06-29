# -*- coding: utf-8 -*-
"""Soi trace huuhung@gmail.com trên Langfuse -> tìm BUG leak: raw [rag_retrieve]{results} dump +
<NEED_MORE> token lọt vào answer. Login 2 lớp (nginx basic + Langfuse form). Mở từng trace, expand
generation (answer/synth/verify), bắt OUTPUT + MODEL + node nào leak."""
import re
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://langfuse.vsfchat.cloud"
BASIC = {"username": "team", "password": "2EG4sxyGBGybDVVZ"}
LF_EMAIL = "admin@company.com"
LF_PW = "e00015033a465bf1933b6e120b527d1f7198"
TARGET = "huuhung@gmail.com"
LEAK_MARKERS = ["[rag_retrieve]", '"results"', "parent_text", "<NEED_MORE>", "document_name", "caption"]
OUT = Path(__file__).parent / "out_langfuse"
OUT.mkdir(parents=True, exist_ok=True)


def login(pg):
    pg.goto(f"{BASE}/auth/sign-in", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector("input", timeout=30000); time.sleep(1)
    pg.locator('input[name="email"]').first.fill(LF_EMAIL)
    pg.locator('input[name="password"]').first.fill(LF_PW); time.sleep(0.3)
    pg.get_by_role("button", name="Sign in", exact=True).click()
    pg.wait_for_url("**/", timeout=30000); time.sleep(3)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 1400}, http_credentials=BASIC)
        pg = ctx.new_page()
        login(pg)
        proj = "rag-chatbot"
        m = re.search(r"/project/([^/?#]+)", pg.url)
        if m:
            proj = m.group(1)
        print("project =", proj)

        pg.goto(f"{BASE}/project/{proj}/traces", wait_until="networkidle", timeout=60000)
        time.sleep(4)
        # search/filter theo user huuhung
        try:
            sb = pg.get_by_placeholder(re.compile("Search", re.I)).first
            sb.click(); sb.fill(TARGET); sb.press("Enter"); time.sleep(4)
        except Exception as e:
            print("search fail:", str(e)[:60])
        pg.screenshot(path=str(OUT / "00_huuhung_list.png"))

        hrefs = pg.eval_on_selector_all('a[href*="/traces/"]', "els=>els.map(e=>e.getAttribute('href'))")
        ids = []
        for h in hrefs:
            mm = re.search(r"/traces/([0-9a-f\-]{20,})", h or "")
            if mm and mm.group(1) not in ids:
                ids.append(mm.group(1))
        print(f"huuhung traces (trang đầu): {len(ids)}")

        rows = []
        for tid in ids[:10]:
            pg.goto(f"{BASE}/project/{proj}/traces/{tid}", wait_until="domcontentloaded", timeout=60000)
            body = ""
            for _ in range(12):
                time.sleep(1.2); body = pg.inner_text("body")
                if len(body) > 800 and "loading" not in body.lower()[:200]:
                    break
            user = (re.search(r"User ID:?\s*(\S+)", body) or [None, ""])[1] if "User" in body else ""
            # expand các generation node để output lộ ra body
            for node in ["answer", "synth", "verify", "verify_answer", "rag_retrieve", "orchestrator"]:
                try:
                    loc = pg.get_by_text(node, exact=True)
                    if loc.count():
                        loc.first.click(); time.sleep(0.8)
                except Exception:
                    pass
            time.sleep(1.5)
            body = pg.inner_text("body")
            # models xuất hiện trong trace
            models = sorted(set(re.findall(r"(deepseek[\w\-./]*|qwen[\w\-./]*|llama[\w\-./]*|glm[\w\-./]*|hy3[\w\-./]*|gpt[\w\-.]*|xiaomi[\w\-./]*)", body)))
            hits = {mk: (mk in body) for mk in LEAK_MARKERS}
            leak = any(hits.values())
            rows.append({"tid": tid, "user": user, "leak": leak, "markers": [k for k, v in hits.items() if v], "models": models})
            tag = "🔴LEAK" if leak else "✅"
            print(f"{tag} {tid[:8]} | {user[:25]} | markers={[k for k,v in hits.items() if v]} | models={models}")
            if leak:
                pg.screenshot(path=str(OUT / f"leak_{tid[:8]}.png"), full_page=True)
                # lưu 1 đoạn body quanh marker đầu tiên để xem raw
                for mk in LEAK_MARKERS:
                    i = body.find(mk)
                    if i >= 0:
                        (OUT / f"leak_{tid[:8]}_{mk.strip('[]<>\"')[:8]}.txt").write_text(body[max(0, i-300):i+800], encoding="utf-8")
                        break
        (OUT / "huuhung_leak.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        leaks = [r for r in rows if r["leak"]]
        print(f"\n=> {len(leaks)}/{len(rows)} trace LEAK. Models dính: {sorted(set(m for r in leaks for m in r['models']))}")
        b.close()


if __name__ == "__main__":
    main()
