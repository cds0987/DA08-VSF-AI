<script setup lang="ts">
// LIVE (lúc streaming) — DÙNG CHUNG timeline kiểu DeepSeek với MessageSteps: 1 rail dọc liền
// mạch, mốc chính (Orchestrator/Verify) + sub-step (plan/tool) canh thẳng trên rail. Khác
// MessageSteps ở chỗ có chỉ báo LIVE: dot/marker của bước ĐANG chạy được tô màu + pulse,
// spinner + thinkingStatus. SSE KHÔNG đổi: chỉ sắp xếp lại cách hiển thị.
import { computed } from 'vue'
import { Search, Database, Sparkles, GitBranch, ShieldCheck, FileSearch, Lightbulb, XCircle } from '@lucide/vue'
import type { TraceEntry, NodeModel, AgentPlan, AgentPlanStep } from '~/types'
import { nodeGroup } from '~/types/sse-contract.gen'
import { summarizeThought, truncateFilename } from '~/lib/timeline'
import ThoughtDetail from './ThoughtDetail.vue'

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
const ROLE_LABEL: Record<string, string> = {
  rag_retrieve: 'Tìm tài liệu', hr_lookup: 'Tra cứu HR', synthesize_recommend: 'Tổng hợp & khuyến nghị', analyze: 'Phân tích', critic: 'Kiểm chứng',
}
const ROLE_ICON: Record<string, any> = {
  rag_retrieve: FileSearch, hr_lookup: Database, synthesize_recommend: Sparkles, analyze: Lightbulb, critic: ShieldCheck,
}
// dot trạng thái plan step — running tô xanh (đang hoạt động, không pulse; hiệu ứng "đang chạy"
// thể hiện bằng shimmer trên tiêu đề), còn lại theo status.
function stepDotColor(s?: AgentPlanStep['status']): string {
  return s === 'running' ? 'bg-blue-500'
    : s === 'error' ? 'bg-red-400'
      : s === 'ok' || s === 'no_info' ? 'bg-emerald-400'
        : 'bg-slate-300 dark:bg-white/25'
}

// Gom theo GROUP của hợp đồng SSE (sse-contract.gen) -> node mới thuộc group orchestrator/
// verify TỰ vào đúng mục, KHÔNG cần sửa file này. Node group khác (worker/answer) -> "khác".
const orchThoughts = computed(() => (props.thoughts ?? []).filter(t => nodeGroup(t.node) === 'orchestrator'))
const verifyThoughts = computed(() => (props.thoughts ?? []).filter(t => nodeGroup(t.node) === 'verify'))
const otherThoughts = computed(() => (props.thoughts ?? []).filter(t => !['orchestrator', 'verify'].includes(nodeGroup(t.node))))

// Tóm tắt 1 dòng cho mỗi thought (chi tiết + raw ẩn trong ThoughtDetail). View song song mảng gốc.
const orchViews = computed(() => orchThoughts.value.map(t => summarizeThought(t.text)))
const verifyViews = computed(() => verifyThoughts.value.map(t => summarizeThought(t.text)))
const otherViews = computed(() => otherThoughts.value.map(t => summarizeThought(t.text)))

// Mốc đang hoạt động -> marker tô màu/ring để phân biệt: verify chạy sau khi đã có tool;
// còn lại đang ở orchestrator.
const verifyActive = computed(() => !!props.isThinking && props.traceLog.length > 0)
const orchActive = computed(() => !!props.isThinking && !verifyActive.value)

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
    const docStr = docs.length > 0 ? ` — ${docs.slice(0, 2).map(d => truncateFilename(d)).join(', ')}${docs.length > 2 ? '...' : ''}` : ''
    return `${count} tài liệu${docStr}`
  }
  if (entry.tool === 'hr_query' && entry.resultRaw) return entry.resultRaw.slice(0, 60) + (entry.resultRaw.length > 60 ? '…' : '')
  return ''
}
</script>

<template>
  <div class="px-4 py-3">
    <!-- header: cỡ chữ bằng câu trả lời (16px) -->
    <div class="mb-2.5 flex items-center gap-2 text-base font-medium text-slate-700 dark:text-foreground/80">
      <Sparkles class="h-4 w-4 text-blue-500" /> Agent đang xử lý
    </div>

    <div class="relative pl-7">
      <!-- 1 rail dọc liền mạch xuyên qua mọi dot -->
      <span aria-hidden="true" class="absolute left-[9px] top-1.5 bottom-2 w-px bg-slate-200 dark:bg-white/10" />

      <div class="space-y-3">
        <!-- ═══ ORCHESTRATOR ═══ -->
        <div v-if="orchThoughts.length || plan?.steps?.length || (isThinking && traceLog.length === 0)" class="space-y-2">
          <div class="relative">
            <!-- marker: ring xanh + pulse khi đang hoạt động -->
            <span
              aria-hidden="true"
              class="absolute -left-7 top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-white ring-1 dark:bg-background"
              :class="orchActive ? 'ring-blue-400 dark:ring-blue-500/50' : 'ring-slate-200 dark:ring-white/10'"
            >
              <GitBranch class="h-3 w-3 text-blue-700 dark:text-blue-300" />
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-sm font-medium text-blue-700 dark:text-blue-300" :class="orchActive && 'ai-shimmer'">Orchestrator</span>
            </div>
            <!-- reasoning live: summary + chi tiết human-readable + raw lồng (ThoughtDetail) -->
            <ThoughtDetail v-for="(view, i) in orchViews" :key="`o-${i}`" :view="view" class="mt-1.5" />
            <!-- trạng thái lập kế hoạch (trước khi có thought/plan) — text thường, KHÔNG shimmer -->
            <div v-if="isThinking && !orchThoughts.length && !plan?.steps?.length && traceLog.length === 0" class="mt-1.5 text-[13px] text-slate-500 dark:text-muted-foreground">
              {{ thinkingStatus || 'Đang lập kế hoạch…' }}
            </div>
          </div>

          <!-- plan step: dot canh trên rail, running = xanh + pulse -->
          <div v-for="s in (plan?.steps || [])" :key="`p-${s.id}`" class="relative">
            <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full" :class="stepDotColor(s.status)" />
            <div class="flex items-center gap-1.5 text-sm">
              <component :is="ROLE_ICON[s.role] ?? FileSearch" class="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-muted-foreground" />
              <span class="flex-1 truncate font-medium text-slate-700 dark:text-foreground/80" :class="s.status === 'running' && 'ai-shimmer'">{{ ROLE_LABEL[s.role] ?? s.role }}</span>
              <XCircle v-if="s.status === 'error'" class="h-3 w-3 shrink-0 text-red-400" />
            </div>
          </div>

          <!-- tool: dot trên rail xanh khi đang chạy; tiêu đề shimmer thay cho spinner -->
          <div v-for="(entry, i) in traceLog" :key="`t-${i}`" class="relative">
            <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full" :class="entry.pending ? 'bg-blue-500' : 'bg-slate-300 dark:bg-white/25'" />
            <div class="flex items-center gap-1.5">
              <component :is="TOOL_ICON[entry.tool] ?? Search" class="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-muted-foreground" />
              <span class="text-sm font-medium text-slate-700 dark:text-foreground/80" :class="entry.pending && 'ai-shimmer'">{{ TOOL_LABEL[entry.tool] ?? entry.tool }}</span>
              <span v-if="getQueryLabel(entry)" class="flex-1 truncate text-xs text-slate-500 dark:text-muted-foreground">{{ getQueryLabel(entry) }}</span>
            </div>
            <div v-if="!entry.pending && getResultLabel(entry)" class="mt-0.5 pl-5 text-xs text-slate-400 dark:text-muted-foreground/70">{{ getResultLabel(entry) }}</div>
          </div>
        </div>

        <!-- ═══ VERIFY ═══ -->
        <div v-if="verifyThoughts.length || verifyActive" class="space-y-2">
          <div class="relative">
            <span
              aria-hidden="true"
              class="absolute -left-7 top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-white ring-1 dark:bg-background"
              :class="verifyActive ? 'ring-violet-400 dark:ring-violet-500/50' : 'ring-slate-200 dark:ring-white/10'"
            >
              <ShieldCheck class="h-3 w-3 text-violet-700 dark:text-violet-300" />
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-sm font-medium text-violet-700 dark:text-violet-300" :class="verifyActive && 'ai-shimmer'">Verify — Kiểm tra &amp; tổng hợp</span>
            </div>
            <ThoughtDetail v-for="(view, i) in verifyViews" :key="`v-${i}`" :view="view" class="mt-1.5" />
            <div v-if="verifyActive && !verifyThoughts.length" class="mt-1.5 text-[13px] text-slate-500 dark:text-muted-foreground">
              {{ thinkingStatus || 'Đang tổng hợp kết quả…' }}
            </div>
          </div>
        </div>

        <!-- thoughts khác (group lạ) -->
        <div v-for="(view, i) in otherViews" :key="`x-${i}`" class="relative">
          <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-white/25" />
          <ThoughtDetail :view="view" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Hiệu ứng ánh sáng lướt ngang (DeepSeek-style) cho TIÊU ĐỀ bước đang chạy — thay cho spinner.
   QUAN TRỌNG: background-color = currentColor làm NỀN base phủ KÍN chữ (giữ đúng màu tiêu đề
   blue/violet/slate). Gradient chỉ là 1 DẢI SÁNG (phần còn lại trong suốt) chạy trên nền đó ->
   dù dải sáng chạy ra ngoài vùng chữ thì nền base vẫn phủ -> KHÔNG bao giờ mất chữ. */
.ai-shimmer {
  background-color: currentColor;
  background-image: linear-gradient(
    90deg,
    transparent 0%,
    transparent 42%,
    color-mix(in srgb, currentColor 30%, #fff) 50%,
    transparent 58%,
    transparent 100%
  );
  background-size: 200% 100%;
  background-repeat: no-repeat;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: ai-shimmer-sweep 1.8s linear infinite;
}
/* dải sáng vào từ trái (-100%) ra phải (200%); khi ra ngoài thì vô hình -> loop liền mạch. */
@keyframes ai-shimmer-sweep {
  0% { background-position: -100% 0; }
  100% { background-position: 200% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .ai-shimmer {
    animation: none;
    background-image: none;
    background-color: transparent;
    -webkit-text-fill-color: currentColor;
  }
}
</style>
