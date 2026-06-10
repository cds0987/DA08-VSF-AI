<script setup lang="ts">
import { ref } from 'vue'
import { Calendar, Check, Loader2, Send } from '@lucide/vue'
import { toast } from 'vue-sonner'
import type { HRActionPayload } from '~/types'
import { useHRService } from '~/lib/api/hrService'

const props = defineProps<{ action: HRActionPayload }>()
const hrService = useHRService()
const isSubmitting = ref(false)
const isDone = ref(false)

async function handleConfirm() {
  if (isSubmitting.value || isDone.value) return

  isSubmitting.value = true
  try {
    if (props.action.action_type === 'create_leave_request') {
      await hrService.createLeaveRequest(props.action.parameters)
      toast.success('Leave request submitted successfully!')
      isDone.value = true
    }
  } catch (error) {
    console.error('Action failed:', error)
    toast.error('Failed to submit action. Please try again.')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="mt-4 rounded-xl border border-blue-100 bg-blue-50/30 p-4">
    <div class="mb-3 flex items-center gap-2">
      <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600">
        <Calendar class="h-4 w-4" />
      </div>
      <div>
        <h4 class="text-[13px] font-semibold text-slate-900">
          {{ action.action_type === 'create_leave_request' ? 'Leave Request Draft' : 'Action Required' }}
        </h4>
        <p class="text-[11px] text-slate-500 uppercase font-bold tracking-wider">HR Service Tool</p>
      </div>
    </div>

    <div v-if="action.action_type === 'create_leave_request'" class="space-y-2.5 rounded-lg border border-blue-100 bg-white p-3 shadow-sm">
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="text-[10px] font-bold uppercase text-slate-400">Type</label>
          <div class="text-[13px] font-medium text-slate-700 capitalize">{{ action.parameters.leave_type }}</div>
        </div>
        <div>
          <label class="text-[10px] font-bold uppercase text-slate-400">Reason</label>
          <div class="text-[13px] font-medium text-slate-700 truncate" :title="action.parameters.reason">
            {{ action.parameters.reason || '—' }}
          </div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4 pt-1">
        <div>
          <label class="text-[10px] font-bold uppercase text-slate-400">Start Date</label>
          <div class="text-[13px] font-medium text-slate-700">{{ action.parameters.start_date }}</div>
        </div>
        <div>
          <label class="text-[10px] font-bold uppercase text-slate-400">End Date</label>
          <div class="text-[13px] font-medium text-slate-700">{{ action.parameters.end_date }}</div>
        </div>
      </div>
    </div>

    <div class="mt-4 flex justify-end">
      <button
        v-if="!isDone"
        class="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
        :disabled="isSubmitting"
        @click="handleConfirm"
      >
        <Loader2 v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
        <Send v-else class="h-3.5 w-3.5" />
        Confirm and Submit
      </button>
      <div v-else class="inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-600">
        <Check class="h-4 w-4" />
        Submitted to HR
      </div>
    </div>
  </div>
</template>
