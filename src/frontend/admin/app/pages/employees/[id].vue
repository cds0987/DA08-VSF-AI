<script setup lang="ts">
import { ArrowLeft, Loader2, Save } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import hrService from '~/lib/api/hrService'
import type { EmployeeDetail, EmployeeItem } from '~/types'

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

// --- edit form ---
const form = reactive({
  employee_code: '',
  job_title: '',
  manager_user_id: '',
})
const isSaving = ref(false)

const syncForm = () => {
  if (!employee.value) return
  form.employee_code = employee.value.employee_code ?? ''
  form.job_title = employee.value.job_title ?? ''
  form.manager_user_id = employee.value.manager_user_id ?? ''
}

// --- manager select ---
const allEmployees = ref<EmployeeItem[]>([])

const loadManagers = async () => {
  try {
    const res = await hrService.listEmployees({ status: 'active', limit: 200, offset: 0 })
    allEmployees.value = res.items.filter(e => e.id !== employeeId)
  } catch {
    // non-critical, leave list empty
  }
}

onMounted(async () => {
  await loadEmployee()
  await loadManagers()
})

const saveEmployee = async () => {
  if (!employee.value) return
  isSaving.value = true
  try {
    const payload = {
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

const formatDateOnly = (d: string | null) => d
  ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  : '—'

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
          class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] font-medium hover:bg-accent cursor-pointer"
        >
          <ArrowLeft class="h-3.5 w-3.5" />
          Back
        </NuxtLink>
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
      <div v-else-if="employee" class="flex flex-col gap-6 max-w-2xl">

        <!-- read-only info -->
        <div class="rounded-lg border border-border bg-card p-5">
          <h2 class="mb-4 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">Profile Info</h2>
          <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px]">
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Full Name</dt>
              <dd class="mt-0.5 text-foreground">{{ employee.full_name || '—' }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Email</dt>
              <dd class="mt-0.5 text-foreground">{{ employee.company_email }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Phone Number</dt>
              <dd class="mt-0.5 text-foreground">{{ employee.phone_number || '—' }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Date of Birth</dt>
              <dd class="mt-0.5 text-foreground">{{ formatDateOnly(employee.date_of_birth) }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Department</dt>
              <dd class="mt-0.5 text-foreground">{{ employee.department || '—' }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Hire Date</dt>
              <dd class="mt-0.5 text-foreground">{{ formatDateOnly(employee.hire_date) }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Status</dt>
              <dd class="mt-0.5"><StatusBadge :status="employee.employment_status" /></dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">User ID</dt>
              <dd class="mt-0.5 font-mono text-[11px] text-muted-foreground">{{ employee.user_id }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Created</dt>
              <dd class="mt-0.5 text-muted-foreground">{{ formatDate(employee.created_at) }}</dd>
            </div>
            <div>
              <dt class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Updated</dt>
              <dd class="mt-0.5 text-muted-foreground">{{ formatDate(employee.updated_at) }}</dd>
            </div>
          </dl>
        </div>

        <!-- editable form -->
        <div class="rounded-lg border border-border bg-card p-5">
          <h2 class="mb-4 text-[13px] font-semibold uppercase tracking-wider text-muted-foreground">Edit HR Fields</h2>
          <form class="flex flex-col gap-4" @submit.prevent="saveEmployee">

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-code">Employee Code</label>
              <input
                id="emp-code"
                v-model="form.employee_code"
                type="text"
                placeholder="e.g. EMP-001"
                class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              >
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-title">Job Title</label>
              <input
                id="emp-title"
                v-model="form.job_title"
                type="text"
                placeholder="e.g. Backend Engineer"
                class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              >
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-manager">Manager</label>
              <select
                id="emp-manager"
                v-model="form.manager_user_id"
                class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
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
</template>
