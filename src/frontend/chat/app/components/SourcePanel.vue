<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, ExternalLink, FileText, X } from '@lucide/vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import type { Citation } from '~/types'
import documentService from '~/lib/api/documentService'
import { citationHeadingPath, formatRelevance } from '~/lib/utils'

type ViewerMode = 'pdf' | 'html' | 'text' | 'image' | 'unsupported'
type SupportedFileType = 'pdf' | 'docx' | 'txt' | 'xlsx' | 'csv' | 'pptx' | 'md' | ImageFileType
type ImageFileType = 'png' | 'jpg' | 'jpeg' | 'gif' | 'bmp' | 'webp'

const props = defineProps<{ citation: Citation | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
})
const HIGHLIGHT_ID = 'vsf-citation-highlight'
const imageFileTypes = new Set<ImageFileType>(['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'])
const supportedFileTypes = new Set<SupportedFileType>([
  'pdf',
  'docx',
  'txt',
  'xlsx',
  'csv',
  'pptx',
  'md',
  ...imageFileTypes,
])

const viewerMode = ref<ViewerMode>('unsupported')
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
  type: Exclude<SupportedFileType, 'pdf' | 'txt' | 'md'>,
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
  viewerMode.value = 'unsupported'
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
      errorMsg.value = 'Document preview is unavailable because the citation payload has no document ID'
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

      if (!supportedFileTypes.has(normalizedType as SupportedFileType)) {
        viewerMode.value = 'unsupported'
        errorMsg.value = `Preview is not supported for .${normalizedType || 'unknown'} files`
        return
      }

      const supportedType = normalizedType as SupportedFileType
      if (imageFileTypes.has(supportedType as ImageFileType)) {
        viewerMode.value = 'image'
        fileUrl.value = result.url
        return
      }

      const data = await fetchFile(result.url, controller.signal)
      if (controller.signal.aborted) return

      if (supportedType === 'pdf') {
        // Tải PDF qua blob same-origin để vượt qua origin check của PDF.js viewer.
        objectUrl = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }))
        viewerMode.value = 'pdf'
        fileUrl.value = createPdfViewerUrl(objectUrl, newCitation)
        return
      }

      if (supportedType === 'txt') {
        viewerMode.value = 'text'
        textContent.value = new TextDecoder('utf-8').decode(data)
        return
      }

      if (supportedType === 'md') {
        viewerMode.value = 'html'
        const source = new TextDecoder('utf-8').decode(data)
        htmlContent.value = createHtmlDocument(markdown.render(source), newCitation.snippet?.trim() || newCitation.caption)
        return
      }

      viewerMode.value = 'html'
      htmlContent.value = createHtmlDocument(
        await renderOfficeFile(data, supportedType),
        newCitation.snippet?.trim() || newCitation.caption,
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
      errorMsg.value = 'Failed to load document preview'
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
            <div :title="citation?.caption || ''" class="line-clamp-2 text-sm font-semibold text-slate-900 dark:text-foreground">
              {{ citation?.caption || citation?.document || 'No source selected' }}
            </div>
            <div v-if="headingPath.length" class="mt-1 text-xs font-medium text-slate-500 dark:text-muted-foreground">
              {{ headingPath.join(' › ') }}
            </div>
            <div class="mt-1 flex items-center gap-2 truncate text-[11px] text-slate-400 dark:text-muted-foreground">
              <span class="truncate">{{ citation?.document || '—' }}</span>
              <span v-if="fileTypeLabel" class="rounded bg-slate-100 dark:bg-muted px-1.5 py-0.5 font-semibold text-slate-500 dark:text-muted-foreground">
                {{ fileTypeLabel }}
              </span>
              <span v-if="citation?.page_number">Đoạn {{ citation.page_number }}</span>
              <span v-if="formatRelevance(citation?.score)" class="rounded-full bg-blue-50 dark:bg-blue-900/30 px-1.5 py-0.5 font-semibold text-blue-600 dark:text-blue-300" title="Độ liên quan">
                {{ formatRelevance(citation?.score) }}
              </span>
            </div>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <a
            v-if="sourceUrl"
            :href="sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-accent hover:text-slate-900 dark:hover:text-accent-foreground"
            title="Open original document"
          >
            <ExternalLink class="h-4 w-4" />
          </a>
          <a
            v-if="sourceUrl"
            :href="sourceUrl"
            :download="citation?.document"
            class="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-accent hover:text-slate-900 dark:hover:text-accent-foreground"
            title="Download document"
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
      <div v-if="isLoading" class="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-background/80">
        <div class="text-sm text-slate-500 dark:text-muted-foreground">Loading document...</div>
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
          Open original document
        </a>
      </div>
      <iframe
        v-else-if="viewerMode === 'pdf' && fileUrl"
        :src="fileUrl"
        class="h-full w-full border-none"
        title="PDF document viewer"
      />
      <iframe
        v-else-if="viewerMode === 'html'"
        :srcdoc="htmlContent"
        sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
        class="h-full w-full border-none bg-white dark:bg-card"
        title="Document preview"
      />
      <pre
        v-else-if="viewerMode === 'text'"
        class="h-full overflow-auto whitespace-pre-wrap break-words bg-white dark:bg-card p-6 font-mono text-sm leading-6 text-slate-800 dark:text-foreground"
      >{{ textContent }}</pre>
      <div
        v-else-if="viewerMode === 'image' && fileUrl"
        class="flex h-full w-full items-center justify-center overflow-auto bg-slate-100 dark:bg-background p-6"
      >
        <img
          :src="fileUrl"
          :alt="citation?.caption || citation?.document || 'Document preview'"
          class="max-h-full max-w-full object-contain"
        >
      </div>
      <div v-else class="absolute inset-0 flex items-center justify-center bg-white dark:bg-card text-sm text-slate-400 dark:text-muted-foreground">
        Preview not available
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center p-6 text-sm text-slate-400 dark:text-muted-foreground">
      Select a citation from an answer to inspect its metadata.
    </div>
  </div>
</template>
