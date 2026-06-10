"""Tự lái UI (Playwright) review toàn bộ tính năng + full RAG flow, bắt lỗi thay F12.
Chạy: python tmp-ui-check/ui_check.py
"""
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://34.158.47.236"
EMAIL = "admin@company.com"
PASSWORD = "***REDACTED-SEED-ADMIN-PW***"
UPLOAD_FILE = str(Path("src/rag-worker/eval/validation/leave_policy.md").resolve())
OUT = Path("tmp-ui-check")
OUT.mkdir(exist_ok=True)

# Lỗi gắn theo trang đang xem.
cur = {"page": "init"}
console_err = []   # (page, text)
page_err = []      # (page, text)
net_err = []       # (page, status, url)
IGNORE = ("favicon.ico", "/_nuxt/", ".css", ".js.map", ".woff")


def report_line(s=""):
    print(s)
    with open(OUT / "report.txt", "a", encoding="utf-8") as f:
        f.write(s + "\n")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, ignore_https_errors=True)
        page = ctx.new_page()
        page.on("console", lambda m: console_err.append((cur["page"], m.text)) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_err.append((cur["page"], str(e))))
        page.on("response", lambda r: net_err.append((cur["page"], r.status, r.url))
                 if r.status >= 400 and not any(x in r.url for x in IGNORE) else None)

        def goto(name, path, wait=2000):
            cur["page"] = name
            print(f"[VISIT] {name}: {path}")
            try:
                page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=45000)
            except Exception as e:
                print("   nav warn:", e)
            page.wait_for_timeout(wait)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

        # ---------- ADMIN ----------
        goto("admin-login", "/admin/login")
        cur["page"] = "admin-login"
        page.fill("input[type='email'], input[name='email'], input[placeholder*='@']", EMAIL)
        page.fill("input[type='password']", PASSWORD)
        page.click("button:has-text('Login'), button[type='submit']")
        page.wait_for_timeout(4000)
        print("   url sau login:", page.url)
        page.screenshot(path=str(OUT / "admin-after-login.png"), full_page=True)

        for name, path in [("admin-dashboard", "/admin/"), ("admin-documents", "/admin/documents"),
                           ("admin-audit", "/admin/audit"), ("admin-users", "/admin/users"),
                           ("admin-upload", "/admin/upload")]:
            goto(name, path)

        # Upload flow trên /admin/upload (đang ở đó)
        cur["page"] = "admin-upload-flow"
        finputs = page.locator("input[type='file']")
        if finputs.count():
            finputs.first.set_input_files(UPLOAD_FILE)
            page.wait_for_timeout(1500)
            for sel in ["button:has-text('Upload All')", "button:has-text('Upload')", "button[type='submit']"]:
                b = page.locator(sel)
                if b.count() and b.first.is_enabled():
                    b.first.click(); break
            page.wait_for_timeout(6000)
            page.screenshot(path=str(OUT / "admin-upload-done.png"), full_page=True)
            body = page.inner_text("body")
            print("   upload có 'indexed'? ", "indexed" in body.lower())

        # ---------- CHAT (full RAG flow) ----------
        goto("chat-login", "/login")
        cur["page"] = "chat-login"
        try:
            page.fill("input[type='email'], input[name='email'], input[placeholder*='@']", EMAIL)
            page.fill("input[type='password']", PASSWORD)
            page.click("button:has-text('Login'), button[type='submit']")
            page.wait_for_timeout(4000)
            print("   url sau login chat:", page.url)
        except Exception as e:
            print("   chat login warn:", e)
        page.screenshot(path=str(OUT / "chat-after-login.png"), full_page=True)

        cur["page"] = "chat-query"
        q = "Nhân viên được bao nhiêu ngày phép năm?"
        try:
            box = page.locator("textarea, input[type='text']").last
            box.click()
            box.fill(q)
            page.wait_for_timeout(500)
            # gửi: Enter hoặc nút send
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            for sel in ["button:has-text('Send')", "button[type='submit']", "button[aria-label*='send' i]"]:
                b = page.locator(sel)
                if b.count() and b.first.is_enabled():
                    b.first.click(); break
            print("   chờ trả lời RAG...")
            page.wait_for_timeout(12000)
        except Exception as e:
            print("   chat query warn:", e)
        page.screenshot(path=str(OUT / "chat-answer.png"), full_page=True)

        browser.close()


if __name__ == "__main__":
    open(OUT / "report.txt", "w", encoding="utf-8").close()
    try:
        run()
    except Exception as e:
        report_line(f"SCRIPT ERROR: {type(e).__name__} {e}")
    report_line("\n========== BÁO CÁO LỖI THEO TRANG ==========")
    report_line(f"PAGE ERRORS (uncaught JS): {len(page_err)}")
    for pg, e in page_err:
        report_line(f"  ✗ [{pg}] {e[:200]}")
    report_line(f"CONSOLE ERRORS: {len(console_err)}")
    for pg, e in console_err:
        report_line(f"  ✗ [{pg}] {e[:200]}")
    report_line(f"NETWORK >=400 (bỏ asset): {len(net_err)}")
    for pg, st, url in net_err:
        report_line(f"  ! [{pg}] {st} {url}")
    report_line(f"\nScreenshots + report -> {OUT.resolve()}")
