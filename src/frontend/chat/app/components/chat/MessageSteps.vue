<script setup lang="ts">
// Khúc "agent đã làm" PHÂN CẤP, đọc theo thứ tự logic:
//   Orchestrator (lập kế hoạch + suy nghĩ)
//     └─ subagents song song (Tìm tài liệu / Tra HR / Phân tích) + kết quả tool
//   Verify (kiểm tra & tổng hợp)
//   (câu trả lời ở dưới message)
// Gắn vào message (bền) -> user mở lại xem agent đã làm gì. Khác Pipeline.vue (chỉ live).
import { computed } from 'vue'
import { Search, Database, CheckCircle2, ChevronRight, Sparkles, GitBranch, ShieldCheck } from '@lucide/vue'
import type { TraceEntry, NodeModel, Thought, AgentPlan } from '~/types'
import AgentPlanView from './AgentPlan.vue'

const props = defineProps<{ trace: TraceEntry[]; models?: NodeModel[]; thoughts?: Thought[]; plan?: AgentPlan }>()

const open = ref(false)

const TOOL_LABEL: Record<string, string> = {
  rag_search: 'Tìm kiếm tài liệu',
  hr_query: 'Truy vấn dữ liệu HR',
  leave_approvals: 'Lấy danh sách đơn chờ duyệt',
  resolve_date: 'Xác định ngày',
  leave_types: 'Lấy danh mục loại nghỉ',
}
const TOOL_ICON: Record<string, any> = { rag_search: Search, hr_query: Database }

// Gom suy nghĩ theo TẦNG: orchestrator (lập kế hoạch) vs verify (kiểm tra) vs khác.
const orchThoughts = computed(() => (props.thoughts ?? []).filter(t => t.node === 'plan' || t.node === 'orchestrate' || t.node === 'think'))
const verifyThoughts = computed(() => (props.thoughts ?? []).filter(t => t.node === 'verify'))
const otherThoughts = computed(() => (props.thoughts ?? []).filter(t => !['plan', 'orchestrate', 'think', 'verify'].includes(t.node)))

function queryLabel(e: TraceEntry): string {
  if (e.tool === 'rag_search') { const q = (e.args.query as string) || ''; return q ? `"${q}"` : '' }
  return (e.args.intent as string) || ''
}
function resultLabel(e: TraceEntry): string {
  if (e.tool === 'rag_search') {
    const count = e.resultCount ?? 0
    if (count === 0) return 'Không tìm thấy kết quả'
    const docs = e.resultDocs ?? []
    const docStr = docs.length ? ` — ${docs.slice(0, 3).join(', ')}${docs.length > 3 ? '…' : ''}` : ''
    return `${count} tài liệu${docStr}`
  }
  if (e.resultRaw) return e.resultRaw.slice(0, 80) + (e.resultRaw.length > 80 ? '…' : '')
  return 'Hoàn tất'
}
</script>

<template>
  <div v-if="trace.length || models?.length || thoughts?.length || plan?.steps?.length" class="mb-2.5">
    <!-- Header toggle -->
    <button
      v-if="trace.length || thoughts?.length || plan?.steps?.length"
      class="group flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground"
      @click="open = !open"
    >
      <Sparkles class="h-3.5 w-3.5 text-blue-500" />
      <span>{{ trace.length ? `Agent đã thực hiện ${trace.length} bước` : 'Xem suy nghĩ của agent' }}</span>
      <ChevronRight class="h-3.5 w-3.5 transition-transform" :class="open && 'rotate-90'" />
    </button>

    <div v-if="open" class="mt-1.5 space-y-2">
      <!-- ═══ ORCHESTRATOR ═══ -->
      <div v-if="orchThoughts.length || plan?.steps?.length">
        <div class="flex items-center gap-1.5 text-[12px] font-semibold text-blue-700 dark:text-blue-300">
          <GitBranch class="h-3.5 w-3.5" /> Orchestrator
        </div>
        <!-- suy nghĩ lập kế hoạch -->
        <div v-for="(t, i) in orchThoughts" :key="`o-${i}`"
          class="mt-1 max-h-40 overflow-y-auto rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:border-blue-500/15 dark:bg-blue-500/5 dark:text-muted-foreground">
          {{ t.text }}
        </div>
        <!-- subagents + tool: THỤT LỀ dưới orchestrator (viền trái = phân cấp) -->
        <div v-if="plan?.steps?.length || trace.length" class="mt-1.5 ml-2 space-y-1 border-l-2 border-blue-100 pl-3 dark:border-blue-500/20">
          <AgentPlanView v-if="plan?.steps?.length" :plan="plan" />
          <div v-for="(e, i) in trace" :key="`t-${i}`"
            class="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 dark:border-white/5 dark:bg-white/[0.03]">
            <div class="flex items-center gap-2">
              <component :is="TOOL_ICON[e.tool] ?? Search" class="h-3.5 w-3.5 shrink-0 text-blue-500" />
              <span class="text-[12px] font-semibold text-slate-700 dark:text-foreground/80">{{ TOOL_LABEL[e.tool] ?? e.tool }}</span>
              <span v-if="queryLabel(e)" class="flex-1 truncate text-[11.5px] text-slate-500 dark:text-muted-foreground">{{ queryLabel(e) }}</span>
              <CheckCircle2 class="h-3 w-3 shrink-0 text-emerald-500" />
            </div>
            <div class="mt-1 pl-5 text-[11px] text-slate-500 dark:text-muted-foreground/80">{{ resultLabel(e) }}</div>
          </div>
        </div>
      </div>

      <!-- ═══ VERIFY ═══ -->
      <div v-if="verifyThoughts.length">
        <div class="flex items-center gap-1.5 text-[12px] font-semibold text-violet-700 dark:text-violet-300">
          <ShieldCheck class="h-3.5 w-3.5" /> Verify — Kiểm tra &amp; tổng hợp
        </div>
        <div v-for="(t, i) in verifyThoughts" :key="`v-${i}`"
          class="mt-1 max-h-40 overflow-y-auto rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:border-violet-500/15 dark:bg-violet-500/5 dark:text-muted-foreground">
          {{ t.text }}
        </div>
      </div>

      <!-- thoughts khác (nếu có) -->
      <div v-for="(t, i) in otherThoughts" :key="`x-${i}`"
        class="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-1.5 text-[11.5px] text-slate-600 dark:border-white/5 dark:bg-white/[0.03] dark:text-muted-foreground">
        {{ t.text }}
      </div>
    </div>
  </div>
</template>
