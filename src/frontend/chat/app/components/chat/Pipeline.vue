<script setup lang="ts">
// LIVE (lúc streaming) — PHÂN CẤP giống MessageSteps: Orchestrator -> subagents -> Verify.
// Giữ chỉ báo live (spinner, thinkingStatus). SSE KHÔNG đổi: chỉ sắp xếp lại cách hiển thị.
import { computed } from 'vue'
import { Search, Database, Loader2, CheckCircle2, Sparkles, GitBranch, ShieldCheck } from '@lucide/vue'
import type { TraceEntry, NodeModel, AgentPlan } from '~/types'
import AgentPlanView from './AgentPlan.vue'

interface Props {
  traceLog: TraceEntry[]
  thinkingStatus?: string
  isThinking?: boolean
  models?: NodeModel[]
  thoughts?: { node: string; text: string }[]
  plan?: AgentPlan | null
}
const props = defineProps<Props>()

const TOOL_LABEL: Record<string, string> = { rag_search: 'Tìm kiếm tài liệu', hr_query: 'Truy vấn dữ liệu HR' }
const TOOL_ICON: Record<string, any> = { rag_search: Search, hr_query: Database }

const orchThoughts = computed(() => (props.thoughts ?? []).filter(t => t.node === 'plan' || t.node === 'orchestrate' || t.node === 'think'))
const verifyThoughts = computed(() => (props.thoughts ?? []).filter(t => t.node === 'verify'))
const otherThoughts = computed(() => (props.thoughts ?? []).filter(t => !['plan', 'orchestrate', 'think', 'verify'].includes(t.node)))

function getQueryLabel(entry: TraceEntry): string {
  const args = entry.args
  if (entry.tool === 'rag_search') { const q = (args.query as string) || ''; return q ? `"${q}"` : '' }
  if (entry.tool === 'hr_query') {
    const intent = (args.intent as string) || ''
    const m: Record<string, string> = { leave_balance: 'số ngày phép còn lại', leave_requests: 'lịch sử đơn nghỉ phép', payroll: 'thông tin lương' }
    return m[intent] || intent
  }
  return ''
}
function getResultLabel(entry: TraceEntry): string {
  if (entry.tool === 'rag_search') {
    const count = entry.resultCount ?? 0
    if (count === 0) return 'Không tìm thấy kết quả'
    const docs = entry.resultDocs ?? []
    const docStr = docs.length > 0 ? ` — ${docs.slice(0, 2).join(', ')}${docs.length > 2 ? '...' : ''}` : ''
    return `${count} tài liệu${docStr}`
  }
  if (entry.tool === 'hr_query' && entry.resultRaw) return entry.resultRaw.slice(0, 60) + (entry.resultRaw.length > 60 ? '…' : '')
  return ''
}
</script>

<template>
  <div class="rounded-xl bg-transparent px-4 py-3">
    <div class="mb-2.5 flex items-center gap-2 text-[12px] font-medium text-slate-700 dark:text-foreground/80">
      <Sparkles class="h-3.5 w-3.5 text-blue-500" /> Agent đang xử lý
    </div>

    <!-- ═══ ORCHESTRATOR ═══ -->
    <div v-if="orchThoughts.length || plan?.steps?.length || (isThinking && traceLog.length === 0)" class="mb-2">
      <div class="flex items-center gap-1.5 text-[12px] font-semibold text-blue-700 dark:text-blue-300">
        <GitBranch class="h-3.5 w-3.5" /> Orchestrator
      </div>
      <!-- reasoning live: bounded (max-h + scroll) -> stream SSE nhưng KHÔNG thành tường dài -->
      <div v-for="(t, i) in orchThoughts" :key="`o-${i}`"
        class="mt-1 max-h-32 overflow-y-auto rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:border-blue-500/15 dark:bg-blue-500/5 dark:text-muted-foreground">
        {{ t.text }}
      </div>
      <!-- spinner lập kế hoạch (trước khi có thought/plan) -->
      <div v-if="isThinking && !orchThoughts.length && !plan?.steps?.length && traceLog.length === 0" class="mt-1 flex items-center gap-2.5 px-1 py-1">
        <Loader2 class="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
        <span class="text-[12.5px] text-slate-600 dark:text-muted-foreground animate-pulse">{{ thinkingStatus || 'Đang lập kế hoạch…' }}</span>
      </div>
      <!-- subagents + tool THỤT LỀ dưới orchestrator -->
      <div v-if="plan?.steps?.length || traceLog.length" class="mt-1.5 ml-2 space-y-1 border-l-2 border-blue-100 pl-3 dark:border-blue-500/20">
        <AgentPlanView v-if="plan?.steps?.length" :plan="plan" />
        <div v-for="(entry, i) in traceLog" :key="`t-${i}`"
          class="rounded-lg border border-slate-100 dark:border-white/5 bg-slate-50/60 dark:bg-white/[0.03] px-3 py-2">
          <div class="flex items-center gap-2">
            <component :is="TOOL_ICON[entry.tool] ?? Search" class="h-3.5 w-3.5 shrink-0 text-blue-500" />
            <span class="text-[12px] font-semibold text-slate-700 dark:text-foreground/80">{{ TOOL_LABEL[entry.tool] ?? entry.tool }}</span>
            <span v-if="getQueryLabel(entry)" class="flex-1 truncate text-[11.5px] text-slate-500 dark:text-muted-foreground">{{ getQueryLabel(entry) }}</span>
            <Loader2 v-if="entry.pending" class="h-3 w-3 shrink-0 animate-spin text-blue-400" />
            <CheckCircle2 v-else class="h-3 w-3 shrink-0 text-emerald-500" />
          </div>
          <div v-if="!entry.pending" class="mt-1 pl-5 text-[11px] text-slate-500 dark:text-muted-foreground/80">{{ getResultLabel(entry) }}</div>
        </div>
      </div>
    </div>

    <!-- ═══ VERIFY ═══ -->
    <div v-if="verifyThoughts.length || (isThinking && traceLog.length > 0)" class="mb-1">
      <div class="flex items-center gap-1.5 text-[12px] font-semibold text-violet-700 dark:text-violet-300">
        <ShieldCheck class="h-3.5 w-3.5" /> Verify — Kiểm tra &amp; tổng hợp
      </div>
      <div v-for="(t, i) in verifyThoughts" :key="`v-${i}`"
        class="mt-1 max-h-32 overflow-y-auto rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:border-violet-500/15 dark:bg-violet-500/5 dark:text-muted-foreground">
        {{ t.text }}
      </div>
      <div v-if="isThinking && traceLog.length > 0" class="mt-1 flex items-center gap-2 px-1 py-1">
        <Loader2 class="h-3 w-3 shrink-0 animate-spin text-violet-400" />
        <span class="text-[11.5px] text-slate-500 dark:text-muted-foreground animate-pulse">{{ thinkingStatus || 'Đang tổng hợp kết quả…' }}</span>
      </div>
    </div>

    <!-- thoughts khác -->
    <div v-for="(t, i) in otherThoughts" :key="`x-${i}`"
      class="mb-1 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-1.5 text-[11.5px] text-slate-600 dark:border-white/5 dark:bg-white/[0.03] dark:text-muted-foreground">
      {{ t.text }}
    </div>
  </div>
</template>
