# -*- coding: utf-8 -*-
"""Parse micro-benchmark: tách sàn SYNC của reader PDF (PyMuPDF) khỏi OCR network.

PyMuPDF là thư viện C SYNC; reader rasterize từng trang tuần tự trong 1 thread executor
TRƯỚC khi OCR async chạy. Script đo: get_text + get_pixmap(rasterize)/trang -> biết
rasterize có phải sàn p99 không (nếu rasterize << OCR ~20s/trang thì //hoá OCR là đòn
bẩy đúng; nếu rasterize lớn thì phải //hoá reader = mở nhiều fitz.Document/thread).

Chạy TRONG container (fitz có sẵn):
  python parse_microbench.py /app/eval/validation/fire_evacuation_scanned.pdf ...
"""
import sys, time, statistics as st
import fitz  # PyMuPDF (chỉ có trong container rag-worker)

SCALE = float(sys.argv[1]) if sys.argv[1:] and sys.argv[1].replace(".", "").isdigit() else 2.0
paths = [a for a in sys.argv[1:] if not a.replace(".", "").isdigit()]

print(f"PyMuPDF {fitz.VersionBind} | rasterize scale={SCALE}")
for path in paths:
    doc = fitz.open(path)
    n = doc.page_count
    text_ms, rast_ms, png_kb = [], [], []
    t0 = time.perf_counter()
    for page in doc:
        a = time.perf_counter(); _ = page.get_text("text"); b = time.perf_counter()
        pm = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), alpha=False)
        data = pm.tobytes("png"); c = time.perf_counter()
        text_ms.append((b - a) * 1000); rast_ms.append((c - b) * 1000); png_kb.append(len(data) / 1024)
    total = (time.perf_counter() - t0) * 1000
    name = path.split("/")[-1]
    print(f"\n{name}: pages={n}")
    print(f"  SYNC reader total = {total:.0f} ms  ({total/n:.0f} ms/trang)")
    print(f"  text_extract/trang = {st.mean(text_ms):.1f} ms")
    print(f"  rasterize/trang    = {st.mean(rast_ms):.0f} ms (max {max(rast_ms):.0f}, png ~{st.mean(png_kb):.0f}KB)")
    # Phân rã so OCR ~20s/trang (đo prod): sàn sync vs trần OCR
    ocr_seq = n * 20000
    ocr_par = -(-n // 6) * 20000  # ceil(n/6)*20s, OCR_MAX_CONCURRENCY=6
    print(f"  => ước tính: SYNC sàn={total:.0f}ms | OCR tuần tự≈{ocr_seq/1000:.0f}s | OCR //6≈{ocr_par/1000:.0f}s")
    print(f"     -> rasterize chiếm {total/(total+ocr_seq)*100:.1f}% thời gian (nếu nhỏ: //OCR là đòn bẩy đúng)")
