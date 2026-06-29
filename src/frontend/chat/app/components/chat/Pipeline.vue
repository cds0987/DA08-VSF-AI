<script setup lang="ts">
// LIVE (lúc streaming) — DÙNG CHUNG timeline kiểu DeepSeek với MessageSteps: 1 rail dọc liền
// mạch, mốc chính (Orchestrator/Verify) + sub-step (plan/tool) canh thẳng trên rail. Khác
// MessageSteps ở chỗ có chỉ báo LIVE: dot/marker của bước ĐANG chạy được tô màu + pulse,
// spinner + thinkingStatus. SSE KHÔNG đổi: chỉ sắp xếp lại cách hiển thị.
import { computed, ref, watch, onUnmounted } from 'vue'
import { Search, Database, Sparkles, GitBranch, ShieldCheck, FileSearch, Lightbulb, XCircle, Check } from '@lucide/vue'
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

// Rotating hint cho wait DÀI (outlier >25s / pre-plan chậm) — đổi 1 chuỗi mỗi 4s, CHỈ khi đang
// nghĩ. RẺ: không per-token, không reflow (chỉ swap text); shimmer CSS lo phần "sống". Clear khi
// dừng/unmount -> KHÔNG để timer rò. Dùng làm fallback khi chưa có status thật từ backend.
const HINTS = ['Đang lập kế hoạch…', 'Đang phân tích yêu cầu…', 'Đang đối chiếu dữ liệu…', 'Sắp có kết quả…']
const hintIdx = ref(0)
const rotatingHint = computed(() => HINTS[hintIdx.value % HINTS.length])
let hintTimer: ReturnType<typeof setInterval> | null = null
watch(() => props.isThinking, (on) => {
  if (on && !hintTimer) hintTimer = setInterval(() => { hintIdx.value++ }, 4000)
  else if (!on && hintTimer) { clearInterval(hintTimer); hintTimer = null; hintIdx.value = 0 }
}, { immediate: true })
onUnmounted(() => { if (hintTimer) clearInterval(hintTimer) })

const TOOL_LABEL: Record<string, string> = { rag_search: 'Tìm kiếm tài liệu', hr_query: 'Truy vấn dữ liệu HR' }
const TOOL_ICON: Record<string, any> = { rag_search: Search, hr_query: Database }
const ROLE_LABEL: Record<string, string> = {
  rag_retrieve: 'Tìm tài liệu', hr_lookup: 'Tra cứu HR', synthesize_recommend: 'Tổng hợp & khuyến nghị', analyze: 'Phân tích', critic: 'Kiểm chứng',
}
const ROLE_ICON: Record<string, any> = {
  rag_retrieve: FileSearch, hr_lookup: Database, synthesize_recommend: Sparkles, analyze: Lightbulb, critic: ShieldCheck,
}
const WORKER_TINT = 'text-blue-500 dark:text-blue-400'
const PHASE_TINT = {
  orchestrator: { tint: 'text-indigo-500 dark:text-indigo-400', ring: 'ring-indigo-200 dark:ring-indigo-500/30' },
  verify: { tint: 'text-emerald-500 dark:text-emerald-400', ring: 'ring-emerald-200 dark:ring-emerald-500/30' },
}
// Dot trạng thái: bước ĐANG suy nghĩ -> XANH (đang hoạt động), xong/chờ -> XÁM, lỗi -> ĐỎ.
function stepDotColor(s?: AgentPlanStep['status']): string {
  return s === 'error' ? 'bg-red-400'
    : s === 'running' ? 'bg-blue-500'
      : 'bg-slate-300 dark:bg-white/25'
}

// Gom theo GROUP của hợp đồng SSE (sse-contract.gen) -> node mới thuộc group orchestrator/
// verify TỰ vào đúng mục, KHÔNG cần sửa file này. Node group khác (worker/answer) -> "khác".
const orchThoughts = computed(() => (props.thoughts ?? []).filter(t => nodeGroup(t.node) === 'orchestrator'))
const verifyThoughts = computed(() => (props.thoughts ?? []).filter(t => nodeGroup(t.node) === 'verify'))
const otherThoughts = computed(() => (props.thoughts ?? []).filter(t => !['orchestrator', 'verify'].includes(nodeGroup(t.node))))

// STREAM LIVE: orchestrator reasoning hiện DẦN cho user thấy agent đang nghĩ (CoT thô -> rồi tự
// chuyển sang tóm tắt cấu trúc khi JSON kế hoạch đóng). Trước đây phải CHỜ JSON đóng mới render để
// chống "flash" — vì summarizeThought CŨ parse nhầm mảnh '[1]'/object step con thành rác "1". Nay
// summarizeThought đã miễn nhiễm (isMeaningfulJson bỏ qua mảng primitive + step rời) nên render thẳng
// prose đang stream là AN TOÀN, không còn rác -> khôi phục cảm giác streaming. (verify/khác vẫn live.)
const orchReady = computed(() => orchThoughts.value.filter(t => t.text.trim().length > 0))

// Tóm tắt 1 dòng cho mỗi thought (chi tiết + raw ẩn trong ThoughtDetail). View song song mảng gốc.
const orchViews = computed(() => orchReady.value.map(t => summarizeThought(t.text)))
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
    <!-- header luồng suy nghĩ -->
    <div class="mb-2.5 flex items-center gap-2 text-[15px] font-medium text-slate-700 dark:text-foreground/80">
      <Sparkles class="h-4 w-4 text-slate-500 dark:text-muted-foreground" /> Agent đang xử lý
    </div>

    <div class="relative pl-7">
      <!-- 1 rail dọc liền mạch xuyên qua mọi dot -->
      <span aria-hidden="true" class="absolute left-[9px] top-1.5 bottom-2 w-px bg-slate-200 dark:bg-white/10" />

      <div class="space-y-3">
        <!-- ═══ ORCHESTRATOR ═══ -->
        <div v-if="orchReady.length || plan?.steps?.length || (isThinking && traceLog.length === 0)" class="space-y-2">
          <div class="relative">
            <!-- marker: ring xanh + pulse khi đang hoạt động -->
            <span
              aria-hidden="true"
              class="absolute -left-7 top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-white ring-1 dark:bg-background"
              :class="[orchActive ? PHASE_TINT.orchestrator.ring : 'ring-slate-200 dark:ring-white/10', orchActive && `tl-marker-pulse ${PHASE_TINT.orchestrator.tint}`]"
            >
              <GitBranch class="h-3 w-3" :class="PHASE_TINT.orchestrator.tint" />
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-[15px] font-medium text-slate-600 dark:text-foreground/80" :class="orchActive && 'ai-shimmer'">Orchestrator</span>
            </div>
            <!-- reasoning live: summary + chi tiết human-readable + raw lồng (ThoughtDetail) -->
            <ThoughtDetail v-for="(view, i) in orchViews" :key="`o-${i}`" :view="view" class="mt-1.5" />
            <!-- trạng thái lập kế hoạch (trước khi có thought/plan) — text thường, KHÔNG shimmer -->
            <div v-if="isThinking && !orchReady.length && !plan?.steps?.length && traceLog.length === 0" class="mt-1.5 text-sm font-medium text-slate-500 dark:text-muted-foreground">
              {{ thinkingStatus || rotatingHint }}
            </div>
          </div>

          <!-- plan step: dot canh trên rail, running = xanh + pulse -->
          <div v-for="(s, i) in (plan?.steps || [])" :key="`p-${s.id}`" class="relative tl-step-enter" :style="{ '--i': i }">
            <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full" :class="stepDotColor(s.status)" />
            <div class="flex items-center gap-1.5 text-[15px]">
              <component :is="ROLE_ICON[s.role] ?? FileSearch" class="h-3.5 w-3.5 shrink-0" :class="WORKER_TINT" />
              <span class="flex-1 truncate font-medium text-slate-700 dark:text-foreground/80" :class="s.status === 'running' && 'ai-shimmer'" :title="ROLE_LABEL[s.role] ?? s.role">{{ ROLE_LABEL[s.role] ?? s.role }}</span>
              <XCircle v-if="s.status === 'error'" class="h-3 w-3 shrink-0 text-red-400" />
              <Check v-else-if="s.status === 'done'" class="tl-check-pop h-3 w-3 shrink-0 text-emerald-500 dark:text-emerald-400" />
            </div>
          </div>

          <!-- tool: dot trên rail xanh khi đang chạy; tiêu đề shimmer thay cho spinner -->
          <div v-for="(entry, i) in traceLog" :key="`t-${i}`" class="relative tl-step-enter" :style="{ '--i': i }">
            <span aria-hidden="true" class="absolute -left-[22px] top-[7px] h-1.5 w-1.5 rounded-full" :class="entry.pending ? 'bg-blue-500' : 'bg-slate-300 dark:bg-white/25'" />
            <div class="flex items-center gap-1.5">
              <component :is="TOOL_ICON[entry.tool] ?? Search" class="h-3.5 w-3.5 shrink-0" :class="WORKER_TINT" />
              <span class="text-[15px] font-medium text-slate-700 dark:text-foreground/80" :class="entry.pending && 'ai-shimmer'">{{ TOOL_LABEL[entry.tool] ?? entry.tool }}</span>
              <span v-if="getQueryLabel(entry)" class="flex-1 truncate text-[13px] font-medium text-slate-500 dark:text-muted-foreground">{{ getQueryLabel(entry) }}</span>
            </div>
            <div v-if="!entry.pending && getResultLabel(entry)" class="mt-0.5 pl-5 text-[13px] font-medium text-slate-500 dark:text-muted-foreground">{{ getResultLabel(entry) }}</div>
          </div>
        </div>

        <!-- ═══ VERIFY ═══ — MỐC CỐ ĐỊNH: hiện bất cứ khi nào pipeline nặng đã chạy (có plan/
             trace), KHÔNG chỉ khi có verify-thought. Gate GIỐNG HỆT MessageSteps persisted ->
             hiện nhất quán cả lúc stream lẫn lúc xong (không còn nhấp nháy rồi biến mất). Có
             reasoning thật -> render dưới header; không có -> chỉ mốc tĩnh báo bước đã chạy. -->
        <div v-if="verifyThoughts.length || plan?.steps?.length || traceLog.length" class="space-y-2">
          <div class="relative">
            <span
              aria-hidden="true"
              class="absolute -left-7 top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-white ring-1 dark:bg-background"
              :class="[verifyActive ? PHASE_TINT.verify.ring : 'ring-slate-200 dark:ring-white/10', verifyActive && `tl-marker-pulse ${PHASE_TINT.verify.tint}`]"
            >
              <ShieldCheck class="h-3 w-3" :class="PHASE_TINT.verify.tint" />
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-[15px] font-medium text-slate-600 dark:text-foreground/80" :class="verifyActive && 'ai-shimmer'">Verify — Kiểm tra &amp; tổng hợp</span>
            </div>
            <ThoughtDetail v-for="(view, i) in verifyViews" :key="`v-${i}`" :view="view" class="mt-1.5" />
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
   xám đơn sắc). Gradient chỉ là 1 DẢI SÁNG (phần còn lại trong suốt) chạy trên nền đó ->
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
