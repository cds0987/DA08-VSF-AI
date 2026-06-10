<script setup lang="ts">
import {
  FileCheck2,
  FilePlus2,
  FileClock,
  FileX2,
  Layers,
  MessageSquare,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Loader2,
} from '@lucide/vue'
import PageHeader from '~/components/admin-ui/PageHeader.vue'
import SectionHeader from '~/components/admin-ui/SectionHeader.vue'
import StatCard from '~/components/admin-ui/StatCard.vue'
import StatusBadge from '~/components/admin-ui/StatusBadge.vue'
import auditService from '~/lib/api/auditService'
import { useQueryService } from '~/lib/api/queryService'
import documentService from '~/lib/api/documentService'
import type { AuditLogItem } from '~/types'

const queryService = useQueryService()
const metrics = ref<import('~/types').AdminMetrics | null>(null)
const recentActivity = ref<AuditLogItem[]>([])
const docStats = ref({
  total: 0,
  indexed: 0,
  processing: 0,
  failed: 0,
  chunks: 0,
})
const isLoadingMetrics = ref(false)
const isLoadingDocs = ref(false)
const isLoadingActivity = ref(false)

async function fetchMetrics() {
  isLoadingMetrics.value = true
  try {
    metrics.value = await queryService.getAdminMetrics()
  } catch (error) {
    console.error('Failed to fetch admin metrics:', error)
  } finally {
    isLoadingMetrics.value = false
  }
}

async function fetchDocStats() {
  isLoadingDocs.value = true
  try {
    const [all, indexed, proc, failed] = await Promise.all([
      documentService.listDocuments({ limit: 200 }),
      documentService.listDocuments({ status: 'indexed', limit: 1 }),
      documentService.listDocuments({ status: 'processing', limit: 1 }),
      documentService.listDocuments({ status: 'failed', limit: 1 }),
    ])

    docStats.value = {
      total: all.total,
      indexed: indexed.total,
      processing: proc.total,
      failed: failed.total,
      chunks: all.items.reduce((acc, curr) => acc + (curr.chunk_count || 0), 0),
    }
  } catch (error) {
    console.error('Failed to fetch document stats:', error)
  } finally {
    isLoadingDocs.value = false
  }
}

async function fetchRecentActivity() {
  isLoadingActivity.value = true
  try {
    const response = await auditService.listAuditLogs({ limit: 6, offset: 0 })
    recentActivity.value = response.items
  } catch (error) {
    console.error('Failed to fetch recent activity:', error)
  } finally {
    isLoadingActivity.value = false
  }
}

function formatAuditMeta(item: AuditLogItem) {
  return `${item.actor_email} · ${item.resource}`
}

onMounted(() => {
  fetchMetrics()
  fetchDocStats()
  fetchRecentActivity()
})
</script>

<template>
  <div class="flex h-full flex-col overflow-y-auto">
    <PageHeader
      title="Knowledge Operations"
      description="Manage the enterprise knowledge base, ingestion pipelines, and access."
    >
      <template #actions>
        <NuxtLink
          to="/upload"
          class="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground shadow-xs transition hover:bg-primary/90"
        >
          <FilePlus2 class="h-3.5 w-3.5" /> Upload documents
        </NuxtLink>
      </template>
    </PageHeader>
    <div class="space-y-6 px-8 pb-8 pt-2">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total documents"
          :value="docStats.total.toLocaleString()"
          hint="Across knowledge base"
        >
          <template #icon><Layers class="h-4 w-4" /></template>
        </StatCard>
        <StatCard
          label="Indexed"
          :value="docStats.indexed.toLocaleString()"
          intent="success"
          hint="Searchable content"
        >
          <template #icon><FileCheck2 class="h-4 w-4" /></template>
        </StatCard>
        <StatCard
          label="Processing / queued"
          :value="docStats.processing.toLocaleString()"
          intent="info"
          hint="Pipeline active"
        >
          <template #icon><FileClock class="h-4 w-4" /></template>
        </StatCard>
        <StatCard
          label="Failed"
          :value="docStats.failed.toLocaleString()"
          intent="error"
          hint="Requires attention"
        >
          <template #icon><FileX2 class="h-4 w-4" /></template>
        </StatCard>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total chunks"
          :value="docStats.chunks.toLocaleString()"
          hint="Indexed fragments from the latest 200 documents"
        >
          <template #icon><Layers class="h-4 w-4" /></template>
        </StatCard>
        <StatCard
          label="Total Queries"
          :value="metrics?.total_questions?.toLocaleString() || '...'"
          intent="info"
          hint="All time questions"
        >
          <template #icon><MessageSquare class="h-4 w-4" /></template>
        </StatCard>
        <StatCard
          label="Positive Feedback"
          :value="metrics ? `${(metrics.feedback.rate * 100).toFixed(0)}%` : '...'"
          :intent="(metrics?.feedback.rate ?? 0) > 0.8 ? 'success' : 'info'"
          :delta="metrics ? `${metrics.feedback.up} Up / ${metrics.feedback.down} Down` : ''"
        >
          <template #icon>
            <ArrowUpRight v-if="(metrics?.feedback.rate ?? 0) > 0.5" class="h-4 w-4" />
            <ArrowDownRight v-else class="h-4 w-4" />
          </template>
        </StatCard>
        <StatCard
          label="System health"
          value="Healthy"
          intent="success"
          hint="All services operational"
        >
          <template #icon><Activity class="h-4 w-4" /></template>
        </StatCard>
      </div>

      <div class="grid gap-6 lg:grid-cols-3">
        <div class="rounded-lg border border-border bg-card lg:col-span-2">
          <div class="border-b border-border px-4 py-3">
            <SectionHeader
              title="Top Questions"
              description="Most frequent queries from users."
            />
          </div>
          <div class="divide-y divide-border">
            <div v-if="isLoadingMetrics" class="p-8 text-center text-muted-foreground">
              Loading metrics...
            </div>
            <div v-else-if="!metrics?.top_questions?.length" class="p-8 text-center text-muted-foreground">
              No query data available yet.
            </div>
            <div v-for="question in metrics?.top_questions" :key="question.question" class="flex items-center gap-3 px-4 py-3">
              <div class="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                <MessageSquare class="h-4 w-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="truncate text-[13px] font-medium text-foreground">
                  {{ question.question }}
                </div>
                <div class="text-[11.5px] text-muted-foreground">
                  Asked {{ question.count }} times
                </div>
              </div>
              <div class="text-[12px] font-bold text-primary">
                {{ question.count }}
              </div>
            </div>
          </div>
        </div>

        <div class="rounded-lg border border-border bg-card">
          <div class="border-b border-border px-4 py-3">
            <SectionHeader
              title="Recent activity"
              description="Latest audit events from live backend services."
            />
          </div>
          <div class="divide-y divide-border">
            <div v-if="isLoadingActivity" class="p-8 text-center text-muted-foreground">
              <div class="flex items-center justify-center gap-2">
                <Loader2 class="h-4 w-4 animate-spin" />
                Loading activity...
              </div>
            </div>
            <div v-else-if="recentActivity.length === 0" class="p-8 text-center text-muted-foreground">
              No audit activity available yet.
            </div>
            <div v-for="item in recentActivity" :key="item.id" class="flex items-center gap-3 px-4 py-3">
              <div class="min-w-0 flex-1">
                <div class="truncate text-[12.5px] font-medium text-foreground">
                  {{ item.action }}
                </div>
                <div class="truncate text-[11px] text-muted-foreground">
                  {{ formatAuditMeta(item) }}
                </div>
              </div>
              <StatusBadge :status="item.status" />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
