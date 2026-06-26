<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { CalendarCheck, Check, Loader2, RefreshCw, X } from '@lucide/vue'
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

// Chữ cái viết tắt cho avatar nhân viên: 2 ký tự đầu của tối đa 2 từ trong tên/email.
function initials(req: LeaveRequest): string {
  const source = req.employee_name || req.employee_email || req.user_id
  const words = source.trim().split(/[\s@._-]+/).filter(Boolean)
  if (words.length === 0) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[words.length - 1][0]).toUpperCase()
}

// ISO yyyy-mm-dd -> dd/mm/yyyy (định dạng VN), fallback giữ nguyên nếu lạ.
function fmtDate(d: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : d
}

const isSingleDay = (req: LeaveRequest) => req.start_date === req.end_date

const hrService = useHRService()
const items = ref<LeaveRequest[]>([])
const isLoading = ref(false)
const actingId = ref<string | null>(null)
const actingType = ref<'approve' | 'reject' | null>(null)

// Modal từ chối (thay window.prompt thô): giữ đơn đang xử lý + lý do nhập vào.
const rejectTarget = ref<LeaveRequest | null>(null)
const rejectReason = ref('')
const rejectInput = ref<HTMLTextAreaElement | null>(null)

// Mở modal -> focus textarea cho thao tác bàn phím.
watch(rejectTarget, async (req) => {
  if (req) {
    await nextTick()
    rejectInput.value?.focus()
  }
})

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
  actingType.value = 'approve'
  try {
    await hrService.approveLeaveRequest(req.id)
    toast.success(`Đã duyệt đơn ${req.leave_type} (${req.start_date} → ${req.end_date}).`)
    items.value = items.value.filter((r) => r.id !== req.id)
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Duyệt đơn thất bại.')
  } finally {
    actingId.value = null
    actingType.value = null
  }
}

function openReject(req: LeaveRequest) {
  if (actingId.value) return
  rejectReason.value = ''
  rejectTarget.value = req
}

function closeReject() {
  if (actingId.value) return  // đang gọi API -> không cho đóng giữa chừng.
  rejectTarget.value = null
}

async function confirmReject() {
  const req = rejectTarget.value
  if (!req || actingId.value) return
  const reason = rejectReason.value.trim()
  actingId.value = req.id
  actingType.value = 'reject'
  try {
    await hrService.rejectLeaveRequest(req.id, reason)
    toast.success('Đã từ chối đơn.')
    items.value = items.value.filter((r) => r.id !== req.id)
    rejectTarget.value = null
  } catch (e: any) {
    console.error(e)
    toast.error(e?.data?.detail || 'Từ chối đơn thất bại.')
  } finally {
    actingId.value = null
    actingType.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="flex h-full w-full flex-col overflow-y-auto px-6 pb-6 pt-16">
    <div class="mx-auto w-full max-w-2xl">
      <div class="mb-6 flex items-start justify-between gap-4">
        <div class="space-y-1">
          <div class="flex items-center gap-2.5">
            <h1 class="text-xl font-semibold text-slate-900 dark:text-foreground">Đơn nghỉ phép chờ duyệt</h1>
            <span
              v-if="items.length"
              class="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-primary/10 px-1.5 text-xs font-semibold text-primary"
            >
              {{ items.length }}
            </span>
          </div>
          <p class="text-sm text-slate-500 dark:text-muted-foreground">
            Các đơn mà bạn là người duyệt. Duyệt sẽ tự trừ ngày phép của nhân viên.
          </p>
        </div>
        <button
          class="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-200 dark:border-border px-3 py-2 text-[13px] font-medium text-slate-600 transition hover:bg-slate-100 active:scale-[0.98] dark:text-foreground/80 dark:hover:bg-accent disabled:opacity-50"
          :disabled="isLoading"
          @click="load"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="isLoading ? 'animate-spin' : ''" />
          Làm mới
        </button>
      </div>

      <!-- Loading: skeleton khớp dáng card thật, dễ chịu hơn spinner trống -->
      <div v-if="isLoading && items.length === 0" class="flex flex-col gap-3">
        <div
          v-for="n in 3"
          :key="n"
          class="animate-pulse rounded-xl border border-slate-200 dark:border-border bg-white dark:bg-card p-4"
        >
          <div class="flex items-center gap-3">
            <div class="h-9 w-9 rounded-full bg-slate-200 dark:bg-muted" />
            <div class="flex-1 space-y-2">
              <div class="h-3.5 w-40 rounded bg-slate-200 dark:bg-muted" />
              <div class="h-2.5 w-56 rounded bg-slate-100 dark:bg-muted/60" />
            </div>
          </div>
          <div class="mt-3 h-16 rounded-lg bg-slate-100 dark:bg-muted/40" />
        </div>
      </div>

      <!-- Empty: icon + tiêu đề + hướng dẫn, thay vì chỉ một dòng chữ -->
      <div
        v-else-if="items.length === 0"
        class="flex flex-col items-center rounded-2xl border border-dashed border-slate-200 dark:border-border px-6 py-16 text-center"
      >
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500 dark:bg-muted dark:text-muted-foreground">
          <CalendarCheck class="h-6 w-6" />
        </div>
        <h3 class="mt-4 text-sm font-semibold text-slate-900 dark:text-foreground">Không có đơn nào chờ duyệt</h3>
        <p class="mt-1 max-w-xs text-sm text-slate-500 dark:text-muted-foreground">
          Khi nhân viên gửi đơn nghỉ phép mà bạn là người duyệt, đơn sẽ xuất hiện ở đây.
        </p>
      </div>

      <div v-else class="flex flex-col gap-3">
        <div
          v-for="req in items"
          :key="req.id"
          class="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-slate-300 dark:border-border dark:bg-card dark:hover:border-border/70"
        >
          <div class="flex items-start gap-3">
            <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              {{ initials(req) }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <h4 class="truncate text-sm font-semibold text-slate-900 dark:text-foreground">
                  {{ employeeLabel(req) }}
                </h4>
                <span class="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium capitalize text-primary">
                  Nghỉ {{ req.leave_type }}
                </span>
              </div>
              <p v-if="employeeSubtitle(req)" class="truncate text-xs text-slate-500 dark:text-muted-foreground">
                {{ employeeSubtitle(req) }}
              </p>
            </div>
            <span class="shrink-0 text-sm font-semibold text-slate-700 dark:text-foreground/90">
              {{ req.days_count }} ngày
            </span>
          </div>

          <dl class="mt-3 space-y-2 rounded-lg bg-slate-50 p-3 dark:bg-muted/40">
            <div class="flex gap-3">
              <dt class="w-16 shrink-0 text-xs font-medium text-slate-500 dark:text-muted-foreground">
                {{ isSingleDay(req) ? 'Ngày nghỉ' : 'Thời gian' }}
              </dt>
              <dd class="text-sm font-medium text-slate-700 dark:text-foreground/90">
                <template v-if="isSingleDay(req)">{{ fmtDate(req.start_date) }}</template>
                <template v-else>{{ fmtDate(req.start_date) }} → {{ fmtDate(req.end_date) }}</template>
              </dd>
            </div>
            <div v-if="req.reason" class="flex gap-3">
              <dt class="w-16 shrink-0 text-xs font-medium text-slate-500 dark:text-muted-foreground">Lý do</dt>
              <dd class="text-sm font-medium text-slate-700 dark:text-foreground/90">{{ req.reason }}</dd>
            </div>
          </dl>

          <div class="mt-4 flex justify-end gap-2">
            <button
              class="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-[13px] font-semibold text-red-600 transition hover:bg-red-50 active:scale-[0.98] disabled:opacity-50 dark:border-red-500/30 dark:text-red-400 dark:hover:bg-red-500/10"
              :disabled="actingId === req.id"
              @click="openReject(req)"
            >
              <Loader2 v-if="actingId === req.id && actingType === 'reject'" class="h-3.5 w-3.5 animate-spin" />
              <X v-else class="h-3.5 w-3.5" /> Từ chối
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-blue-700 active:scale-[0.98] disabled:opacity-50"
              :disabled="actingId === req.id"
              @click="approve(req)"
            >
              <Loader2 v-if="actingId === req.id && actingType === 'approve'" class="h-3.5 w-3.5 animate-spin" />
              <Check v-else class="h-3.5 w-3.5" /> Duyệt
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal từ chối: thay window.prompt. Esc/click nền/Hủy để đóng, Ctrl/Cmd+Enter để xác nhận. -->
    <Teleport to="body">
      <div
        v-if="rejectTarget"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        @keydown.esc="closeReject"
      >
        <div class="absolute inset-0 bg-black/60" @click="closeReject" />
        <div
          class="relative w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-border dark:bg-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="reject-title"
        >
          <h3 id="reject-title" class="text-base font-semibold text-slate-900 dark:text-foreground">
            Từ chối đơn nghỉ phép
          </h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-muted-foreground">
            Đơn của
            <span class="font-medium text-slate-700 dark:text-foreground/90">{{ employeeLabel(rejectTarget) }}</span>
            sẽ bị từ chối. Bạn có thể ghi lý do (tùy chọn).
          </p>
          <textarea
            ref="rejectInput"
            v-model="rejectReason"
            rows="3"
            placeholder="Lý do từ chối…"
            class="mt-3 w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 placeholder:text-slate-400 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-border dark:bg-background dark:text-foreground dark:placeholder:text-muted-foreground"
            @keydown.meta.enter="confirmReject"
            @keydown.ctrl.enter="confirmReject"
          />
          <div class="mt-4 flex justify-end gap-2">
            <button
              class="inline-flex items-center rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-medium text-slate-600 transition hover:bg-slate-100 active:scale-[0.98] disabled:opacity-50 dark:border-border dark:text-foreground/80 dark:hover:bg-accent"
              :disabled="actingId === rejectTarget.id"
              @click="closeReject"
            >
              Hủy
            </button>
            <button
              class="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-red-700 active:scale-[0.98] disabled:opacity-50"
              :disabled="actingId === rejectTarget.id"
              @click="confirmReject"
            >
              <Loader2 v-if="actingId === rejectTarget.id" class="h-3.5 w-3.5 animate-spin" />
              <X v-else class="h-3.5 w-3.5" /> Từ chối
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
