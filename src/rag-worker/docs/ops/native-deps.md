# Native deps (Windows) + markitdown có thừa không?

> Ghi lại sự cố gặp khi chạy e2e validation corpus với provider thật trên máy
> Windows (Python 3.13), và phân tích dependency `markitdown`/`onnxruntime`.

## 1. Triệu chứng

Chạy parse/e2e trên Windows fail dù `pip install` báo thành công:

```
PyMuPDF   : ImportError: DLL load failed while importing _extra: The specified module could not be found.
markitdown: ImportError: DLL load failed while importing onnxruntime_pybind11_state: The specified module could not be found.
```

Hệ quả: 2 PDF (`security_incident.pdf`, `fire_evacuation_scanned.pdf`) và pptx/xlsx
trong `eval/validation` không parse được → `tests/e2e` validation-corpus fail. **Không
liên quan tới refactor config-driven** (wiring chạy đúng; xem `docs/refactor/`).

## 2. Nguyên nhân gốc

Thiếu **Microsoft Visual C++ Redistributable** ở cấp hệ điều hành — `System32` không có
`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`. Các extension native
(PyMuPDF `_extra`, `onnxruntime_pybind11_state`) link tới MSVC runtime; thiếu nó →
"The specified module could not be found".

→ **Không fix được bằng pip** (gói Python đã cài đúng). Đây là dependency cấp OS.

## 3. `onnxruntime` từ đâu ra (vì sao có nó)

`onnxruntime` KHÔNG phải thứ pipeline cần trực tiếp — nó là **transitive dep của
`markitdown`**:

```
markitdown[pptx,xls,xlsx]
   └─ magika          (Google: nhận diện loại file bằng model ML)
        └─ onnxruntime (chạy model ONNX của magika)
        └─ python-dotenv
```

Xác nhận bằng `pip show`: `onnxruntime` Required-by `magika`; `magika` Required-by
`markitdown`. (Tiện thể: `python-dotenv` trong env cũng chỉ là transitive của `magika`
— app KHÔNG load `.env`, nên muốn dùng `.env` phải truyền qua môi trường, vd
`docker --env-file`.)

`markitdown` chỉ được dùng ở **một chỗ**: `LocalFileParser._convert_with_markitdown`
cho `suffix in {pptx, xls, xlsx}`. Các định dạng khác (md/txt/html/docx/pdf/ảnh) dùng
reader tự viết, không qua markitdown.

## 4. Cách xử lý

### Khuyến nghị: chạy trong Docker (Linux)
Image `python:3.13-slim-bookworm` có sẵn glibc/toolchain → PyMuPDF + onnxruntime chạy
bình thường, không cần VC++ runtime. Đã thêm `.dockerignore` để build không vướng
`.pytest_cache` (Access denied trên Windows).

```bash
docker build -t rag-worker:eval src/rag-worker
# e2e thật (provider lấy từ .env ở repo root; corpus validation đã nằm trong image):
docker run --rm --env-file .env -e RAG_EVAL_REAL_PROVIDER=1 -e APP_ENV=development \
  rag-worker:eval python -m pytest tests/e2e -q -ra
```

### Dev trên Windows (nếu muốn chạy native)
Cài VC++ Redistributable x64 — fix CẢ PyMuPDF lẫn onnxruntime một lần:
```powershell
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

## 5. `markitdown` có thừa không?

**Không thừa hoàn toàn, nhưng kéo theo phần thừa thật sự.**

- **Đang được dùng thật:** parse `pptx/xls/xlsx`. Corpus validation có
  `remote_work_policy.pptx` + `travel_per_diem.xlsx`. Nếu các định dạng này **in-scope**
  thì markitdown là thứ duy nhất xử lý chúng → không bỏ được vô điều kiện.
- **Phần thừa:** subtree `magika → onnxruntime` (~vài trăm MB + DLL fragility) tồn tại
  chỉ để **đoán loại file** — mà pipeline KHÔNG cần, vì parser luôn nhận `file_type`
  tường minh. Ta trả "thuế" ML cho một năng lực không dùng.

**Quyết định theo product:**

| Tình huống | Hành động |
|---|---|
| pptx/xls/xlsx KHÔNG phải định dạng thật cần ingest | **Bỏ `markitdown`** khỏi requirements → gỡ luôn magika/onnxruntime, image nhẹ hẳn |
| Cần pptx/xlsx nhưng muốn nhẹ + hết DLL fragility | Thay `markitdown` bằng `python-pptx` (pptx) + `openpyxl` (xlsx) + `xlrd` (xls); nhất quán với cách hand-roll reader `docx` hiện có; gỡ được onnxruntime/magika |
| Chấp nhận hiện trạng | Giữ `markitdown`, chỉ cần chạy trong Docker (hoặc cài VC++ redist trên Windows) |

**Khuyến nghị:** trước mắt dùng Docker để chạy/đánh giá. Trung hạn, nếu pptx/xlsx thực
sự cần, thay `markitdown` bằng `python-pptx`/`openpyxl` để loại bỏ onnxruntime — vừa
nhẹ image, vừa hết phụ thuộc native dễ vỡ trên Windows.
