"""Chụp dashboard ai-router trên Grafana (nginx basic auth + anonymous view).
Cuộn qua từng section, screenshot. Chạy KHI đang có tải để panel có số (nhất là inflight)."""
import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://grafana.vsfchat.cloud"
BASIC = {"username": "team", "password": "2EG4sxyGBGybDVVZ"}
DASH = f"{BASE}/d/ai-router-main/ai-router-key-model-ops?orgId=1&from=now-30m&to=now&refresh=10s"
OUT = Path(__file__).parent / "out" / "grafana"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    w = int(os.environ.get("CAPTURE_WAIT", "0"))
    if w:
        print(f"chờ {w}s cho tải vào pha streaming..."); time.sleep(w)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 1200}, http_credentials=BASIC,
                            device_scale_factor=1.5)
        pg = ctx.new_page()
        pg.goto(DASH, wait_until="networkidle", timeout=90000)
        time.sleep(9)  # chờ panel query xong
        # Grafana dùng scroll container riêng -> cuộn bằng mouse.wheel (hover giữa dashboard).
        pg.mouse.move(800, 600)
        shots = []
        for idx in range(1, 9):                 # ~8 bước phủ hết 6 section
            sp = OUT / f"dash_{idx:02d}.png"
            pg.screenshot(path=str(sp)); shots.append(sp.name)
            pg.mouse.wheel(0, 780); time.sleep(2.2)
        print(f"đã chụp {len(shots)} ảnh -> {OUT}")
        for s in shots:
            print("  ", s)
        b.close()


if __name__ == "__main__":
    main()
