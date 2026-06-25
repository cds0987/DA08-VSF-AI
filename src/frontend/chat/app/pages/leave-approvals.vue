<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Calendar, Check, Loader2, RefreshCw, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { useHRService } from '~/lib/api/hrService'

interface LeaveRequest {
  id: string
  user_id: string
  leave_type: string
  start_date: string
  end_date: string
  days_count: number
  status: string
  reason?: string | null
  // Danh tính nhân viên (backend _enrich_approval đính kèm) -> hiện tên/email thay user_id.
  employee_name?: string | null
  employee_email?: string | null
  employee_department?: string | null
  employee_job_title?: string | null
}

// Nhãn nhân viên: ưu tiên tên thật -> email -> user_id rút gọn (mirror ApprovalReviewCard).
function employeeLabel(req: LeaveRequest): string {
  if (req.employee_name) return req.employee_name
  if (req.employee_email) return req.employee_email
  return req.user_id.length > 10 ? `${req.user_id.slice(0, 6)}…${req.user_id.slice(-2)}` : req.user_id
}

// Dòng phụ: email (nếu đã hiện tên) + phòng ban/chức danh nếu có.
function employeeSubtitle(req: LeaveRequest): string {
  const parts: string[] = []
  if (req.employee_name && req.employee_email) parts.push(req.employee_email)
  if (req.employee_job_title) parts.push(req.employee_job_title)
  if (req.employee_department) parts.push(req.employee_department)
  return parts.join(' · ')
}

const hrService = useHRService()
const items = ref<LeaveRequest[]>([])
const isLoading = ref(false)
const actingId = ref<string | null>(null)

async function load() {
  isLoading.value = true
  try {
    items.value = (await hrService.fetchPendingApprovals()) as LeaveRequest[]
  } catch (e) {
    console.error(e)
    toast.error('Không tải được danh sách đơn chờ duyệt.')
  } finally {
    isLoading.value = false
  }
}

async function approve(req: LeaveRequest) {
  if (actingId.value) return
  actingId.value = req.id
  try {
    await hrService.approveLeaveRequest(req.id)
    toast.success(`Đã duyệt đơn ${req.leave_type} (${req.start_date} → ${req.end_date}).`)
    items.value = items.value.filter((r) => r.id !== req.id)
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Duyệt đơn thất bại.')
  } finally {
    actingId.value = null
  }
}

async function reject(req: LeaveRequest) {
  if (actingId.value) return
  const input = window.prompt('Lý do từ chối (tùy chọn):', '')
  if (input === null) return  // bấm Cancel -> KHÔNG từ chối (trước đây ?? '' vẫn reject — bug).
  const reason = input
  actingId.value = req.id
  try {
    await hrService.rejectLeaveRequest(req.id, reason)
    toast.success('Đã từ chối đơn.')
    items.value = items.value.filter((r) => r.id !== req.id)
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Từ chối đơn thất bại.')
  } finally {
    actingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="flex h-full w-full flex-col overflow-y-auto px-6 pb-6 pt-16">
    <div class="mx-auto w-full max-w-3xl">
      <div class="mb-6 flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-slate-900 dark:text-foreground">Đơn nghỉ phép chờ duyệt</h1>
          <p class="text-sm text-slate-500 dark:text-muted-foreground">
            Các đơn mà bạn là người duyệt. Duyệt sẽ tự trừ ngày phép của nhân viên.
          </p>
        </div>
        <button
          class="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-border px-3 py-2 text-[13px] font-medium text-slate-600 dark:text-foreground/80 hover:bg-slate-100 dark:hover:bg-accent disabled:opacity-50"
          :disabled="isLoading"
          @click="load"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="isLoading ? 'animate-spin' : ''" />
          Làm mới
        </button>
      </div>

      <div v-if="isLoading && items.length === 0" class="flex items-center justify-center py-16 text-slate-400">
        <Loader2 class="h-5 w-5 animate-spin" />
      </div>

      <div
        v-else-if="items.length === 0"
        class="rounded-xl border border-dashed border-slate-200 dark:border-border py-16 text-center text-sm text-slate-500 dark:text-muted-foreground"
      >
        Không có đơn nào chờ bạn duyệt.
      </div>

      <div v-else class="flex flex-col gap-3">
        <div
          v-for="req in items"
          :key="req.id"
          class="rounded-xl border border-blue-100 dark:border-blue-500/20 bg-blue-50/30 dark:bg-blue-500/5 p-4"
        >
          <div class="mb-3 flex items-center gap-2">
            <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600">
              <Calendar class="h-4 w-4" />
            </div>
            <div>
              <h4 class="text-[13px] font-semibold capitalize text-slate-900 dark:text-foreground">
                Nghỉ {{ req.leave_type }} · {{ req.days_count }} ngày
              </h4>
              <p class="text-[11px] uppercase font-bold tracking-wider text-slate-500 dark:text-muted-foreground">
                Nhân viên: {{ employeeLabel(req) }}
              </p>
              <p v-if="employeeSubtitle(req)" class="text-[11px] text-slate-400 dark:text-muted-foreground/80">
                {{ employeeSubtitle(req) }}
              </p>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4 rounded-lg border border-blue-100 dark:border-border bg-white dark:bg-card p-3">
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

          <div class="mt-4 flex justify-end gap-2">
            <button
              class="inline-flex items-center gap-1.5 rounded-lg border border-red-200 dark:border-red-500/30 px-3 py-2 text-[13px] font-semibold text-red-600 transition hover:bg-red-50 dark:hover:bg-red-500/10 disabled:opacity-50"
              :disabled="actingId === req.id"
              @click="reject(req)"
            >
              <X class="h-3.5 w-3.5" /> Từ chối
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
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
  </div>
</template>
