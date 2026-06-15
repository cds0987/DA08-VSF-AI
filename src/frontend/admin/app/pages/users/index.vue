<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { UserPlus, Power, PowerOff, Loader2 } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import userService from '~/lib/api/userService'
import hrService from '~/lib/api/hrService'
import type { User } from '~/types'

const users = ref<(User & { department?: string })[]>([])
const isLoading = ref(true)
const total = ref(0)

const fetchUsers = async () => {
  isLoading.value = true
  try {
    const [usersRes, deptMap] = await Promise.all([
      userService.listUsers(),
      hrService.getEmployeeDepartments().catch(() => ({} as Record<string, string>)),
    ])
    users.value = usersRes.items.map(u => ({ ...u, department: deptMap[u.id] }))
    total.value = usersRes.total
  } catch (error) {
    toast.error('Failed to fetch users')
  } finally {
    isLoading.value = false
  }
}

const toggleStatus = async (user: User) => {
  if (!user.id) return
  try {
    if (user.is_active) {
      await userService.deactivateUser(user.id)
      toast.success(`User ${user.email} deactivated`)
    } else {
      await userService.reactivateUser(user.id)
      toast.success(`User ${user.email} reactivated`)
    }
    await fetchUsers()
  } catch (error) {
    toast.error('Failed to update user status')
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader
      title="User Management"
      description="Roles, access, and account status across your organization."
    >
      <template #actions>
        <button class="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90 cursor-pointer">
          <UserPlus class="h-3.5 w-3.5" /> Invite user
        </button>
      </template>
    </PageHeader>
    <div class="px-8 pb-8 pt-2">
      <div class="overflow-hidden rounded-lg border border-border bg-card">
        <table class="w-full text-[13px]">
          <thead class="bg-background/60 text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th class="px-4 py-2.5 text-left font-medium">User</th>
              <th class="px-4 py-2.5 text-left font-medium">
                Department
              </th>
              <th class="px-4 py-2.5 text-left font-medium">Role</th>
              <th class="px-4 py-2.5 text-left font-medium">Status</th>
              <th class="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-if="isLoading" class="hover:bg-accent/30">
              <td colspan="5" class="px-4 py-8 text-center text-muted-foreground">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="h-4 w-4 animate-spin" />
                  Loading users...
                </div>
              </td>
            </tr>
            <tr v-else-if="users.length === 0" class="hover:bg-accent/30">
              <td colspan="5" class="px-4 py-8 text-center text-muted-foreground">
                No users found.
              </td>
            </tr>
            <tr v-for="u in users" :key="u.id" class="hover:bg-accent/30">
              <td class="px-4 py-2.5">
                <div class="flex items-center gap-2.5">
                  <div class="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                    {{ (u.name || u.email).substring(0, 2).toUpperCase() }}
                  </div>
                  <div>
                    <div class="text-[13px] font-medium text-foreground">
                      {{ u.name || u.email.split('@')[0] }}
                    </div>
                    <div class="text-[11px] text-muted-foreground">
                      {{ u.email }}
                    </div>
                  </div>
                </div>
              </td>
              <td class="px-4 py-2.5 text-foreground">
                {{ u.department || 'N/A' }}
              </td>
              <td class="px-4 py-2.5">
                <span class="rounded-md border border-border bg-background px-2 py-0.5 text-[11.5px] font-medium text-foreground capitalize">
                  {{ u.role }}
                </span>
              </td>
              <td class="px-4 py-2.5">
                <StatusBadge :status="u.is_active ? 'Active' : 'Suspended'" />
              </td>
              <td class="px-4 py-2.5 text-right">
                <button
                  @click="toggleStatus(u)"
                  class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer"
                  :class="u.is_active ? 'text-destructive hover:bg-destructive/10' : 'text-emerald-600 hover:bg-emerald-50'"
                  :title="u.is_active ? 'Deactivate user' : 'Reactivate user'"
                >
                  <PowerOff v-if="u.is_active" class="h-3.5 w-3.5" />
                  <Power v-else class="h-3.5 w-3.5" />
                  {{ u.is_active ? 'Deactivate' : 'Reactivate' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-4 text-[12px] text-muted-foreground">
        Total: {{ total }} users
      </div>
    </div>
  </div>
</template>
