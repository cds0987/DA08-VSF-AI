<script setup lang="ts">
import { Download, Loader2, Search } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import auditService from '~/lib/api/auditService'
import type { AuditLogItem } from '~/types'

const q = ref('')
const rows = ref<AuditLogItem[]>([])
const total = ref(0)
const isLoading = ref(true)

const filteredRows = computed(() => rows.value.filter((item) =>
  [item.actor_email, item.action, item.resource, item.source]
    .join(' ')
    .toLowerCase()
    .includes(q.value.toLowerCase()),
))

async function fetchAuditLogs() {
  isLoading.value = true
  try {
    const response = await auditService.listAuditLogs({ limit: 100, offset: 0 })
    rows.value = response.items
    total.value = response.total
  } catch (error) {
    console.error('Failed to fetch audit logs:', error)
    toast.error('Failed to load audit logs')
  } finally {
    isLoading.value = false
  }
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function exportCsv() {
  const lines = [
    ['timestamp', 'source', 'user', 'action', 'resource', 'status'].join(','),
    ...filteredRows.value.map((item) => [
      escapeCsv(formatTimestamp(item.created_at)),
      escapeCsv(item.source),
      escapeCsv(item.actor_email),
      escapeCsv(item.action),
      escapeCsv(item.resource),
      escapeCsv(item.status),
    ].join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'audit-logs.csv'
  link.click()
  URL.revokeObjectURL(url)
}

function escapeCsv(value: string) {
  return `"${value.replaceAll('"', '""')}"`
}

onMounted(() => {
  fetchAuditLogs()
})
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader
      title="Audit Logs"
      description="Immutable, read-only trail sourced from live backend services."
    >
      <template #actions>
        <button
          class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12.5px] hover:bg-accent"
          :disabled="isLoading || filteredRows.length === 0"
          @click="exportCsv"
        >
          <Download class="h-3.5 w-3.5" /> Export CSV
        </button>
      </template>
    </PageHeader>
    <div class="px-8 pb-8 pt-2">
      <div class="mb-3 flex items-center justify-between gap-3">
        <div class="relative max-w-sm flex-1">
          <Search class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="q"
            placeholder="Filter by user, action, resource, or source..."
            class="w-full rounded-md border border-input bg-card py-1.5 pl-8 pr-3 text-[13px] outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
          />
        </div>
        <span class="text-[12px] text-muted-foreground">
          {{ filteredRows.length }} of {{ total }} events
        </span>
      </div>
      <div class="overflow-hidden rounded-lg border border-border bg-card">
        <table class="w-full text-[13px]">
          <thead class="bg-background/60 text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th class="px-4 py-2.5 text-left font-medium">Timestamp</th>
              <th class="px-4 py-2.5 text-left font-medium">Source</th>
              <th class="px-4 py-2.5 text-left font-medium">User</th>
              <th class="px-4 py-2.5 text-left font-medium">Action</th>
              <th class="px-4 py-2.5 text-left font-medium">Resource</th>
              <th class="px-4 py-2.5 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-if="isLoading">
              <td colspan="6" class="px-4 py-8 text-center text-muted-foreground">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="h-4 w-4 animate-spin" />
                  Loading audit logs...
                </div>
              </td>
            </tr>
            <tr v-else-if="filteredRows.length === 0">
              <td colspan="6" class="px-4 py-8 text-center text-muted-foreground">
                No audit events found.
              </td>
            </tr>
            <tr v-for="item in filteredRows" :key="item.id" class="hover:bg-accent/30">
              <td class="px-4 py-2.5 font-mono text-[12px] text-muted-foreground">
                {{ formatTimestamp(item.created_at) }}
              </td>
              <td class="px-4 py-2.5 text-foreground">{{ item.source }}</td>
              <td class="px-4 py-2.5 text-foreground">{{ item.actor_email }}</td>
              <td class="px-4 py-2.5">
                <code class="rounded bg-muted px-1.5 py-0.5 text-[11.5px] text-foreground">
                  {{ item.action }}
                </code>
              </td>
              <td class="px-4 py-2.5 text-foreground">{{ item.resource }}</td>
              <td class="px-4 py-2.5">
                <StatusBadge :status="item.status" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
