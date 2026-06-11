<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, ExternalLink, FileText, X } from '@lucide/vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import type { Citation } from '~/types'
import documentService from '~/lib/api/documentService'

type ViewerMode = 'pdf' | 'html' | 'text' | 'unsupported'
type SupportedFileType = 'pdf' | 'docx' | 'txt' | 'xlsx' | 'csv' | 'pptx' | 'md'

const props = defineProps<{ citation: Citation | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
})
const supportedFileTypes = new Set<SupportedFileType>([
  'pdf',
  'docx',
  'txt',
  'xlsx',
  'csv',
  'pptx',
  'md',
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

const fileTypeLabel = computed(() => fileType.value ? fileType.value.toUpperCase() : '')

function normalizeFileType(value: string, documentName: string): string {
  const normalized = value.trim().toLowerCase().replace(/^\./, '')
  if (normalized) return normalized
  return documentName.split('.').pop()?.toLowerCase() || ''
}

function createPdfViewerUrl(url: string, citation: Citation): string {
  const snippet = citation.caption.split(/\s+/).slice(0, 15).join(' ')
  let viewerUrl = '/pdfjs/web/viewer.html?file=' + encodeURIComponent(url)
  const params = new URLSearchParams()
  if (citation.page_number) params.set('page', String(citation.page_number))
  if (snippet) params.set('search', snippet)
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

function createHtmlDocument(content: string, caption: string): string {
  const parser = new DOMParser()
  const document = parser.parseFromString(sanitizeHtml(content), "text/html")
  const snippet = caption.trim().split(/\s+/).slice(0, 10).join(" ")

  if (snippet) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      const node = walker.currentNode as Text
      const index = node.data.toLocaleLowerCase().indexOf(snippet.toLocaleLowerCase())
      if (index < 0 || !node.parentNode) continue

      const mark = document.createElement("mark")
      mark.textContent = node.data.slice(index, index + snippet.length)
      const after = node.splitText(index)
      after.deleteData(0, snippet.length)
      node.parentNode.insertBefore(mark, after)
      break
    }
  }

  const style = document.createElement("style")
  style.textContent = `
    html, body { margin: 0; min-height: 100%; background: white; color: #1e293b; }
    body { box-sizing: border-box; padding: 24px; font: 14px/1.6 ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; max-width: 100%; }
    img { height: auto; }
    table { width: max-content; min-width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #cbd5e1; padding: 8px 12px; vertical-align: top; }
    th { background: #f1f5f9; font-weight: 600; }
    mark { border-radius: 3px; background: #fde68a; padding: 0 2px; color: inherit; }
  `
  document.head.appendChild(style)
  return "<!doctype html>" + document.documentElement.outerHTML
}

function resetViewer() {
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
      if (supportedType === 'pdf') {
        viewerMode.value = 'pdf'
        fileUrl.value = createPdfViewerUrl(result.url, newCitation)
        return
      }

      const data = await fetchFile(result.url, controller.signal)
      if (controller.signal.aborted) return

      if (supportedType === 'txt') {
        viewerMode.value = 'text'
        textContent.value = new TextDecoder('utf-8').decode(data)
        return
      }

      if (supportedType === 'md') {
        viewerMode.value = 'html'
        const source = new TextDecoder('utf-8').decode(data)
        htmlContent.value = createHtmlDocument(markdown.render(source), newCitation.caption)
        return
      }

      viewerMode.value = 'html'
      htmlContent.value = createHtmlDocument(
        await renderOfficeFile(data, supportedType),
        newCitation.caption,
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

onBeforeUnmount(() => loadController?.abort())
</script>

<template>
  <div class="flex h-full flex-col bg-slate-50/50">
    <div class="shrink-0 border-b border-slate-200/50 bg-white px-6 py-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600">
            <FileText class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <div class="truncate text-sm font-semibold text-slate-900">
              {{ citation?.caption || citation?.document || 'No source selected' }}
            </div>
            <div v-if="citation?.heading_path?.length" class="mt-1 text-xs font-medium text-slate-500">
              {{ citation.heading_path.join(' › ') }}
            </div>
            <div class="mt-1 flex items-center gap-2 truncate text-[11px] text-slate-400">
              <span class="truncate">{{ citation?.document || '—' }}</span>
              <span v-if="fileTypeLabel" class="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-500">
                {{ fileTypeLabel }}
              </span>
              <span v-if="citation?.page_number">Page {{ citation.page_number }}</span>
            </div>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <a
            v-if="sourceUrl"
            :href="sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-900"
            title="Open original document"
          >
            <ExternalLink class="h-4 w-4" />
          </a>
          <a
            v-if="sourceUrl"
            :href="sourceUrl"
            :download="citation?.document"
            class="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-900"
            title="Download document"
          >
            <Download class="h-4 w-4" />
          </a>
          <button class="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-900" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>

    <div v-if="citation" class="relative flex-1 overflow-hidden bg-slate-200">
      <div v-if="isLoading" class="absolute inset-0 z-10 flex items-center justify-center bg-white/80">
        <div class="text-sm text-slate-500">Loading document...</div>
      </div>
      <div v-else-if="errorMsg" class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white p-6 text-center">
        <div class="text-sm text-red-500">{{ errorMsg }}</div>
        <a
          v-if="sourceUrl"
          :href="sourceUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="text-sm font-medium text-blue-600 hover:text-blue-700"
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
        sandbox="allow-popups allow-popups-to-escape-sandbox"
        class="h-full w-full border-none bg-white"
        title="Document preview"
      />
      <pre
        v-else-if="viewerMode === 'text'"
        class="h-full overflow-auto whitespace-pre-wrap break-words bg-white p-6 font-mono text-sm leading-6 text-slate-800"
      >{{ textContent }}</pre>
      <div v-else class="absolute inset-0 flex items-center justify-center bg-white text-sm text-slate-400">
        Preview not available
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center p-6 text-sm text-slate-400">
      Select a citation from an answer to inspect its metadata.
    </div>
  </div>
</template>
