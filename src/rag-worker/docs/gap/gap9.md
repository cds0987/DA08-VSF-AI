# GAP v9 — rag-worker: mismatch file type whitelist giữa document-service và rag-worker

Scope: `src/rag-worker` + `src/document-service` — parser whitelist, ingest pipeline.
Grounding: code review tại `nguyendev` HEAD (2026-06-09) — đọc
`document-service/app/application/use_cases/documents/common.py` (ALLOWED_EXTENSIONS) và
`rag-worker/app/infrastructure/external/local_parser.py` (_DEFAULT_READER_IMPL).
Status: **OPEN** — gap G9-1 là bug latent hiện diện trong production path, chưa fix.

---

## Tóm tắt

| ID | Mức | Vấn đề | Trạng thái |
|----|-----|---------|------------|
| G9-1 | **P1** | `csv` có trong `ALLOWED_EXTENSIONS` (doc-service) nhưng không có reader trong `_DEFAULT_READER_IMPL` (rag-worker) → upload thành công, ingest FAILED | **OPEN** |
| G9-2 | P3 | `html`/`htm`/`xls`/image có reader ở rag-worker nhưng bị chặn ở doc-service → rag-worker hỗ trợ lặng lẽ hơn whitelist doc-service | OPEN |
| G9-3 | P2 | Không có parity contract/test giữa hai danh sách → gap có thể tái xuất hiện mà CI không bắt | OPEN |

---

## Đối chiếu hai whitelist (2026-06-09)

### document-service `ALLOWED_EXTENSIONS`
File: `src/document-service/app/application/use_cases/documents/common.py:9`

```python
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"}
```

### rag-worker `_DEFAULT_READER_IMPL`
File: `src/rag-worker/app/infrastructure/external/local_parser.py:318`

```python
_DEFAULT_READER_IMPL = {
    "md":   "text",
    "txt":  "text",
    "html": "html_strip",
    "htm":  "html_strip",
    "docx": "docx_xml",
    "pdf":  "pymupdf",
    "pptx": "markitdown",
    "xls":  "markitdown",
    "xlsx": "markitdown",
    # + png, jpg, jpeg, tif, tiff, bmp, gif, webp → reader "image"
}
```

### So sánh chi tiết

| File type | doc-service cho phép | rag-worker có reader | Hướng gap |
|-----------|---------------------|----------------------|-----------|
| `pdf`     | ✅ | ✅ | — |
| `docx`    | ✅ | ✅ | — |
| `txt`     | ✅ | ✅ | — |
| `xlsx`    | ✅ | ✅ | — |
| `pptx`    | ✅ | ✅ | — |
| `md`      | ✅ | ✅ | — |
| **`csv`** | ✅ **cho phép** | ❌ **không có reader** | **G9-1 — bug** |
| `html`/`htm` | ❌ chặn | ✅ có reader | G9-2 |
| `xls`     | ❌ chặn | ✅ có reader | G9-2 |
| `png`/`jpg`/... (image) | ❌ chặn | ✅ có reader + OCR | G9-2 |

---

## G9-1 — `csv` upload thành công nhưng ingest FAILED (P1 · bug latent)

**Vấn đề:**
`ALLOWED_EXTENSIONS` ở document-service (`common.py:9`) chứa `"csv"`. Admin có thể upload file
`.csv` thành công — doc-service lưu GCS, tạo row DB với `status=queued`, publish event
`doc.ingest` lên NATS.

Rag-worker nhận event, gọi `LocalFileParser.parse(file_type="csv", ...)`. Tại
`local_parser.py:419`, method `_reader_for_suffix` tra `_DEFAULT_READER_IMPL.get("csv")` → trả
`None` → raise ngay:

```python
raise ValueError(f"unsupported file_type for local parser: csv")
```

Exception leo lên `IngestDocumentUseCase.process_next_job` → `classify_ingest_error` phân loại
**permanent** (không phải `TransientAIError` hay `CaptionFallbackThresholdExceededError`) →
`fail_job` đặt doc **FAILED terminal**.

Kết quả người dùng thấy: upload 202 "Ingestion started", nhưng sau đó trạng thái chuyển
`failed` mà không có thông báo rõ ràng. Reconciler (G8-4) sẽ không retry do error class
permanent. File CSV vẫn tồn tại trên GCS nhưng không bao giờ được index.

**Tại sao `csv` có trong `ALLOWED_EXTENSIONS` nhưng không có reader?**
Hai list được phát triển độc lập — doc-service kiểm soát upload boundary, rag-worker kiểm soát
parse capability. Không có contract chung buộc hai bên phải khớp; `csv` được thêm vào
`ALLOWED_EXTENSIONS` mà không có reader tương ứng.

**Fix — hai lựa chọn, chọn một:**

**(A) Thêm CSV reader vào rag-worker (mở rộng capability):**
CSV là plain text với delimiter cấu trúc — đọc bằng stdlib `csv` rồi render markdown table
hoặc flat text.

```python
# local_parser.py — thêm vào _READER_REGISTRY và _DEFAULT_READER_IMPL

def _read_csv_file(path: Path) -> _ParseStep:
    import csv as _csv
    _ensure_source_file(path)
    lines: list[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = _csv.reader(fh)
        for row in reader:
            lines.append(" | ".join(cell.strip() for cell in row))
    return _text_step("\n".join(lines))

_READER_REGISTRY.register("csv", lambda params: _read_csv_file)

_DEFAULT_READER_IMPL: dict[str, str] = {
    ...
    "csv": "csv",    # thêm dòng này
    ...
}
```

Ưu: CSV được index, tìm kiếm được nội dung bảng. Nhược: CSV dạng bảng pivot/formula phức tạp
có thể cho kết quả chunking kém — cần eval trên tập validation.

**(B) Xóa `csv` khỏi `ALLOWED_EXTENSIONS` (thu hẹp whitelist):**
Nếu CSV không phải use-case ưu tiên, loại nó ra để fail sớm tại upload thay vì fail muộn tại ingest.

```python
# common.py
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "xlsx", "pptx", "md"}  # bỏ "csv"
```

Ưu: nhất quán ngay, không cần reader mới. Nhược: mất khả năng upload CSV (cần thông báo admin).

> **Khuyến nghị:** Chọn **(A)** — CSV là định dạng phổ biến cho tài liệu nội bộ (bảng phân
> công, danh sách nhân viên, báo cáo). Reader stdlib, không cần dependency mới, ít rủi ro.
> Chạy eval gate (golden queries) trước khi merge để xác nhận recall không tụt.

---

## G9-2 — rag-worker hỗ trợ nhiều định dạng hơn whitelist doc-service (P3)

**Vấn đề:**
Rag-worker có reader cho `html`/`htm`, `xls`, và 8 định dạng ảnh (`png`, `jpg`, `jpeg`, `tif`,
`tiff`, `bmp`, `gif`, `webp`) với OCR qua AI gateway — nhưng doc-service chặn tất cả tại upload.

Đây **không phải bug** (doc-service block trước, rag-worker không bao giờ nhận các file này qua
pipeline chuẩn). Nhưng nếu ai đó gọi rag-worker trực tiếp qua API internal hoặc thêm format vào
`ALLOWED_EXTENSIONS` sau này mà không biết reader đã sẵn, capability bị bỏ phí.

**Định dạng rag-worker hỗ trợ sẵn nhưng doc-service chặn:**

| Format | Reader | Ghi chú |
|--------|--------|---------|
| `html`, `htm` | `html_strip` — stdlib HTMLParser | Hữu ích cho doc nội bộ export từ wiki/confluence |
| `xls` | `markitdown` | Excel cũ; đã có `xlsx` rồi |
| `png`, `jpg`, `jpeg`, `tif`, `tiff`, `bmp`, `gif`, `webp` | `image` → OCR qua Gemini Vision | Ảnh scan tài liệu; chi phí OCR cao |

**Fix:** Không cần làm ngay. Ghi nhận để tham khảo khi mở rộng whitelist doc-service.
Khi thêm format mới vào `ALLOWED_EXTENSIONS`, kiểm tra `_DEFAULT_READER_IMPL` trước khi merge.

---

## G9-3 — Không có parity contract/test giữa hai whitelist (P2)

**Vấn đề:**
Không có điểm nào trong CI bắt được việc hai danh sách lệch nhau. G9-1 tồn tại vì:
- `ALLOWED_EXTENSIONS` (doc-service) và `_DEFAULT_READER_IMPL` (rag-worker) là hai hằng số
  độc lập trong hai service khác nhau.
- Không có test nào verify rằng mọi extension doc-service cho phép đều có reader tương ứng.

Nếu fix G9-1 theo hướng (A) nhưng sau đó ai thêm format mới vào một bên mà quên bên kia, bug
sẽ tái xuất hiện mà CI không bắt.

**Fix — parity contract:**

**(1) Thêm integration test trong rag-worker:**

```python
# tests/infrastructure/external/test_parser_parity.py

DOCUMENT_SERVICE_ALLOWED = {"pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"}

def test_all_document_service_extensions_have_reader():
    """Mọi extension doc-service cho phép phải có reader trong rag-worker."""
    from app.infrastructure.external.local_parser import _DEFAULT_READER_IMPL
    missing = DOCUMENT_SERVICE_ALLOWED - set(_DEFAULT_READER_IMPL.keys())
    assert not missing, (
        f"Extensions được doc-service cho phép nhưng rag-worker chưa có reader: {missing}. "
        "Thêm reader vào _DEFAULT_READER_IMPL hoặc xóa extension khỏi ALLOWED_EXTENSIONS."
    )
```

Test này fail ngay ở CI nếu hai danh sách lệch nhau. Khi cập nhật một bên, CI buộc cập nhật bên kia.

**(2) Comment cross-reference trong code:**

```python
# common.py (document-service)
# QUAN TRỌNG: mọi extension ở đây phải có reader tương ứng trong
# rag-worker/app/infrastructure/external/local_parser.py → _DEFAULT_READER_IMPL
# Test parity: rag-worker/tests/infrastructure/external/test_parser_parity.py
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"}
```

---

## Thứ tự fix khuyến nghị

```
G9-1A  thêm csv reader + _DEFAULT_READER_IMPL["csv"]   → fix bug latent ngay
  └─ kèm eval gate (golden queries) trước khi merge
G9-3   parity test test_parser_parity.py               → CI bắt mọi mismatch tương lai
G9-2   (tùy chọn) mở whitelist doc-service cho html/image  → sau khi có nhu cầu thực tế
```

---

## Missing tests cần bổ sung

| Test | File đề xuất | Covers |
|------|-------------|--------|
| Parse file `.csv` hợp lệ → trả markdown không rỗng | `tests/infrastructure/external/test_local_parser.py` | G9-1 |
| Parse file `.csv` rỗng → `EmptyIngestResultError` qua use-case | `tests/application/ingestion/test_ingest_document_use_case.py` | G9-1 |
| Mọi extension trong `ALLOWED_EXTENSIONS` đều có reader | `tests/infrastructure/external/test_parser_parity.py` | G9-3 |

---

## Trước khi fix: đọc nền bắt buộc

- **[handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md) §1**: reader mới chỉ dùng stdlib hoặc
  dependency đã có trong `requirements.txt`; không kéo thêm package mà không cập nhật
  `Dockerfile` + `requirements.txt`.
- **[handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md) §2 Pipeline quality gate**: thêm CSV
  reader đụng parse → chunking → embed → search pipeline → **eval gate bắt buộc** (golden
  queries) trước khi merge. Không merge chỉ bằng unit test parser.
- **CI không có Postgres**: test G9-1/G9-3 là unit/integration test thuần Python, không cần DB
  hay Qdrant — chạy được trong CI hiện tại.
