<script setup lang="ts">
import { ChevronLeft, ChevronRight, Eye, FileText, Loader2, RefreshCw, Search, Trash2, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import { Checkbox } from '~/components/ui/checkbox'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { getApiErrorMessage } from '~/lib/api/apiError'
import documentService from '~/lib/api/documentService'
import { useDocumentStore } from '~/stores/documents'
import type { DocumentStatus } from '~/types'

const q = ref('')
const statusFilter = ref<DocumentStatus | ''>('')
const limit = ref(10)
const offset = ref(0)
const store = useDocumentStore()

// --- Multi-select state ---
const selected = ref(new Set<string>())   // id chọn thủ công trên trang hiện tại
const selectAllMatching = ref(false)       // cờ "chọn tất cả N" theo bộ lọc (qua mọi trang)
const confirmIds = ref<string[] | null>(null) // != null -> mở AlertDialog
const preparing = ref(false)               // đang gom id cho "chọn tất cả N"
const deleting = ref(false)                // đang gọi API xóa

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

const isRowChecked = (id: string) => selectAllMatching.value || selected.value.has(id)

const allPageChecked = computed(() =>
  filtered.value.length > 0 && filtered.value.every(d => isRowChecked(d.id)),
)
const somePageChecked = computed(() =>
  !allPageChecked.value && filtered.value.some(d => isRowChecked(d.id)),
)
const headerState = computed<boolean | 'indeterminate'>(() =>
  allPageChecked.value ? true : (somePageChecked.value ? 'indeterminate' : false),
)

// Còn trang khác để mời "chọn tất cả N".
const hasMorePages = computed(() => store.total > filtered.value.length)
const showSelectAllBanner = computed(() =>
  allPageChecked.value && hasMorePages.value && !selectAllMatching.value,
)

const selectedCount = computed(() => (selectAllMatching.value ? store.total : selected.value.size))

function toggleRow(id: string, value: boolean | 'indeterminate') {
  // Bỏ chọn 1 dòng khi đang "chọn tất cả N" -> thu hẹp về trang hiện tại.
  if (selectAllMatching.value) {
    selectAllMatching.value = false
    selected.value = new Set(filtered.value.map(d => d.id))
  }
  const next = new Set(selected.value)
  if (value === true) next.add(id)
  else next.delete(id)
  selected.value = next
}

function togglePage(value: boolean | 'indeterminate') {
  selectAllMatching.value = false
  if (value === true) selected.value = new Set(filtered.value.map(d => d.id))
  else selected.value = new Set()
}

function clearSelection() {
  selected.value = new Set()
  selectAllMatching.value = false
}

// Mở dialog cho 1 doc (icon thùng rác).
function askDeleteOne(id: string) {
  confirmIds.value = [id]
}

// Mở dialog cho lựa chọn hàng loạt.
async function askDeleteSelected() {
  if (selectAllMatching.value) {
    preparing.value = true
    try {
      confirmIds.value = await documentService.fetchAllIds(statusFilter.value || undefined)
    } catch (error) {
      toast.error(getApiErrorMessage(error, 'Không gom được danh sách tài liệu'))
    } finally {
      preparing.value = false
    }
  } else {
    confirmIds.value = [...selected.value]
  }
}

async function confirmDelete() {
  const ids = confirmIds.value
  if (!ids || ids.length === 0) return
  deleting.value = true
  try {
    const result = await documentService.deleteDocuments(ids)
    const skipped = result.not_found.length + result.failed.length
    if (skipped > 0) {
      toast.warning(`Đã xóa ${result.deleted}/${ids.length} tài liệu (${skipped} bị bỏ qua).`)
    } else {
      toast.success(`Đã xóa ${result.deleted} tài liệu.`)
    }
    confirmIds.value = null
    clearSelection()
    // Nếu trang hiện tại có thể rỗng sau khi xóa -> lùi 1 trang.
    if (offset.value > 0 && result.deleted >= filtered.value.length) {
      offset.value = Math.max(0, offset.value - limit.value)
    } else {
      await fetchDocuments()
    }
  } catch (error) {
    toast.error(getApiErrorMessage(error, 'Xóa tài liệu thất bại'))
  } finally {
    deleting.value = false
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
  clearSelection()
  void fetchDocuments()
})

watch(limit, () => {
  offset.value = 0
  clearSelection()
  void fetchDocuments()
})

watch(offset, () => {
  clearSelection()
  void fetchDocuments()
})

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

      <!-- Thanh hành động hàng loạt: hiện khi có lựa chọn -->
      <div
        v-if="selectedCount > 0"
        class="mb-3 flex items-center justify-between gap-3 rounded-lg border border-primary/40 bg-primary/5 px-4 py-2.5"
      >
        <span class="text-[13px] font-medium">
          Đã chọn {{ selectedCount }} tài liệu
        </span>
        <div class="flex items-center gap-2">
          <button
            class="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-[12.5px] font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            :disabled="preparing"
            @click="askDeleteSelected"
          >
            <Loader2 v-if="preparing" class="h-3.5 w-3.5 animate-spin" />
            <Trash2 v-else class="h-3.5 w-3.5" />
            Xóa
          </button>
          <button
            class="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-[12.5px] hover:bg-accent"
            @click="clearSelection"
          >
            <X class="h-3.5 w-3.5" /> Bỏ chọn
          </button>
        </div>
      </div>

      <div class="overflow-hidden rounded-lg border border-border bg-card transform-gpu">
        <table class="w-full text-[13px]">
          <thead class="bg-background/60 text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th class="w-10 px-4 py-2.5 text-left font-medium">
                <Checkbox
                  :model-value="headerState"
                  aria-label="Chọn tất cả trên trang này"
                  @update:model-value="togglePage"
                />
              </th>
              <th class="px-4 py-2.5 text-left font-medium">Document</th>
              <th class="px-4 py-2.5 text-left font-medium">Status</th>
              <th class="px-4 py-2.5 text-left font-medium">Classification</th>
              <th class="px-4 py-2.5 text-left font-medium">Uploaded At</th>
              <th class="px-4 py-2.5 text-right font-medium">Chunks</th>
              <th class="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <!-- Banner mời chọn tất cả N qua nhiều trang -->
            <tr v-if="showSelectAllBanner" class="bg-primary/5">
              <td colspan="7" class="px-4 py-2 text-center text-[12px] text-muted-foreground">
                Đã chọn {{ filtered.length }} trên trang này.
                <button
                  class="font-medium text-primary hover:underline"
                  @click="selectAllMatching = true"
                >
                  Chọn tất cả {{ store.total }} tài liệu
                </button>
              </td>
            </tr>
            <tr v-if="store.isLoading && store.items.length === 0">
              <td colspan="7" class="px-4 py-12 text-center">
                <Loader2 class="mx-auto h-6 w-6 animate-spin text-primary" />
                <p class="mt-2 text-muted-foreground">Loading documents...</p>
              </td>
            </tr>
            <tr v-else-if="filtered.length === 0">
              <td colspan="7" class="px-4 py-12 text-center text-muted-foreground">
                No documents found on this page.
              </td>
            </tr>
            <tr
              v-for="document in filtered"
              :key="document.id"
              class="hover:bg-accent/30"
              :class="isRowChecked(document.id) && 'bg-primary/5'"
            >
              <td class="px-4 py-3">
                <Checkbox
                  :model-value="isRowChecked(document.id)"
                  :aria-label="`Chọn ${document.name}`"
                  @update:model-value="(v) => toggleRow(document.id, v)"
                />
              </td>
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
                    class="rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-destructive"
                    @click="askDeleteOne(document.id)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
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

    <!-- Xác nhận xóa (đơn lẻ & hàng loạt dùng chung) -->
    <AlertDialog
      :open="confirmIds !== null"
      @update:open="(o) => { if (!o) confirmIds = null }"
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Xóa {{ confirmIds?.length ?? 0 }} tài liệu?</AlertDialogTitle>
          <AlertDialogDescription>
            Gỡ vĩnh viễn {{ confirmIds?.length ?? 0 }} tài liệu và toàn bộ chunk khỏi knowledge base.
            Việc dọn index có thể không tức thì.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel :disabled="deleting">Hủy</AlertDialogCancel>
          <button
            class="inline-flex items-center justify-center rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            :disabled="deleting"
            @click="confirmDelete"
          >
            <Loader2 v-if="deleting" class="mr-1.5 h-3.5 w-3.5 animate-spin" />
            Xóa {{ confirmIds?.length ?? 0 }}
          </button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
