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
import { summarizeThought, truncateFilename, type ThoughtSummary } from '~/lib/timeline'
import ThoughtDetail from './ThoughtDetail.vue'

const props = defineProps<{ trace: TraceEntry[]; models?: NodeModel[]; thoughts?: Thought[]; plan?: AgentPlan }>()

// Nhãn + icon role của plan step (subagent). Render INLINE trong timeline để dot nằm thẳng trên
// rail. Pipeline.vue (live) cũng render inline cùng kiểu -> 2 nơi đồng bộ, không qua component riêng.
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
// Đơn sắc kiểu DeepSeek: chỉ giữ ĐỎ cho lỗi (1 màu ngữ nghĩa); còn lại đều xám.
function stepDotColor(s?: AgentPlanStep['status']): string {
  return s === 'error' ? 'bg-red-400'
    : 'bg-slate-300 dark:bg-white/25'
}

// Mỗi thought render qua <ThoughtDetail>: summary 1 dòng + disclosure "Xem chi tiết"
// (human-readable) + "Xem dữ liệu thô" lồng. Trạng thái mở do từng ThoughtDetail tự giữ.
const open = ref(false)

// Nhãn + icon tool: ưu tiên hợp đồng SSE_TOOLS (1 nguồn sự thật), bổ sung vài nhãn cũ.
const TOOL_LABEL: Record<string, string> = { ...SSE_TOOLS }
const TOOL_ICON: Record<string, any> = { rag_search: Search, hr_query: Database }

// Style theo GROUP (tập cố định, nhỏ) — node động map vào 1 trong các group này. Thêm NODE
// KHÔNG thêm group -> style ổn định; node mới mượn style group của nó.
// Đơn sắc kiểu DeepSeek: chỉ KHÁC icon từng group, màu tiêu đề/marker dùng CHUNG tông xám.
const GROUP_HEAD = 'text-slate-600 dark:text-foreground/80'
const WORKER_TINT = 'text-blue-500 dark:text-blue-400'
const GROUP_STYLE: Record<SseGroup, { title: string; icon: any; tint: string; ring: string }> = {
  orchestrator: { title: 'Orchestrator', icon: GitBranch, tint: 'text-indigo-500 dark:text-indigo-400', ring: 'ring-indigo-200 dark:ring-indigo-500/30' },
  worker: { title: 'Worker', icon: Search, tint: WORKER_TINT, ring: 'ring-blue-200 dark:ring-blue-500/30' },
  verify: { title: 'Verify — Kiểm tra & tổng hợp', icon: ShieldCheck, tint: 'text-emerald-500 dark:text-emerald-400', ring: 'ring-emerald-200 dark:ring-emerald-500/30' },
  answer: { title: 'Soạn câu trả lời', icon: Sparkles, tint: 'text-amber-500 dark:text-amber-400', ring: 'ring-amber-200 dark:ring-amber-500/30' },
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

// Bản tóm tắt (summary + detail) cho mỗi thought, gom theo group — tránh gọi summarizeThought
// lặp nhiều lần trong template.
const groupedViews = computed<Record<string, ThoughtSummary[]>>(() => {
  const by: Record<string, ThoughtSummary[]> = {}
  for (const [g, list] of Object.entries(grouped.value)) {
    by[g] = list.map(t => summarizeThought(t.text))
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
    const docStr = docs.length ? ` — ${docs.slice(0, 3).map(d => truncateFilename(d)).join(', ')}${docs.length > 3 ? '…' : ''}` : ''
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
      class="group flex items-center gap-1.5 rounded-md px-2 py-1 text-[15px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground"
      :aria-expanded="open"
      @click="open = !open"
    >
      <Sparkles class="h-4 w-4 text-slate-500 dark:text-muted-foreground" />
      <span>{{ trace.length ? `Agent đã thực hiện ${trace.length} bước` : 'Xem suy nghĩ của agent' }}</span>
      <ChevronRight class="tl-chevron h-4 w-4 transition-transform" :class="open && 'rotate-90'" />
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
              class="absolute -left-7 top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-white ring-1 dark:bg-background"
              :class="GROUP_STYLE[g].ring"
            >
              <component :is="GROUP_STYLE[g].icon" class="h-3 w-3" :class="GROUP_STYLE[g].tint" />
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-[15px] font-medium" :class="GROUP_HEAD">{{ GROUP_STYLE[g].title }}</span>
            </div>
            <!-- TÓM TẮT 1 dòng + chi tiết human-readable + raw lồng (do ThoughtDetail lo) -->
            <ThoughtDetail
              v-for="(view, i) in (groupedViews[g] || [])"
              :key="`${g}-${i}`"
              :view="view"
              class="mt-1.5"
            />
          </div>

          <!-- SUB-STEP (orchestrator): plan step + kết quả tool — dot nhỏ canh thẳng trên CÙNG rail -->
          <template v-if="g === 'orchestrator'">
            <div v-for="s in (plan?.steps || [])" :key="`p-${s.id}`" class="relative">
              <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full" :class="stepDotColor(s.status)" />
              <div class="flex items-center gap-1.5 text-[15px]">
                <component :is="ROLE_ICON[s.role] ?? FileSearch" class="h-3.5 w-3.5 shrink-0" :class="WORKER_TINT" />
                <span class="flex-1 truncate font-medium text-slate-700 dark:text-foreground/80" :title="ROLE_LABEL[s.role] ?? s.role">{{ ROLE_LABEL[s.role] ?? s.role }}</span>
                <Loader2 v-if="s.status === 'running'" class="h-3 w-3 shrink-0 animate-spin text-slate-500 dark:text-muted-foreground" />
                <XCircle v-else-if="s.status === 'error'" class="h-3 w-3 shrink-0 text-red-400" />
                <Circle v-else-if="!s.status || s.status === 'pending'" class="h-3 w-3 shrink-0 text-slate-300 dark:text-muted-foreground/40" />
              </div>
            </div>

            <div v-for="(e, i) in trace" :key="`t-${i}`" class="relative">
              <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-white/25" />
              <div class="flex items-center gap-1.5">
                <component :is="TOOL_ICON[e.tool] ?? Search" class="h-3.5 w-3.5 shrink-0" :class="WORKER_TINT" />
                <span class="text-[15px] font-medium text-slate-700 dark:text-foreground/80">{{ TOOL_LABEL[e.tool] ?? e.tool }}</span>
                <span v-if="queryLabel(e)" class="flex-1 truncate text-[13px] font-medium text-slate-500 dark:text-muted-foreground">{{ queryLabel(e) }}</span>
              </div>
              <div class="mt-0.5 pl-5 text-[13px] font-medium text-slate-500 dark:text-muted-foreground">{{ resultLabel(e) }}</div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Tôn trọng prefers-reduced-motion: chevron không animate khi user yêu cầu giảm chuyển động. */
@media (prefers-reduced-motion: reduce) {
  .tl-chevron {
    transition: none;
  }
}
</style>
