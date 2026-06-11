# RAG Worker — Trace & Debug pipeline ingest bằng Langfuse

**Mục tiêu:** mỗi job ingest = 1 trace trên Langfuse, mỗi stage (parse → chunk → caption → embed → ghi Qdrant) = 1 span. Khi crash, mở trace là thấy NGAY span nào đỏ + input/error của nó → biết vỡ ở đâu mà không phải đọc log mò.

> **✅ ĐÃ TRIỂN KHAI (2026-06-11, deploy develop):** Langfuse tracing cho ingest đã code + test + lên production. Adapter `app/infrastructure/observability/langfuse_tracer.py` (`IngestTracer`), wiring qua `bootstrap_runtime`→engine+use_case, config parity đủ. CI: failure-matrix trong `rag-test` + job `rag-langfuse` (integration Langfuse thật) — pipeline `develop` PASS full. File này giờ vừa là **hướng dẫn** vừa là **tài liệu tham chiếu** cho phần đã làm. Pattern gốc tái dùng từ `query-service` (low-level client).

---

## TRƯỚC KHI CODE — đọc 5 quyết định đã chốt (từ phân tích tradeoff)

Đừng bê nguyên Langfuse vào worker như web service. 5 ràng buộc bắt buộc, vi phạm = throughput tụt hoặc storage phình:

1. **Fix log stdout TRƯỚC** (task #3 roadmap) — Langfuse KHÔNG thay log. Log lo debug thường ngày (rẻ); Langfuse lo soi **nội dung AI + cây stage** (đắt). Đừng dựng Langfuse để né việc fix log.
2. **OFF mặc định** (`LANGFUSE_ENABLED=0`) — bật chủ động khi cần soi 1 batch/1 doc lỗi. Worker ingest bulk → trace dày hơn query-service nhiều lần.
3. **Sampling bắt buộc** — KHÔNG trace 100% job. Mặc định: chỉ trace job **FAILED/retry** + tỉ lệ mẫu nhỏ job thành công (`LANGFUSE_SAMPLE_RATE`). Tránh volume + storage.
4. **`flush()` qua `asyncio.to_thread`** — flush v2 là blocking; gọi thẳng trong event loop sẽ chặn → giảm thông lượng ingest.
5. **Best-effort PHẢI có test** — "langfuse chết = ingest vẫn pass". Đây là worker production, tracing không bao giờ là lý do mất dữ liệu.

Phân vai rõ để đội khỏi phân vân: **New Relic = infra/APM/alert · Langfuse = debug nội dung AI + thấy stage crash.**

---

## CÁC BƯỚC CODE (làm theo đúng thứ tự này)

> Mỗi bước là 1 commit nhỏ. Đừng gộp. Theo workflow [dev.md](dev.md) §2.

- [ ] **B0.** (tiền đề) Fix log INFO ra docker stdout — task #3 roadmap. Có thể song song, nhưng đừng dựng Langfuse để né nó.
- [ ] **B1. Config + parity** — thêm 6 env (§4) vào `config.yaml` **VÀ** `config_schema.py` cùng commit (nếu thiếu → CI parity fail `extra_forbidden`). Thêm `langfuse>=2,<3` vào `requirements.txt`.
- [ ] **B2. Adapter** — tạo `app/infrastructure/observability/langfuse_tracer.py` theo §3.1 (copy pattern query-service). Thêm `flush()` qua `to_thread` (§6) + sampling guard (§4.1).
- [ ] **B3. Unit test adapter** — §7: tracer=None no-op; stub ném lỗi → không vỡ; sampling đúng tỉ lệ. **Viết test ở bước này, trước khi wire.**
- [ ] **B4. Wire composition** — `build_ingest_tracer(settings)` ở `app/interfaces/api/composition.py`, truyền vào use_case (§3.3). Giữ đúng layer — domain không biết Langfuse.
- [ ] **B5. Instrument use_case** — bọc từng stage parse/chunk/caption/embed/qdrant-write theo §3.2. caption & embed dùng `generation` (có model/usage).
- [ ] **B6. Test use_case** — §7: thứ tự span đúng; stage lỗi → `span_error` + `finish_job(FAILED)` + lỗi vẫn re-raise.
- [ ] **B7. Verify local OFF** — chạy `pytest` + ingest 1 doc với `LANGFUSE_ENABLED=0` → hành vi y hệt trước, không gọi Langfuse.
- [ ] **B8. Verify trên VM ON** — bật env, ingest 1 doc thật, mở dashboard (SSH `-L` tunnel) thấy trace `doc-ingest` đủ span. (DoD luồng RAG: [04-definition-of-done.md](04-definition-of-done.md).)
- [ ] **B9. PR** nguyendev → develop, self-review checklist [dev.md](dev.md) §5.

---

## 0. Vì sao Langfuse hợp với rag-worker
- Pipeline ingest nhiều stage tuần tự → cây span phản ánh đúng luồng, nhìn 1 phát ra chỗ nghẽn/đỏ.
- Stage `caption` (LLM vision) + `embed` (embedding model) là **generation** → Langfuse hiện model/token/cost/latency.
- Bổ trợ chứ KHÔNG thay New Relic: New Relic lo APM/infra metric; Langfuse lo **trace nghiệp vụ AI + debug nội dung** (input/output từng stage).
- Giải quyết đúng nỗi đau hiện tại: "log INFO không ra docker stdout" → Langfuse trace là kênh quan sát thay thế khi log bị nuốt.

---

## 1. Nguyên tắc BẮT BUỘC (học từ query-service)
1. **Dùng low-level client `langfuse.Langfuse` (v2, <3). TUYỆT ĐỐI KHÔNG import langchain / CallbackHandler** — callback v2 cần langchain-core đời cũ → xung đột → crash. rag-worker không cần langchain nên càng phải giữ sạch.
2. **Best-effort tuyệt đối:** mọi call Langfuse bọc `try/except`, nuốt lỗi, log warning. **Langfuse chết = no-op, KHÔNG được làm hỏng/treo job ingest.** Đây là worker production, tracing không bao giờ là lý do mất dữ liệu.
3. **Phải `flush()` cuối job** — không flush thì trace chưa gửi (worker không phải web request có lifecycle tự đẩy).
4. **Bật/tắt bằng env, OFF khi thiếu key** — dev/test offline không có key → tracer = None → use_case bỏ qua. Không được fail-closed vì thiếu key tracing.
5. Env đến từ git (`deploy/env/*.env`), key commit thẳng theo convention repo. KHÔNG provision secret tay.

---

## 2. Mô hình trace cho 1 job ingest

```
trace  name="doc-ingest"  session_id=<document_id>  input={uri, mime, size}
 ├─ span  "parse"        (OCR / pdf→text / csv→markdown)   input=uri        output={num_pages, chars}
 ├─ span  "chunk"        input={chars}                      output={num_chunks}
 ├─ generation "caption" model=<vision>  input=<image>      output=<caption>  usage={...}
 ├─ generation "embed"   model=text-embedding-3-small       input={num_chunks} usage={tokens}
 └─ span  "qdrant-write" input={collection, num_vectors}    output={upserted}
trace.update(output={status, total_chunks, error?})  → flush()
```

- **1 trace / 1 job.** `session_id = document_id` để gom mọi lần re-ingest cùng doc.
- Span lỗi: đóng bằng `level="ERROR"` + `output={"error": ...}` → trace đỏ ngay tại stage đó.
- `metadata` gắn `job_id`, `tenant`, `collection`, `attempt` để filter trên UI.

---

## 3. Wiring (theo Clean Architecture của rag-worker)

Giữ đúng layer (xem [dev.md](dev.md) §1): tracer là 1 **port best-effort** truyền từ `composition` → `ingest_document_use_case`. Domain KHÔNG biết Langfuse.

### 3.1 Adapter — `app/infrastructure/observability/langfuse_tracer.py`
Sao gần như nguyên pattern `query-service/app/infrastructure/observability/langfuse_tracing.py`, rút gọn cho ingest (span theo stage + generation cho caption/embed):

```python
from __future__ import annotations
from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)


class IngestTracer:
    """Best-effort wrapper quanh langfuse v2 low-level client. Mọi lỗi đều nuốt."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def start_job(self, document_id: str, job_meta: dict) -> Any | None:
        try:
            return self._client.trace(
                name="doc-ingest",
                session_id=document_id,
                input={"uri": job_meta.get("uri"), "mime": job_meta.get("mime")},
                metadata={"job_id": job_meta.get("job_id"), "attempt": job_meta.get("attempt")},
            )
        except Exception as exc:  # noqa: BLE001 — tracing KHÔNG được làm vỡ ingest
            logger.warning("lf_job_start_failed", extra={"error": str(exc)[:200]})
            return None

    def span_start(self, trace: Any | None, name: str, input_data: Any = None) -> Any | None:
        if trace is None:
            return None
        try:
            return trace.span(name=name, start_time=datetime.now(timezone.utc), input=input_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lf_span_start_failed", extra={"name": name, "error": str(exc)[:200]})
            return None

    def span_ok(self, span: Any | None, output: Any = None) -> None:
        self._end(span, output=output, level=None)

    def span_error(self, span: Any | None, error: BaseException) -> None:
        # ĐÂY là chỗ "biết crash ở đâu": stage đỏ + error string hiện trên UI
        self._end(span, output={"error": str(error)[:500]}, level="ERROR")

    def _end(self, span: Any | None, output: Any, level: str | None) -> None:
        if span is None:
            return
        try:
            kwargs: dict[str, Any] = {"output": output, "end_time": datetime.now(timezone.utc)}
            if level:
                kwargs["level"] = level
            span.end(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lf_span_end_failed", extra={"error": str(exc)[:200]})

    def generation(self, trace, name, model, start_dt, input_data, output, usage):
        if trace is None:
            return
        try:
            trace.generation(name=name, model=model, start_time=start_dt,
                             end_time=datetime.now(timezone.utc),
                             input=input_data, output=output, usage=usage)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lf_generation_failed", extra={"error": str(exc)[:200]})

    def finish_job(self, trace, status: str, output: dict) -> None:
        if trace is None:
            return
        try:
            trace.update(output={"status": status, **output})
            self._client.flush()   # BẮT BUỘC
        except Exception as exc:  # noqa: BLE001
            logger.warning("lf_job_finish_failed", extra={"error": str(exc)[:200]})


def build_ingest_tracer(settings: Any) -> "IngestTracer | None":
    """None khi tắt/thiếu key → use_case bỏ qua tracing (dev/test offline OK)."""
    if not getattr(settings, "langfuse_enabled", False):
        return None
    pub = (settings.langfuse_public_key or "").strip()
    sec = (settings.langfuse_secret_key or "").strip()
    if not pub or not sec:
        return None
    try:
        from langfuse import Langfuse  # v2 low-level, KHÔNG import langchain
    except ImportError as exc:
        raise RuntimeError("langfuse (v2, <3) required khi LANGFUSE_ENABLED=1") from exc
    return IngestTracer(Langfuse(public_key=pub, secret_key=sec, host=settings.langfuse_host))
```

### 3.2 Use case — bọc từng stage
Trong `app/application/use_cases/ingestion/ingest_document_use_case.py`, mỗi stage mở span trước, đóng `span_ok` khi xong, `span_error` khi ném lỗi rồi re-raise (giữ nguyên hành vi nghiệp vụ):

```python
async def execute(self, job):
    trace = self._tracer.start_job(job.document_id, job.meta) if self._tracer else None

    sp = self._tracer.span_start(trace, "parse", {"uri": job.uri}) if self._tracer else None
    try:
        doc = await self._parser.parse(job.uri)
        self._tracer and self._tracer.span_ok(sp, {"chars": len(doc.text)})
    except Exception as exc:
        self._tracer and self._tracer.span_error(sp, exc)   # ← parse đỏ trên UI
        self._tracer and self._tracer.finish_job(trace, "FAILED", {"stage": "parse", "error": str(exc)[:300]})
        raise

    # ... chunk / caption(generation) / embed(generation) / qdrant-write tương tự ...

    self._tracer and self._tracer.finish_job(trace, "SUCCESS", {"total_chunks": n})
```

> Gợi ý gọn hơn: viết 1 async context manager `traced_stage(tracer, trace, name)` để khỏi lặp try/except — nhưng giữ đúng tinh thần best-effort.

### 3.3 Composition — wire vào
Ở `app/interfaces/api/composition.py`: `tracer = build_ingest_tracer(settings)` rồi truyền vào use_case. `settings` lấy từ `config_schema.py` (xem §4).

---

## 4. Config & env (đừng quên parity!)
Thêm các field vào **`config_schema.py` CÙNG LÚC** với khi thêm vào `config.yaml`, nếu không CI parity fail `extra_forbidden` (bẫy kinh điển — xem [dev.md](dev.md) §4):

| Env | Ý nghĩa | Mặc định |
|-----|---------|----------|
| `LANGFUSE_ENABLED` | bật/tắt tracer | `0` (OFF) |
| `LANGFUSE_PUBLIC_KEY` | key public | — |
| `LANGFUSE_SECRET_KEY` | key secret | — |
| `LANGFUSE_HOST` | URL Langfuse self-host | `http://langfuse-web:3000` (nội bộ VM) |
| `LANGFUSE_SAMPLE_RATE` | tỉ lệ trace job THÀNH CÔNG (0.0–1.0) | `0.0` (chỉ trace job lỗi) |
| `LANGFUSE_TRACE_ON_ERROR` | luôn trace job FAILED/retry dù sample miss | `1` |

- Thêm `langfuse>=2,<3` vào `src/rag-worker/requirements.txt` (ghim v2 — v3 đổi API).
- Env vào `deploy/env/*.env` commit thẳng. Mặc định OFF để bật có kiểm soát.

### 4.1 Sampling — KHÔNG trace 100% job
Worker bulk → trace dày. Quyết định trace NGAY ở `start_job`, trước khi tạo trace object:

```python
import random

def start_job(self, document_id, job_meta):
    # luôn trace nếu job đang retry/đã từng lỗi; còn lại theo sample_rate
    forced = self._trace_on_error and int(job_meta.get("attempt", 0)) > 0
    if not forced and random.random() >= self._sample_rate:
        return None          # bỏ qua → span_start nhận None → no-op toàn bộ
    # ... tạo trace như §3.1
```

> Mẹo: vì mọi `span_*`/`finish_job` đã guard `trace is None`, chỉ cần `start_job` trả None là cả job không trace — không phải rải `if` khắp use_case.

---

## 5. Dùng để DEBUG — quy trình "tìm chỗ crash"
1. Tái hiện: gửi lại doc qua NATS `doc.ingest` (xem quy trình re-ingest staging).
2. Mở Langfuse dashboard — **truy cập phải qua SSH `-L` tunnel** (không dùng start-iap-tunnel vì nó bind loopback). Login `admin@company.com`. (Chi tiết: memory `langfuse VM tunnel access`.)
3. Filter trace `name=doc-ingest`, `session_id=<document_id>` hoặc `metadata.job_id`.
4. Trace đỏ → click → span `level=ERROR` chính là **stage crash**; đọc `input`/`output.error` của span đó.
5. Stage chậm bất thường → nhìn latency từng span → biết nghẽn ở parse/embed/qdrant.
6. Caption/embed sai nội dung → mở generation, xem input/output/model thực tế.

**Khớp với bản đồ bẫy ([01-rag-worker.md](01-rag-worker.md)):** span `qdrant-write` đỏ với lỗi 404 → khả năng cao collection biến mất (cache `_ready`) → restart rag-worker. Span `parse` đỏ với GCS → kiểm scheme `gs://` / billing / checksum.

---

## 6. Cạm bẫy riêng khi trace trong worker
- **Worker không có request lifecycle** → PHẢI gọi `flush()` cuối mỗi job, nếu không trace lửng (thấy span dở).
- `flush()` của langfuse v2 là **blocking/đồng bộ** → trong vòng async **PHẢI** gọi qua `asyncio.to_thread`, không thì chặn event loop và tụt throughput ingest:

```python
async def finish_job(self, trace, status, output):
    if trace is None:
        return
    try:
        trace.update(output={"status": status, **output})
        await asyncio.to_thread(self._client.flush)   # KHÔNG flush thẳng trong loop
    except Exception as exc:  # noqa: BLE001
        logger.warning("lf_job_finish_failed", extra={"error": str(exc)[:200]})
```
(Lưu ý: đổi `finish_job` thành `async` thì callsite ở use_case phải `await` — cập nhật §3.2 tương ứng.)
- **Concurrency:** mỗi job tạo trace/span object RIÊNG (không share state) → an toàn song song. Đừng dùng biến module global giữ trace.
- Nuốt lỗi nhưng **vẫn log warning** — để khi Langfuse chết còn biết, đừng nuốt im lặng.
- Đừng nhét cả `parent_text`/ảnh base64 nặng vào input span → trace phình, UI chậm. Cắt ngắn (`[:500]`), chỉ giữ metadata định danh.

---

## 7. Test cho phần tracing (best-effort phải có test)
Theo [dev.md](dev.md) §3 — dùng Stub thủ công:
- [ ] **Tracer = None** (tắt) → use_case chạy bình thường, không gọi gì, không lỗi.
- [ ] **Stub tracer ném lỗi** ở `span_start`/`finish_job` → ingest VẪN thành công (chứng minh best-effort).
- [ ] **Happy path** → assert thứ tự span đúng: parse → chunk → caption → embed → qdrant-write.
- [ ] **Stage ném lỗi** → assert `span_error` được gọi đúng span + job finish `status=FAILED` + lỗi vẫn re-raise.

```python
class StubTracer:
    def __init__(self, fail_on=None):
        self.events, self._fail = [], fail_on
    def start_job(self, *a, **k): self.events.append("start"); return object()
    def span_start(self, trace, name, input_data=None):
        if name == self._fail: raise RuntimeError("boom")   # mô phỏng langfuse chết
        self.events.append(f"span:{name}"); return object()
    def span_ok(self, *a, **k): pass
    def span_error(self, *a, **k): self.events.append("error")
    def finish_job(self, trace, status, output): self.events.append(f"finish:{status}")

async def test_ingest_survives_tracer_failure():
    tracer = StubTracer(fail_on="parse")
    out = await use_case_with(tracer).execute(valid_job)
    assert out.status == "SUCCESS"        # langfuse chết KHÔNG làm vỡ ingest
```

---

## 9. Bật/tắt trace lúc RUNTIME qua HTTP + internal token (không restart)

Nhu cầu: bật trace để điều tra **mà không restart container**, và **chỉ ai có internal token mới bật được**. rag-worker đã có sẵn FastAPI (`app/interfaces/api/main.py`) + pattern guard → tận dụng.

### 9.1 Mô hình 2 lớp (đừng nhầm)
| Lớp | Quyết định | Khi nào set | Real-time? |
|-----|-----------|-------------|-----------|
| **Capability** `LANGFUSE_ENABLED` + key | worker có **dựng được** client Langfuse không | startup (env từ git) | ❌ cần restart |
| **Runtime switch** (in-memory `tracing_on`) | có **thật sự trace** job tới hay không | qua HTTP admin | ✅ tức thì |

→ Client Langfuse dựng sẵn lúc start (khi có key), nhưng `start_job` chỉ trace khi `tracing_on=True`. Bật/tắt runtime = lật cờ in-memory, **không đụng process**.

> Nếu `LANGFUSE_ENABLED=0` (không có client) thì endpoint admin trả 409 "tracer not built" — capability tắt thì runtime switch vô nghĩa. Muốn bật runtime, deploy phải để `ENABLED=1` + có key, còn `tracing_on` khởi tạo `False`.

### 9.2 State runtime — `app/interfaces/api/runtime.py` (hoặc tracer giữ cờ)
```python
class TracingSwitch:
    """Cờ in-memory bật/tắt trace lúc chạy. Mặc định TẮT."""
    def __init__(self) -> None:
        self._on = False
    def is_on(self) -> bool: return self._on
    def set(self, on: bool) -> None: self._on = on
```
`start_job` thêm guard đầu hàm: `if not self._switch.is_on(): return None` (trước cả sampling).

### 9.3 Guard token — FAIL-CLOSED (khác `require_delete_api_key`)
`require_delete_api_key` là **fail-OPEN** (token rỗng → cho qua). Endpoint bật trace phải **fail-CLOSED**: thiếu token cấu hình HOẶC sai token → **TỪ CHỐI, không bật**.

```python
import hmac, os
from fastapi import Header, HTTPException, status

def require_tracing_admin_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    required = os.getenv("TRACING_ADMIN_TOKEN", "").strip()
    if not required:                                   # CHƯA cấu hình token → KHÓA, không bật được
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tracing admin disabled (no token set)")
    if not x_internal_token or not hmac.compare_digest(x_internal_token, required):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal token")
    # constant-time compare → tránh timing attack đoán token
```

### 9.4 Endpoint admin
```python
from fastapi import APIRouter, Depends, Request

router = APIRouter()

@router.post("/admin/tracing", dependencies=[Depends(require_tracing_admin_token)])
async def set_tracing(request: Request, on: bool, sample_rate: float | None = None):
    switch = request.app.state.tracing_switch
    tracer = getattr(request.app.state, "tracer", None)
    if tracer is None:
        raise HTTPException(409, "tracer not built (LANGFUSE_ENABLED=0 hoặc thiếu key)")
    switch.set(on)
    if sample_rate is not None:
        tracer.set_sample_rate(max(0.0, min(1.0, sample_rate)))   # chỉnh sampling runtime luôn
    return {"tracing_on": switch.is_on(), "sample_rate": tracer.sample_rate}

@router.get("/admin/tracing", dependencies=[Depends(require_tracing_admin_token)])
async def get_tracing(request: Request):
    return {"tracing_on": request.app.state.tracing_switch.is_on()}
```
Wire ở `create_app()`: `app.state.tracing_switch = TracingSwitch()` + `app.include_router(admin.router, prefix="/api")`.

### 9.5 Dùng (qua SSH tunnel tới worker, không expose public)
```bash
# BẬT trace + sample 100% để điều tra
curl -X POST "http://localhost:8000/api/admin/tracing?on=true&sample_rate=1.0" \
     -H "X-Internal-Token: $TRACING_ADMIN_TOKEN"
# ... reproduce ingest doc lỗi, xem Langfuse ...
# TẮT lại khi xong
curl -X POST "http://localhost:8000/api/admin/tracing?on=false" \
     -H "X-Internal-Token: $TRACING_ADMIN_TOKEN"
```
Sai/thiếu token → 401/403, cờ KHÔNG đổi → không ai bật trộm được.

### 9.6 Cạm bẫy của cơ chế này (đọc kỹ)
- **State per-process:** cờ in-memory sống trong 1 container. Nếu chạy **nhiều replica**, 1 lần curl chỉ bật 1 replica → phải gọi từng replica hoặc dùng nguồn chung (NATS KV/Redis). rag-worker hiện chạy đơn trên VM → tạm ổn, nhưng GHI RÕ giả định này.
- **Mất khi restart:** deploy/restart → cờ về `False` (đúng ý: trace là tạm thời, không kẹt ON). Đừng coi đây là cấu hình bền.
- **Token đặt qua env từ git** (`deploy/env/*.env`) như mọi secret khác; KHÔNG hardcode. Endpoint admin **đừng route public qua nginx** — chỉ gọi nội bộ/qua tunnel (giống hr-service internal-only).
- **Endpoint admin phải bị rate-limit + bodyless-safe** — middleware edge-guard hiện có (`main.py`) đã phủ; đừng thêm path admin vào `_HEALTH_PATHS` (đừng bypass guard).
- **Test bắt buộc:** thiếu token env → 403; sai token → 401; đúng token + tracer None → 409; đúng token + tracer có → lật cờ và `start_job` phản ánh ngay.

### 9.7 Khi nào KHÔNG cần cơ chế này
Nếu đội chỉ bật trace vài lần/tuần → **đổi env + restart là đủ**, đừng dựng endpoint (thêm code + bề mặt bảo mật). Chỉ làm §9 khi cần bật/tắt **nhiều lần trong ngày mà không được restart**. Cân nhắc đúng nhu cầu thật (xem mục tradeoff đầu file).

---

## 10. Liên kết
- Pattern gốc (low-level client): [../../src/query-service/app/infrastructure/observability/langfuse_tracing.py](../../src/query-service/app/infrastructure/observability/langfuse_tracing.py)
- Hướng dẫn dev chung: [dev.md](dev.md) · RAG Worker: [01-rag-worker.md](01-rag-worker.md)
- Truy cập dashboard (SSH tunnel + login): memory `langfuse VM tunnel access`
