# Combined Load Test — vừa CHAT vừa UPLOAD (2026-06-29)

> Câu hỏi: hệ thống (800 nhân sự) chịu được tải **chat đồng thời với upload tài liệu** thế nào?
> Phương pháp: bắn `run_load.py` (chat) + `run_ingest_load.py` (upload) **ĐỒNG THỜI** lên prod
> `vsfchat.cloud`, đo qua ai-router log + Grafana. Dataset chat = `labels_combined200` (150 nhẹ + 50
> nặng multi-agent). Docs upload = **PDF/DOCX/DOC THẬT** (82 doc HR từ `systemeval/data`).

---

## 1. Kết quả ĐO THẬT — 100 doc/phút (PDF/DOCX) + chat 3.3 req/s · coalescer OFF

| Metric | Giá trị |
|---|---|
| Chat | **200/200 trả lời, 0 hard-fail** (165 SUCCESS / 18 off-topic / 9 no-info / 8 clarify) |
| **Chat TTFT p95** (UX thật) | **5.45s** ✅ — user thấy câu trả lời bắt đầu trong ~5s |
| Ingest | **98/100 indexed, 2 fail** (chunk 11–152/doc) |
| Upstream embed-call | 273 |
| **embed-502** | **7** (transient, hồi được) |
| OCR-call | **554/90s** 🔥 (real PDF nhiều ảnh) |
| Window drain | 279s (~4.6 phút) |

### ⚠️ Bài học #1: đo đúng METRIC
- "Chat p95 53.6s / max 218s" (end-to-end total, đo client open-loop) = **SAI metric** — gồm queue-wait
  lúc bắn + stream HẾT câu. **Không phải cái user cảm nhận.**
- **TTFT (time-to-first-token) p95 = 5.45s** mới đúng UX → **chat responsive, ổn**.
- Dashboard "Latency p95 (call) 1.80 mins" (đỏ) = ai-router CALL latency **GỘP MỌI capability** (bị
  ingest embed 18s + OCR 25s kéo lên), **KHÔNG phải chat**.

### ⚠️ Bài học #2: data THẬT lộ stress mà synthetic .md GIẤU
| | synthetic .md | **real PDF/DOCX** |
|---|---|---|
| OCR | 0 | **554/90s** |
| embed-502 | 0–1 | **7** |
| ingest fail | 0 | 2 |
| Window | 156s | 279s |
→ .md (text thuần, 0 OCR) đánh giá SAI là "pool nhàn". Real docs (OCR-nặng) mới ra tải thật. **Luôn
test bằng PDF/DOCX thật, không .md.**

---

## 2. Coalescer embed batcher — A/B (synthetic .md, cùng tải chat 200@3.3 + 100 doc)

Demand-driven coalescing `/v1/embeddings` ở ai-router (gom request embed theo queue-depth → 1 upstream
call → tách trả đúng caller). Opt-in `EMBED_COALESCE_ENABLED` (default OFF).

| | OFF | ON | |
|---|---|---|---|
| Upstream embed-call | 247 | **163** | **−34%** |
| 502 | 0 | 1 | ~ngang |
| Chat / Ingest | OK | OK | không degrade |

→ Coalescer **gom call thật (−34%), không trả nhầm vector** (7 unit-test split/mapping). Lợi ngay cả ở
8-worker (gom per-worker, pha loãng 8×).

---

## 3. Ước tính peak THỰC TẾ 800 nhân sự (chat 3-5 req/s + **30-40 doc/phút**)

100 doc/phút liền là **phi thực tế** (upload thưa + chỉ admin/role upload được). Mức đẹp peak ≈
**30-40 doc/phút**. Scale từ điểm đo 100/phút (≈⅓ tải ingest):

| Metric | Đo @100/phút | **Ước tính @40/phút** |
|---|---|---|
| OCR-call | 554/90s | ~220/90s (pool 4 model nhàn) |
| embed-502 | 7 | **~0-2** (pool xa bão hòa) |
| Ingest fail | 2 | **~0-1** |
| Chat TTFT p95 | 5.45s | **~5s, không đổi** |

**Lý do an toàn:** 502 KHÔNG tuyến tính (bùng khi pool bão hòa); ở ⅓ tải → xa ngưỡng. Chat-intent là
call lẻ nhẹ, ingest 40/phút không chèn đáng kể. **Đã đo ở 3× mức peak (100/phút) chỉ stress nhẹ.**

---

## 4. VERDICT

✅ **Hệ THỪA SỨC lo peak 800 nhân sự** (3-5 req/s chat + 30-40 doc/phút upload):
- Chat **TTFT ~5s, responsive**, không degrade.
- Ingest ~0-1 fail, embed-502 ~0-2 transient (không ảnh hưởng UX).
- Biên an toàn lớn (đo ở 3× peak vẫn không sập).

**Coalescer:** chưa cần bật ở 40/phút (502 ~0-2). Bật khi upload dồn **> 80-100 doc/phút** (lúc đó 502
mới đáng kể như đã đo). Config: `EMBED_COALESCE_ENABLED=1`, `EMBED_COALESCE_WINDOW_MS=15-20`,
`EMBED_COALESCE_MAX_BATCH=256`.

---

## 5. Bug + việc cần làm (phát hiện trong test)

1. **✅ ĐÃ FIX — Orphan Qdrant/GCS khi xóa doc** (commit `1465b201`, deployed 2026-06-29): delete API
   từng KHÔNG cascade sang Qdrant + GCS-artifact → orphan (khảo sát prod thấy **1636 loadtest doc rác**,
   1 đợt = 5753 point). **Gốc:** 6 replica rag-worker durable push-subscribe cùng consumer →
   `nats: consumer already bound`; doc.ingest+doc.access chung 1 try → ingest fail kéo doc.access không
   start → handler delete 0-firing. **Fix:** tách try riêng mỗi subscription + retry-on-already-bound.
   **Verified end-to-end:** delete API → Qdrant 100→0 + GCS raw/artifact→0 + handler `doc_access_delete_done`
   firing. (Rác 1636 doc cũ đã purge tay 1 lần — Qdrant+GCS+doc_db.)
2. **Trần CHƯA đo:** mới thấy "saturate êm" (chậm, 502 transient), **chưa tìm điểm GÃY cứng** — cần
   ramp 3→8→12 req/s + upload tăng dần tới khi chat FAIL.
3. **Coalescer 8-worker:** gom per-worker (không cross-process). Muốn cắt mạnh hơn → shared-queue
   (Redis) hoặc ít worker. Hiện đủ cho mục tiêu.

## Harness
- Chat: `queryeval/benchmark/run_load.py --rate 3.3 --dataset combined200 --limit 200`
- Ingest: `systemeval/doc-ingest-eval/runners/run_ingest_load.py --count N --rate R --files-dir <PDF/DOCX>`
- Orchestrator: `scratchpad/combined_loadtest.py {off|on}` (chạy 2 cái đồng thời + đếm embed-call/502)
- Cleanup: bulk-delete API + **xóa trực tiếp Qdrant filter `document_name~loadtest_`** (vì bug #1)
