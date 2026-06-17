<script setup lang="ts">
import {
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Eye,
  Loader2,
  Power,
  PowerOff,
  UserPlus,
  X,
} from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import { getApiErrorMessage, getApiStatus } from '~/lib/api/apiError'
import hrService from '~/lib/api/hrService'
import userService from '~/lib/api/userService'
import type { AccountType, EmployeeItem, EmploymentStatus, Role, UpdateEmployeeRequest, User } from '~/types'

const router = useRouter()

// --- list state ---
const employees = ref<EmployeeItem[]>([])
const total = ref(0)
const isLoading = ref(true)
const departmentFilter = ref('')
const statusFilter = ref<EmploymentStatus | ''>('')
const limit = ref(20)
const offset = ref(0)

// user_id → account info (role, is_active) from User Service, joined onto each employee row
const usersById = ref<Record<string, User>>({})
const togglingUserId = ref<string | null>(null)

const fetchEmployees = async () => {
  isLoading.value = true
  try {
    const [res, usersRes] = await Promise.all([
      hrService.listEmployees({
        department: departmentFilter.value || undefined,
        status: (statusFilter.value as EmploymentStatus) || undefined,
        limit: limit.value,
        offset: offset.value,
      }),
      userService.listUsers().catch(() => ({ items: [] as User[], total: 0 })),
    ])
    employees.value = res.items
    total.value = res.total
    usersById.value = Object.fromEntries(usersRes.items.map(u => [u.id, u]))
  } catch (error) {
    const status = getApiStatus(error)
    if (status === 403) toast.error('Access denied: admin role required')
    else toast.error(getApiErrorMessage(error, 'Failed to load employees'))
  } finally {
    isLoading.value = false
  }
}

const toggleAccountStatus = async (emp: EmployeeItem) => {
  const account = usersById.value[emp.user_id]
  if (!account) return
  togglingUserId.value = emp.user_id
  try {
    if (account.is_active) {
      await userService.deactivateUser(emp.user_id)
      toast.success(`${emp.full_name || emp.company_email} deactivated`)
    } else {
      await userService.reactivateUser(emp.user_id)
      toast.success(`${emp.full_name || emp.company_email} reactivated`)
    }
    await fetchEmployees()
  } catch (error) {
    const status = getApiStatus(error)
    if (status === 403) toast.error('Access denied: admin role required')
    else toast.error(getApiErrorMessage(error, 'Failed to update account status'))
  } finally {
    togglingUserId.value = null
  }
}

watch([departmentFilter, statusFilter], () => {
  offset.value = 0
  void fetchEmployees()
})
watch(offset, () => void fetchEmployees())

onMounted(() => void fetchEmployees())

const prevPage = () => { if (offset.value >= limit.value) offset.value -= limit.value }
const nextPage = () => { if (offset.value + limit.value < total.value) offset.value += limit.value }

const formatDate = (d: string) => new Date(d).toLocaleDateString('en-GB', {
  day: '2-digit', month: 'short', year: 'numeric',
})

// Build user_id→display name map from the current page so Manager column can resolve names
const managerMap = computed(() =>
  Object.fromEntries(employees.value.map(e => [e.user_id, e.full_name || e.company_email]))
)
const resolveManager = (managerId: string | null) => {
  if (!managerId) return '—'
  return managerMap.value[managerId] ?? managerId.slice(0, 8) + '…'
}

// --- create dialog ---
// Luồng: nhập đầy đủ thông tin -> tạo account (POST /users) -> chờ HR profile sinh ra
// (eventual consistency) -> PATCH các trường hồ sơ -> điều hướng tới trang detail.
const showCreate = ref(false)
const form = reactive({
  // account (User Service)
  email: '',
  password: '',
  role: 'user' as Role,
  account_type: 'internal' as AccountType,
  // profile (HR Service — set qua PATCH sau khi profile tồn tại)
  full_name: '',
  phone_number: '',
  date_of_birth: '',
  hire_date: '',
  department: '',
  employee_code: '',
  job_title: '',
  manager_user_id: '',
})
const formErrors = reactive({ email: '', password: '' })
const isSubmitting = ref(false)
const isPolling = ref(false)

// Danh sách nhân viên active để chọn Manager trong form tạo
const managerOptions = ref<EmployeeItem[]>([])
const loadManagerOptions = async () => {
  try {
    const res = await hrService.listEmployees({ status: 'active', limit: 200, offset: 0 })
    managerOptions.value = res.items
  } catch {
    managerOptions.value = []
  }
}
const managerOptionLabel = (e: EmployeeItem) =>
  `${e.full_name || e.company_email}${e.job_title ? ` · ${e.job_title}` : ''}`

const openCreate = () => {
  resetForm()
  showCreate.value = true
  void loadManagerOptions()
}

const resetForm = () => {
  form.email = ''
  form.password = ''
  form.role = 'user'
  form.account_type = 'internal'
  form.full_name = ''
  form.phone_number = ''
  form.date_of_birth = ''
  form.hire_date = ''
  form.department = ''
  form.employee_code = ''
  form.job_title = ''
  form.manager_user_id = ''
  formErrors.email = ''
  formErrors.password = ''
}

const validateForm = () => {
  let ok = true
  formErrors.email = ''
  formErrors.password = ''
  if (!form.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    formErrors.email = 'Valid email required'
    ok = false
  }
  if (form.password.length < 8) {
    formErrors.password = 'Password must be at least 8 characters'
    ok = false
  }
  return ok
}

// Gom các trường hồ sơ HR người dùng đã nhập thành payload PATCH (bỏ trường rỗng)
const buildProfilePayload = (): UpdateEmployeeRequest => {
  const payload: UpdateEmployeeRequest = {}
  if (form.full_name.trim()) payload.full_name = form.full_name.trim()
  if (form.phone_number.trim()) payload.phone_number = form.phone_number.trim()
  if (form.date_of_birth) payload.date_of_birth = form.date_of_birth
  if (form.hire_date) payload.hire_date = form.hire_date
  if (form.department.trim()) payload.department = form.department.trim()
  if (form.employee_code.trim()) payload.employee_code = form.employee_code.trim()
  if (form.job_title.trim()) payload.job_title = form.job_title.trim()
  if (form.manager_user_id) payload.manager_user_id = form.manager_user_id
  return payload
}

const submitCreate = async () => {
  if (!validateForm()) return
  isSubmitting.value = true
  const profilePayload = buildProfilePayload()
  try {
    const created = await userService.createUser({
      email: form.email,
      password: form.password,
      role: form.role,
      account_type: form.account_type,
    })
    form.password = ''
    showCreate.value = false
    toast.info('Account created, syncing HR profile...')
    isPolling.value = true
    await pollAndApplyProfile(created.id, profilePayload)
  } catch (error) {
    const status = getApiStatus(error)
    if (status === 409) {
      formErrors.email = 'Email already exists'
      showCreate.value = true
    } else {
      toast.error(getApiErrorMessage(error, 'Failed to create account'))
    }
  } finally {
    isSubmitting.value = false
  }
}

const pollAndApplyProfile = async (userId: string, profilePayload: UpdateEmployeeRequest) => {
  const deadline = Date.now() + 10_000
  const INTERVAL = 500
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, INTERVAL))
    try {
      const res = await hrService.listEmployees({ limit: 50, offset: 0 })
      const found = res.items.find(e => e.user_id === userId)
      if (found) {
        // Profile đã sinh ra — áp các trường hồ sơ đã nhập (nếu có)
        if (Object.keys(profilePayload).length > 0) {
          try {
            await hrService.updateEmployee(found.id, profilePayload)
          } catch (error) {
            toast.warning(getApiErrorMessage(error, 'Account created, but some profile fields could not be saved. Please edit them on the detail page.'))
          }
        }
        isPolling.value = false
        resetForm()
        await router.push(`/employees/${found.id}`)
        return
      }
    } catch {
      // keep polling
    }
  }
  isPolling.value = false
  toast.warning('Account created but HR profile is still syncing. Refresh the list in a moment.')
  resetForm()
  await fetchEmployees()
}
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader
      title="Employee Management"
      description="HR profiles, departments, job titles, manager assignments, and account status."
    >
      <template #actions>
        <button
          class="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90 cursor-pointer"
          @click="openCreate"
        >
          <UserPlus class="h-3.5 w-3.5" />
          Create employee
        </button>
      </template>
    </PageHeader>

    <div class="px-8 pb-8 pt-2">
      <!-- filters -->
      <div class="mb-3 flex items-center justify-between gap-3">
        <div class="flex flex-1 items-center gap-3">
          <input
            v-model="departmentFilter"
            placeholder="Filter by department..."
            class="w-44 rounded-md border border-input bg-card py-1.5 px-3 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
          >
          <select
            v-model="statusFilter"
            class="rounded-md border border-input bg-card px-3 py-1.5 text-[13px] outline-none focus:border-primary"
          >
            <option value="">All Employment Statuses</option>
            <option value="active">Employment: Active</option>
            <option value="inactive">Employment: Inactive</option>
          </select>
        </div>
        <span class="text-[12px] text-muted-foreground">{{ total }} total employees</span>
      </div>

      <!-- table -->
      <div class="overflow-hidden rounded-lg border border-border bg-card">
        <table class="w-full text-[13px]">
          <thead class="bg-background/60 text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th class="px-4 py-2.5 text-left font-medium">Tên</th>
              <th class="px-4 py-2.5 text-left font-medium">Email</th>
              <th class="px-4 py-2.5 text-left font-medium">Department</th>
              <th class="px-4 py-2.5 text-left font-medium">Job Title</th>
              <th class="px-4 py-2.5 text-left font-medium">Manager</th>
              <th class="px-4 py-2.5 text-left font-medium">Status</th>
              <th class="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-if="isLoading">
              <td colspan="7" class="px-4 py-12 text-center">
                <Loader2 class="mx-auto h-6 w-6 animate-spin text-primary" />
                <p class="mt-2 text-muted-foreground">Loading employees...</p>
              </td>
            </tr>
            <tr v-else-if="employees.length === 0">
              <td colspan="7" class="px-4 py-12 text-center">
                <Briefcase class="mx-auto h-8 w-8 text-muted-foreground/40" />
                <p class="mt-2 text-muted-foreground">No employees found.</p>
              </td>
            </tr>
            <tr
              v-for="emp in employees"
              :key="emp.id"
              class="hover:bg-accent/30 cursor-pointer"
              @click="router.push(`/employees/${emp.id}`)"
            >
              <td class="px-4 py-2.5">
                <div class="flex items-center gap-2.5">
                  <div class="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                    {{ (emp.full_name || emp.company_email).substring(0, 2).toUpperCase() }}
                  </div>
                  <span class="font-medium text-foreground">{{ emp.full_name || '—' }}</span>
                </div>
              </td>
              <td class="px-4 py-2.5 text-foreground">{{ emp.company_email }}</td>
              <td class="px-4 py-2.5 text-foreground">{{ emp.department || '—' }}</td>
              <td class="px-4 py-2.5 text-foreground">{{ emp.job_title ?? '—' }}</td>
              <td class="px-4 py-2.5 text-muted-foreground">{{ resolveManager(emp.manager_user_id) }}</td>
              <td class="px-4 py-2.5">
                <StatusBadge
                  v-if="usersById[emp.user_id]"
                  :status="usersById[emp.user_id].is_active ? 'active' : 'suspended'"
                />
                <span v-else class="text-muted-foreground">—</span>
              </td>
              <td class="px-4 py-2.5 text-right" @click.stop>
                <div class="flex items-center justify-end gap-1">
                  <NuxtLink
                    :to="`/employees/${emp.id}`"
                    title="View employee detail"
                    class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground"
                  >
                    <Eye class="h-3.5 w-3.5" />
                    View
                  </NuxtLink>
                  <button
                    v-if="usersById[emp.user_id]"
                    :disabled="togglingUserId === emp.user_id"
                    class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-50"
                    :class="usersById[emp.user_id].is_active ? 'text-destructive hover:bg-destructive/10' : 'text-emerald-600 hover:bg-emerald-50'"
                    :title="usersById[emp.user_id].is_active ? 'Deactivate account' : 'Reactivate account'"
                    @click="toggleAccountStatus(emp)"
                  >
                    <Loader2 v-if="togglingUserId === emp.user_id" class="h-3.5 w-3.5 animate-spin" />
                    <PowerOff v-else-if="usersById[emp.user_id].is_active" class="h-3.5 w-3.5" />
                    <Power v-else class="h-3.5 w-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- pagination -->
      <div v-if="total > limit" class="mt-4 flex items-center justify-between">
        <span class="text-[12px] text-muted-foreground">
          Showing {{ offset + 1 }}–{{ Math.min(offset + limit, total) }} of {{ total }}
        </span>
        <div class="flex gap-2">
          <button
            class="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[12px] hover:bg-accent disabled:opacity-50"
            :disabled="offset === 0"
            @click="prevPage"
          >
            <ChevronLeft class="h-3.5 w-3.5" /> Prev
          </button>
          <button
            class="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[12px] hover:bg-accent disabled:opacity-50"
            :disabled="offset + limit >= total"
            @click="nextPage"
          >
            Next <ChevronRight class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- polling overlay -->
    <Teleport to="body">
      <div v-if="isPolling" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
        <div class="rounded-xl border border-border bg-card p-6 text-center shadow-xl">
          <Loader2 class="mx-auto h-8 w-8 animate-spin text-primary" />
          <p class="mt-3 text-[13px] font-medium text-foreground">Syncing HR profile...</p>
          <p class="mt-1 text-[12px] text-muted-foreground">This may take a few seconds.</p>
        </div>
      </div>
    </Teleport>

    <!-- create dialog -->
    <Teleport to="body">
      <div
        v-if="showCreate"
        class="fixed inset-0 z-40 flex items-center justify-center bg-black/40 backdrop-blur-sm"
        @click.self="showCreate = false"
      >
        <div class="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-card shadow-xl">
          <div class="flex items-center justify-between border-b border-border p-6">
            <div>
              <h2 class="text-[15px] font-semibold text-foreground">Create Employee</h2>
              <p class="mt-0.5 text-[12px] text-muted-foreground">Enter the full profile first; the account and HR profile are created on submit.</p>
            </div>
            <button
              class="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              @click="showCreate = false; resetForm()"
            >
              <X class="h-4 w-4" />
            </button>
          </div>

          <form class="flex min-h-0 flex-1 flex-col" @submit.prevent="submitCreate">
            <div class="flex flex-col gap-5 overflow-y-auto p-6">
            <!-- Account section -->
            <div class="flex flex-col gap-4">
              <h3 class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Account</h3>
              <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-email">Email</label>
              <input
                id="emp-email"
                v-model="form.email"
                type="email"
                autocomplete="off"
                placeholder="employee@company.com"
                class="w-full rounded-md border bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                :class="formErrors.email ? 'border-destructive' : 'border-input'"
              >
              <p v-if="formErrors.email" class="mt-1 text-[11px] text-destructive">{{ formErrors.email }}</p>
            </div>

            <div>
              <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-password">Temporary Password</label>
              <input
                id="emp-password"
                v-model="form.password"
                type="password"
                autocomplete="new-password"
                placeholder="Min. 8 characters"
                class="w-full rounded-md border bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                :class="formErrors.password ? 'border-destructive' : 'border-input'"
              >
              <p v-if="formErrors.password" class="mt-1 text-[11px] text-destructive">{{ formErrors.password }}</p>
            </div>

            <div class="flex gap-3">
              <div class="flex-1">
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-role">Role</label>
                <select
                  id="emp-role"
                  v-model="form.role"
                  class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div class="flex-1">
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-account-type">Account Type</label>
                <select
                  id="emp-account-type"
                  v-model="form.account_type"
                  class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="internal">Internal</option>
                  <option value="external">External</option>
                </select>
              </div>
              </div>
            </div>

            <!-- Profile section -->
            <div class="flex flex-col gap-4 border-t border-border pt-5">
              <h3 class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Employee Profile</h3>

              <div class="flex gap-3">
                <div class="flex-1">
                  <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-full-name">Full Name</label>
                  <input
                    id="emp-full-name"
                    v-model="form.full_name"
                    type="text"
                    placeholder="e.g. Nguyễn Văn A"
                    class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                  >
                </div>
                <div class="flex-1">
                  <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-phone">Phone Number</label>
                  <input
                    id="emp-phone"
                    v-model="form.phone_number"
                    type="tel"
                    placeholder="e.g. 0901234567"
                    class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
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
                    class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                  >
                </div>
                <div class="flex-1">
                  <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-hire">Hire Date</label>
                  <input
                    id="emp-hire"
                    v-model="form.hire_date"
                    type="date"
                    class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                  >
                </div>
              </div>

              <div>
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-department">Department</label>
                <input
                  id="emp-department"
                  v-model="form.department"
                  type="text"
                  placeholder="e.g. Engineering"
                  class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                >
              </div>

              <div class="flex gap-3">
                <div class="flex-1">
                  <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-code">Employee Code</label>
                  <input
                    id="emp-code"
                    v-model="form.employee_code"
                    type="text"
                    placeholder="e.g. EMP-001"
                    class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                  >
                </div>
                <div class="flex-1">
                  <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-title">Job Title</label>
                  <input
                    id="emp-title"
                    v-model="form.job_title"
                    type="text"
                    placeholder="e.g. Backend Engineer"
                    class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                  >
                </div>
              </div>

              <div>
                <label class="mb-1 block text-[12px] font-medium text-foreground" for="emp-manager">Manager</label>
                <select
                  id="emp-manager"
                  v-model="form.manager_user_id"
                  class="w-full rounded-md border border-input bg-background px-3 py-1.5 text-[13px] outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">No manager</option>
                  <option
                    v-for="mgr in managerOptions"
                    :key="mgr.user_id"
                    :value="mgr.user_id"
                  >
                    {{ managerOptionLabel(mgr) }}
                  </option>
                </select>
              </div>
            </div>
            </div>

            <!-- footer -->
            <div class="flex justify-end gap-2 border-t border-border p-6">
              <button
                type="button"
                class="rounded-md border border-border px-3 py-1.5 text-[12.5px] font-medium hover:bg-accent cursor-pointer"
                @click="showCreate = false; resetForm()"
              >
                Cancel
              </button>
              <button
                type="submit"
                class="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60 cursor-pointer"
                :disabled="isSubmitting"
              >
                <Loader2 v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
                Create employee
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </div>
</template>
