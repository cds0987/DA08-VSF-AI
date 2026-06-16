<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { AlertTriangle, ArrowRight, CalendarDays, Check, Loader2, RefreshCw, User, X } from '@lucide/vue'
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
  employee_leave_remaining?: number | null
  employee_leave_total?: number | null
  has_conflict?: boolean
  employee_name?: string | null
  employee_email?: string | null
  employee_department?: string | null
  employee_job_title?: string | null
}

const hrService = useHRService()
const items = ref<LeaveApproval[]>([])
const isLoading = ref(false)
const actingId = ref<string | null>(null)
const loaded = ref(false)
// id đơn đang ở chế độ nhập lý do từ chối -> lý do tạm.
const rejecting = reactive<Record<string, string>>({})

const TYPE_META: Record<string, { label: string; cls: string }> = {
  annual: { label: 'Phép năm', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300' },
  sick: { label: 'Nghỉ ốm', cls: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300' },
  personal: { label: 'Cá nhân', cls: 'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300' },
}
function typeMeta(t: string) {
  return TYPE_META[t] || { label: t, cls: 'bg-slate-100 text-slate-600 dark:bg-accent dark:text-foreground/80' }
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
    toast.success(`Đã duyệt đơn ${typeMeta(req.leave_type).label} (${req.start_date} → ${req.end_date}).`)
    items.value = items.value.filter(r => r.id !== req.id)
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Duyệt đơn thất bại.')
  } finally {
    actingId.value = null
  }
}

function startReject(req: LeaveApproval) {
  if (actingId.value) return
  rejecting[req.id] = ''
}
function cancelReject(req: LeaveApproval) {
  delete rejecting[req.id]
}
async function confirmReject(req: LeaveApproval) {
  if (actingId.value) return
  const reason = (rejecting[req.id] || '').trim()
  actingId.value = req.id
  try {
    await hrService.rejectLeaveRequest(req.id, reason)
    toast.success('Đã từ chối đơn.')
    items.value = items.value.filter(r => r.id !== req.id)
    delete rejecting[req.id]
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Từ chối đơn thất bại.')
  } finally {
    actingId.value = null
  }
}

// Nhãn nhân viên: ưu tiên tên thật -> email -> user_id rút gọn.
function employeeLabel(req: LeaveApproval): string {
  if (req.employee_name) return req.employee_name
  if (req.employee_email) return req.employee_email
  return req.user_id.length > 10 ? `${req.user_id.slice(0, 6)}…${req.user_id.slice(-2)}` : req.user_id
}
function employeeSub(req: LeaveApproval): string {
  const parts = [req.employee_job_title, req.employee_department].filter(Boolean) as string[]
  // Nếu nhãn chính là tên thật thì phụ hiện thêm email; ngược lại hiện chức danh/phòng ban.
  if (req.employee_name && req.employee_email) parts.unshift(req.employee_email)
  return parts.join(' · ')
}
function initials(req: LeaveApproval): string {
  const base = req.employee_name || req.employee_email || req.user_id || '?'
  const words = base.replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean)
  const ini = words.length >= 2 ? words[0][0] + words[1][0] : base.slice(0, 2)
  return (ini || '?').toUpperCase()
}
</script>

<template>
  <div class="mt-4 rounded-2xl border border-slate-200/80 dark:border-border bg-white/70 dark:bg-card/60 p-4 shadow-sm backdrop-blur">
    <div class="mb-4 flex items-center justify-between">
      <div class="flex items-center gap-2.5">
        <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-500 text-white shadow-sm">
          <CalendarDays class="h-[18px] w-[18px]" />
        </div>
        <div>
          <h4 class="text-[13.5px] font-semibold text-slate-900 dark:text-foreground">Đơn chờ bạn duyệt</h4>
          <p class="text-[11px] text-slate-400 dark:text-muted-foreground">
            Duyệt sẽ tự trừ ngày phép của nhân viên
          </p>
        </div>
      </div>
      <button
        class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-border px-2.5 py-1.5 text-[12px] font-medium text-slate-500 dark:text-foreground/70 transition hover:bg-slate-50 dark:hover:bg-accent disabled:opacity-50"
        :disabled="isLoading"
        @click="load"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="isLoading ? 'animate-spin' : ''" /> Làm mới
      </button>
    </div>

    <div v-if="isLoading && items.length === 0" class="flex items-center justify-center py-10 text-slate-300">
      <Loader2 class="h-6 w-6 animate-spin" />
    </div>

    <div
      v-else-if="loaded && items.length === 0"
      class="rounded-xl border border-dashed border-slate-200 dark:border-border py-10 text-center text-[13px] text-slate-400 dark:text-muted-foreground"
    >
      🎉 Hiện không có đơn nào chờ bạn duyệt.
    </div>

    <div v-else class="flex flex-col gap-3">
      <div
        v-for="req in items"
        :key="req.id"
        class="group rounded-xl border border-slate-200/80 dark:border-border bg-white dark:bg-card p-3.5 transition hover:border-blue-300/70 hover:shadow-md"
      >
        <!-- Header: nhân viên + loại nghỉ -->
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2.5">
            <div class="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-slate-200 to-slate-300 dark:from-accent dark:to-accent/60 text-[12px] font-bold text-slate-600 dark:text-foreground/80">
              {{ initials(req) }}
            </div>
            <div class="leading-tight">
              <div class="flex items-center gap-1 text-[13px] font-semibold text-slate-800 dark:text-foreground">
                <User class="h-3.5 w-3.5 text-slate-400" /> {{ employeeLabel(req) }}
              </div>
              <div v-if="employeeSub(req)" class="text-[11px] text-slate-400 dark:text-muted-foreground">{{ employeeSub(req) }}</div>
              <div class="text-[11.5px] font-medium text-slate-500 dark:text-foreground/70">{{ req.days_count }} ngày nghỉ</div>
            </div>
          </div>
          <span class="rounded-full px-2.5 py-1 text-[11px] font-semibold" :class="typeMeta(req.leave_type).cls">
            {{ typeMeta(req.leave_type).label }}
          </span>
        </div>

        <!-- Khoảng ngày -->
        <div class="mt-3 flex items-center gap-2 rounded-lg bg-slate-50 dark:bg-accent/40 px-3 py-2 text-[13px] font-medium text-slate-700 dark:text-foreground/90">
          <span>{{ req.start_date }}</span>
          <ArrowRight class="h-3.5 w-3.5 text-slate-400" />
          <span>{{ req.end_date }}</span>
        </div>

        <!-- Lý do -->
        <div v-if="req.reason" class="mt-2 text-[12.5px] text-slate-500 dark:text-muted-foreground">
          <span class="text-slate-400">Lý do:</span> {{ req.reason }}
        </div>

        <!-- Gợi ý quyết định -->
        <div
          v-if="req.employee_leave_remaining != null || req.has_conflict"
          class="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11.5px]"
        >
          <span
            v-if="req.employee_leave_remaining != null"
            class="inline-flex items-center gap-1 rounded-md bg-emerald-50 dark:bg-emerald-500/10 px-2 py-0.5 font-medium text-emerald-700 dark:text-emerald-400"
          >
            Phép còn {{ req.employee_leave_remaining }}<span v-if="req.employee_leave_total != null">/{{ req.employee_leave_total }}</span> ngày
          </span>
          <span
            v-if="req.has_conflict"
            class="inline-flex items-center gap-1 rounded-md bg-amber-50 dark:bg-amber-500/10 px-2 py-0.5 font-semibold text-amber-700 dark:text-amber-400"
          >
            <AlertTriangle class="h-3 w-3" /> Trùng lịch nghỉ khác
          </span>
        </div>

        <!-- Ô nhập lý do từ chối (inline, thay window.prompt) -->
        <div v-if="rejecting[req.id] !== undefined" class="mt-3 rounded-lg border border-red-200 dark:border-red-500/30 bg-red-50/50 dark:bg-red-500/5 p-2.5">
          <label class="mb-1 block text-[11px] font-semibold text-red-600 dark:text-red-400">Lý do từ chối (tùy chọn)</label>
          <input
            v-model="rejecting[req.id]"
            type="text"
            placeholder="Nhập lý do rồi xác nhận…"
            class="w-full rounded-md border border-red-200 dark:border-red-500/30 bg-white dark:bg-card px-2.5 py-1.5 text-[13px] text-slate-700 dark:text-foreground/90 outline-none focus:ring-2 focus:ring-red-400/40"
            @keydown.enter="confirmReject(req)"
          >
          <div class="mt-2 flex justify-end gap-2">
            <button
              class="rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-slate-500 dark:text-foreground/70 hover:bg-slate-100 dark:hover:bg-accent"
              :disabled="actingId === req.id"
              @click="cancelReject(req)"
            >
              Hủy
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-[12.5px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              :disabled="actingId === req.id"
              @click="confirmReject(req)"
            >
              <Loader2 v-if="actingId === req.id" class="h-3.5 w-3.5 animate-spin" />
              <X v-else class="h-3.5 w-3.5" /> Xác nhận từ chối
            </button>
          </div>
        </div>

        <!-- Nút hành động -->
        <div v-else class="mt-3 flex justify-end gap-2">
          <button
            class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-border px-3 py-1.5 text-[13px] font-semibold text-slate-600 dark:text-foreground/80 transition hover:border-red-300 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10 disabled:opacity-50"
            :disabled="!!actingId"
            @click="startReject(req)"
          >
            <X class="h-3.5 w-3.5" /> Từ chối
          </button>
          <button
            class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
            :disabled="!!actingId"
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
