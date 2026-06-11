# DEV GUIDE — Làm việc trên 3 service mà KHÔNG làm vỡ codebase

**Đối tượng:** dev tham gia rag-worker / mcp-service / hr-service (và query-service khi cần).
**Mục tiêu:** code hiệu quả, chặt chẽ, có test bảo vệ regression. Đọc kèm [04-definition-of-done.md](04-definition-of-done.md).

> Nguyên tắc vàng: **mọi service ở đây theo Clean Architecture**. Hiểu đúng layer = không làm vỡ. Viết sai chỗ = nợ kỹ thuật + vỡ test.

---

## 0. TL;DR — 10 điều bất di bất dịch
1. Làm trên branch `nguyendev`, PR vào `develop`. **KHÔNG commit thẳng `develop`/`main`.**
2. Đọc layer trước khi sửa: `domain` không phụ thuộc ai; `application` chỉ phụ thuộc `domain`; `infrastructure`/`interfaces` ở ngoài cùng.
3. Thêm key vào `config.yaml` → **thêm field vào `config_schema.py` cùng commit** (nếu không CI parity fail `extra_forbidden`).
4. Đổi env = sửa `deploy/env/*.env` + commit. KHÔNG provision secret tay, KHÔNG sửa tay trên VM.
5. Feature mới = **feature-flag OFF mặc định** + backward-compatible tuyệt đối.
6. Mỗi thay đổi logic phải kèm test. Test mirror cây `app/` (xem §3).
7. Dùng **Stub thủ công**, không lạm dụng `unittest.mock.Mock` cho domain/application.
8. Async: `pytest.ini` đã bật `asyncio_mode=auto` → viết `async def test_...` thẳng, không cần decorator.
9. Chạy test + lint LOCAL trước khi push. CI xanh ≠ chạy được — vẫn phải verify trên VM cho luồng E2E.
10. Đừng đụng `core_engine/` của rag-worker từ mcp-service. Hai service độc lập, chỉ ghép qua **Qdrant URL**.

---

## 1. Bản đồ kiến trúc (đọc trước khi sửa)

Cả 3 service dùng 4 lớp (tên thư mục có thể là `app/core` ở mcp, `app/{domain,application,...}` ở rag-worker/hr):

```
interfaces / api / nats   ← cổng vào (HTTP route, NATS consumer, MCP tool). Mỏng, không chứa business logic.
        │ gọi xuống
application (use_cases)    ← orchestrate nghiệp vụ. Nhận port (interface), không biết chi tiết hạ tầng.
        │ gọi xuống
domain (entities/repos)    ← model + interface thuần. KHÔNG import boto3/httpx/qdrant/sqlalchemy.
        ▲ được implement bởi
infrastructure             ← adapter thật: Postgres, Qdrant, S3/GCS, NATS, HTTP proxy.
```

**Quy tắc phụ thuộc (CHIỀU MŨI TÊN CHỈ HƯỚNG VÀO TRONG):**
- `domain` không được import bất kỳ thứ gì từ 3 lớp kia.
- `application` chỉ phụ thuộc `domain` (qua interface/Protocol), KHÔNG import `infrastructure` trực tiếp.
- `infrastructure` implement interface của `domain`; được "wire" vào ở `interfaces/composition.py`.
- Sửa nghiệp vụ → sửa `application`. Đổi DB/Qdrant/HTTP → sửa `infrastructure`. **Đừng nhét logic vào router/consumer.**

> Vi phạm chiều phụ thuộc là cách nhanh nhất "làm vỡ codebase" mà CI có thể không bắt ngay. Nếu thấy mình `import` ngược chiều → dừng, refactor qua interface.

---

## 2. Quy trình làm một thay đổi (workflow chuẩn)

```
1. git fetch + checkout nguyendev + cập nhật (xem git sync workflow của team)
2. Hiểu yêu cầu → xác định layer cần sửa
3. Viết/sửa interface ở domain (nếu cần) TRƯỚC
4. Implement ở infrastructure / application
5. Viết test cho từng layer đụng tới (§3)
6. Chạy local: pytest + (nếu có) ruff/lint
7. Cập nhật config_schema.py nếu đụng config.yaml
8. Commit nhỏ, message rõ: feat(scope): ... / fix(scope): ...
9. Push → mở PR nguyendev → develop
10. CI xanh → deploy → VERIFY TRÊN VM cho luồng E2E
```

**Commit message** theo convention repo: `feat(rag-worker): ...`, `fix(mcp): ...`, `docs: ...`, `style(chat): ...`.

---

## 3. Viết test case THẾ NÀO cho chặt

### 3.1 Test mirror cây source
Test đặt theo đúng layer của code nó kiểm. Ví dụ rag-worker:
```
app/application/use_cases/ingestion/ingest_document_use_case.py
tests/application/ingestion/test_ingest_document_use_case.py   ← song ánh 1-1
```
Cấu trúc test thật trong repo: `tests/{application,infrastructure,interfaces,core_engine,e2e,eval}/`.

### 3.2 Phân tầng test (test pyramid)
| Loại | Phạm vi | Khi nào | Dùng gì |
|------|---------|---------|---------|
| **Unit** | 1 use_case / 1 hàm domain | mặc định, nhiều nhất | Stub thủ công các port |
| **Integration** | adapter thật chạm hạ tầng giả/lập | DB/Qdrant/HTTP adapter | Qdrant in-mem/offline embedder, sqlite/fixture |
| **E2E** (`tests/e2e`) | nhiều service qua Docker | luồng then chốt | CI e2e Docker thật |
| **Eval** (`tests/eval`) | chất lượng retrieval/answer | tuning chunk/caption | validation corpus |

Nguyên tắc: **đẩy logic xuống unit nhiều nhất có thể**; E2E chỉ giữ vài kịch bản xương sống (đắt, chậm, dễ flake).

### 3.3 Dùng Stub thủ công — KHÔNG lạm dụng Mock
Repo đã chuẩn hoá kiểu này (xem `tests/test_search_service.py`): viết class Stub implement đúng port, **ghi lại call để assert**. Lợi: type-safe, đọc được, không vỡ ngầm khi đổi signature.

```python
from __future__ import annotations
import pytest
from app.core.search import SearchService
from app.core.vectorstore import SearchHit

class StubEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []
    async def embed(self, text: str) -> list[float]:
        self.queries.append(text)      # ghi lại để assert
        return [0.1, 0.2]

class StubReader:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[dict] = []
    async def search(self, vector, query_text, top_k, document_ids=None):
        self.calls.append({"query_text": query_text, "top_k": top_k})
        return list(self.hits)

async def test_search_embeds_query_and_passes_topk():   # asyncio_mode=auto → không cần @pytest.mark.asyncio
    embedder, reader = StubEmbedder(), StubReader(hits=[...])
    svc = SearchService(embedder=embedder, reader=reader, reranker=StubReranker())

    await svc.search("chính sách nghỉ phép", top_k=5)

    assert embedder.queries == ["chính sách nghỉ phép"]   # đã embed đúng query
    assert reader.calls[0]["top_k"] == 5                  # đã truyền top_k xuống reader
```

### 3.4 Một test case chặt gồm gì (AAA)
- **Arrange:** dựng stub + input tối thiểu, rõ ràng.
- **Act:** gọi đúng 1 hành vi.
- **Assert:** kiểm **cả output lẫn tương tác** (stub có được gọi đúng tham số không).

Checklist mỗi feature phải có test cho:
- [ ] **Happy path** — input hợp lệ → output đúng.
- [ ] **Edge cases** — rỗng/null/top_k=0/list trống/Unicode tiếng Việt (giữ dấu!).
- [ ] **Failure path** — adapter ném lỗi → use_case xử lý đúng (retry/fallback/raise rõ).
- [ ] **Fallback/best-effort** — vd reranker lỗi → fallback `NoopReranker`, KHÔNG vỡ `rag_search`.
- [ ] **Boundary contract** — fail-closed startup (`verify_contract`): dimension/collection lệch → thoát sớm.
- [ ] **Idempotency** (ingest) — re-ingest cùng doc không nhân đôi chunk.
- [ ] **Security/self-access** (hr) — 3 intent nhạy cảm chỉ trả data của chính user + có audit.

### 3.5 Quy tắc test "chống vỡ"
- Test phải **deterministic**: không phụ thuộc thời gian thật/mạng thật/thứ tự chạy. Không `sleep` chờ; dùng offline embedder/in-mem store.
- Một assert một ý; tên test mô tả hành vi: `test_<đối_tượng>_<điều_kiện>_<kỳ_vọng>`.
- KHÔNG test internal private — test qua public API của layer.
- Test mới phải **fail trước khi fix, pass sau khi fix** (đặc biệt với bug → viết regression test tái hiện bug trước).
- Đừng nới test để cho qua. Nếu test cản, hỏi: code sai hay test sai? Sửa cái sai.

### 3.6 Chạy test
```powershell
# trong thư mục service (vd src/rag-worker)
python -m pytest                      # tất cả
python -m pytest tests/application    # 1 layer
python -m pytest -k ingest -q         # lọc theo tên
python -m pytest tests/.../test_x.py::test_case   # 1 case
```
`asyncio_mode=auto` → test async chạy thẳng, không cần `@pytest.mark.asyncio`.

---

## 4. Bẫy đã biết — đọc để khỏi vỡ (lessons learned)

| Bẫy | Hậu quả | Cách tránh |
|-----|---------|-----------|
| Thêm key `config.yaml` quên `config_schema.py` | CI parity fail `extra_forbidden` | Sửa 2 file cùng commit |
| Remote Qdrant client không qua `remote_client_kwargs()` | Cloud Run ConnectTimeout | Luôn qua `VectorStoreConfig.remote_client_kwargs()` (port 443 + timeout) |
| Env trỏ Qdrant cloud thay vì `qdrant:6333` | 404 crash khi deploy | Env trỏ Qdrant **nội bộ** |
| Xóa nguyên collection Qdrant | ingest 404 (cache cờ `_ready`) | Restart rag-worker, hoặc fix `_ensure` recover |
| Sửa tay trên VM | deploy `git reset --hard` ghi đè mất | Mọi sửa qua git |
| mcp dùng chung `core_engine` của rag-worker | phá tính độc lập | mcp tự dựng hạ tầng, ghép qua Qdrant URL |
| Mất dấu tiếng Việt trong summary | output xấu/sai | Test có case Unicode tiếng Việt |
| pybreaker `call_async` (tornado) trong asyncio | NameError, gãy MCP call | Dùng `_AsyncCircuitBreaker` asyncio-native |
| Tin CI smoke pass = ổn | smoke chỉ check 2xx, pass giả | Verify luồng thật trên VM |
| Log INFO không ra docker stdout | không debug được | Dùng New Relic / reproduce in-container (đang có task fix) |

---

## 5. Trước khi mở PR — self-review checklist
- [ ] Sửa đúng layer, không vi phạm chiều phụ thuộc.
- [ ] Có test cho happy + edge + failure path; test fail-trước-pass-sau.
- [ ] `pytest` xanh local; không skip/xfail mới mà không ghi lý do + điều kiện gỡ.
- [ ] `config.yaml` ↔ `config_schema.py` đồng bộ.
- [ ] Env (nếu đổi) đã vào `deploy/env/*.env`.
- [ ] Feature mới có flag OFF mặc định; backward-compatible.
- [ ] Commit nhỏ, message theo convention.
- [ ] Với luồng E2E: đã verify (hoặc có kế hoạch verify) trên VM.

---

## 6. Liên kết
- Roadmap & ưu tiên: [00-roadmap.md](00-roadmap.md)
- Definition of Done: [04-definition-of-done.md](04-definition-of-done.md)
- Per-service: [01-rag-worker.md](01-rag-worker.md) · [02-mcp-service.md](02-mcp-service.md) · [03-hr-service.md](03-hr-service.md)
- Docs vận hành CI/CD: [../ci-cd-onboarding.md](../ci-cd-onboarding.md) · [../onboard_cicd.md](../onboard_cicd.md) · [../devops-runbook.md](../devops-runbook.md)
