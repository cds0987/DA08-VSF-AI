<script setup lang="ts">
// Khúc "agent đã làm" PHÂN CẤP, đọc theo thứ tự logic:
//   Orchestrator (lập kế hoạch + suy nghĩ)
//     └─ subagents song song (Tìm tài liệu / Tra HR / Phân tích) + kết quả tool
//   Worker / Verify / Answer (theo group khai trong hợp đồng SSE)
//
// GENERIC theo HỢP ĐỒNG SSE (sse-contract.gen.ts): thought gom theo NODE.group, vẽ các
// group theo ĐÚNG THỨ TỰ SSE_GROUPS. Thêm node mới ở backend (khai NodeDescriptor) ->
// TỰ HIỆN dưới group của nó, KHÔNG cần sửa file này. Node lạ chưa khai -> nodeGroup()
// fallback 'orchestrator' -> vẫn hiện (KHÔNG bao giờ câm).
import { computed } from 'vue'
import { Search, Database, CheckCircle2, ChevronRight, Sparkles, GitBranch, ShieldCheck } from '@lucide/vue'
import type { TraceEntry, NodeModel, Thought, AgentPlan } from '~/types'
import { SSE_GROUPS, SSE_TOOLS, nodeGroup, type SseGroup } from '~/types/sse-contract.gen'
import AgentPlanView from './AgentPlan.vue'

const props = defineProps<{ trace: TraceEntry[]; models?: NodeModel[]; thoughts?: Thought[]; plan?: AgentPlan }>()

const open = ref(false)

// Nhãn + icon tool: ưu tiên hợp đồng SSE_TOOLS (1 nguồn sự thật), bổ sung vài nhãn cũ.
const TOOL_LABEL: Record<string, string> = { ...SSE_TOOLS }
const TOOL_ICON: Record<string, any> = { rag_search: Search, hr_query: Database }

// Style theo GROUP (tập cố định, nhỏ) — node động map vào 1 trong các group này. Thêm NODE
// KHÔNG thêm group -> style ổn định; node mới mượn style group của nó.
const GROUP_STYLE: Record<SseGroup, { title: string; icon: any; head: string; box: string }> = {
  orchestrator: {
    title: 'Orchestrator', icon: GitBranch,
    head: 'text-blue-700 dark:text-blue-300',
    box: 'border-blue-100 bg-blue-50/50 dark:border-blue-500/15 dark:bg-blue-500/5',
  },
  worker: {
    title: 'Worker', icon: Search,
    head: 'text-amber-700 dark:text-amber-300',
    box: 'border-amber-100 bg-amber-50/50 dark:border-amber-500/15 dark:bg-amber-500/5',
  },
  verify: {
    title: 'Verify — Kiểm tra & tổng hợp', icon: ShieldCheck,
    head: 'text-violet-700 dark:text-violet-300',
    box: 'border-violet-100 bg-violet-50/50 dark:border-violet-500/15 dark:bg-violet-500/5',
  },
  answer: {
    title: 'Soạn câu trả lời', icon: Sparkles,
    head: 'text-emerald-700 dark:text-emerald-300',
    box: 'border-emerald-100 bg-emerald-50/50 dark:border-emerald-500/15 dark:bg-emerald-500/5',
  },
}

// thought gom theo group (qua nodeGroup của hợp đồng). Node lạ -> 'orchestrator'.
const grouped = computed<Record<string, Thought[]>>(() => {
  const by: Record<string, Thought[]> = {}
  for (const t of props.thoughts ?? []) {
    const g = nodeGroup(t.node)
    ;(by[g] ??= []).push(t)
  }
  return by
})

// Group cần hiển thị, ĐÚNG THỨ TỰ SSE_GROUPS. orchestrator còn hiện khi có plan/trace.
const visibleGroups = computed(() =>
  SSE_GROUPS.filter(g =>
    (grouped.value[g]?.length)
    || (g === 'orchestrator' && (props.plan?.steps?.length || props.trace.length)),
  ),
)

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
      <!-- Các GROUP theo thứ tự hợp đồng. orchestrator kèm plan + tool (subagents). -->
      <div v-for="g in visibleGroups" :key="g">
        <div class="flex items-center gap-1.5 text-[12px] font-semibold" :class="GROUP_STYLE[g].head">
          <component :is="GROUP_STYLE[g].icon" class="h-3.5 w-3.5" /> {{ GROUP_STYLE[g].title }}
        </div>

        <!-- suy nghĩ của các node thuộc group -->
        <div v-for="(t, i) in (grouped[g] || [])" :key="`${g}-${i}`"
          class="mt-1 max-h-40 overflow-y-auto rounded-lg border px-3 py-1.5 text-[11.5px] leading-relaxed text-slate-600 dark:text-muted-foreground"
          :class="GROUP_STYLE[g].box">
          {{ t.text }}
        </div>

        <!-- orchestrator: subagents (plan song song) + kết quả tool, THỤT LỀ (viền trái = phân cấp) -->
        <div v-if="g === 'orchestrator' && (plan?.steps?.length || trace.length)"
          class="mt-1.5 ml-2 space-y-1 border-l-2 border-blue-100 pl-3 dark:border-blue-500/20">
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
    </div>
  </div>
</template>
