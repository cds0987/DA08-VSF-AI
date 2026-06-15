<script setup lang="ts">
import { AlertTriangle, CheckCircle2, FileText, Loader2, Shield, UploadCloud, User as UserIcon, Users, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import documentService from '~/lib/api/documentService'
import type { Classification, DocumentStatus } from '~/types'

type UploadStatus = DocumentStatus | 'uploading' | 'uncertain'

interface UploadItem {
  id: string
  docId?: string
  file: File
  name: string
  sizeMb: number
  classification: Classification
  allowedDepartments: string
  allowedUserIds: string
  status: UploadStatus
  message?: string
}

// Loại file hợp lệ LẤY TỪ backend (manifest rag-worker ∩ allow_list) -> FE không
// hardcode lệch. Fallback = 7 loại tài liệu cơ bản khi API chưa kịp/ lỗi.
const FALLBACK_EXTENSIONS = ['pdf', 'docx', 'txt', 'xlsx', 'csv', 'pptx', 'md']
const allowedExtensions = ref<Set<string>>(new Set(FALLBACK_EXTENSIONS))
const maxFileBytes = ref(50 * 1024 * 1024)

const acceptAttr = computed(() => [...allowedExtensions.value].map(ext => `.${ext}`).join(','))
const formatsLabel = computed(() => [...allowedExtensions.value].map(ext => ext.toUpperCase()).join(', '))
const maxFileMb = computed(() => Math.round(maxFileBytes.value / (1024 * 1024)))

const loadSupportedFormats = async () => {
  try {
    const res = await documentService.getSupportedFormats()
    if (res.extensions?.length) allowedExtensions.value = new Set(res.extensions.map(ext => ext.toLowerCase()))
    if (res.max_file_bytes) maxFileBytes.value = res.max_file_bytes
  } catch (error) {
    console.error('Failed to load supported formats, using fallback:', error)
  }
}

const items = ref<UploadItem[]>([])
const drag = ref(false)
const fileRef = ref<HTMLInputElement | null>(null)

const openFilePicker = () => {
  fileRef.value?.click()
}
const isUploading = ref(false)
const defaultClassification = ref<Classification>('internal')
const defaultDepartments = ref('')
const defaultUserIds = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const parseAcl = (value: string) => [...new Set(
  value.split(',').map(item => item.trim()).filter(Boolean),
)]

const fileExtension = (name: string) => name.includes('.') ? name.split('.').pop()?.toLowerCase() || '' : ''

const handleFiles = (files: FileList | null) => {
  if (!files) return

  const accepted: UploadItem[] = []
  for (const file of Array.from(files)) {
    const extension = fileExtension(file.name)
    if (!allowedExtensions.value.has(extension)) {
      toast.error(`${file.name}: unsupported file type`)
      continue
    }
    if (file.size > maxFileBytes.value) {
      toast.error(`${file.name}: file exceeds ${maxFileMb.value} MiB`)
      continue
    }

    accepted.push({
      id: `u-${Date.now()}-${crypto.randomUUID()}`,
      file,
      name: file.name,
      sizeMb: +(file.size / (1024 * 1024)).toFixed(2),
      classification: defaultClassification.value,
      allowedDepartments: defaultDepartments.value,
      allowedUserIds: defaultUserIds.value,
      status: 'queued',
    })
  }
  items.value = [...accepted, ...items.value]
  if (fileRef.value) fileRef.value.value = ''
}

const removeFile = (id: string) => {
  items.value = items.value.filter(item => item.id !== id)
}

const validateItem = (item: UploadItem): string | null => {
  if (item.classification === 'secret' && parseAcl(item.allowedDepartments).length === 0) {
    return 'At least one allowed department is required for secret documents'
  }
  if (item.classification === 'top_secret' && parseAcl(item.allowedUserIds).length === 0) {
    return 'At least one allowed user ID is required for top secret documents'
  }
  return null
}

const startUpload = async (item: UploadItem) => {
  if (item.docId || (item.status !== 'queued' && item.status !== 'failed')) return

  const validationError = validateItem(item)
  if (validationError) {
    item.status = 'failed'
    item.message = validationError
    toast.error(`${item.name}: ${validationError}`)
    return
  }

  item.status = 'uploading'
  item.message = undefined
  try {
    const response = await documentService.uploadDocument({
      file: item.file,
      classification: item.classification,
      allowedDepartments: parseAcl(item.allowedDepartments),
      allowedUserIds: parseAcl(item.allowedUserIds),
    })
    item.docId = response.document_id
    item.status = response.status
    item.message = response.message
    toast.success(`${item.name} queued for ingestion`)
  } catch (error) {
    const status = getApiStatus(error)
    item.status = status === 503 ? 'uncertain' : 'failed'
    item.message = status === 503
      ? 'The backend may have created this document. Check the document list before retrying.'
      : getApiErrorMessage(error, 'Upload failed')
    toast.error(`${item.name}: ${item.message}`)
  }
}

const uploadAll = async () => {
  const pending = items.value.filter(item => !item.docId && (item.status === 'queued' || item.status === 'failed'))
  if (pending.length === 0) return

  isUploading.value = true
  try {
    for (const item of pending) await startUpload(item)
  } finally {
    isUploading.value = false
  }
}

const refreshUploadedStatuses = async () => {
  const pending = items.value.filter(
    item => item.docId && (item.status === 'queued' || item.status === 'processing'),
  )

  await Promise.all(pending.map(async (item) => {
    try {
      const document = await documentService.getDocument(item.docId!)
      item.status = document.status
      item.message = document.status === 'failed'
        ? document.error_message || 'Ingestion failed'
        : document.status === 'indexed'
          ? `Indexed into ${document.chunk_count} chunks`
          : 'Ingestion in progress'
    } catch (error) {
      console.error(`Failed to refresh document ${item.docId}:`, error)
    }
  }))
}

const classificationOptions: { value: Classification; label: string }[] = [
  { value: 'public', label: 'Public' },
  { value: 'internal', label: 'Internal' },
  { value: 'secret', label: 'Secret (department only)' },
  { value: 'top_secret', label: 'Top Secret (user only)' },
]

onMounted(() => {
  void loadSupportedFormats()
  pollTimer = setInterval(() => void refreshUploadedStatuses(), 4000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader title="Upload Center" description="Add new documents to the enterprise knowledge base." />
    <div class="space-y-6 px-8 pb-8 pt-2">
      <div class="grid grid-cols-1 gap-4 rounded-xl border border-border bg-card p-4 md:grid-cols-3">
        <div class="space-y-1.5">
          <label class="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <Shield class="h-3.5 w-3.5" /> Default Classification
          </label>
          <select v-model="defaultClassification" class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/15">
            <option v-for="option in classificationOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <Users class="h-3.5 w-3.5" /> Default Allowed Departments
          </label>
          <input
            v-model="defaultDepartments"
            placeholder="IT, HR, Finance"
            class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/15 disabled:opacity-50"
            :disabled="defaultClassification !== 'secret'"
          >
        </div>
        <div class="space-y-1.5">
          <label class="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <UserIcon class="h-3.5 w-3.5" /> Default Allowed User IDs
          </label>
          <input
            v-model="defaultUserIds"
            placeholder="UUIDs separated by commas"
            class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/15 disabled:opacity-50"
            :disabled="defaultClassification !== 'top_secret'"
          >
        </div>
      </div>

      <div
        :class="[
          'flex flex-col items-center justify-center rounded-xl border-2 border-dashed bg-card px-6 py-12 text-center transition',
          drag ? 'border-primary bg-primary/5' : 'border-border',
        ]"
        @dragover.prevent="drag = true"
        @dragleave.prevent="drag = false"
        @drop.prevent="drag = false; handleFiles($event.dataTransfer?.files || null)"
      >
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <UploadCloud class="h-6 w-6" />
        </div>
        <h3 class="mt-3 text-[15px] font-semibold text-foreground">Drop files here, or click to browse</h3>
        <p class="mt-1 text-[12.5px] text-muted-foreground">{{ formatsLabel }} - up to {{ maxFileMb }} MiB per file.</p>
        <button class="mt-4 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90" @click="openFilePicker">
          Select files
        </button>
        <input
          ref="fileRef"
          type="file"
          multiple
          class="hidden"
          :accept="acceptAttr"
          @change="handleFiles(($event.target as HTMLInputElement).files)"
        >
      </div>

      <div v-if="items.length" class="rounded-lg border border-border bg-card">
        <div class="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 class="text-[14px] font-semibold text-foreground">Upload Queue</h2>
            <p class="text-[12px] text-muted-foreground">Uploads run sequentially. A 503 result must be checked before retrying.</p>
          </div>
          <button
            class="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="isUploading"
            @click="uploadAll"
          >
            <Loader2 v-if="isUploading" class="h-3.5 w-3.5 animate-spin" /> Upload All
          </button>
        </div>

        <ul class="divide-y divide-border">
          <li v-for="item in items" :key="item.id" class="px-4 py-4">
            <div class="mb-4 flex items-center gap-3">
              <div class="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary"><FileText class="h-4 w-4" /></div>
              <div class="min-w-0 flex-1">
                <div class="truncate text-[13px] font-medium text-foreground">{{ item.name }}</div>
                <div class="text-[11px] text-muted-foreground">{{ item.sizeMb }} MiB</div>
              </div>
              <div
                :class="[
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
                  item.status === 'queued' && 'bg-muted text-muted-foreground',
                  (item.status === 'processing' || item.status === 'uploading') && 'bg-primary/10 text-primary',
                  item.status === 'indexed' && 'bg-emerald-500/10 text-emerald-600',
                  (item.status === 'failed' || item.status === 'uncertain') && 'bg-destructive/10 text-destructive',
                ]"
              >
                <Loader2 v-if="item.status === 'uploading' || item.status === 'processing'" class="h-3 w-3 animate-spin" />
                <CheckCircle2 v-if="item.status === 'indexed'" class="h-3 w-3" />
                <AlertTriangle v-if="item.status === 'failed' || item.status === 'uncertain'" class="h-3 w-3" />
                {{ item.status === 'uploading' ? 'Uploading...' : item.status }}
              </div>
              <button class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" @click="removeFile(item.id)">
                <X class="h-3.5 w-3.5" />
              </button>
            </div>

            <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div class="space-y-1">
                <span class="text-[11px] font-medium text-muted-foreground">Classification</span>
                <select
                  v-model="item.classification"
                  class="w-full rounded-md border border-input bg-background px-2 py-1 text-[12px] outline-none disabled:opacity-50"
                  :disabled="Boolean(item.docId) || item.status === 'uploading' || item.status === 'uncertain'"
                >
                  <option v-for="option in classificationOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </div>
              <div class="space-y-1">
                <span class="text-[11px] font-medium text-muted-foreground">Allowed Departments</span>
                <input
                  v-model="item.allowedDepartments"
                  class="w-full rounded-md border border-input bg-background px-2 py-1 text-[12px] outline-none disabled:opacity-50"
                  placeholder="IT, HR"
                  :disabled="Boolean(item.docId) || item.status === 'uploading' || item.status === 'uncertain' || item.classification !== 'secret'"
                >
              </div>
              <div class="space-y-1">
                <span class="text-[11px] font-medium text-muted-foreground">Allowed User IDs</span>
                <input
                  v-model="item.allowedUserIds"
                  class="w-full rounded-md border border-input bg-background px-2 py-1 text-[12px] outline-none disabled:opacity-50"
                  placeholder="UUIDs separated by commas"
                  :disabled="Boolean(item.docId) || item.status === 'uploading' || item.status === 'uncertain' || item.classification !== 'top_secret'"
                >
              </div>
            </div>

            <div v-if="item.message" :class="['mt-3 text-[11px]', item.status === 'failed' || item.status === 'uncertain' ? 'text-destructive' : 'text-primary']">
              {{ item.message }}
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
