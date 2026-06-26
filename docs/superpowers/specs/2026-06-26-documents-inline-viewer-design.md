# Documents — viewer nhúng in-page (Open File)

Ngày: 2026-06-26
Scope: frontend admin (`src/frontend/admin/app/pages/documents/[id].vue`). Backend không đổi.

## Bối cảnh / vấn đề

Sau fix proxy-stream (`GET /documents/{id}/file/raw`), "Open File" mở **tab mới** với
object-URL → URL hiển thị thành `blob:https://vsfchat.cloud/<uuid>`. User muốn xem file
**ngay trên trang** `/admin/documents/{id}` (giống Google Drive): không nhảy tab, không đổi
URL, render trực tiếp trong trang.

## Mục tiêu

- Bấm "Open File" → bật **khung viewer nhúng** trong trang detail; URL giữ nguyên.
- PDF / ảnh / text render inline trong khung.
- Office (docx/xlsx/pptx) → fallback card + nút Tải về.
- Không `window.open`, không điều hướng `window.location` sang blob URL.
- Không convert server-side, không thêm lib render office client-side. Giữ nhẹ.

## Phi mục tiêu

- Không đụng backend (tái dùng `/file/raw` + `documentService.getFileBlob`).
- Không preview inline cho office (chỉ tải về).
- Không thêm test runner (vitest) cho admin.

## Thiết kế

### Bố trí
Khi viewer bật, nó thay thế **thẻ status tổng quan** ở cột `lg:col-span-2`; panel
"Source metadata" bên phải giữ nguyên. Viewer gồm header (tên file + nút đóng X) và vùng
nội dung cuộn cao ~70vh. Khi đóng → quay lại thẻ status.

### Phân loại render — helper thuần
`previewMode(fileType: string): 'pdf' | 'image' | 'text' | 'download'`

- `pdf` → `'pdf'`
- `png|jpg|jpeg|gif|webp` → `'image'`
- `txt|md|csv` → `'text'`
- còn lại → `'download'`

Khớp với `_INLINE_TYPES` của backend (`get_document_file_stream_use_case.py`). Chuẩn hoá
input: `trim().toLowerCase().replace(/^\./, '')`.

### Luồng dữ liệu
1. Click "Open File" → `openPreview()`:
   - set `previewState = 'loading'`, hiển thị khung + spinner.
   - `blob = await documentService.getFileBlob(id)`.
   - `mode = previewMode(doc.file_type)`.
   - `mode === 'text'` → `previewText = await blob.text()`, `previewState = 'ready'`.
   - `mode` pdf/image → `previewObjectUrl = URL.createObjectURL(blob)`, `previewState = 'ready'`.
   - `mode === 'download'` → `previewState = 'unsupported'` (giữ blob để nút Tải về dùng).
2. Render theo `mode`:
   - pdf → `<iframe :src="previewObjectUrl">` (blob chỉ là src iframe, top-level URL không đổi).
   - image → `<img :src="previewObjectUrl">`.
   - text → `<pre>{{ previewText }}</pre>` cuộn.
   - download → fallback card "Không thể xem trước định dạng này" + nút Tải về.

### Tải về (office / fallback)
`downloadFile()`: dùng blob đã fetch (hoặc fetch nếu chưa có) → `URL.createObjectURL` →
tạo `<a download="doc.name">`, `a.click()`, rồi revoke. Không `window.location`, không tab mới.

### Vòng đời & lỗi
- Revoke `previewObjectUrl` khi: đóng viewer, mở file khác, `onUnmounted`. Reset `previewText`/blob.
- Lỗi fetch (403/404/503) → `previewState = 'error'`, hiển thị `getApiErrorMessage(...)` trong khung.
- Khung có spinner ở `previewState === 'loading'`.

### State (ref)
- `previewState: 'idle' | 'loading' | 'ready' | 'unsupported' | 'error'`
- `previewObjectUrl: string | null`
- `previewText: string | null`
- `previewBlob: Blob | null`
- `previewError: string | null`

Nút "Open File" disabled khi `previewState === 'loading'`.

## Test
Phần này thuần presentation; admin chỉ có Playwright e2e (cần backend + file thật). Helper
`previewMode` là pure function dễ đọc/kiểm. Không dựng vitest trong scope này — ghi rõ
test-gap trong PR. Verify thủ công: pdf/ảnh/txt render inline cùng URL; docx hiện fallback +
tải về; không xuất hiện URL `blob:` trên thanh địa chỉ.

## Rủi ro
- Trình duyệt cũ có thể không render PDF trong iframe blob → chấp nhận (fallback: nút Tải về vẫn có).
- File lớn: đã giới hạn upload 50MB ở backend → fetch toàn bộ chấp nhận được.
