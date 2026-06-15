<script setup lang="ts">
import { AlertTriangle, CheckCircle2, ChevronDown, FileText, Loader2, Shield, UploadCloud, User as UserIcon, Users, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import documentService from '~/lib/api/documentService'
import hrService from '~/lib/api/hrService'
import userService from '~/lib/api/userService'
import type { Classification, DocumentStatus, User } from '~/types'

type UploadStatus = DocumentStatus | 'uploading' | 'uncertain'

interface UploadItem {
  id: string
  docId?: string
  file: File
  name: string
  sizeMb: number
  classification: Classification
  allowedDepartments: string[]
  allowedUserIds: string[]
  status: UploadStatus
  message?: string
}

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

const openFilePicker = () => { fileRef.value?.click() }
const isUploading = ref(false)
const defaultClassification = ref<Classification>('internal')
const defaultDepartments = ref<string[]>([])
const defaultUserIds = ref<string[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

// Picker state
const allDepartments = ref<string[]>([])
const allUsers = ref<User[]>([])
const openDropdown = ref<string | null>(null)
const deptSearch = ref('')
const userSearch = ref('')

const filteredDepts = computed(() => {
  const q = deptSearch.value.toLowerCase()
  return q ? allDepartments.value.filter(d => d.toLowerCase().includes(q)) : allDepartments.value
})

const filteredUsers = computed(() => {
  const q = userSearch.value.toLowerCase()
  if (!q) return allUsers.value
  return allUsers.value.filter(u => u.email.toLowerCase().includes(q) || (u.name || '').toLowerCase().includes(q))
})

const getUserLabel = (uid: string): string => {
  const u = allUsers.value.find(u => u.id === uid)
  return u ? (u.name || u.email) : uid.slice(0, 12) + '…'
}

const toggleInArray = (arr: string[], item: string) => {
  const i = arr.indexOf(item)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(item)
}

const openDeptPicker = (key: string) => {
  openDropdown.value = openDropdown.value === `${key}-dept` ? null : `${key}-dept`
  deptSearch.value = ''
}

const openUserPicker = (key: string) => {
  openDropdown.value = openDropdown.value === `${key}-user` ? null : `${key}-user`
  userSearch.value = ''
}

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
      allowedDepartments: [...defaultDepartments.value],
      allowedUserIds: [...defaultUserIds.value],
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
  if (item.classification === 'secret' && item.allowedDepartments.length === 0) {
    return 'At least one allowed department is required for secret documents'
  }
  if (item.classification === 'top_secret' && item.allowedUserIds.length === 0) {
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
      allowedDepartments: item.allowedDepartments,
      allowedUserIds: item.allowedUserIds,
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
  void hrService.listDepartments().then(d => { allDepartments.value = d }).catch(() => {})
  void userService.listUsers({ is_active: true, limit: 200 }).then(r => { allUsers.value = r.items }).catch(() => {})
  pollTimer = setInterval(() => void refreshUploadedStatuses(), 4000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto" @click="openDropdown = null">
    <!-- Transparent overlay to close open dropdowns when clicking outside -->
    <div v-if="openDropdown" class="fixed inset-0 z-10" @click.stop="openDropdown = null" />

    <PageHeader title="Upload Center" description="Add new documents to the enterprise knowledge base." />
    <div class="space-y-6 px-8 pb-8 pt-2">
      <!-- Default classification / ACL settings -->
      <div class="grid grid-cols-1 gap-4 rounded-xl border border-border bg-card p-4 md:grid-cols-3">
        <div class="space-y-1.5">
          <label class="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <Shield class="h-3.5 w-3.5" /> Default Classification
          </label>
          <select v-model="defaultClassification" class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/15">
            <option v-for="option in classificationOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>

        <!-- Default Allowed Departments picker -->
        <div class="space-y-1.5">
          <label class="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <Users class="h-3.5 w-3.5" /> Default Allowed Departments
          </label>
          <div class="relative z-20">
            <div
              class="flex min-h-[34px] w-full cursor-pointer flex-wrap items-center gap-1 rounded-md border border-input bg-background px-2.5 py-1 text-[13px] transition focus-within:ring-2 focus-within:ring-primary/15"
              :class="defaultClassification !== 'secret' ? 'pointer-events-none opacity-50' : ''"
              @click.stop="openDeptPicker('default')"
            >
              <span v-if="!defaultDepartments.length" class="flex-1 text-[13px] text-muted-foreground">Select departments...</span>
              <template v-else>
                <span v-for="d in defaultDepartments" :key="d" class="inline-flex items-center gap-0.5 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  {{ d }}<button class="ml-0.5 rounded hover:text-destructive" @click.stop="toggleInArray(defaultDepartments, d)"><X class="h-3 w-3" /></button>
                </span>
              </template>
              <ChevronDown class="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </div>
            <div v-if="openDropdown === 'default-dept'" class="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-background shadow-lg">
              <div class="border-b border-border px-2 py-1.5">
                <input v-model="deptSearch" class="w-full rounded bg-muted px-2 py-1 text-[12px] outline-none" placeholder="Filter departments..." @click.stop />
              </div>
              <ul class="max-h-44 overflow-y-auto py-1">
                <li v-if="!filteredDepts.length" class="px-3 py-2 text-[12px] text-muted-foreground">
                  {{ allDepartments.length === 0 ? 'No departments found in HR data' : 'No match' }}
                </li>
                <li
                  v-for="dept in filteredDepts"
                  :key="dept"
                  class="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-[12px] hover:bg-accent"
                  @click.stop="toggleInArray(defaultDepartments, dept)"
                >
                  <input type="checkbox" :checked="defaultDepartments.includes(dept)" class="h-3.5 w-3.5 accent-primary" readonly @click.stop />
                  {{ dept }}
                </li>
              </ul>
            </div>
          </div>
        </div>

        <!-- Default Allowed Users picker -->
        <div class="space-y-1.5">
          <label class="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <UserIcon class="h-3.5 w-3.5" /> Default Allowed Users
          </label>
          <div class="relative z-20">
            <div
              class="flex min-h-[34px] w-full cursor-pointer flex-wrap items-center gap-1 rounded-md border border-input bg-background px-2.5 py-1 text-[13px] transition focus-within:ring-2 focus-within:ring-primary/15"
              :class="defaultClassification !== 'top_secret' ? 'pointer-events-none opacity-50' : ''"
              @click.stop="openUserPicker('default')"
            >
              <span v-if="!defaultUserIds.length" class="flex-1 text-[13px] text-muted-foreground">Select users...</span>
              <template v-else>
                <span v-for="uid in defaultUserIds" :key="uid" class="inline-flex items-center gap-0.5 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  {{ getUserLabel(uid) }}<button class="ml-0.5 rounded hover:text-destructive" @click.stop="toggleInArray(defaultUserIds, uid)"><X class="h-3 w-3" /></button>
                </span>
              </template>
              <ChevronDown class="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </div>
            <div v-if="openDropdown === 'default-user'" class="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-background shadow-lg">
              <div class="border-b border-border px-2 py-1.5">
                <input v-model="userSearch" class="w-full rounded bg-muted px-2 py-1 text-[12px] outline-none" placeholder="Search by name or email..." @click.stop />
              </div>
              <ul class="max-h-44 overflow-y-auto py-1">
                <li v-if="!filteredUsers.length" class="px-3 py-2 text-[12px] text-muted-foreground">No users found</li>
                <li
                  v-for="u in filteredUsers"
                  :key="u.id"
                  class="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-accent"
                  @click.stop="toggleInArray(defaultUserIds, u.id)"
                >
                  <input type="checkbox" :checked="defaultUserIds.includes(u.id)" class="h-3.5 w-3.5 shrink-0 accent-primary" readonly @click.stop />
                  <div class="min-w-0">
                    <div class="truncate text-[12px] font-medium">{{ u.name || u.email }}</div>
                    <div v-if="u.name" class="truncate text-[11px] text-muted-foreground">{{ u.email }}</div>
                  </div>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- Drop zone -->
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

      <!-- Upload queue -->
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
              <!-- Per-file classification -->
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

              <!-- Per-file Allowed Departments picker -->
              <div class="space-y-1">
                <span class="text-[11px] font-medium text-muted-foreground">Allowed Departments</span>
                <div class="relative z-20">
                  <div
                    class="flex min-h-[28px] w-full cursor-pointer flex-wrap items-center gap-1 rounded-md border border-input bg-background px-2 py-0.5 text-[12px] transition"
                    :class="(Boolean(item.docId) || item.status === 'uploading' || item.status === 'uncertain' || item.classification !== 'secret') ? 'pointer-events-none opacity-50' : ''"
                    @click.stop="openDeptPicker(item.id)"
                  >
                    <span v-if="!item.allowedDepartments.length" class="flex-1 text-[12px] text-muted-foreground">Select...</span>
                    <template v-else>
                      <span v-for="d in item.allowedDepartments" :key="d" class="inline-flex items-center gap-0.5 rounded bg-primary/10 px-1 py-0.5 text-[10px] font-medium text-primary">
                        {{ d }}<button class="ml-0.5 hover:text-destructive" @click.stop="toggleInArray(item.allowedDepartments, d)"><X class="h-2.5 w-2.5" /></button>
                      </span>
                    </template>
                    <ChevronDown class="ml-auto h-3 w-3 shrink-0 text-muted-foreground" />
                  </div>
                  <div v-if="openDropdown === `${item.id}-dept`" class="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-background shadow-lg">
                    <div class="border-b border-border px-2 py-1">
                      <input v-model="deptSearch" class="w-full rounded bg-muted px-2 py-0.5 text-[11px] outline-none" placeholder="Filter..." @click.stop />
                    </div>
                    <ul class="max-h-36 overflow-y-auto py-0.5">
                      <li v-if="!filteredDepts.length" class="px-3 py-1.5 text-[11px] text-muted-foreground">
                        {{ allDepartments.length === 0 ? 'No departments in HR data' : 'No match' }}
                      </li>
                      <li
                        v-for="dept in filteredDepts"
                        :key="dept"
                        class="flex cursor-pointer items-center gap-2 px-3 py-1 text-[11px] hover:bg-accent"
                        @click.stop="toggleInArray(item.allowedDepartments, dept)"
                      >
                        <input type="checkbox" :checked="item.allowedDepartments.includes(dept)" class="h-3 w-3 accent-primary" readonly @click.stop />
                        {{ dept }}
                      </li>
                    </ul>
                  </div>
                </div>
              </div>

              <!-- Per-file Allowed Users picker -->
              <div class="space-y-1">
                <span class="text-[11px] font-medium text-muted-foreground">Allowed Users</span>
                <div class="relative z-20">
                  <div
                    class="flex min-h-[28px] w-full cursor-pointer flex-wrap items-center gap-1 rounded-md border border-input bg-background px-2 py-0.5 text-[12px] transition"
                    :class="(Boolean(item.docId) || item.status === 'uploading' || item.status === 'uncertain' || item.classification !== 'top_secret') ? 'pointer-events-none opacity-50' : ''"
                    @click.stop="openUserPicker(item.id)"
                  >
                    <span v-if="!item.allowedUserIds.length" class="flex-1 text-[12px] text-muted-foreground">Select...</span>
                    <template v-else>
                      <span v-for="uid in item.allowedUserIds" :key="uid" class="inline-flex items-center gap-0.5 rounded bg-primary/10 px-1 py-0.5 text-[10px] font-medium text-primary">
                        {{ getUserLabel(uid) }}<button class="ml-0.5 hover:text-destructive" @click.stop="toggleInArray(item.allowedUserIds, uid)"><X class="h-2.5 w-2.5" /></button>
                      </span>
                    </template>
                    <ChevronDown class="ml-auto h-3 w-3 shrink-0 text-muted-foreground" />
                  </div>
                  <div v-if="openDropdown === `${item.id}-user`" class="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-border bg-background shadow-lg">
                    <div class="border-b border-border px-2 py-1">
                      <input v-model="userSearch" class="w-full rounded bg-muted px-2 py-0.5 text-[11px] outline-none" placeholder="Search name or email..." @click.stop />
                    </div>
                    <ul class="max-h-36 overflow-y-auto py-0.5">
                      <li v-if="!filteredUsers.length" class="px-3 py-1.5 text-[11px] text-muted-foreground">No users found</li>
                      <li
                        v-for="u in filteredUsers"
                        :key="u.id"
                        class="flex cursor-pointer items-center gap-2 px-3 py-1 hover:bg-accent"
                        @click.stop="toggleInArray(item.allowedUserIds, u.id)"
                      >
                        <input type="checkbox" :checked="item.allowedUserIds.includes(u.id)" class="h-3 w-3 shrink-0 accent-primary" readonly @click.stop />
                        <div class="min-w-0">
                          <div class="truncate text-[11px] font-medium">{{ u.name || u.email }}</div>
                          <div v-if="u.name" class="truncate text-[10px] text-muted-foreground">{{ u.email }}</div>
                        </div>
                      </li>
                    </ul>
                  </div>
                </div>
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
