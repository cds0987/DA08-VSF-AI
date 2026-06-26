<script setup lang="ts">
import { AlertCircle, ArrowLeft, CheckCircle2, Download, ExternalLink, FileText, Loader2, RefreshCw, Trash2, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatCard from '~/components/admin-ui/StatCard.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import documentService from '~/lib/api/documentService'
import { previewKindFromMime, type PreviewKind } from '~/lib/documentPreview'
import type { DocumentDetail } from '~/types'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

const doc = ref<DocumentDetail | null>(null)
const isLoading = ref(true)
const isRefreshing = ref(false)
const isDeleting = ref(false)
const loadState = ref<'ready' | 'forbidden' | 'not_found' | 'invalid' | 'error'>('ready')
let pollTimer: ReturnType<typeof setInterval> | null = null

const isPending = computed(() => doc.value?.status === 'queued' || doc.value?.status === 'processing')

const fetchDetail = async (showLoader = false) => {
  if (!uuidPattern.test(id)) {
    loadState.value = 'invalid'
    isLoading.value = false
    return
  }

  if (showLoader) isRefreshing.value = true
  try {
    doc.value = await documentService.getDocument(id)
    loadState.value = 'ready'
  } catch (error) {
    const status = getApiStatus(error)
    loadState.value = status === 403 ? 'forbidden' : status === 404 ? 'not_found' : 'error'
    if (showLoader || loadState.value === 'error') {
      toast.error(getApiErrorMessage(error, 'Failed to load document details'))
    }
  } finally {
    isLoading.value = false
    isRefreshing.value = false
  }
}

const deleteDoc = async () => {
  if (!confirm('Delete this document? Retrieval-index cleanup may not be immediate.')) return

  isDeleting.value = true
  try {
    await documentService.deleteDocument(id)
    toast.success('Document deleted')
    await router.push('/documents')
  } catch (error) {
    toast.error(getApiErrorMessage(error, 'Failed to delete document'))
  } finally {
    isDeleting.value = false
  }
}

// Viewer nhúng in-page: render file ngay trên /admin/documents/{id} (giống Google Drive),
// KHÔNG mở tab mới / KHÔNG điều hướng location sang blob URL.
type PreviewState = 'idle' | 'loading' | 'ready' | 'error'
const previewState = ref<PreviewState>('idle')
const previewObjectUrl = ref<string | null>(null)
const previewText = ref<string | null>(null)
const previewBlob = ref<Blob | null>(null)
const previewError = ref<string | null>(null)
const previewKind = ref<PreviewKind>('unknown')

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
  try {
    // Fetch nội dung render-được (office đã convert -> PDF). Object-URL làm src iframe/img
    // -> top-level URL vẫn /admin/documents/{id}.
    const blob = await documentService.getPreviewBlob(id)
    previewBlob.value = blob
    previewKind.value = previewKindFromMime(blob.type)
    if (previewKind.value === 'text') {
      previewText.value = await blob.text()
      previewState.value = 'ready'
    } else if (previewKind.value === 'unknown') {
      previewState.value = 'error'
      previewError.value = 'Không tạo được bản xem trước cho định dạng này.'
    } else {
      previewObjectUrl.value = URL.createObjectURL(blob)
      previewState.value = 'ready'
    }
  } catch (error) {
    previewState.value = 'error'
    previewError.value = getApiErrorMessage(error, 'Không tạo được bản xem trước')
  }
}

const downloadFile = async () => {
  if (!doc.value) return
  try {
    // Tải BẢN GỐC (không phải bản PDF preview). <a download> + revoke -> trang đứng yên.
    const blob = await documentService.getFileBlob(id)
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

const formatDate = (dateStr?: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const metadata = computed(() => {
  if (!doc.value) return []
  return [
    ['Document ID', doc.value.id],
    ['File type', doc.value.file_type.toUpperCase()],
    ['Classification', doc.value.classification.toUpperCase()],
    ['Uploaded by', doc.value.uploaded_by],
    ['Allowed departments', doc.value.allowed_departments.join(', ') || 'None'],
    ['Allowed users', doc.value.allowed_user_ids.join(', ') || 'None'],
  ]
})

const statusCopy = computed(() => {
  switch (doc.value?.status) {
    case 'indexed':
      return {
        title: 'Indexed and available',
        description: `The document was indexed into ${doc.value.chunk_count} chunks and is available for queries.`,
      }
    case 'failed':
      return {
        title: 'Ingestion failed',
        description: doc.value.error_message || 'The backend did not provide an error message.',
      }
    case 'processing':
      return {
        title: 'Processing',
        description: 'The backend is processing this document. Detailed pipeline stages are not exposed.',
      }
    default:
      return {
        title: 'Queued for ingestion',
        description: 'The upload was accepted and is waiting for a terminal indexing result.',
      }
  }
})

onMounted(async () => {
  await fetchDetail()
  pollTimer = setInterval(() => {
    if (isPending.value) void fetchDetail()
  }, 4000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  resetPreview()
})
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <div v-if="isLoading" class="flex flex-1 items-center justify-center">
      <Loader2 class="h-8 w-8 animate-spin text-primary" />
    </div>

    <template v-else-if="doc && loadState === 'ready'">
      <PageHeader
        :title="doc.name"
        description="Document status and source metadata"
      >
        <template #actions>
          <div class="flex gap-2">
            <button
              class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent disabled:opacity-50"
              :disabled="previewState === 'loading'"
              @click="openPreview"
            >
              <Loader2 v-if="previewState === 'loading'" class="h-3.5 w-3.5 animate-spin" />
              <ExternalLink v-else class="h-3.5 w-3.5" /> Open File
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent disabled:opacity-50"
              :disabled="isRefreshing"
              @click="fetchDetail(true)"
            >
              <RefreshCw :class="['h-3.5 w-3.5', isRefreshing && 'animate-spin']" /> Refresh
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-[12.5px] text-destructive hover:bg-destructive/10 disabled:opacity-50"
              :disabled="isDeleting"
              @click="deleteDoc"
            >
              <Loader2 v-if="isDeleting" class="h-3.5 w-3.5 animate-spin" />
              <Trash2 v-else class="h-3.5 w-3.5" />
              {{ isDeleting ? 'Deleting...' : 'Delete' }}
            </button>
          </div>
        </template>
        <template #meta>
          <NuxtLink to="/documents" class="inline-flex items-center gap-1 hover:text-foreground">
            <ArrowLeft class="h-3 w-3" /> All documents
          </NuxtLink>
        </template>
      </PageHeader>

      <div class="space-y-6 px-8 pb-8 pt-2">
        <div class="grid gap-3 md:grid-cols-4">
          <StatCard label="Status" :value="doc.status.toUpperCase()" />
          <StatCard label="Chunks" :value="doc.chunk_count.toLocaleString()" />
          <StatCard label="Classification" :value="doc.classification.toUpperCase()" />
          <StatCard label="Uploaded At" :value="formatDate(doc.created_at)" />
        </div>

        <div class="grid gap-6 lg:grid-cols-3">
          <!-- Viewer nhúng: render file ngay trong trang khi bấm Open File -->
          <div
            v-if="previewState !== 'idle'"
            class="flex flex-col rounded-lg border border-border bg-card lg:col-span-2"
          >
            <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span class="truncate text-[13px] font-semibold text-foreground">{{ doc.name }}</span>
              <button
                class="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="Close preview"
                @click="closePreview"
              >
                <X class="h-4 w-4" />
              </button>
            </div>
            <div class="flex min-h-[70vh] flex-1 items-center justify-center overflow-auto bg-muted/30">
              <Loader2 v-if="previewState === 'loading'" class="h-7 w-7 animate-spin text-primary" />

              <div v-else-if="previewState === 'error'" class="flex flex-col items-center gap-3 px-6 text-center">
                <AlertCircle class="h-10 w-10 text-destructive opacity-70" />
                <p class="text-[13px] font-medium text-foreground">{{ previewError || 'Không tạo được bản xem trước' }}</p>
                <div class="flex items-center gap-2">
                  <button
                    class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent"
                    @click="openPreview"
                  >
                    <Loader2 v-if="previewState === 'loading'" class="h-3.5 w-3.5 animate-spin" /> Thử lại
                  </button>
                  <button
                    class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent"
                    @click="downloadFile"
                  >
                    <Download class="h-3.5 w-3.5" /> Tải bản gốc
                  </button>
                </div>
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
              >

              <pre
                v-else-if="previewState === 'ready' && previewKind === 'text'"
                class="h-[70vh] w-full overflow-auto whitespace-pre-wrap break-words p-4 text-left text-[12.5px] text-foreground"
              >{{ previewText }}</pre>

            </div>
          </div>

          <div v-else class="rounded-lg border border-border bg-card p-8 lg:col-span-2">
            <div class="flex flex-col items-center justify-center text-center">
              <div
                :class="[
                  'flex h-12 w-12 items-center justify-center rounded-full',
                  doc.status === 'indexed' && 'bg-emerald-500/10 text-emerald-600',
                  doc.status === 'failed' && 'bg-destructive/10 text-destructive',
                  isPending && 'bg-primary/10 text-primary',
                ]"
              >
                <CheckCircle2 v-if="doc.status === 'indexed'" class="h-6 w-6" />
                <AlertCircle v-else-if="doc.status === 'failed'" class="h-6 w-6" />
                <Loader2 v-else class="h-6 w-6 animate-spin" />
              </div>
              <h3 class="mt-4 text-[15px] font-semibold text-foreground">{{ statusCopy.title }}</h3>
              <p class="mt-1 max-w-lg text-[12.5px] text-muted-foreground">{{ statusCopy.description }}</p>
              <p v-if="isPending" class="mt-3 text-[11px] text-muted-foreground">Status refreshes every 4 seconds.</p>
            </div>
          </div>

          <div class="rounded-lg border border-border bg-card">
            <div class="border-b border-border px-4 py-3 text-[13px] font-semibold text-muted-foreground">Source metadata</div>
            <dl class="divide-y divide-border text-[12.5px]">
              <div v-for="[key, value] in metadata" :key="key" class="px-4 py-2.5">
                <dt class="text-muted-foreground">{{ key }}</dt>
                <dd class="mt-1 break-all font-medium text-foreground">{{ value }}</dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="flex flex-1 flex-col items-center justify-center px-6 text-center">
      <FileText class="h-12 w-12 text-muted-foreground opacity-20" />
      <h3 class="mt-4 text-[16px] font-semibold">
        {{ loadState === 'forbidden' ? 'Access denied' : loadState === 'invalid' ? 'Invalid document ID' : 'Document not found' }}
      </h3>
      <p class="mt-1 max-w-md text-muted-foreground">
        {{ loadState === 'forbidden'
          ? 'Your account does not have access to this document.'
          : loadState === 'invalid'
            ? 'The document URL does not contain a valid UUID.'
            : 'The document may have been deleted or is unavailable.' }}
      </p>
      <NuxtLink to="/documents" class="mt-4 text-primary hover:underline">Back to documents</NuxtLink>
    </div>
  </div>
</template>
