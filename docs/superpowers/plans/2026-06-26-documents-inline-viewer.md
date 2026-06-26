# Documents Inline Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho "Open File" ở `/admin/documents/{id}` render file ngay trong trang (PDF/ảnh/text inline, office → fallback + tải về), không mở tab/blob URL.

**Architecture:** Chỉ sửa frontend admin. Tách `previewMode()` thành helper thuần. `[id].vue` thêm state viewer + logic fetch blob (tái dùng `documentService.getFileBlob`) và template render theo mode. Backend không đổi.

**Tech Stack:** Nuxt 3 / Vue 3 `<script setup>`, Tailwind, lucide icons, axios (`getFileBlob`), Blob/`URL.createObjectURL`.

## Global Constraints

- KHÔNG `window.open`, KHÔNG điều hướng `window.location` sang blob URL.
- KHÔNG convert server-side, KHÔNG thêm lib render office client-side, KHÔNG thêm test runner.
- Tải về dùng `<a download>` + object URL rồi revoke (trang đứng yên).
- Revoke object URL khi đóng/đổi file/`onUnmounted` (không leak).
- Phân loại render khớp `_INLINE_TYPES` backend: pdf/txt/md/csv/png/jpg/jpeg/gif/webp = inline.

---

### Task 1: Helper `previewMode` (pure function)

**Files:**
- Create: `src/frontend/admin/app/lib/documentPreview.ts`

**Interfaces:**
- Produces: `previewMode(fileType: string): 'pdf' | 'image' | 'text' | 'download'`

- [ ] **Step 1: Tạo helper thuần**

```ts
// src/frontend/admin/app/lib/documentPreview.ts
export type PreviewMode = 'pdf' | 'image' | 'text' | 'download'

const IMAGE_TYPES = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp'])
const TEXT_TYPES = new Set(['txt', 'md', 'csv'])

// Quyết định cách render file trong khung viewer nhúng. Khớp _INLINE_TYPES của
// document-service (get_document_file_stream_use_case.py). Office/nhị phân -> 'download'.
export function previewMode(fileType: string): PreviewMode {
  const ext = fileType.trim().toLowerCase().replace(/^\./, '')
  if (ext === 'pdf') return 'pdf'
  if (IMAGE_TYPES.has(ext)) return 'image'
  if (TEXT_TYPES.has(ext)) return 'text'
  return 'download'
}
```

- [ ] **Step 2: Kiểm tra biên dịch (không có unit runner)**

Run: `cd src/frontend/admin && npx nuxi typecheck 2>&1 | grep documentPreview || echo "no errors in documentPreview"`
Expected: `no errors in documentPreview`

- [ ] **Step 3: Commit**

```bash
git add src/frontend/admin/app/lib/documentPreview.ts
git commit -m "feat(documents): helper previewMode phân loại render file"
```

---

### Task 2: Viewer nhúng trong `[id].vue`

**Files:**
- Modify: `src/frontend/admin/app/pages/documents/[id].vue`

**Interfaces:**
- Consumes: `previewMode` (Task 1), `documentService.getFileBlob(id)` (đã có), `getApiErrorMessage`.

- [ ] **Step 1: Thay logic `openFile` cũ bằng state + hàm viewer (script)**

Trong `<script setup>`, xoá khối `isOpeningFile` + `openFile` (mở tab cũ), thêm import và state mới:

```ts
import { previewMode, type PreviewMode } from '~/lib/documentPreview'

type PreviewState = 'idle' | 'loading' | 'ready' | 'unsupported' | 'error'
const previewState = ref<PreviewState>('idle')
const previewObjectUrl = ref<string | null>(null)
const previewText = ref<string | null>(null)
const previewBlob = ref<Blob | null>(null)
const previewError = ref<string | null>(null)
const previewKind = ref<PreviewMode>('download')

const resetPreview = () => {
  if (previewObjectUrl.value) URL.revokeObjectURL(previewObjectUrl.value)
  previewObjectUrl.value = null
  previewText.value = null
  previewBlob.value = null
  previewError.value = null
}

const closePreview = () => {
  resetPreview()
  previewState.value = 'idle'
}

const openPreview = async () => {
  if (!doc.value) return
  resetPreview()
  previewState.value = 'loading'
  previewKind.value = previewMode(doc.value.file_type)
  try {
    const blob = await documentService.getFileBlob(id)
    previewBlob.value = blob
    if (previewKind.value === 'text') {
      previewText.value = await blob.text()
      previewState.value = 'ready'
    } else if (previewKind.value === 'download') {
      previewState.value = 'unsupported'
    } else {
      previewObjectUrl.value = URL.createObjectURL(blob)
      previewState.value = 'ready'
    }
  } catch (error) {
    previewState.value = 'error'
    previewError.value = getApiErrorMessage(error, 'Failed to open the document file')
  }
}

const downloadFile = async () => {
  if (!doc.value) return
  try {
    const blob = previewBlob.value ?? (await documentService.getFileBlob(id))
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = doc.value.name
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
  } catch (error) {
    toast.error(getApiErrorMessage(error, 'Failed to download the document file'))
  }
}
```

- [ ] **Step 2: Revoke khi unmount**

Trong `onUnmounted` hiện có (xoá `pollTimer`), thêm `resetPreview()`:

```ts
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  resetPreview()
})
```

- [ ] **Step 3: Đổi nút "Open File" (template)**

```html
<button
  class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent disabled:opacity-50"
  :disabled="previewState === 'loading'"
  @click="openPreview"
>
  <Loader2 v-if="previewState === 'loading'" class="h-3.5 w-3.5 animate-spin" />
  <ExternalLink v-else class="h-3.5 w-3.5" /> Open File
</button>
```

- [ ] **Step 4: Khung viewer thay thẻ status khi active (template)**

Thay khối `<div class="rounded-lg border border-border bg-card p-8 lg:col-span-2">...</div>`
(thẻ status) bằng: nếu `previewState === 'idle'` → giữ nguyên thẻ status cũ; ngược lại render
khung viewer trong cùng `lg:col-span-2`:

```html
<!-- VIEWER (active) -->
<div v-if="previewState !== 'idle'" class="flex flex-col rounded-lg border border-border bg-card lg:col-span-2">
  <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
    <span class="truncate text-[13px] font-semibold text-foreground">{{ doc.name }}</span>
    <button class="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" @click="closePreview">
      <X class="h-4 w-4" />
    </button>
  </div>
  <div class="flex min-h-[70vh] flex-1 items-center justify-center overflow-auto bg-muted/30">
    <Loader2 v-if="previewState === 'loading'" class="h-7 w-7 animate-spin text-primary" />

    <div v-else-if="previewState === 'error'" class="px-6 text-center text-[12.5px] text-destructive">
      {{ previewError }}
    </div>

    <iframe
      v-else-if="previewState === 'ready' && previewKind === 'pdf'"
      :src="previewObjectUrl!"
      class="h-[70vh] w-full border-0"
      title="Document preview"
    />

    <img
      v-else-if="previewState === 'ready' && previewKind === 'image'"
      :src="previewObjectUrl!"
      :alt="doc.name"
      class="max-h-[70vh] max-w-full object-contain"
    />

    <pre
      v-else-if="previewState === 'ready' && previewKind === 'text'"
      class="h-[70vh] w-full overflow-auto whitespace-pre-wrap break-words p-4 text-left text-[12.5px] text-foreground"
    >{{ previewText }}</pre>

    <div v-else class="flex flex-col items-center gap-3 px-6 text-center">
      <FileText class="h-10 w-10 text-muted-foreground opacity-30" />
      <p class="text-[13px] font-medium text-foreground">Không thể xem trước định dạng này</p>
      <p class="text-[12px] text-muted-foreground">{{ doc.file_type.toUpperCase() }} không hiển thị trực tiếp trong trình duyệt.</p>
      <button
        class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent"
        @click="downloadFile"
      >
        <Download class="h-3.5 w-3.5" /> Tải về
      </button>
    </div>
  </div>
</div>

<!-- STATUS card (idle) — giữ nguyên nội dung cũ, chỉ thêm v-else -->
<div v-else class="rounded-lg border border-border bg-card p-8 lg:col-span-2">
  ... (nội dung thẻ status hiện tại giữ nguyên) ...
</div>
```

- [ ] **Step 5: Thêm icon import**

Sửa dòng import lucide: thêm `X` và `Download` vào danh sách `@lucide/vue`.

- [ ] **Step 6: Typecheck — không lỗi mới ở file đã sửa**

Run: `cd src/frontend/admin && npx nuxi typecheck 2>&1 | grep -E "\[id\].vue|documentPreview" || echo "no new errors in changed files"`
Expected: chỉ có thể còn lỗi pre-existing project-wide; không có lỗi mới thuộc `[id].vue`/`documentPreview` ngoài pattern `service` đã biết.

- [ ] **Step 7: Commit**

```bash
git add "src/frontend/admin/app/pages/documents/[id].vue"
git commit -m "feat(documents): viewer nhúng in-page thay vì mở tab blob"
```

---

## Manual Verification (sau Task 2)

- Mở `/admin/documents/{id}` của 1 PDF → bấm Open File → PDF render trong khung, thanh địa chỉ vẫn `/admin/documents/{id}` (KHÔNG có `blob:`).
- Ảnh → hiện inline. txt/md/csv → hiện text cuộn.
- docx/xlsx → fallback "Không thể xem trước định dạng này" + nút Tải về → tải file, trang đứng yên.
- Bấm X → quay lại thẻ status.

## Self-Review

- Spec coverage: bố trí (Task 2 Step 4) ✓; phân loại render (Task 1) ✓; tải về không điều hướng (Task 2 Step 1 `downloadFile`) ✓; vòng đời/revoke (Step 1/2) ✓; lỗi (Step 1 catch) ✓; không tab/blob nav ✓; không server-convert/lib/test-runner ✓.
- Type consistency: `previewMode`/`PreviewMode` dùng nhất quán giữa Task 1 và Task 2; state names khớp template.
