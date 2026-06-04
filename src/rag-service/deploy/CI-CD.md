# CI/CD — rag-service

> DevOps/CI-CD của riêng `src/rag-service`. Pipeline + các sự cố đã gặp và cách phòng ngừa.

## Pipeline

File: [`.github/workflows/rag-service-ci.yml`](../../../.github/workflows/rag-service-ci.yml)

- **Trigger:** `push` / `pull_request` chỉ khi đụng `src/rag-service/**` hoặc chính file workflow (path-filtered → service khác không kích hoạt).
- **Job `test`** (working-directory `src/rag-service`):
  1. checkout + `setup-python@v5` (Python **3.13**, `cache: pip` theo `requirements.txt`).
  2. `pip install -r requirements.txt`.
  3. `pytest tests -q` (env `APP_ENV=development`, `AI_PROVIDER=offline`).
- Migration loop được kiểm gián tiếp qua `tests/infrastructure/db/test_migration.py` (chạy `alembic upgrade head` + `downgrade base` in-process), nên không cần step riêng.
- Image build / k8s rollout: xem [`README.md`](./README.md).

---

## Sự cố & bài học

### 2026-06-04 — Dependency pin không có wheel cho Python 3.13 ⇒ CI build fail

**Triệu chứng:** job CI treo ở "Install dependencies" ~8 phút rồi **fail** với
`Failed to build installable wheels for some pyproject.toml based projects: asyncpg, pydantic-core`.
Không phải "chậm" — là **không build được**.

**Nguyên nhân gốc:** `requirements.txt` pin version cũ (chọn cho Python ≤3.12) trong khi
CI + Dockerfile chạy **Python 3.13**. Hai package biên dịch native **không có wheel `cp313`**
nên pip phải build từ source qua `pyproject.toml`, và build vỡ trên 3.13:

- `asyncpg==0.29.0` — C extension, gcc lỗi vì CPython 3.13 đổi API:
  ```
  asyncpg/pgproto/pgproto.c: error: too few arguments to function ‘_PyLong_AsByteArray’
  error: command '/usr/bin/gcc' failed with exit code 1
  ```
- `pydantic-core==2.18.2` (kéo theo `pydantic==2.7.1`) — Rust/maturin lỗi vì PyO3 quá cũ:
  ```
  error: the configured Python interpreter version (3.13) is newer than
         PyO3's maximum supported version (3.12)
  ```

Nghịch lý: `.venv` local (Python 3.13) lại chạy được + test xanh — vì venv đã drift sang
bản **mới hơn** (có wheel cp313). Tức `requirements.txt` đã lệch khỏi thực tế đang chạy.

**Cách sửa:** giữ Python 3.13 (khớp Dockerfile + venv) và đồng bộ `requirements.txt` sang
version **có wheel cp313**, xác minh từng cái bằng `pip download --only-binary=:all:`:

| Package | Cũ (no cp313 wheel) | Mới (có cp313/abi3 wheel) |
|---|---|---|
| asyncpg | 0.29.0 | 0.31.0 |
| pydantic | 2.7.1 | 2.13.4 |
| pydantic-core (transitive) | 2.18.2 | 2.46.4 |
| fastapi | 0.111.0 | 0.136.3 |
| uvicorn | 0.29.0 | 0.48.0 |
| sqlalchemy | 2.0.30 | 2.0.50 |
| alembic | 1.13.1 | 1.18.4 |
| qdrant-client | 1.9.1 | 1.18.0 |
| pymupdf | 1.24.3 | 1.27.2.3 (abi3) |
| httpx | 0.27.0 | 0.28.1 |

Kết quả: install toàn wheel → nhanh, không cần compiler; CI xanh; `44 passed, 1 skipped`.

**Quy tắc phòng ngừa (bắt buộc khi đụng dep nhị phân hoặc bump Python):**

1. **Khớp interpreter ↔ wheel:** mọi dep biên dịch native (asyncpg, pydantic-core, pymupdf,
   grpcio…) phải có wheel cho **đúng** phiên bản Python của CI/Dockerfile. Đổi Python = kiểm lại wheel.
2. **Xác minh trước khi pin:** `pip download --only-binary=:all: --python-version <ver> <pkg>`;
   nếu pip phải build từ sdist (`Building wheel … (pyproject.toml)`) → pin sai, chọn version khác.
3. **Đồng bộ `requirements.txt` với môi trường chạy thật** — không để venv local drift khỏi pin.
4. **CI là nguồn sự thật**, không phải venv local: venv có thể đã có sẵn bản mới nên che lỗi.
5. Cùng Python cho **cả ba**: CI (`setup-python`), Dockerfile (`FROM python:<ver>`), venv dev.

---

### 2026-06-04 (follow-up) — Đồng bộ driver DB + parser dep với code thật (commit `75dd288`)

Sau post-mortem trên, review gap3 phát hiện `requirements.txt` lệch khỏi code/deploy thật:

- **`asyncpg` → `psycopg[binary]==3.3.4`.** Repo metadata dùng **sync** SQLAlchemy (`create_engine`
  + `asyncio.to_thread`), còn deploy cấu hình `postgresql+psycopg://`. `asyncpg` (driver async) **không
  dùng được** với sync engine ⇒ là dead dependency. Bảng pin ở §"Cách sửa" phía trên giữ nguyên giá trị
  **lịch sử**; trạng thái hiện tại của driver DB là `psycopg[binary]`. `runtime.validate_metadata_backend`
  nay **fail-fast** nếu URL PostgreSQL không phải `postgresql+psycopg://`.
- **`markitdown[all]` → `markitdown[pptx,xls,xlsx]`.** Extra `[all]` kéo `youtube-transcript-api~=1.0.0`
  **không có bản thỏa mãn** (PyPI nhảy 0.6.x → 1.2.x) ⇒ resolution vỡ, chưa kể azure/speechrecognition/
  pandas vô ích. Thu hẹp về đúng extras phục vụ `pptx/xls/xlsx`; đã xác minh
  `pip install --dry-run "markitdown[pptx,xls,xlsx]==0.1.6" "openai==1.59.6"` resolve sạch, **giữ nguyên
  `openai==1.59.6`** (không conflict).

**Bổ sung quy tắc phòng ngừa:**

6. **Pin phải khớp code path đang chạy**, không chỉ "package có tồn tại": driver async vs sync engine,
   extras thực sự được `import`. Một dep không được code dùng tới = nợ, không phải an toàn.
7. **Extras rộng (`[all]`) là bẫy resolution**: chỉ khai báo extra thật sự cần; verify bằng
   `pip install --dry-run` cùng *toàn bộ* pin khác để bắt conflict transitive sớm.
