<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { AlertTriangle, Calendar, Check, Loader2, Send } from '@lucide/vue'
import { toast } from 'vue-sonner'
import type { HRActionPayload } from '~/types'
import { useHRService } from '~/lib/api/hrService'

const props = defineProps<{ action: HRActionPayload }>()
const hrService = useHRService()
const isSubmitting = ref(false)
const isDone = ref(false)
const serverError = ref<string | null>(null)

// Cảnh báo chồng ngày từ server (code=leave_overlap): user có thể quên đã đặt đơn.
// -> đổi sang "form khác": hiện đơn cũ + nút Vẫn tạo (gửi lại confirm_overlap=true).
interface ExistingLeave {
  request_id?: string
  leave_type?: string
  start_date?: string
  end_date?: string
  status?: string
  reason?: string
}
const overlapWarning = ref<{ message: string; existing: ExistingLeave[] } | null>(null)
const isDuplicateBlocked = ref(false)

const LEAVE_TYPES = [
  { value: 'annual', label: 'Phép năm' },
  { value: 'sick', label: 'Nghỉ ốm' },
  { value: 'personal', label: 'Cá nhân' },
] as const
const TYPE_LABEL: Record<string, string> = {
  annual: 'Phép năm', sick: 'Nghỉ ốm', personal: 'Cá nhân',
}
const STATUS_LABEL: Record<string, string> = {
  pending: 'đang chờ duyệt', approved: 'đã được duyệt',
}

// Form cục bộ: nguồn sự thật cuối là giá trị user chỉnh sửa (không phải draft của model).
const form = reactive({
  leave_type: props.action.parameters.leave_type || 'personal',
  start_date: props.action.parameters.start_date || '',
  end_date: props.action.parameters.end_date || '',
  reason: props.action.parameters.reason || '',
})

const error = computed<string | null>(() => {
  if (!form.start_date || !form.end_date) return 'Vui lòng chọn ngày bắt đầu và kết thúc.'
  if (form.end_date < form.start_date) return 'Ngày kết thúc phải sau hoặc bằng ngày bắt đầu.'
  if (!['annual', 'sick', 'personal'].includes(form.leave_type)) return 'Loại nghỉ không hợp lệ.'
  return null
})

// Khi user sửa form (ngày/loại/lý do) -> reset trạng thái xung đột cũ để check lại từ đầu.
function onFieldChange() {
  overlapWarning.value = null
  isDuplicateBlocked.value = false
  serverError.value = null
}

async function submit(confirmOverlap: boolean) {
  if (isSubmitting.value || isDone.value) return
  if (error.value) {
    toast.error(error.value)
    return
  }
  isSubmitting.value = true
  serverError.value = null
  try {
    await hrService.createLeaveRequest({
      leave_type: form.leave_type,
      start_date: form.start_date,
      end_date: form.end_date,
      reason: form.reason,
      idempotency_key: props.action.idempotency_key,
      confirm_overlap: confirmOverlap,
    })
    toast.success('Đã gửi đơn nghỉ phép thành công!')
    isDone.value = true
    overlapWarning.value = null
    isDuplicateBlocked.value = false
  } catch (err: any) {
    console.error('Action failed:', err)
    // $fetch (ofetch) ném FetchError: body ở err.data, http code ở err.statusCode/status.
    const status = err?.statusCode ?? err?.status ?? err?.response?.status
    const detail = err?.data?.detail ?? err?.response?._data?.detail
    if (status === 409 && detail && typeof detail === 'object') {
      if (detail.code === 'leave_overlap') {
        overlapWarning.value = { message: detail.message, existing: detail.existing || [] }
        isDuplicateBlocked.value = false
      } else if (detail.code === 'leave_duplicate') {
        isDuplicateBlocked.value = true
        overlapWarning.value = null
        serverError.value = detail.message
        toast.error(detail.message)
      } else {
        serverError.value = detail.message || 'Gửi đơn thất bại.'
        toast.error(serverError.value)
      }
    } else {
      const msg = typeof detail === 'string' ? detail : 'Gửi đơn thất bại. Vui lòng thử lại.'
      serverError.value = msg
      toast.error(msg)
    }
  } finally {
    isSubmitting.value = false
  }
}

function fmtExisting(e: ExistingLeave): string {
  const type = TYPE_LABEL[e.leave_type || ''] || e.leave_type || ''
  const range = e.start_date === e.end_date ? e.start_date : `${e.start_date} → ${e.end_date}`
  const st = STATUS_LABEL[e.status || ''] || e.status || ''
  const reason = e.reason ? ` · lý do: "${e.reason}"` : ''
  return `${type} · ${range} (${st})${reason}`
}

const fieldClass
  = 'w-full rounded-md border border-blue-100 dark:border-border bg-white dark:bg-card px-2.5 py-1.5 text-[13px] font-medium text-slate-700 dark:text-foreground/90 outline-none focus:ring-2 focus:ring-blue-500/40 disabled:opacity-60'
</script>

<template>
  <div class="mt-4 rounded-xl border border-blue-100 dark:border-blue-500/20 bg-blue-50/30 dark:bg-blue-500/5 p-4">
    <div class="mb-3 flex items-center gap-2">
      <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600">
        <Calendar class="h-4 w-4" />
      </div>
      <div>
        <h4 class="text-[13px] font-semibold text-slate-900 dark:text-foreground">
          {{ action.action_type === 'create_leave_request' ? 'Xác nhận đơn nghỉ phép' : 'Action Required' }}
        </h4>
        <p class="text-[11px] text-slate-500 dark:text-muted-foreground uppercase font-bold tracking-wider">
          Kiểm tra & chỉnh sửa trước khi gửi
        </p>
      </div>
    </div>

    <div
      v-if="action.action_type === 'create_leave_request'"
      class="space-y-3 rounded-lg border border-blue-100 dark:border-border bg-white dark:bg-card p-3"
    >
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Loại nghỉ</label>
          <select v-model="form.leave_type" :disabled="isDone" :class="fieldClass" @change="onFieldChange">
            <option v-for="t in LEAVE_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Lý do</label>
          <input v-model="form.reason" type="text" :disabled="isDone" :class="fieldClass" placeholder="Tùy chọn" @input="onFieldChange">
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Ngày bắt đầu</label>
          <input v-model="form.start_date" type="date" :disabled="isDone" :class="fieldClass" @change="onFieldChange">
        </div>
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Ngày kết thúc</label>
          <input v-model="form.end_date" type="date" :disabled="isDone" :class="fieldClass" @change="onFieldChange">
        </div>
      </div>

      <p v-if="error && !isDone" class="text-[12px] font-medium text-red-500">{{ error }}</p>
      <p v-else-if="serverError && !isDone" class="text-[12px] font-medium text-amber-600 dark:text-amber-500">{{ serverError }}</p>

      <!-- Form khác: cảnh báo chồng ngày -> liệt kê đơn cũ để user nhớ lại -->
      <div
        v-if="overlapWarning && !isDone"
        class="rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50/70 dark:bg-amber-500/10 p-3"
      >
        <div class="flex items-start gap-2">
          <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <div class="space-y-2">
            <p class="text-[12.5px] font-semibold text-amber-800 dark:text-amber-300">{{ overlapWarning.message }}</p>
            <ul class="space-y-1">
              <li
                v-for="(e, i) in overlapWarning.existing"
                :key="e.request_id || i"
                class="text-[12px] text-amber-800/90 dark:text-amber-200/90"
              >
                • {{ fmtExisting(e) }}
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>

    <div class="mt-4 flex items-center justify-end gap-2">
      <template v-if="!isDone">
        <!-- Mặc định: gửi (server check trùng/overlap). -->
        <button
          v-if="!overlapWarning"
          class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
          :disabled="isSubmitting || !!error || isDuplicateBlocked"
          @click="submit(false)"
        >
          <Loader2 v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
          <Send v-else class="h-3.5 w-3.5" />
          Xác nhận & Gửi
        </button>

        <!-- Form khác: đã cảnh báo chồng ngày -> cho phép vẫn tạo. -->
        <template v-else>
          <span class="mr-auto text-[12px] font-medium text-slate-500 dark:text-muted-foreground">
            Bạn vẫn muốn tạo đơn mới này?
          </span>
          <button
            class="inline-flex items-center gap-2 rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-500 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-amber-600 disabled:opacity-50"
            :disabled="isSubmitting"
            @click="submit(true)"
          >
            <Loader2 v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
            <Send v-else class="h-3.5 w-3.5" />
            Vẫn tạo đơn mới
          </button>
        </template>
      </template>

      <div v-else class="inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-600">
        <Check class="h-4 w-4" />
        Đã gửi đến HR
      </div>
    </div>
  </div>
</template>
