<script setup lang="ts">
import { ChevronLeft, ChevronRight, Eye, FileText, Loader2, RefreshCw, Search, Trash2 } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import { getApiErrorMessage } from '~/lib/api/apiError'
import documentService from '~/lib/api/documentService'
import { useDocumentStore } from '~/stores/documents'
import type { DocumentStatus } from '~/types'

const q = ref('')
const statusFilter = ref<DocumentStatus | ''>('')
const limit = ref(10)
const offset = ref(0)
const deletingIds = ref(new Set<string>())
const store = useDocumentStore()

const fetchDocuments = async () => {
  try {
    await store.fetchDocuments({
      status: statusFilter.value || undefined,
      limit: limit.value,
      offset: offset.value,
    })
  } catch (error) {
    toast.error(getApiErrorMessage(error, 'Failed to load documents'))
  }
}

const filtered = computed(() => {
  const query = q.value.trim().toLowerCase()
  if (!query) return store.items
  return store.items.filter(document => document.name.toLowerCase().includes(query))
})

const deleteDocument = async (id: string) => {
  if (!confirm('Delete this document? Retrieval-index cleanup may not be immediate.')) return

  deletingIds.value.add(id)
  try {
    await documentService.deleteDocument(id)
    toast.success('Document deleted')
    if (store.items.length === 1 && offset.value > 0) {
      offset.value = Math.max(0, offset.value - limit.value)
    } else {
      await fetchDocuments()
    }
  } catch (error) {
    toast.error(getApiErrorMessage(error, 'Failed to delete document'))
  } finally {
    deletingIds.value.delete(id)
  }
}

const formatDate = (dateStr: string) => new Date(dateStr).toLocaleString('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

watch(statusFilter, () => {
  offset.value = 0
  void fetchDocuments()
})

watch(limit, () => {
  offset.value = 0
  void fetchDocuments()
})

watch(offset, () => void fetchDocuments())

onMounted(async () => {
  await fetchDocuments()
  store.startPolling()
})

onUnmounted(() => store.stopPolling())

const nextPage = () => {
  if (offset.value + limit.value < store.total) offset.value += limit.value
}

const prevPage = () => {
  if (offset.value >= limit.value) offset.value -= limit.value
}
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader
      title="Documents"
      description="Browse and manage documents in the knowledge base."
    >
      <template #actions>
        <NuxtLink
          to="/upload"
          class="rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90"
        >
          Upload
        </NuxtLink>
      </template>
    </PageHeader>

    <div class="px-8 pb-8 pt-2">
      <div class="mb-3 flex items-center justify-between gap-3">
        <div class="flex flex-1 items-center gap-3">
          <div class="relative max-w-sm flex-1">
            <Search class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              v-model="q"
              placeholder="Filter this page by name..."
              class="w-full rounded-md border border-input bg-card py-1.5 pl-8 pr-3 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
          </div>
          <select
            v-model="statusFilter"
            class="rounded-md border border-input bg-card px-3 py-1.5 text-[13px] outline-none focus:border-primary"
          >
            <option value="">All Statuses</option>
            <option value="queued">Queued</option>
            <option value="processing">Processing</option>
            <option value="indexed">Indexed</option>
            <option value="failed">Failed</option>
          </select>
          <button
            class="rounded-md p-1.5 hover:bg-accent disabled:opacity-50"
            :disabled="store.isLoading"
            title="Refresh"
            @click="fetchDocuments"
          >
            <RefreshCw :class="['h-4 w-4 text-muted-foreground', store.isLoading && 'animate-spin']" />
          </button>
        </div>
        <span class="text-[12px] text-muted-foreground">{{ store.total }} total documents</span>
      </div>

      <p v-if="q" class="mb-2 text-[11px] text-muted-foreground">
        Name filtering applies only to the {{ store.items.length }} documents on this page.
      </p>

      <div class="overflow-hidden rounded-lg border border-border bg-card transform-gpu">
        <table class="w-full text-[13px]">
          <thead class="bg-background/60 text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th class="px-4 py-2.5 text-left font-medium">Document</th>
              <th class="px-4 py-2.5 text-left font-medium">Status</th>
              <th class="px-4 py-2.5 text-left font-medium">Classification</th>
              <th class="px-4 py-2.5 text-left font-medium">Uploaded At</th>
              <th class="px-4 py-2.5 text-right font-medium">Chunks</th>
              <th class="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-if="store.isLoading && store.items.length === 0">
              <td colspan="6" class="px-4 py-12 text-center">
                <Loader2 class="mx-auto h-6 w-6 animate-spin text-primary" />
                <p class="mt-2 text-muted-foreground">Loading documents...</p>
              </td>
            </tr>
            <tr v-else-if="filtered.length === 0">
              <td colspan="6" class="px-4 py-12 text-center text-muted-foreground">
                No documents found on this page.
              </td>
            </tr>
            <tr v-for="document in filtered" :key="document.id" class="hover:bg-accent/30">
              <td class="px-4 py-3">
                <NuxtLink
                  :to="`/documents/${document.id}`"
                  class="flex items-center gap-2 font-medium text-foreground hover:text-primary"
                >
                  <FileText class="h-4 w-4 text-muted-foreground" />
                  {{ document.name }}
                </NuxtLink>
              </td>
              <td class="px-4 py-3"><StatusBadge :status="document.status" /></td>
              <td class="px-4 py-3">
                <span class="text-[11px] font-medium uppercase text-muted-foreground">{{ document.classification }}</span>
              </td>
              <td class="px-4 py-3 text-muted-foreground">{{ formatDate(document.created_at) }}</td>
              <td class="px-4 py-3 text-right tabular-nums">{{ document.chunk_count }}</td>
              <td class="px-4 py-3">
                <div class="flex justify-end gap-1">
                  <NuxtLink
                    :to="`/documents/${document.id}`"
                    title="View"
                    class="rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-foreground"
                  >
                    <Eye class="h-3.5 w-3.5" />
                  </NuxtLink>
                  <button
                    title="Delete"
                    class="rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-destructive disabled:opacity-50"
                    :disabled="deletingIds.has(document.id)"
                    @click="deleteDocument(document.id)"
                  >
                    <Loader2 v-if="deletingIds.has(document.id)" class="h-3.5 w-3.5 animate-spin" />
                    <Trash2 v-else class="h-3.5 w-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="store.total > limit" class="mt-4 flex items-center justify-between">
        <span class="text-[12px] text-muted-foreground">
          Showing {{ offset + 1 }} to {{ Math.min(offset + limit, store.total) }} of {{ store.total }}
        </span>
        <div class="flex gap-2">
          <button
            class="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[12px] hover:bg-accent disabled:opacity-50"
            :disabled="offset === 0"
            @click="prevPage"
          >
            <ChevronLeft class="h-3.5 w-3.5" /> Prev
          </button>
          <button
            class="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[12px] hover:bg-accent disabled:opacity-50"
            :disabled="offset + limit >= store.total"
            @click="nextPage"
          >
            Next <ChevronRight class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
