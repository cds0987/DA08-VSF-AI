<script setup lang="ts">
import { AlertCircle, ArrowLeft, CheckCircle2, ExternalLink, FileText, Loader2, RefreshCw, Trash2 } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatCard from '~/components/admin-ui/StatCard.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import documentService from '~/lib/api/documentService'
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

const openFile = async () => {
  const fileTab = window.open('', '_blank')
  if (!fileTab) {
    toast.error('Allow pop-ups to open the document file')
    return
  }

  fileTab.document.title = 'Opening document...'
  try {
    const { url } = await documentService.getFileUrl(id)
    fileTab.location.href = url
  } catch (error) {
    fileTab.close()
    toast.error(getApiErrorMessage(error, 'Failed to get file access URL'))
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
              class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent"
              @click="openFile"
            >
              <ExternalLink class="h-3.5 w-3.5" /> Open File
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
          <div class="rounded-lg border border-border bg-card p-8 lg:col-span-2">
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
