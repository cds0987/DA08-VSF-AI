# Weekly Journal

Ghi lại hành trình xây dựng sản phẩm mỗi tuần — những gì đã làm, học được gì, AI giúp như thế nào.

Cập nhật mỗi cuối tuần (trước khi tạo PR). Không cần dài, chỉ cần thật.

> Sản phẩm: RAG chatbot HR nội bộ (prod `https://vsfchat.cloud`). Bắt đầu 29/05/2026.
> Tính tới 29/06: **768 commit** của mình (4 danh tính cds0987 / ttnguyen1410 / Nguyen Tran / Nguyên Trần).

---

## Tuần 1 — 29/05 → 04/06 · Dựng nền (~82 commit)

**Làm gì:** Mang prototype rag-service về thành service thật, rồi rename `rag-service → rag-worker` cho khớp main (lúc merge bị drop âm thầm 35 file, phải recover lại). Dựng pipeline config-driven, alembic migration thay `create_all`, structured logging, fail-closed startup health, ingest API, search contract. Thêm transport NATS `doc.ingest` + consumer `doc.delete`, parser nguồn S3/GCS an toàn. Tách `mcp-service` search-only độc lập + e2e Docker CI.

**Học được:** Build Python 3.13 hay vỡ vì thiếu wheel (phải pin); native-dep DLL trên Windows; botocore <1.36 đổi checksum kwargs; contract drift giữa rerank prompt↔parser; NATS phải durable subscription mới reliable.

**AI giúp:** Gần như dựng cả pipeline + đóng loạt "gap" blocker, viết design docs (`decide/`, `lesson/`). Mình định hướng, AI cày phần lặp.

## Tuần 2 — 05/06 → 11/06 · Lên cloud + CI/CD gated (~246 commit)

**Làm gì:** Chuyển hẳn lên 1 VM (Postgres/Qdrant in-compose, GCS keyless). Gom toàn bộ CI/CD thành **1 pipeline gated** trên push:develop, tách 3 phase (test → Docker Hub → VM pull), thêm stage-gate smoke chọn-lọc + **auto-rollback**, env-in-git `common.env`, secret dồn về GitHub Secrets. Self-host **Langfuse v2** + step tracing cho query và ingest. MCP: internal-token auth, refactor tool registry, `hr_query` MVP; tách hr-service thành HTTP proxy; thêm intent payroll/benefits/performance. rag-worker: store reconciler + doc-status outbox + hardening Qdrant.

**Học được:** e2e race (phải đợi *tất cả* doc ingested, không đếm tổng chunk); chuẩn hoá URL Qdrant; vệ sinh secret để repo public được; Langfuse v2 không có API delete trace.

**AI giúp:** Tuần nặng nhất về hạ tầng — AI lo phần CI/CD, observability, hardening lặp đi lặp lại; mình quyết kiến trúc (1 VM, env-in-git).

## Tuần 3 — 12/06 → 18/06 · ai-router + leave-chat + sự cố RAG (~318 commit)

**Làm gì:** Đẻ ra **ai-router** — gateway OpenAI-compatible (banded rotation + deepseek blend cho "think" + save-mode + observability per-key×model + control-plane drain/resume key). Chat UI minh bạch: stream "model nghĩ gì / quyết định gì", node orchestrator-workers song song, các bước agent hiện dưới câu trả lời. **Leave-chat** (mảng lớn, dồn ngày 16/06): draft date-aware + form xác nhận sửa được, registry 4 rổ loại nghỉ theo luật LĐ VN, duyệt đơn bằng thẻ trong chat, `leave_approvals`, `resolve_date` deterministic, chống trùng đơn, nhiều đơn trong 1 lượt. Security: bỏ hardcode seed password, SSH lockdown (WIF+IAP), GCS V4 signed URL qua IAM signBlob.

**Sự cố 16/06 (nhớ đời):** RAG trả **0 sources** trên prod — gốc là thiếu migration `user_access_profile` + DSN sai + rerank threshold quá chặt. Sửa xong còn hardening: chuẩn hoá DSN, CI schema-drift, poison-message, migrator fail-fast, deploy forward-only (không rollback huỷ dữ liệu).

**Học được:** Drift contract có thể **giết RAG âm thầm** (không test nào đỏ); deploy phải fail-safe (pre-flight migration); image rollback mà thiếu migration thì DB treo.

**AI giúp:** AI trace tận gốc sự cố 0-sources, dựng ai-router + leave-chat end-to-end, viết các gate CI. Mình review + quyết khi nào ship.

## Tuần 4 — 19/06 → 25/06 · Chất lượng + hiệu năng (~243 commit)

**Làm gì:** ai-router selector `elastic_banded` + `adaptive_balanced` (TPM cho OpenAI · AIMD cho OpenRouter); thử //hóa model cắt p99 (rồi revert vì xiaomi kéo tail xấu); Grafana histogram TTFT/latency + tải/cost theo key. Rerank cohere qua OpenRouter + diversity cap (chống 1 doc thống trị) → precision text 39%→100%. OCR vector-chart + cap trang graceful; Contextual Retrieval L1 (precision ảnh 25→71%). Chuỗi **benchmark BM1–5**: fast-path cắt plan-bottleneck −31%, //hóa answer −41% p95, triage reasoning-OFF 4s→1s. **Chiến dịch test đối kháng** query-service (ACL 6/6, LEAK, đơn vị USD/VND loạn, memory horizon, streaming) → plan fix phân tầng P0–P3. Khoá 3 seam liên-service bằng gate (jwt / http / mcp).

**Học được:** đuôi p99 đến từ model chậm chứ không phải tải; NAK-storm đốt 110% CPU lúc idle; OpenRAGBench cho thấy query path khoẻ (recall@1 0.984, ≥10 concurrent 0-shed) nhưng **ingest 1-worker ~75s/doc là trần** → phải scale.

**AI giúp:** AI chạy phần lớn benchmark + viết báo cáo, dựng selector/Grafana, làm chiến dịch test-fix. Mình đọc số rồi quyết hướng tối ưu.

## Tuần 5 — 26/06 → 29/06 · Embed migration + đo tải + dọn docs (~92 commit)

**Làm gì:** Migrate embedding qwen3 4b→**8b** (3 provider), dim 2560→**4096 native** (bỏ MRL-truncate). Thử **multi-collection** (shard 5 model, append-migrate + backfill) → lộ **bug qwen8b giả-multi-collection** → sửa tận gốc (route theo `body['model']`, est = MAX per-text, bỏ inflight-cap embed, gate drift xuyên-service) → đo recall → **QUYẾT giữ single qwen8b** (recall 0.73 vs 0.53 của multi). Loạt fix "giết doc" tận gốc: ép `encoding_format=float` (base64 leak), transient retry không giết doc, delete-cascade NATS bound, miễn rate-limit RPC nội bộ (chat 429). Scale ingest ×8 cô lập khỏi search, bỏ per-worker distill (câu nặng −53% latency). Dựng `systemeval/` + HF data-repo + bộ 450 câu, đo **load benchmark 800–1200 user** (peak 450q/60s + 40 ingest, agent timing qua Langfuse). Cuối tuần **refactor toàn bộ docs/** verify từ code.

**Học được:** model Matryoshka (MRL) che được bug multi-collection (upsert vừa khít dim nên 0 lỗi); nghẽn tải là **tầng agent reasoning xếp hàng**, không phải rate-limit (đo 7.5 q/s 0 mất request); và **docs đã lệch code** nhiều chỗ → chốt nguyên tắc *code là bằng chứng duy nhất*.

**AI giúp:** AI dò ra bug qwen8b + chạy toàn bộ eval/recall/load-test, fan-out 8 agent đọc code viết lại docs từng service. Mình quyết single-vs-multi dựa số, và quyết cách dọn docs.

---

### Vài điều ngấm sau 5 tuần
- **Code là bằng chứng** — docs, comment, design cũ đều có thể nói dối; chỉ code đang chạy là thật.
- Lỗi nguy nhất là loại **âm thầm** (RAG 0-sources, qwen8b giả-multi): không crash, không test đỏ, chỉ sai. → phải có gate/contract chặn drift trước prod.
- Đo trước khi tối ưu: gần như mọi "tối ưu theo cảm giác" đều bị số liệu bác (multi-collection, //hóa model, chunk-180).
- AI là cặp tay cày được khối lượng lớn + trace sâu, nhưng **quyết định kiến trúc/ship vẫn là mình** dựa trên số.
