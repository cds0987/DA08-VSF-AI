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
import { Search, Database, ChevronRight, Sparkles, GitBranch, ShieldCheck, FileSearch, Lightbulb, Loader2, XCircle, Circle } from '@lucide/vue'
import type { TraceEntry, NodeModel, Thought, AgentPlan, AgentPlanStep } from '~/types'
import { SSE_GROUPS, SSE_TOOLS, nodeGroup, type SseGroup } from '~/types/sse-contract.gen'

const props = defineProps<{ trace: TraceEntry[]; models?: NodeModel[]; thoughts?: Thought[]; plan?: AgentPlan }>()

// Nhãn + icon role của plan step (subagent). Render INLINE trong timeline để dot nằm thẳng trên
// rail — không qua AgentPlan.vue (component đó còn dùng ở Pipeline với layout grid song song).
const ROLE_LABEL: Record<string, string> = {
  rag_retrieve: 'Tìm tài liệu',
  hr_lookup: 'Tra cứu HR',
  synthesize_recommend: 'Tổng hợp & khuyến nghị',
  analyze: 'Phân tích',
  critic: 'Kiểm chứng',
}
const ROLE_ICON: Record<string, any> = {
  rag_retrieve: FileSearch, hr_lookup: Database, synthesize_recommend: Sparkles, analyze: Lightbulb, critic: ShieldCheck,
}
function stepDotColor(s?: AgentPlanStep['status']): string {
  return s === 'running' ? 'bg-blue-400'
    : s === 'error' ? 'bg-red-400'
      : s === 'ok' || s === 'no_info' ? 'bg-emerald-400'
        : 'bg-slate-300 dark:bg-white/25'
}

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

    <!-- Timeline dọc kiểu DeepSeek: MỘT đường line liền mạch chạy qua TẤT CẢ dot (mốc chính +
         sub-step), mọi dot canh thẳng trên cùng rail. Chỉ đổi VISUAL, giữ nguyên dữ liệu/logic. -->
    <div v-if="open" class="relative mt-2 pl-7">
      <!-- rail liền mạch: marker (opaque) che đầu line ở mỗi icon, dot nhỏ nằm đè lên line -->
      <span aria-hidden="true" class="absolute left-[9px] top-1.5 bottom-2 w-px bg-slate-200 dark:bg-white/10" />

      <div class="space-y-3">
        <div v-for="g in visibleGroups" :key="g" class="space-y-2">
          <!-- MỐC CHÍNH: dot icon nằm trên rail -->
          <div class="relative">
            <span
              aria-hidden="true"
              class="absolute -left-7 top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-white ring-1 ring-slate-200 dark:bg-background dark:ring-white/10"
            >
              <component :is="GROUP_STYLE[g].icon" class="h-3 w-3" :class="GROUP_STYLE[g].head" />
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-[12px] font-medium" :class="GROUP_STYLE[g].head">{{ GROUP_STYLE[g].title }}</span>
            </div>
            <!-- raw text / JSON: container gọn, nền nhẹ, scroll nội bộ, không phá layout -->
            <div
              v-for="(t, i) in (grouped[g] || [])"
              :key="`${g}-${i}`"
              class="mt-1.5 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-slate-200/70 bg-slate-50/70 px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-muted-foreground"
            >
              {{ t.text }}
            </div>
          </div>

          <!-- SUB-STEP (orchestrator): plan step + kết quả tool — dot nhỏ canh thẳng trên CÙNG rail -->
          <template v-if="g === 'orchestrator'">
            <div v-for="s in (plan?.steps || [])" :key="`p-${s.id}`" class="relative">
              <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full" :class="stepDotColor(s.status)" />
              <div class="flex items-center gap-1.5 text-[11px]">
                <component :is="ROLE_ICON[s.role] ?? FileSearch" class="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-muted-foreground" />
                <span class="flex-1 truncate font-medium text-slate-700 dark:text-foreground/80">{{ ROLE_LABEL[s.role] ?? s.role }}</span>
                <Loader2 v-if="s.status === 'running'" class="h-3 w-3 shrink-0 animate-spin text-blue-400" />
                <XCircle v-else-if="s.status === 'error'" class="h-3 w-3 shrink-0 text-red-400" />
                <Circle v-else-if="!s.status || s.status === 'pending'" class="h-3 w-3 shrink-0 text-slate-300 dark:text-muted-foreground/40" />
              </div>
            </div>

            <div v-for="(e, i) in trace" :key="`t-${i}`" class="relative">
              <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-white/25" />
              <div class="flex items-center gap-1.5">
                <component :is="TOOL_ICON[e.tool] ?? Search" class="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-muted-foreground" />
                <span class="text-[11.5px] font-medium text-slate-700 dark:text-foreground/80">{{ TOOL_LABEL[e.tool] ?? e.tool }}</span>
                <span v-if="queryLabel(e)" class="flex-1 truncate text-[11px] text-slate-500 dark:text-muted-foreground">{{ queryLabel(e) }}</span>
              </div>
              <div class="mt-0.5 pl-5 text-[11px] text-slate-400 dark:text-muted-foreground/70">{{ resultLabel(e) }}</div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
