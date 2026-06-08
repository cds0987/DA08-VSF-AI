# GAP — rag-worker: lớp kết nối Qdrant cứng nhắc, vi phạm Open/Closed

Scope: `src/rag-worker` — lớp **dựng kết nối tới Qdrant remote** (URL normalize + auth +
transport options). Lan sang `src/mcp-service` (consumer, có bản sao cùng smell).
Grounding: code tại `nguyendev` HEAD (2026-06-08) — đọc `VectorStoreConfig.remote_client_kwargs`
→ `normalize_remote_qdrant_url` → 3 call-site dựng `AsyncQdrantClient` → 2 path build config.
Status: **OPEN** — đề xuất thiết kế CHƯA code; phần mô tả hiện trạng đã re-check trực tiếp trên code.

> Quy ước trạng thái:
> - `OPEN` = đã xác minh trong code hiện tại, chưa có implementation.
> - `CHỐT` = đã chốt hướng, **chưa code**.

---

## 0. ⚠️ BẮT BUỘC đọc trước khi sửa lớp connect (để không phá codebase)

Lớp connect Qdrant là **ranh giới giữa rag-worker (producer) và mcp-service (consumer)** + chạm
**2 đường build config** + **3 call-site** + **CI thật**. Sửa mà không nắm các tài liệu dưới đây rất dễ
gây fail-closed sai, 401, hoặc lệch contract producer/consumer. Đọc theo thứ tự:

### A. Pattern registry phải tái dùng (đừng phát minh cơ chế mới)
| Đọc | Vì sao — bỏ qua sẽ phá |
|-----|------------------------|
| [`core_engine/registry.py`](../../core_engine/registry.py) | Primitive `register`/`get`/`available` + guard trùng tên + entry-point. Thiết kế mới PHẢI dùng lại cái này. |
| [`core_engine/vectorstore/registry.py`](../../core_engine/vectorstore/registry.py) | Mẫu áp dụng đúng chuẩn (`register_backend`) — copy đúng cách lazy import + built-in thắng entry-point. |
| [`tests/core_engine/test_registry.py`](../../tests/core_engine/test_registry.py) | Hợp đồng hành vi registry (case-insensitive, `override`, built-in-wins). Contributor mới phải khớp hợp đồng này. |

### B. Lớp connect hiện tại + 2 path build config (gốc của G-C3)
| Đọc | Vì sao — bỏ qua sẽ phá |
|-----|------------------------|
| [`core_engine/vectorstore/config.py`](../../core_engine/vectorstore/config.py) | `remote_client_kwargs`, `from_env`, `normalize_remote_qdrant_url`, `basic_auth_header` — hành vi phải giữ y hệt (golden). |
| [`core_engine/mapping.py`](../../core_engine/mapping.py) | `to_vector_store_config` = **path build CONFIG production** (CI dùng path này, KHÔNG phải `from_env`). Field mới quên map ở đây → CI fail dù local chạy (đã dính 401, fix `2a01f16`). |
| `config.yaml` (block `vector_store.params`) | Path production đọc params từ đây; thêm field connection phải thêm `${VAR}` tương ứng. |
| [`providers/qdrant/remote.py`](../../core_engine/vectorstore/providers/qdrant/remote.py), [`qdrant_contract.py`](../../core_engine/vectorstore/qdrant_contract.py) | **3 call-site** đang gọi `**remote_client_kwargs()` (provider + `write_contract_stamp` + `verify_contract_or_raise`). Không được đổi chữ ký. |

### C. Contract producer↔consumer (connect lệch = vỡ ranh giới 2 service)
| Đọc | Vì sao — bỏ qua sẽ phá |
|-----|------------------------|
| [`docs/search-split-vectorstore-contract.md`](../search-split-vectorstore-contract.md) | §7 fail-closed + §4.3 hygiene read-path. Connect/url/collection lệch → mcp verify FAIL-CLOSED hoặc đọc rỗng. |
| [`core_engine/vectorstore/qdrant_contract.py`](../../core_engine/vectorstore/qdrant_contract.py) | `write_contract_stamp`/`verify_contract_or_raise` dùng client — nơi connect sai gây 401/timeout lúc startup. |
| `scripts/check_vectorstore_contract.py` | Guard parity CI (rag-worker vs mcp `config.yaml`). Đổi config phải qua guard này. |

### D. Consumer độc lập (G-C4)
| Đọc | Vì sao |
|-----|--------|
| [`mcp-service/app/core/vectorstore.py`](../../../mcp-service/app/core/vectorstore.py) + `app/core/config.py` | mcp KHÔNG dùng `core_engine` — nhân bản pattern, không nhân bản code. Đổi rag-worker phải đồng bộ mcp tay. |

### E. Gap cùng đụng `qdrant/remote.py` (tránh xung đột/regress)
| Đọc | Vì sao |
|-----|--------|
| [`docs/gap/gap8.md`](gap8.md) — **G8-5/G8-6** | Đang CHỐT sửa `qdrant/remote.py` (scroll phân trang, batch upsert). Refactor connect phải biết để không đụng độ / rebase lẫn nhau. |
| [`docs/gap/gap7.md`](gap7.md) — **G7-1, G7-10/18** | Eval gate: đổi **semantics** (chunk/embed/payload) phải chạy golden eval. Refactor connect KHÔNG được đổi semantics — nếu lỡ chạm, eval gate bắt buộc. |

### F. CI & schema (nơi lỗi sẽ lộ ra)
| Đọc | Vì sao |
|-----|--------|
| [`.github/workflows/e2e-cloud.yml`](../../../../.github/workflows/e2e-cloud.yml), `rag-service-ci.yml` | Connect chạy thật ở đây (secret `QDRANT_URL`/`VECTOR_DB_BASIC_AUTH`). Lỗi connect → fail `/readyz`. |
| [`core_engine/config_schema.py`](../../core_engine/config_schema.py) | `params` là dict tự do (ok cho field connect nested); nhưng thêm **key top-level** mới phải thêm field schema, không thì parity fail. |

> **Cổng tự kiểm trước khi mở PR:** (1) golden test connect không đổi; (2) field mới map ở CẢ `from_env`
> + `to_vector_store_config` + `config.yaml`; (3) mcp đồng bộ; (4) `check_vectorstore_contract.py` pass;
> (5) KHÔNG sửa 3 call-site; (6) KHÔNG thêm `if` vào builder/normalize (thêm contributor thay thế).

---

## 1. Vấn đề (vì sao cần làm tốt hơn)

Lớp kết nối Qdrant hiện gom trong một hàm duy nhất:
[`core_engine/vectorstore/config.py:78` `remote_client_kwargs()`](../../core_engine/vectorstore/config.py).
Mỗi lần có **một cách connect mới**, ta phải **mổ lại chính hàm đó** — đó là vi phạm
Open/Closed (mở cho mở rộng, đóng cho sửa đổi).

Bằng chứng thực tế — hàm này đã bị sửa **3 lần** trong 1 ngày, mỗi lần thêm 1 mối quan tâm:

| Lần | Commit | Thêm gì | Sửa vào đâu |
|----|--------|---------|-------------|
| 1 | `73516e7` | ép port 443 cho Cloud Run | `normalize_remote_qdrant_url` (hardcode `if scheme == "https"`) |
| 2 | `1d5aef6` → `c96f6db` | `timeout` cho cold start | thân `remote_client_kwargs` |
| 3 | `aff869e` | HTTP Basic Auth (nginx) | thân `remote_client_kwargs` + thêm field + nhánh `if header` |

Các điểm cứng (re-check trên code hiện tại):

- **G-C1 — URL port hardcode**: `normalize_remote_qdrant_url` ([config.py:38](../../core_engine/vectorstore/config.py))
  chỉ biết `https→443`. Thêm scheme/cổng chuẩn khác (vd grpc, http qua proxy cổng 80) phải sửa hàm.
- **G-C2 — Auth bằng if/branch**: `remote_client_kwargs` tự rẽ nhánh `api_key` vs `basic_auth`.
  Thêm auth mới (bearer token, mTLS, header tùy biến, signature) = thêm nhánh `if` trong hàm core.
- **G-C3 — Hai code-path build config phải sửa song song**: field connection mới phải map ở **CẢ HAI**
  [`config.py:97` `from_env`](../../core_engine/vectorstore/config.py) **và**
  [`mapping.py:118` `to_vector_store_config`](../../core_engine/mapping.py) **và** thêm `${VAR}` vào `config.yaml`.
  Đã dính lỗi này: quên map `basic_auth` ở `to_vector_store_config` → local (`from_env`) chạy nhưng CI
  production fail 401 (fix `2a01f16`).
- **G-C4 — mcp-service có bản sao**: [`mcp-service/app/core/vectorstore.py`](../../../mcp-service/app/core/vectorstore.py)
  tự cài lại `_normalize_remote_url` + `_basic_auth_header` + nhánh timeout/header. Mỗi cách connect mới
  phải nhớ sửa **2 nơi**. (mcp độc lập theo thiết kế — xem §4.)

Hệ quả: lớp connect "phình" theo số cách connect; dễ sót (G-C3/G-C4); review nặng; mỗi PR đụng vào
hàm nóng dùng chung → rủi ro regress.

---

## 2. Nguyên tắc tham chiếu — registry rag-worker ĐÃ có

Codebase **đã** có sẵn primitive OCP đúng bài: [`core_engine/registry.py`](../../core_engine/registry.py).
Đây là khuôn mẫu cần áp dụng lại cho lớp connect, KHÔNG phát minh cơ chế mới.

`Registry[T]` cung cấp:
- `register(name, factory, *, override=False)` — đăng ký; **guard trùng tên** (phải `override=True` mới đè).
- `get(name)` / `available()` — resolve + liệt kê; lỗi kèm danh sách "đã có".
- **Lazy entry-point discovery** (`entry_point_group`) — bên thứ ba cắm thêm qua package metadata
  `[project.entry-points."rag_worker.<group>"]` **không cần import side-effect**; **built-in thắng khi trùng tên**.

Vectorstore provider đã dùng đúng primitive này:
[`vectorstore/registry.py:46` `register_backend(...)`](../../core_engine/vectorstore/registry.py) →
thêm provider mới (`weaviate`, `pgvector`...) chỉ cần `register_backend("weaviate", factory)`,
**không sửa `build_vector_store`**. Lớp connect cần đạt đúng tính chất đó: **thêm cách connect = đăng ký, không sửa builder.**

---

## 3. Thiết kế đề xuất (CHỐT hướng)

Tách lớp connect thành các **contributor** độc lập, đăng ký qua `Registry` — mỗi mối quan tâm
(url, timeout, api_key, basic_auth, …) là một đơn vị tháo-lắp.

### 3.1 Module mới `core_engine/vectorstore/connection.py`

```python
from core_engine.registry import Registry
from core_engine.vectorstore.config import VectorStoreConfig

# Contributor: đọc config, ĐÓNG GÓP vào kwargs cho AsyncQdrantClient/QdrantClient.
ClientKwargsContributor = Callable[[VectorStoreConfig, dict[str, Any]], None]

# CÙNG primitive với provider registry; cho phép plugin bên thứ ba qua entry-point.
_CONTRIBUTORS: Registry[ClientKwargsContributor] = Registry(
    "qdrant_connection", entry_point_group="rag_worker.qdrant_connection"
)

def register_connection_option(name, contributor, *, override=False):
    _CONTRIBUTORS.register(name, contributor, override=override)

def build_remote_client_kwargs(config: VectorStoreConfig) -> dict[str, Any]:
    """Orchestrator ĐÓNG cho sửa: chạy mọi contributor đã đăng ký. Thêm cách
    connect mới = register thêm contributor, KHÔNG đụng hàm này."""
    kwargs: dict[str, Any] = dict(config.options)
    for name in _CONTRIBUTORS.available():
        _CONTRIBUTORS.get(name)(config, kwargs)
    return kwargs
```

### 3.2 URL port: registry scheme → cổng ép (thay hardcode)

```python
# Thêm scheme/cổng chuẩn mới = thêm 1 entry, KHÔNG sửa logic normalize.
SCHEME_FORCED_PORT: dict[str, int] = {"https": 443}

def normalize_remote_qdrant_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or parsed.port is not None or not parsed.hostname:
        return url
    port = SCHEME_FORCED_PORT.get(parsed.scheme)
    return urlunparse(parsed._replace(netloc=f"{parsed.hostname}:{port}")) if port else url
```

### 3.3 Contributor built-in (đăng ký tường minh lúc import — built-in thắng entry-point)

```python
@_register("url")
def _contribute_url(cfg, kw):       kw["url"] = normalize_remote_qdrant_url(cfg.url) or None

@_register("timeout")
def _contribute_timeout(cfg, kw):   kw.setdefault("timeout", int(os.getenv("QDRANT_TIMEOUT", "30")))

@_register("api_key")
def _contribute_api_key(cfg, kw):   kw["api_key"] = cfg.api_key or None

@_register("basic_auth")
def _contribute_basic_auth(cfg, kw):
    header = basic_auth_header(cfg.basic_auth)
    if header:
        kw["headers"] = {"Authorization": header, **(kw.get("headers") or {})}
```

### 3.4 `VectorStoreConfig.remote_client_kwargs` rút thành wrapper mỏng

```python
def remote_client_kwargs(self) -> dict[str, Any]:
    from core_engine.vectorstore.connection import build_remote_client_kwargs
    return build_remote_client_kwargs(self)
```

→ **3 call-site giữ nguyên** (`providers/qdrant/remote.py`, `qdrant_contract.py` ×2 đang gọi
`**vector_config.remote_client_kwargs()`), không phải sửa.

---

## 4. mcp-service (consumer độc lập)

mcp-service KHÔNG dùng chung `core_engine` (thiết kế độc lập — ghép với rag-worker chỉ qua Qdrant).
Vì vậy **nhân bản pattern, không nhân bản code**: tạo `mcp-service/app/core/connection.py` với cùng
`Registry` + contributor (mcp có sẵn `Registry` riêng hoặc copy primitive nhẹ). Consumer chỉ cần
contributor `url` / `api_key` / `basic_auth` (không cần `timeout` write-path nếu không muốn).
`QdrantReader._remote_client` gọi `build_remote_client_kwargs(settings)` thay cho khối inline hiện tại.

---

## 4b. QUYẾT ĐỊNH: 2 nguồn riêng + 1 contract chung (KHÔNG lib code chung)

> **Status: CHỐT.** Lớp connect implement **2 bản riêng** (rag-worker `core_engine/vectorstore/connection.py`
> + mcp `app/core/connection.py`), khớp nhau qua **contract + golden test giống hệt**, **KHÔNG** tách module
> dùng chung.

### Vì sao không làm "1 lib code chung"
- **Build context cô lập**: compose build `context: ./src/rag-worker` và `./src/mcp-service`; Dockerfile mcp
  chỉ `COPY app ./app` / `COPY config.yaml`. Module ở `src/libs/` hay repo-root **Docker build không thấy** →
  phải đổi context → repo-root + sửa Dockerfile + `requirements.txt` + 2 compose + CI cho **cả hai** service.
- **Config 2 bên khác nhau** (`VectorStoreConfig` ≠ `McpSettings`) → lib phải nhận `Protocol`, mỗi service
  vẫn cần 1 adapter. Bỏ ~30 dòng nhưng thêm: package + packaging coupling + Protocol + 2 adapter + sửa build/CI.
  **Lỗ**, và mcp mất tính độc lập.
- **Tiền lệ repo**: `point_id`/`index_id` mcp đã **tự copy** (`app/core/vectorstore.py` — "BẢN RIÊNG mcp"),
  cross-service khớp nhau qua [`docs/contracts.md`](../../../../docs/contracts.md) + `check_vectorstore_contract.py`
  (so 2 config, không share code). Connect theo đúng mô hình đó.
- **Khi nào mới chuyển sang lib chung:** chỉ khi team dựng hẳn hạ tầng shared-package (private index / monorepo
  packaging) cho nhiều thứ — lúc đó chi phí packaging đã trả sẵn.

### Connection conformance — hợp đồng 2 bản PHẢI khớp (thay cho share code)
Cùng input → **cùng** kwargs ở cả 2 service. Đây là contract chống drift:

| Quy tắc | Hành vi BẮT BUỘC giống nhau |
|---------|------------------------------|
| URL https thiếu port | ép `:443` (`SCHEME_FORCED_PORT["https"]=443`) |
| URL có port / scheme khác | giữ nguyên |
| `api_key` rỗng | `api_key=None` (không gửi header api-key) |
| `basic_auth="user:pass"` | thêm `headers["Authorization"]="Basic "+b64(user:pass)` |
| `basic_auth` rỗng / không có `:` | không thêm header |
| `timeout` | rag-worker default 30s (env `QDRANT_TIMEOUT`); mcp tùy chọn nhưng nếu set phải cùng tên env |
| `options` | là base, contributor đè lên (giữ thứ tự ưu tiên) |
| Thêm contributor mới | qua `register_*`, KHÔNG sửa builder/normalize |

### Chống drift bằng GOLDEN TEST giống hệt (không phải share code)
- Cùng một bảng case (input config → kwargs mong đợi) **lặp y hệt** trong test suite của **cả hai** service:
  `rag-worker/tests/.../test_qdrant_connection.py` và `mcp-service/tests/.../test_qdrant_connection.py`.
- Sửa quy tắc connect ở 1 bên mà quên bên kia → golden đỏ ở service còn lại → **CI bắt drift**.
- Đây là cùng cơ chế `check_vectorstore_contract.py` đang dùng cho config: **đối chiếu, không gộp code.**

---

## 5. Kế hoạch triển khai KHÔNG phá codebase

Thực hiện theo phase, mỗi phase **giữ hành vi y hệt** → CI luôn xanh.

1. **P0 — Golden test trước (an toàn lưới)**: viết test chụp output `remote_client_kwargs()` hiện tại cho
   đủ 3 kịch bản: Cloud Run `https` không port; nginx `http://host:80` + basic auth; in-process (không url).
   Đây là hợp đồng phải bất biến qua refactor.
2. **P1 — Thêm `connection.py`** với contributor sao cho output **trùng từng byte** golden ở P0. Giữ public
   `normalize_remote_qdrant_url`, `basic_auth_header` (test/import cũ không vỡ).
3. **P2 — Đổi `remote_client_kwargs` thành wrapper** gọi `build_remote_client_kwargs`. Chạy lại golden + suite.
4. **P3 — mcp mirror** (§4) → import smoke + `scripts/check_vectorstore_contract.py` parity.
5. **P4 — Verify thật 1 lần** với endpoint Basic Auth qua **cả hai** path build config (`from_env` +
   `to_vector_store_config`) — chốt G-C3 không tái diễn.
6. **P5 — Docs + khai báo `entry_point_group`** trong `pyproject` (nếu mở cho plugin ngoài).

### Bất biến BẮT BUỘC (acceptance)
- Output `remote_client_kwargs()` **không đổi** cho mọi kịch bản hiện có (golden P0).
- Giữ **thứ tự ưu tiên** hiện tại: `options` là base, contributor đè lên — kiểm bằng golden, đừng đổi ngầm.
- KHÔNG đổi tên field `VectorStoreConfig` (`url`/`api_key`/`basic_auth`) và env (`VECTOR_DB_*`, `QDRANT_TIMEOUT`).
- KHÔNG sửa 3 call-site dựng client.
- Field connection mới vẫn phải map ở **cả** `from_env` **và** `to_vector_store_config` + `config.yaml` (G-C3).

---

## 6. Hướng dẫn dev: thêm một cách connect MỚI (không phá core)

Ví dụ thêm **Bearer token** auth — chỉ cần **viết + đăng ký**, không đụng builder:

```python
# core_engine/vectorstore/auth_bearer.py  (hoặc package plugin bên thứ ba)
from core_engine.vectorstore.connection import register_connection_option

def _bearer(cfg, kw):
    token = os.getenv("VECTOR_DB_BEARER", "").strip()
    if token:
        kw["headers"] = {"Authorization": f"Bearer {token}", **(kw.get("headers") or {})}

register_connection_option("bearer", _bearer)
```

- Thêm **scheme/cổng** mới: chèn 1 entry vào `SCHEME_FORCED_PORT`, không sửa `normalize`.
- **Plugin ngoài** (không sửa repo core): khai báo entry-point
  `[project.entry-points."rag_worker.qdrant_connection"]` → nạp lazy lúc build; **built-in thắng nếu trùng tên**.
- Cần field config mới cho auth đó? Ưu tiên đi qua **env trong contributor** (như ví dụ) hoặc `options`
  để **không** phải sửa dataclass + 2 path build (tránh G-C3). Chỉ thêm field vào `VectorStoreConfig`
  khi thật sự cần là "first-class config" — và khi đó nhớ map cả 2 path.

### Quy tắc vàng (đừng làm sai như hiện tại)
- ❌ **Không** thêm `if`/nhánh mới vào `build_remote_client_kwargs` hay `normalize_remote_qdrant_url`.
- ✅ Thêm cách connect = **một contributor mới + `register_connection_option`** (hoặc entry-point).
- ✅ Mỗi contributor đóng gói trọn 1 mối quan tâm, không phụ thuộc contributor khác (ghi key rời nhau).
- ✅ Có cách connect mới ⇒ **bổ sung golden test** cho kịch bản đó.

---

## 7. Tóm tắt gaps

| ID | Mức | Vấn đề | File | Trạng thái |
|----|-----|--------|------|------------|
| G-C1 | Trung bình | URL port hardcode `https→443` | `vectorstore/config.py:38` | OPEN |
| G-C2 | Cao | Auth bằng if/branch trong hàm core | `vectorstore/config.py:78` | OPEN |
| G-C3 | Cao | 2 path build config phải sửa song song (đã từng gây 401) | `config.py:97` + `mapping.py:118` | OPEN |
| G-C4 | Trung bình | mcp-service nhân bản lớp connect | `mcp-service/app/core/vectorstore.py` | OPEN |

Đích đến: **thêm cách connect Qdrant = đăng ký contributor/plugin, không sửa builder** — đúng tính chất
mà provider registry của rag-worker đã đạt được.
