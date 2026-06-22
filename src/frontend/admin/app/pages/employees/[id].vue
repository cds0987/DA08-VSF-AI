<script setup lang="ts">
import {
  ArrowLeft,
  Award,
  CalendarClock,
  CalendarDays,
  CalendarOff,
  ClipboardList,
  Clock3,
  Loader2,
  Mail,
  Save,
  UserRound,
  Wallet,
} from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import hrService from '~/lib/api/hrService'
import type { EmployeeDetail, EmployeeDetailsResponse, EmployeeItem } from '~/types'

const route = useRoute()
const employeeId = route.params.id as string

// --- detail ---
const employee = ref<EmployeeDetail | null>(null)
const isLoading = ref(true)
const notFound = ref(false)
const loadError = ref('')

const loadEmployee = async () => {
  isLoading.value = true
  notFound.value = false
  loadError.value = ''
  try {
    employee.value = await hrService.getEmployee(employeeId)
    syncForm()
  } catch (error) {
    const status = getApiStatus(error)
    if (status === 404) notFound.value = true
    else if (status === 403) loadError.value = 'Access denied: admin role required'
    else loadError.value = getApiErrorMessage(error, 'Failed to load employee')
  } finally {
    isLoading.value = false
  }
}

// --- HR details (read-only: leave, payroll, attendance, performance) ---
const details = ref<EmployeeDetailsResponse | null>(null)

const loadDetails = async () => {
  try {
    details.value = await hrService.getEmployeeDetails(employeeId)
  } catch (error) {
    // Không chặn trang nếu phần HR phụ lỗi; profile/edit vẫn dùng được.
    console.error('Failed to load HR details:', error)
  }
}

const formatCurrency = (n: number) =>
  new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND', maximumFractionDigits: 0 }).format(n)

const leaveTypeLabel = (t: string) =>
  ({ annual: 'Annual', sick: 'Sick', unpaid: 'Unpaid' } as Record<string, string>)[t] ?? t

// --- edit form ---
const form = reactive({
  full_name: '',
  phone_number: '',
  date_of_birth: '',
  hire_date: '',
  department: '',
  employee_code: '',
  job_title: '',
  manager_user_id: '',
})
const isSaving = ref(false)

const syncForm = () => {
  if (!employee.value) return
  form.full_name = employee.value.full_name ?? ''
  form.phone_number = employee.value.phone_number ?? ''
  form.date_of_birth = employee.value.date_of_birth ?? ''
  form.hire_date = employee.value.hire_date ?? ''
  form.department = employee.value.department ?? ''
  form.employee_code = employee.value.employee_code ?? ''
  form.job_title = employee.value.job_title ?? ''
  form.manager_user_id = employee.value.manager_user_id ?? ''
}

// --- department select ---
const allDepartments = ref<string[]>([])

// --- manager select ---
const allEmployees = ref<EmployeeItem[]>([])

const loadManagers = async () => {
  try {
    const res = await hrService.listEmployees({ limit: 100, offset: 0, status: 'active' })
    allEmployees.value = res.items.filter(e => e.id !== employeeId)
  } catch (error) {
    console.error('Failed to load manager options:', error)
  }
}

onMounted(async () => {
  await loadEmployee()
  await Promise.all([
    loadDetails(),
    loadManagers(),
    hrService.listDepartments().then(d => { allDepartments.value = d }).catch(() => {}),
  ])
})

const saveErrors = reactive({ full_name: '', department: '' })

const saveEmployee = async () => {
  if (!employee.value) return
  saveErrors.full_name = !form.full_name.trim() ? 'Full name is required' : ''
  saveErrors.department = !form.department ? 'Department is required' : ''
  if (saveErrors.full_name || saveErrors.department) return
  isSaving.value = true
  try {
    const payload = {
      full_name: form.full_name.trim() || null,
      phone_number: form.phone_number.trim() || null,
      date_of_birth: form.date_of_birth || null,
      hire_date: form.hire_date || null,
      department: form.department.trim() || null,
      employee_code: form.employee_code.trim() || null,
      job_title: form.job_title.trim() || null,
      manager_user_id: form.manager_user_id || null,
    }
    employee.value = await hrService.updateEmployee(employeeId, payload)
    syncForm()
    toast.success('Employee profile updated')
  } catch (error) {
    const status = getApiStatus(error)
    if (status === 409) toast.error('Employee code already in use by another employee')
    else if (status === 422) toast.error(getApiErrorMessage(error, 'Validation error'))
    else if (status === 403) toast.error('Access denied: admin role required')
    else toast.error(getApiErrorMessage(error, 'Failed to update employee'))
  } finally {
    isSaving.value = false
  }
}

const formatDate = (d: string) => new Date(d).toLocaleString('en-GB', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
})

const managerLabel = (emp: EmployeeItem) =>
  `${emp.full_name || emp.company_email}${emp.job_title ? ` · ${emp.job_title}` : ''}`
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader
      title="Employee Detail"
      description="View and update HR profile fields."
    >
      <template #actions>
        <NuxtLink
          to="/employees"
          class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] font-medium transition-colors hover:bg-accent cursor-pointer"
        >
          <ArrowLeft class="h-3.5 w-3.5" />
          Back
        </NuxtLink>
      </template>

      <template v-if="employee" #meta>
        <span class="font-medium text-foreground">{{ employee.full_name || employee.company_email }}</span>
        <span v-if="employee.job_title" class="text-muted-foreground">· {{ employee.job_title }}</span>
        <span
          v-if="employee.employee_code"
          class="inline-flex items-center rounded-md border border-border bg-accent/60 px-1.5 py-0.5 font-mono text-[11px] text-foreground"
        >{{ employee.employee_code }}</span>
        <span
          v-if="employee.department"
          class="inline-flex items-center rounded-md border border-border bg-accent/60 px-1.5 py-0.5 text-[11px] text-foreground"
        >{{ employee.department }}</span>
        <StatusBadge :status="employee.employment_status" />
      </template>
    </PageHeader>

    <div class="px-8 pb-8 pt-2">
      <!-- loading -->
      <div v-if="isLoading" class="flex items-center justify-center py-20">
        <Loader2 class="h-8 w-8 animate-spin text-primary" />
      </div>

      <!-- not found -->
      <div v-else-if="notFound" class="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground">
        Employee not found.
      </div>

      <!-- error -->
      <div v-else-if="loadError" class="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-[13px] text-destructive">
        {{ loadError }}
      </div>

      <!-- content -->
      <div v-else-if="employee" class="mx-auto max-w-6xl">
        <div class="grid grid-cols-1 gap-6 lg:grid-cols-12">

          <!-- main column -->
          <div class="flex flex-col gap-6 lg:col-span-7">

            <!-- read-only info -->
            <div class="rounded-xl border border-border bg-card p-5 shadow-sm">
              <div class="mb-4 flex items-center gap-3">
                <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[14px] font-semibold uppercase text-primary">
                  {{ (employee.full_name || employee.company_email).slice(0, 2) }}
                </div>
                <div class="min-w-0">
                  <p class="truncate text-[15px] font-semibold leading-tight text-foreground">
                    {{ employee.full_name || employee.company_email }}
                  </p>
                  <p class="truncate text-[12px] text-muted-foreground">
                    {{ employee.job_title || 'No job title' }}
                  </p>
                </div>
                <StatusBadge :status="employee.employment_status" class="ml-auto" />
              </div>

              <dl class="grid grid-cols-1 gap-x-6 gap-y-3 border-t border-border pt-4 text-[13px] sm:grid-cols-2">
                <div class="flex items-start gap-2">
                  <Mail class="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div class="min-w-0">
                    <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Email</dt>
                    <dd class="mt-0.5 truncate text-foreground">{{ employee.company_email }}</dd>
                  </div>
                </div>
                <div class="flex items-start gap-2">
                  <UserRound class="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div class="min-w-0">
                    <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">User ID</dt>
                    <dd class="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{{ employee.user_id }}</dd>
                  </div>
                </div>
                <div class="flex items-start gap-2">
                  <CalendarDays class="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div class="min-w-0">
                    <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Created</dt>
                    <dd class="mt-0.5 text-muted-foreground">{{ formatDate(employee.created_at) }}</dd>
                  </div>
                </div>
                <div class="flex items-start gap-2">
                  <Clock3 class="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div class="min-w-0">
                    <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Updated</dt>
                    <dd class="mt-0.5 text-muted-foreground">{{ formatDate(employee.updated_at) }}</dd>
                  </div>
                </div>
              </dl>
            </div>

            <!-- HR overview: leave, payroll, attendance, performance -->
            <div v-if="details" class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <!-- Leave balance -->
              <div class="rounded-xl border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md">
                <h2 class="mb-4 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <CalendarOff class="h-4 w-4" /> Leave Balance
                </h2>
                <div v-if="details.leave_balance" class="grid grid-cols-2 gap-4 text-[13px]">
                  <div>
                    <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Annual leave</dt>
                    <dd class="mt-0.5 text-foreground">
                      <span class="text-xl font-semibold tabular-nums">{{ details.leave_balance.annual_remaining }}</span>
                      <span class="text-muted-foreground"> / {{ details.leave_balance.annual_total }} days</span>
                    </dd>
                    <dd class="text-[11px] text-muted-foreground">Used {{ details.leave_balance.annual_used }}</dd>
                  </div>
                  <div>
                    <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Sick leave</dt>
                    <dd class="mt-0.5 text-foreground">
                      <span class="text-xl font-semibold tabular-nums">{{ details.leave_balance.sick_remaining }}</span>
                      <span class="text-muted-foreground"> / {{ details.leave_balance.sick_total }} days</span>
                    </dd>
                    <dd class="text-[11px] text-muted-foreground">Used {{ details.leave_balance.sick_used }}</dd>
                  </div>
                </div>
                <div v-else class="flex flex-col items-center justify-center gap-1.5 py-4 text-center">
                  <CalendarOff class="h-5 w-5 text-muted-foreground/40" />
                  <p class="text-[12px] text-muted-foreground">No leave balance data.</p>
                </div>
              </div>

              <!-- Payroll (latest period) -->
              <div class="rounded-xl border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md">
                <h2 class="mb-4 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <Wallet class="h-4 w-4" /> Payroll
                </h2>
                <div v-if="details.payroll" class="text-[13px]">
                  <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Net salary · {{ details.payroll.period }}</dt>
                  <dd class="mt-0.5 text-xl font-semibold tabular-nums text-foreground">{{ formatCurrency(details.payroll.net_salary) }}</dd>
                  <dd class="mt-1 text-[11px] text-muted-foreground">
                    Gross {{ formatCurrency(details.payroll.gross_salary) }} · Deductions {{ formatCurrency(details.payroll.deductions) }}
                  </dd>
                </div>
                <div v-else class="flex flex-col items-center justify-center gap-1.5 py-4 text-center">
                  <Wallet class="h-5 w-5 text-muted-foreground/40" />
                  <p class="text-[12px] text-muted-foreground">No payroll data.</p>
                </div>
              </div>

              <!-- Attendance (latest period) -->
              <div class="rounded-xl border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md">
                <h2 class="mb-4 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <CalendarClock class="h-4 w-4" /> Attendance
                </h2>
                <div v-if="details.attendance" class="text-[13px]">
                  <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Period {{ details.attendance.period }}</dt>
                  <dd class="mt-2 grid grid-cols-3 gap-2 text-center">
                    <div class="rounded-md border border-border bg-background px-2 py-1.5">
                      <span class="block text-lg font-semibold tabular-nums text-foreground">{{ details.attendance.work_days }}</span>
                      <span class="text-[10px] uppercase tracking-wider text-muted-foreground">Work days</span>
                    </div>
                    <div class="rounded-md border border-border bg-background px-2 py-1.5">
                      <span class="block text-lg font-semibold tabular-nums text-foreground">{{ details.attendance.late_count }}</span>
                      <span class="text-[10px] uppercase tracking-wider text-muted-foreground">Late</span>
                    </div>
                    <div class="rounded-md border border-border bg-background px-2 py-1.5">
                      <span class="block text-lg font-semibold tabular-nums text-foreground">{{ details.attendance.absent_count }}</span>
                      <span class="text-[10px] uppercase tracking-wider text-muted-foreground">Absent</span>
                    </div>
                  </dd>
                </div>
                <div v-else class="flex flex-col items-center justify-center gap-1.5 py-4 text-center">
                  <CalendarClock class="h-5 w-5 text-muted-foreground/40" />
                  <p class="text-[12px] text-muted-foreground">No attendance data.</p>
                </div>
              </div>

              <!-- Performance (latest) -->
              <div class="rounded-xl border border-border bg-card p-5 shadow-sm transition-shadow hover:shadow-md">
                <h2 class="mb-4 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <Award class="h-4 w-4" /> Performance
                </h2>
                <div v-if="details.performance" class="text-[13px]">
                  <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Period {{ details.performance.period }}</dt>
                  <dd class="mt-1">
                    <span class="inline-flex items-center rounded-md border border-border bg-accent px-2 py-0.5 text-[12px] font-medium text-foreground">
                      {{ details.performance.rating }}
                    </span>
                  </dd>
                </div>
                <div v-else class="flex flex-col items-center justify-center gap-1.5 py-4 text-center">
                  <Award class="h-5 w-5 text-muted-foreground/40" />
                  <p class="text-[12px] text-muted-foreground">No performance review.</p>
                </div>
              </div>
            </div>

            <!-- Recent leave requests -->
            <div v-if="details && details.leave_requests.length" class="rounded-xl border border-border bg-card p-5 shadow-sm">
              <h2 class="mb-4 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                <ClipboardList class="h-4 w-4" /> Recent Leave Requests
              </h2>
              <ul class="flex flex-col divide-y divide-border text-[13px]">
                <li v-for="(req, i) in details.leave_requests" :key="i" class="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                  <div class="min-w-0">
                    <span class="font-medium text-foreground">{{ leaveTypeLabel(req.leave_type) }}</span>
                    <span class="text-muted-foreground"> · {{ req.start_date }} → {{ req.end_date }} ({{ req.days_count }}d)</span>
                  </div>
                  <StatusBadge :status="req.status" />
                </li>
              </ul>
            </div>
          </div>

          <!-- editable form (aside) -->
          <div class="lg:col-span-5">
            <div class="rounded-xl border border-border bg-card p-5 shadow-sm lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto">
              <h2 class="mb-4 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">
                <Save class="h-4 w-4" /> Edit HR Fields
              </h2>
              <form class="flex flex-col gap-4" @submit.prevent="saveEmployee">

            <div class="flex gap-3">
              <div class="flex-1">
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-full-name">Full Name <span class="text-destructive">*</span></label>
                <input
                  id="emp-full-name"
                  v-model="form.full_name"
                  type="text"
                  placeholder="e.g. Nguyễn Văn A"
                  class="w-full rounded-md border bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                  :class="saveErrors.full_name ? 'border-destructive' : 'border-input'"
                >
                <p v-if="saveErrors.full_name" class="mt-1 text-[11px] text-destructive">{{ saveErrors.full_name }}</p>
              </div>
              <div class="flex-1">
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-phone">Phone Number</label>
                <input
                  id="emp-phone"
                  v-model="form.phone_number"
                  type="tel"
                  placeholder="e.g. 0901234567"
                  class="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                >
              </div>
            </div>

            <div class="flex gap-3">
              <div class="flex-1">
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-dob">Date of Birth</label>
                <input
                  id="emp-dob"
                  v-model="form.date_of_birth"
                  type="date"
                  class="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                >
              </div>
              <div class="flex-1">
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-hire">Hire Date</label>
                <input
                  id="emp-hire"
                  v-model="form.hire_date"
                  type="date"
                  class="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                >
              </div>
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-department">Department <span class="text-destructive">*</span></label>
              <select
                id="emp-department"
                v-model="form.department"
                class="w-full rounded-md border bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                :class="saveErrors.department ? 'border-destructive' : 'border-input'"
              >
                <option value="">— No department —</option>
                <option v-for="d in allDepartments" :key="d" :value="d">{{ d }}</option>
                <option v-if="form.department && !allDepartments.includes(form.department)" :value="form.department">{{ form.department }}</option>
              </select>
              <p v-if="saveErrors.department" class="mt-1 text-[11px] text-destructive">{{ saveErrors.department }}</p>
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-code">Employee Code</label>
              <input
                id="emp-code"
                v-model="form.employee_code"
                type="text"
                placeholder="e.g. EMP-001"
                class="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              >
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-title">Job Title</label>
              <input
                id="emp-title"
                v-model="form.job_title"
                type="text"
                placeholder="e.g. Backend Engineer"
                class="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              >
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-manager">Manager</label>
              <select
                id="emp-manager"
                v-model="form.manager_user_id"
                class="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              >
                <option value="">No manager</option>
                <option
                  v-for="mgr in allEmployees"
                  :key="mgr.user_id"
                  :value="mgr.user_id"
                >
                  {{ managerLabel(mgr) }}
                </option>
              </select>
            </div>

            <div class="flex justify-end">
              <button
                type="submit"
                class="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60 cursor-pointer"
                :disabled="isSaving"
              >
                <Loader2 v-if="isSaving" class="h-3.5 w-3.5 animate-spin" />
                <Save v-else class="h-3.5 w-3.5" />
                Save changes
              </button>
            </div>
              </form>
            </div>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>
