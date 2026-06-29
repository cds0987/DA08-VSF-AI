# Plan — Chat citation "Open file" mở qua URL vsfchat (không nhảy GCS)

> Plan để GPT 5.5 implement. Phạm vi: **Option A** — chỉ đổi nút Open/Download của
> `SourcePanel`, GIỮ NGUYÊN viewer inline trong panel. Diff nhỏ nhất, đúng gốc.

## Vấn đề (root cause)

`src/frontend/chat/app/components/SourcePanel.vue` lấy URL file qua
`documentService.getDocumentFile()` → trả về **presigned GCS** (`result.url`).
Nút "Mở tài liệu gốc" (ExternalLink) + "Tải xuống" + các link trong thẻ
fallback/error đều `:href="sourceUrl"` → bấm là nhảy thẳng `storage.googleapis.com`.
PDF thì GCS render thô, DOCX (và nhiều định dạng khác) bị ép tải về.

Backend ĐÃ có sẵn (làm cho admin, chat chưa migrate):

- `GET /documents/{id}/file/preview` — inline, office→PDF qua Gotenberg,
  `Content-Disposition: inline`. (`documents.py:194`)
- `GET /documents/{id}/file/raw` — bản gốc, `attachment`. (`documents.py:235`)

Cả hai đi qua gateway cùng domain vsfchat + cần header auth → phải gọi bằng axios
(interceptor gắn `Authorization`), rồi tạo **object URL** (`blob:https://vsfchat…`)
để `window.open` / download. Đây đúng pattern admin đã dùng và guardrail
`document-file-view-proxy-stream` yêu cầu (KHÔNG đưa presigned GCS cho trình duyệt).

## Thay đổi

### 1. `src/frontend/chat/app/lib/api/documentService.ts`

Thêm 2 method (copy nguyên từ admin `documentService.ts`):

```ts
// Inline preview: office đã convert -> application/pdf. Mở tab blob:vsfchat…
async getPreviewBlob(documentId: string): Promise<Blob> {
  const response = await axiosClient.get<Blob>(`/${documentId}/file/preview`, {
    service: 'document',
    responseType: 'blob',
  })
  return response.data
},
// Bản gốc để tải về (attachment).
async getFileBlob(documentId: string): Promise<Blob> {
  const response = await axiosClient.get<Blob>(`/${documentId}/file/raw`, {
    service: 'document',
    responseType: 'blob',
  })
  return response.data
},
```

### 2. `SourcePanel.vue`

Mục tiêu: thay 5 chỗ `:href="sourceUrl"` (header Open, header Download, error
Open, fallback Open, fallback Download) bằng handler dùng blob proxy-stream.
GIỮ `getDocumentFile()` + `sourceUrl` cho phần viewer inline (vẫn fetch như cũ).

- State mới: `let previewObjectUrl: string | null = null` (URL của tab đang mở).
  Thêm `isOpening`/`isDownloading` ref để disable nút khi đang fetch (chống double-click).
- `async function openFile()`:
  - guard `citation?.document_id`.
  - revoke `previewObjectUrl` cũ nếu có; `blob = await documentService.getPreviewBlob(id)`;
    `previewObjectUrl = URL.createObjectURL(blob)`; `window.open(previewObjectUrl, '_blank', 'noopener')`.
  - KHÔNG revoke ngay (tab cần URL còn sống). Revoke ở `resetViewer()` + `onBeforeUnmount`.
  - catch → set `errorMsg` (vd "Không mở được tài liệu").
- `async function downloadFile()`:
  - `blob = await documentService.getFileBlob(id)`; tạo object URL tạm; `<a download=citation.document>`
    .click(); revoke ngay sau (download không cần URL sống lâu).
- Đổi gate `v-if="sourceUrl"` → `v-if="citation?.document_id"` cho cụm nút header
  và 2 thẻ fallback/error.
- Đổi `<a :href="sourceUrl" target="_blank">` (Open) → `<button @click="openFile" :disabled="isOpening">`,
  giữ nguyên class/icon (`ExternalLink`), `type="button"`.
- Đổi `<a :href="sourceUrl" :download>` (Download) → `<button @click="downloadFile" :disabled="isDownloading">`.
- `resetViewer()`: thêm revoke `previewObjectUrl` (đặt về null). `onBeforeUnmount` đã có
  `revokeObjectUrl()` của viewer — thêm revoke previewObjectUrl.

> Lưu ý: `result.url` (GCS) vẫn dùng cho viewer inline (fetch bytes client-side).
> Option A không đụng phần đó — nếu sau này muốn bỏ hẳn GCS khỏi client thì làm
> Option B (chuyển viewer sang `/file/preview`). Để lại `// ponytail:` comment ở
> chỗ viewer còn fetch `sourceUrl`.

## Kiểm thử

- Unit (mirror admin `test_documents_api`-style FE test nếu có): assert
  `getPreviewBlob` gọi `/{id}/file/preview` và `getFileBlob` gọi `/{id}/file/raw`.
  (add when: nếu mock axios sẵn trong `tests/` — xem `tests/*.test.ts`.)
- Manual: bấm Open ở citation PDF → tab `blob:https://<vsfchat>/…` render PDF inline,
  KHÔNG có `storage.googleapis.com`. DOCX → tab mở PDF (đã convert), không ép tải.
  Định dạng lạ (xls/tif) ở thẻ fallback → Open mở blob preview, Download tải bản gốc.

## Không làm (deferred)

- Option B (viewer inline dùng server `/file/preview`) — chỉ làm khi muốn xoá hẳn
  officeparser/pdf.js-fetch-GCS khỏi client.
- Trang viewer riêng dạng `/documents/{id}` cho chat — YAGNI, blob tab đã đủ.
