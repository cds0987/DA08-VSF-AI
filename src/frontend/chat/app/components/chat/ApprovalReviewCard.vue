<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { AlertTriangle, Calendar, Check, Loader2, RefreshCw, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { useHRService } from '~/lib/api/hrService'

// Thẻ duyệt trong chat: KHÔNG tin dữ liệu model — tự nạp hàng đợi LIVE từ hr-service
// (tránh model chép sai request_id). Mỗi đơn có nút Duyệt/Từ chối -> REST sẵn có.
interface LeaveApproval {
  id: string
  user_id: string
  leave_type: string
  start_date: string
  end_date: string
  days_count: number
  reason?: string | null
  // Gợi ý quyết định (enrich từ hr-service, có thể chưa có):
  employee_leave_remaining?: number | null
  employee_leave_total?: number | null
  has_conflict?: boolean
}

const hrService = useHRService()
const items = ref<LeaveApproval[]>([])
const isLoading = ref(false)
const actingId = ref<string | null>(null)
const loaded = ref(false)

const TYPE_LABEL: Record<string, string> = {
  annual: 'Phép năm', sick: 'Nghỉ ốm', personal: 'Cá nhân',
}

async function load() {
  isLoading.value = true
  try {
    items.value = (await hrService.fetchPendingApprovals()) as LeaveApproval[]
  } catch (e) {
    console.error(e)
    toast.error('Không tải được danh sách đơn chờ duyệt.')
  } finally {
    isLoading.value = false
    loaded.value = true
  }
}

async function approve(req: LeaveApproval) {
  if (actingId.value) return
  actingId.value = req.id
  try {
    await hrService.approveLeaveRequest(req.id)
    toast.success(`Đã duyệt đơn ${TYPE_LABEL[req.leave_type] || req.leave_type} (${req.start_date} → ${req.end_date}).`)
    items.value = items.value.filter(r => r.id !== req.id)
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Duyệt đơn thất bại.')
  } finally {
    actingId.value = null
  }
}

async function reject(req: LeaveApproval) {
  if (actingId.value) return
  const reason = window.prompt('Lý do từ chối (tùy chọn):', '') ?? ''
  actingId.value = req.id
  try {
    await hrService.rejectLeaveRequest(req.id, reason)
    toast.success('Đã từ chối đơn.')
    items.value = items.value.filter(r => r.id !== req.id)
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Từ chối đơn thất bại.')
  } finally {
    actingId.value = null
  }
}

function shortId(uid: string): string {
  return uid.length > 12 ? `${uid.slice(0, 8)}…` : uid
}

onMounted(load)
</script>

<template>
  <div class="mt-4 rounded-xl border border-blue-100 dark:border-blue-500/20 bg-blue-50/30 dark:bg-blue-500/5 p-4">
    <div class="mb-3 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600">
          <Calendar class="h-4 w-4" />
        </div>
        <div>
          <h4 class="text-[13px] font-semibold text-slate-900 dark:text-foreground">Đơn chờ bạn duyệt</h4>
          <p class="text-[11px] uppercase font-bold tracking-wider text-slate-500 dark:text-muted-foreground">
            Duyệt sẽ tự trừ ngày phép của nhân viên
          </p>
        </div>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-border px-2.5 py-1.5 text-[12px] font-medium text-slate-600 dark:text-foreground/80 hover:bg-slate-100 dark:hover:bg-accent disabled:opacity-50"
        :disabled="isLoading"
        @click="load"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="isLoading ? 'animate-spin' : ''" /> Làm mới
      </button>
    </div>

    <div v-if="isLoading && items.length === 0" class="flex items-center justify-center py-8 text-slate-400">
      <Loader2 class="h-5 w-5 animate-spin" />
    </div>

    <div
      v-else-if="loaded && items.length === 0"
      class="rounded-lg border border-dashed border-slate-200 dark:border-border py-8 text-center text-[13px] text-slate-500 dark:text-muted-foreground"
    >
      Hiện không có đơn nào chờ bạn duyệt.
    </div>

    <div v-else class="flex flex-col gap-3">
      <div
        v-for="req in items"
        :key="req.id"
        class="rounded-lg border border-blue-100 dark:border-border bg-white dark:bg-card p-3"
      >
        <div class="mb-2 flex items-center justify-between">
          <h5 class="text-[13px] font-semibold capitalize text-slate-900 dark:text-foreground">
            Nghỉ {{ TYPE_LABEL[req.leave_type] || req.leave_type }} · {{ req.days_count }} ngày
          </h5>
          <span class="text-[11px] text-slate-400 dark:text-muted-foreground">NV: {{ shortId(req.user_id) }}</span>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Từ ngày</label>
            <div class="text-[13px] font-medium text-slate-700 dark:text-foreground/90">{{ req.start_date }}</div>
          </div>
          <div>
            <label class="text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Đến ngày</label>
            <div class="text-[13px] font-medium text-slate-700 dark:text-foreground/90">{{ req.end_date }}</div>
          </div>
          <div class="col-span-2">
            <label class="text-[10px] font-bold uppercase text-slate-400 dark:text-muted-foreground">Lý do</label>
            <div class="text-[13px] font-medium text-slate-700 dark:text-foreground/90">{{ req.reason || '—' }}</div>
          </div>
        </div>

        <!-- Gợi ý quyết định (nếu hr-service đã enrich) -->
        <div
          v-if="req.employee_leave_remaining != null || req.has_conflict"
          class="mt-2 flex flex-wrap items-center gap-2 text-[12px]"
        >
          <span
            v-if="req.employee_leave_remaining != null"
            class="rounded-md bg-slate-100 dark:bg-accent px-2 py-0.5 font-medium text-slate-600 dark:text-foreground/80"
          >
            Phép còn lại của NV: {{ req.employee_leave_remaining }}<span v-if="req.employee_leave_total != null">/{{ req.employee_leave_total }}</span> ngày
          </span>
          <span
            v-if="req.has_conflict"
            class="inline-flex items-center gap-1 rounded-md bg-amber-50 dark:bg-amber-500/10 px-2 py-0.5 font-semibold text-amber-700 dark:text-amber-400"
          >
            <AlertTriangle class="h-3 w-3" /> Trùng lịch nghỉ khác
          </span>
        </div>

        <div class="mt-3 flex justify-end gap-2">
          <button
            class="inline-flex items-center gap-1.5 rounded-lg border border-red-200 dark:border-red-500/30 px-3 py-1.5 text-[13px] font-semibold text-red-600 transition hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
            :disabled="actingId === req.id"
            @click="reject(req)"
          >
            <X class="h-3.5 w-3.5" /> Từ chối
          </button>
          <button
            class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-[13px] font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
            :disabled="actingId === req.id"
            @click="approve(req)"
          >
            <Loader2 v-if="actingId === req.id" class="h-3.5 w-3.5 animate-spin" />
            <Check v-else class="h-3.5 w-3.5" /> Duyệt
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
