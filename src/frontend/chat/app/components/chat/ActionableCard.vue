<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { Calendar, Check, Loader2, Send } from '@lucide/vue'
import { toast } from 'vue-sonner'
import type { HRActionPayload } from '~/types'
import { useHRService } from '~/lib/api/hrService'

const props = defineProps<{ action: HRActionPayload }>()
const hrService = useHRService()
const isSubmitting = ref(false)
const isDone = ref(false)

const LEAVE_TYPES = [
  { value: 'annual', label: 'Phép năm' },
  { value: 'sick', label: 'Nghỉ ốm' },
  { value: 'personal', label: 'Cá nhân' },
] as const

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

async function handleConfirm() {
  if (isSubmitting.value || isDone.value) return
  if (error.value) {
    toast.error(error.value)
    return
  }

  isSubmitting.value = true
  try {
    await hrService.createLeaveRequest({
      leave_type: form.leave_type,
      start_date: form.start_date,
      end_date: form.end_date,
      reason: form.reason,
      idempotency_key: props.action.idempotency_key,
    })
    toast.success('Đã gửi đơn nghỉ phép thành công!')
    isDone.value = true
  } catch (err) {
    console.error('Action failed:', err)
    toast.error('Gửi đơn thất bại. Vui lòng thử lại.')
  } finally {
    isSubmitting.value = false
  }
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
          <select v-model="form.leave_type" :disabled="isDone" :class="fieldClass">
            <option v-for="t in LEAVE_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Lý do</label>
          <input v-model="form.reason" type="text" :disabled="isDone" :class="fieldClass" placeholder="Tùy chọn">
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Ngày bắt đầu</label>
          <input v-model="form.start_date" type="date" :disabled="isDone" :class="fieldClass">
        </div>
        <div>
          <label class="mb-1 block text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Ngày kết thúc</label>
          <input v-model="form.end_date" type="date" :disabled="isDone" :class="fieldClass">
        </div>
      </div>
      <p v-if="error && !isDone" class="text-[12px] font-medium text-red-500">{{ error }}</p>
    </div>

    <div class="mt-4 flex justify-end">
      <button
        v-if="!isDone"
        class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
        :disabled="isSubmitting || !!error"
        @click="handleConfirm"
      >
        <Loader2 v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
        <Send v-else class="h-3.5 w-3.5" />
        Xác nhận & Gửi
      </button>
      <div v-else class="inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-600">
        <Check class="h-4 w-4" />
        Đã gửi đến HR
      </div>
    </div>
  </div>
</template>
