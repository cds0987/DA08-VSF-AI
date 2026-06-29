<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  Download, ExternalLink, FileText, X,
  File as FileGeneric, FileCode, FileImage, FileSpreadsheet, Globe, Presentation,
} from '@lucide/vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import type { Citation } from '~/types'
import documentService from '~/lib/api/documentService'
import { citationFileKind, citationHeadingPath, cleanCitationLabel, formatRelevance } from '~/lib/utils'
import { resolveViewerMode } from '~/lib/documentViewer'

// Chế độ RENDER của panel (gộp office/markdown/html-file vào 1 nhánh 'html' iframe).
type ViewerMode = 'pdf' | 'html' | 'text' | 'image' | 'fallback'
// Loại tệp office mà officeparser render được (docx/xlsx/csv/pptx).
type OfficeFileType = 'docx' | 'xlsx' | 'csv' | 'pptx'

const props = defineProps<{ citation: Citation | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
})
const HIGHLIGHT_ID = 'vsf-citation-highlight'

const viewerMode = ref<ViewerMode>('fallback')
const fileUrl = ref<string | null>(null)
const sourceUrl = ref<string | null>(null)
const htmlContent = ref('')
const textContent = ref('')
const fileType = ref('')
const isLoading = ref(false)
const errorMsg = ref<string | null>(null)
let loadController: AbortController | null = null
// Blob URL (same-origin) cấp cho PDF.js viewer: presigned URL của GCS/MinIO khác origin
// nên viewer.mjs validateFileURL chặn ("file origin does not match viewer's").
let objectUrl: string | null = null

function revokeObjectUrl() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = null
  }
}

const fileTypeLabel = computed(() => fileType.value ? fileType.value.toUpperCase() : '')
const headingPath = computed(() => props.citation ? citationHeadingPath(props.citation.heading_path, props.citation.document) : [])

// Icon fallback theo nhóm tệp (tái dùng citationFileKind của Phase 3 — 1 family @lucide).
const FALLBACK_ICON = {
  pdf: FileText, doc: FileText, text: FileCode, web: Globe,
  sheet: FileSpreadsheet, slide: Presentation, image: FileImage, unknown: FileGeneric,
} as const
const fallbackIcon = computed(() => FALLBACK_ICON[citationFileKind(props.citation?.document).group])
// Caption (tóm tắt AI) chỉ là mô tả phụ — dọn tiền tố số thứ tự và bỏ nếu trùng tên
// tài liệu (đã hiển thị làm title) để tránh lặp.
const captionText = computed(() => {
  const caption = cleanCitationLabel(props.citation?.caption)
  if (!caption) return ''
  return caption.toLowerCase() === props.citation?.document?.trim().toLowerCase() ? '' : caption
})

function normalizeFileType(value: string, documentName: string): string {
  const normalized = value.trim().toLowerCase().replace(/^\./, '')
  if (normalized) return normalized
  return documentName.split('.').pop()?.toLowerCase() || ''
}

function createPdfViewerUrl(url: string, citation: Citation): string {
  // Neo highlight bằng đoạn text literal (snippet) đã khớp truy vấn; caption là tóm
  // tắt AI nên thường không khớp nguyên văn trong tài liệu -> chỉ dùng làm fallback.
  const anchor = citation.snippet?.trim() || citation.caption
  // ~12 từ liền mạch: đủ đặc trưng để khớp 1 cụm, không quá dài khiến lệch do PDF
  // ngắt dòng. PHẢI kèm phrase=true, nếu không pdf.js tách thành mảng từ rời -> tô
  // rải rác từng từ và KHÔNG cuộn tới đoạn (viewer.mjs setHash).
  const snippet = anchor.split(/\s+/).slice(0, 12).join(' ')
  let viewerUrl = '/pdfjs/web/viewer.html?file=' + encodeURIComponent(url)
  const params = new URLSearchParams()
  // KHÔNG set 'page': page_number thực ra là section_index (không phải trang PDF thật)
  // -> sẽ nhảy sai trang. Để phrase search tự cuộn tới đúng đoạn khớp.
  if (snippet) {
    params.set('search', snippet)
    params.set('phrase', 'true')
  }
  if (params.size) viewerUrl += `#${params.toString()}`
  return viewerUrl
}

function sanitizeHtml(value: string): string {
  return DOMPurify.sanitize(value, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick'],
  })
}

async function fetchFile(url: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const response = await fetch(url, { signal })
  if (!response.ok) {
    throw new Error(`Document storage returned HTTP ${response.status}`)
  }
  return response.arrayBuffer()
}

async function renderOfficeFile(
  data: ArrayBuffer,
  type: OfficeFileType,
): Promise<string> {
  const { OfficeConverter } = await import('officeparser')
  const { value, messages } = await OfficeConverter.convert(
    new Uint8Array(data),
    'html',
    {
      parseConfig: {
        fileType: type,
        extractAttachments: true,
        ignoreInternalLinks: true,
      },
      generatorConfig: {
        includeCharts: false,
        includeImages: true,
        ignoreInternalLinks: true,
        htmlConfig: {
          standalone: false,
          containerWidth: '100%',
        },
      },
    },
  )

  const errors = messages.filter(message => message.type === 'error')
  if (errors.length) {
    throw new Error(errors.map(message => message.message).join('; '))
  }
  if (typeof value !== 'string') {
    throw new TypeError('Document renderer returned an invalid HTML payload')
  }
  return sanitizeHtml(value)
}

function escapeHtml(value: string): string {
  const map: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
  return value.replace(/[&<>"']/g, ch => map[ch] ?? ch)
}

// Bảng tính (xlsx/xls/csv): officeparser render hỏng (chỉ trả tên sheet.xml) -> dùng SheetJS
// dựng HTML table cho từng sheet, rồi sanitize như mọi path office/html khác.
async function renderSheetFile(data: ArrayBuffer): Promise<string> {
  const XLSX = await import('xlsx')
  const workbook = XLSX.read(new Uint8Array(data), { type: 'array' })
  const parts = workbook.SheetNames.map((name) => {
    const sheet = workbook.Sheets[name]
    if (!sheet) return ''
    const table = XLSX.utils.sheet_to_html(sheet, { editable: false })
    return `<h3 class="sheet-title">${escapeHtml(name)}</h3>${table}`
  }).filter(Boolean)
  if (!parts.length) {
    throw new Error('Workbook has no readable sheets')
  }
  return sanitizeHtml(parts.join('\n'))
}

// TIFF: trình duyệt KHÔNG render natively -> decode bằng UTIF, vẽ mọi page lên canvas
// rồi xuất PNG blob URL để hiển thị như ảnh thường (path 'image' sẵn có).
async function renderTiffToPngUrl(data: ArrayBuffer): Promise<string> {
  const UTIF = (await import('utif')).default
  const ifds = UTIF.decode(data)
  if (!ifds.length) throw new Error('TIFF has no pages')

  const pages: HTMLCanvasElement[] = []
  for (const ifd of ifds) {
    UTIF.decodeImage(data, ifd)
    const rgba = UTIF.toRGBA8(ifd)
    const needed = ifd.width * ifd.height * 4
    if (!ifd.width || !ifd.height || rgba.length < needed) continue
    const canvas = document.createElement('canvas')
    canvas.width = ifd.width
    canvas.height = ifd.height
    const ctx = canvas.getContext('2d')
    if (!ctx) continue
    const pixels = new Uint8ClampedArray(needed)
    pixels.set(rgba.subarray(0, needed))
    ctx.putImageData(new ImageData(pixels, ifd.width, ifd.height), 0, 0)
    pages.push(canvas)
  }
  if (!pages.length) throw new Error('TIFF decode produced no image')

  const gap = 8
  const width = Math.max(...pages.map(c => c.width))
  const height = pages.reduce((sum, c) => sum + c.height, 0) + gap * (pages.length - 1)
  const out = document.createElement('canvas')
  out.width = width
  out.height = height
  const octx = out.getContext('2d')
  if (!octx) throw new Error('Canvas 2D context unavailable')
  octx.fillStyle = '#ffffff'
  octx.fillRect(0, 0, width, height)
  let y = 0
  for (const canvas of pages) {
    octx.drawImage(canvas, 0, y)
    y += canvas.height + gap
  }
  const blob = await new Promise<Blob>((resolve, reject) => {
    out.toBlob(result => (result ? resolve(result) : reject(new Error('Canvas toBlob failed'))), 'image/png')
  })
  return URL.createObjectURL(blob)
}

function createHtmlDocument(content: string, highlight: string): string {
  const parser = new DOMParser()
  const document = parser.parseFromString(sanitizeHtml(content), "text/html")
  const snippet = highlight.trim().split(/\s+/).slice(0, 10).join(" ")

  if (snippet) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      const node = walker.currentNode as Text
      const index = node.data.toLocaleLowerCase().indexOf(snippet.toLocaleLowerCase())
      if (index < 0 || !node.parentNode) continue

      const mark = document.createElement("mark")
      mark.id = HIGHLIGHT_ID
      mark.textContent = node.data.slice(index, index + snippet.length)
      const after = node.splitText(index)
      after.deleteData(0, snippet.length)
      node.parentNode.insertBefore(mark, after)
      break
    }
  }

  const isDark = window.document.documentElement.classList.contains('dark')

  const style = document.createElement("style")
  style.textContent = `
    html, body {
      margin: 0;
      min-height: 100%;
      background: ${isDark ? '#131314' : 'white'};
      color: ${isDark ? '#ececec' : '#1e293b'};
    }
    body { box-sizing: border-box; padding: 24px; font: 14px/1.6 ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; max-width: 100%; }
    img { height: auto; }
    table { width: max-content; min-width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid ${isDark ? '#2f3036' : '#cbd5e1'}; padding: 8px 12px; vertical-align: top; }
    th { background: ${isDark ? '#222327' : '#f1f5f9'}; font-weight: 600; }
    mark { border-radius: 3px; background: ${isDark ? '#3b82f640' : '#fde68a'}; padding: 0 2px; color: inherit; }
  `
  document.head.appendChild(style)

  // Tự cuộn tới đoạn đã tô khi mở (iframe sandbox dùng allow-scripts, KHÔNG
  // allow-same-origin -> opaque origin, script không chạm được parent). Content
  // đã qua DOMPurify nên không còn script lạ; chỉ script tin cậy này chạy.
  const scroll = document.createElement("script")
  scroll.textContent = `(function(){var m=document.getElementById(${JSON.stringify(HIGHLIGHT_ID)});if(m){m.scrollIntoView({block:"center"});}})();`
  document.body.appendChild(scroll)

  return "<!doctype html>" + document.documentElement.outerHTML
}

function resetViewer() {
  revokeObjectUrl()
  viewerMode.value = 'fallback'
  fileUrl.value = null
  sourceUrl.value = null
  htmlContent.value = ''
  textContent.value = ''
  fileType.value = ''
  errorMsg.value = null
}

watch(
  () => props.citation,
  async (newCitation) => {
    loadController?.abort()
    resetViewer()
    if (!newCitation) return
    if (!newCitation.document_id) {
      errorMsg.value = 'Không xem trước được vì trích dẫn thiếu mã tài liệu'
      return
    }
    if (import.meta.server) return

    const controller = new AbortController()
    loadController = controller
    isLoading.value = true

    try {
      const result = await documentService.getDocumentFile(newCitation.document_id)
      if (controller.signal.aborted) return

      const normalizedType = normalizeFileType(result.file_type, newCitation.document)
      fileType.value = normalizedType
      sourceUrl.value = result.url

      const mode = resolveViewerMode(normalizedType)

      // fallback: KHÔNG fetch bytes — thẻ đẹp "Mở/Tải tài liệu gốc" (xls/tif/tiff/type lạ).
      if (mode === 'fallback') {
        viewerMode.value = 'fallback'
        return
      }

      // image: dùng thẳng presigned URL, không fetch.
      if (mode === 'image') {
        viewerMode.value = 'image'
        fileUrl.value = result.url
        return
      }

      const data = await fetchFile(result.url, controller.signal)
      if (controller.signal.aborted) return
      const highlight = newCitation.snippet?.trim() || newCitation.caption

      if (mode === 'pdf') {
        // Tải PDF qua blob same-origin để vượt qua origin check của PDF.js viewer.
        objectUrl = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }))
        viewerMode.value = 'pdf'
        fileUrl.value = createPdfViewerUrl(objectUrl, newCitation)
        return
      }

      if (mode === 'text') {
        viewerMode.value = 'text'
        textContent.value = new TextDecoder('utf-8').decode(data)
        return
      }

      if (mode === 'markdown') {
        viewerMode.value = 'html'
        const source = new TextDecoder('utf-8').decode(data)
        htmlContent.value = createHtmlDocument(markdown.render(source), highlight)
        return
      }

      if (mode === 'html') {
        // HTML/HTM gốc: DOMPurify + iframe sandbox SẴN CÓ (không nới lỏng) — như path md/office.
        viewerMode.value = 'html'
        const source = new TextDecoder('utf-8').decode(data)
        htmlContent.value = createHtmlDocument(source, highlight)
        return
      }

      if (mode === 'sheet') {
        // xlsx/xls/csv -> SheetJS -> HTML table (officeparser render bảng tính bị hỏng).
        viewerMode.value = 'html'
        htmlContent.value = createHtmlDocument(await renderSheetFile(data), highlight)
        return
      }

      if (mode === 'tiff') {
        // TIFF -> UTIF decode -> PNG blob URL -> hiển thị như ảnh (browser không render TIFF).
        revokeObjectUrl()
        objectUrl = await renderTiffToPngUrl(data)
        viewerMode.value = 'image'
        fileUrl.value = objectUrl
        return
      }

      // mode === 'office' (docx/pptx) qua officeparser.
      viewerMode.value = 'html'
      htmlContent.value = createHtmlDocument(
        await renderOfficeFile(data, normalizedType as OfficeFileType),
        highlight,
      )
    } catch (error: any) {
      if (error?.name === 'AbortError') return
      console.error('Failed to render citation document:', {
        documentId: newCitation.document_id,
        fileType: fileType.value,
        status: error?.response?.status,
        detail: error?.response?.data?.detail,
        error,
      })
      errorMsg.value = 'Không tải được bản xem trước tài liệu'
    } finally {
      if (loadController === controller) {
        loadController = null
        isLoading.value = false
      }
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  loadController?.abort()
  revokeObjectUrl()
})
</script>

<template>
  <div class="flex h-full flex-col bg-slate-50/50 dark:bg-background">
    <div class="shrink-0 border-b border-slate-200/50 dark:border-border bg-white dark:bg-card px-6 py-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400">
            <FileText class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <div :title="citation?.document || ''" class="line-clamp-2 text-sm font-semibold text-slate-900 dark:text-foreground">
              {{ citation?.document || 'Chưa chọn nguồn' }}
            </div>
            <div v-if="headingPath.length" class="mt-1 text-xs font-medium text-slate-500 dark:text-muted-foreground">
              {{ headingPath.join(' › ') }}
            </div>
            <div class="mt-1 flex items-center gap-2 truncate text-[11px] text-slate-400 dark:text-muted-foreground">
              <span v-if="fileTypeLabel" class="rounded bg-slate-100 dark:bg-muted px-1.5 py-0.5 font-semibold text-slate-500 dark:text-muted-foreground">
                {{ fileTypeLabel }}
              </span>
              <span v-if="citation?.page_number">Đoạn {{ citation.page_number }}</span>
            </div>
            <p v-if="captionText" :title="captionText" class="mt-1.5 line-clamp-2 text-xs leading-snug text-slate-500 dark:text-muted-foreground">
              {{ captionText }}
            </p>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <a
            v-if="sourceUrl"
            :href="sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-accent hover:text-slate-900 dark:hover:text-accent-foreground"
            title="Mở tài liệu gốc"
          >
            <ExternalLink class="h-4 w-4" />
          </a>
          <a
            v-if="sourceUrl"
            :href="sourceUrl"
            :download="citation?.document"
            class="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-accent hover:text-slate-900 dark:hover:text-accent-foreground"
            title="Tải tài liệu"
          >
            <Download class="h-4 w-4" />
          </a>
          <button class="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-accent hover:text-slate-900 dark:hover:text-accent-foreground" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>

    <div v-if="citation" class="relative flex-1 overflow-hidden bg-slate-200 dark:bg-background">
      <!-- Skeleton trong lúc tải: mô phỏng khung tài liệu cho cảm giác mượt hơn text trống -->
      <div v-if="isLoading" class="absolute inset-0 z-10 overflow-hidden bg-white dark:bg-card p-6">
        <div class="mx-auto max-w-2xl space-y-3">
          <div class="h-6 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-muted" />
          <div class="h-3.5 w-1/3 animate-pulse rounded bg-slate-200 dark:bg-muted" />
          <div class="h-px w-full bg-slate-100 dark:bg-border" />
          <div
            v-for="i in 9"
            :key="i"
            class="h-3.5 animate-pulse rounded bg-slate-200 dark:bg-muted"
            :class="i % 3 === 0 ? 'w-2/3' : 'w-full'"
          />
        </div>
        <div class="absolute bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-2 text-xs text-slate-400 dark:text-muted-foreground">
          <div class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-200 border-t-slate-500 dark:border-muted dark:border-t-muted-foreground" />
          Đang tải tài liệu…
        </div>
      </div>
      <div v-else-if="errorMsg" class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white dark:bg-card p-6 text-center">
        <div class="text-sm text-red-500">{{ errorMsg }}</div>
        <a
          v-if="sourceUrl"
          :href="sourceUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300"
        >
          Mở tài liệu gốc
        </a>
      </div>
      <iframe
        v-else-if="viewerMode === 'pdf' && fileUrl"
        :src="fileUrl"
        class="h-full w-full border-none"
        title="Trình xem PDF"
      />
      <iframe
        v-else-if="viewerMode === 'html'"
        :srcdoc="htmlContent"
        sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
        class="h-full w-full border-none bg-white dark:bg-card"
        title="Bản xem trước tài liệu"
      />
      <pre
        v-else-if="viewerMode === 'text'"
        class="custom-scrollbar h-full overflow-auto whitespace-pre-wrap break-words bg-white dark:bg-card p-6 font-mono text-sm leading-6 text-slate-800 dark:text-foreground"
      >{{ textContent }}</pre>
      <div
        v-else-if="viewerMode === 'image' && fileUrl"
        class="custom-scrollbar flex h-full w-full items-center justify-center overflow-auto bg-slate-100 dark:bg-background p-6"
      >
        <img
          :src="fileUrl"
          :alt="citation?.caption || citation?.document || 'Bản xem trước tài liệu'"
          class="max-h-full max-w-full object-contain"
        >
      </div>
      <!-- Fallback đẹp: type không render được tại đây (xls/tif/tiff/lạ) — KHÔNG phải lỗi -->
      <div v-else class="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-white dark:bg-card p-6 text-center">
        <div class="flex h-20 w-20 items-center justify-center rounded-2xl bg-slate-100 text-slate-500 dark:bg-muted dark:text-muted-foreground">
          <component :is="fallbackIcon" class="h-10 w-10" :stroke-width="1.5" aria-hidden="true" />
        </div>
        <div class="space-y-1">
          <p class="text-sm font-semibold text-slate-700 dark:text-foreground">Không xem trước được tại đây</p>
          <p class="text-xs text-slate-400 dark:text-muted-foreground">
            Định dạng {{ fileTypeLabel || 'này' }} cần mở bằng ứng dụng phù hợp.
          </p>
        </div>
        <div v-if="sourceUrl" class="flex flex-wrap items-center justify-center gap-2.5">
          <a
            :href="sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex h-11 items-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
          >
            <ExternalLink class="h-4 w-4" aria-hidden="true" />
            Mở tài liệu gốc
          </a>
          <a
            :href="sourceUrl"
            :download="citation?.document"
            class="inline-flex h-11 items-center gap-2 rounded-xl border border-slate-200 px-4 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:border-border dark:text-foreground dark:hover:bg-accent"
          >
            <Download class="h-4 w-4" aria-hidden="true" />
            Tải xuống
          </a>
        </div>
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center p-6 text-sm text-slate-400 dark:text-muted-foreground">
      Chọn một trích dẫn trong câu trả lời để xem chi tiết nguồn.
    </div>
  </div>
</template>
