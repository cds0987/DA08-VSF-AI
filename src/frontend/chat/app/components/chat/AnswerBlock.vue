<script setup lang="ts">
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Copy,
  File as FileGeneric,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  Globe,
  Presentation,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from '@lucide/vue'
import { buildCitationSources, citationFileKind, cn } from '~/lib/utils'
import type { CitationFileGroup } from '~/lib/utils'
import type { ChatMessage, Citation } from '~/types'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { createStreamingRenderer } from '~/lib/streamingMarkdown'
import ActionableCard from './ActionableCard.vue'
import ApprovalReviewCard from './ApprovalReviewCard.vue'
import ProactiveSuggestionCard from './ProactiveSuggestionCard.vue'
import MessageSteps from './MessageSteps.vue'

const props = defineProps<{ data: ChatMessage }>()
const emit = defineEmits<{
  (e: 'open-citation', citation: Citation): void
  (e: 'feedback', messageId: string, score: 1 | -1): void
  (e: 'retry', messageId: string): void
}>()

const copied = ref(false)
const sourcesOpen = ref(false)   // disclosure "Tài liệu liên quan" — DeepSeek-style, mặc định gọn

const md = new MarkdownIt({ html: true, breaks: true, linkify: true })
// Render tăng dần khi stream: cache prefix các block đã xong, mỗi frame chỉ render tail.
const streamingRenderer = createStreamingRenderer({
  render: (s: string) => md.render(s),
  sanitize: (h: string) => DOMPurify.sanitize(h),
})

// Gom citation theo tài liệu -> số nguồn + map ref->số. Dùng cho cả pill inline lẫn list nguồn.
const citationSources = computed(() => buildCitationSources(props.data.citations))

function resolveRef(n: number): Citation | undefined {
  return props.data.citations?.find(x => x.ref === n) ?? props.data.citations?.[n - 1]
}

// CHỈ nguồn THỰC SỰ được trích trong câu trả lời (có [N] khớp source) — không liệt kê hết
// mọi chunk đã lấy. Quét marker [N] trong content, map qua refToNumber, giữ số hợp lệ.
const citedSources = computed(() => {
  const content = props.data.content || ''
  const { refToNumber, sources } = citationSources.value
  const used = new Set<number>()
  for (const m of content.matchAll(/\[(\d+)\]/g)) {
    const marker = parseInt(m[1])
    const num = refToNumber[marker]
    if (num !== undefined && resolveRef(marker)) used.add(num)
  }
  return sources.filter(s => used.has(s.number))
})

// Icon + màu theo nhóm loại tệp (không hardcode PDF).
const GROUP_ICON: Record<CitationFileGroup, any> = {
  pdf: FileText, doc: FileText, text: FileCode, web: Globe,
  sheet: FileSpreadsheet, slide: Presentation, image: FileImage, unknown: FileGeneric,
}
const GROUP_ICON_CLASS: Record<CitationFileGroup, string> = {
  pdf: 'text-rose-500', doc: 'text-blue-500', text: 'text-slate-400 dark:text-muted-foreground',
  web: 'text-sky-500', sheet: 'text-emerald-500', slide: 'text-amber-500',
  image: 'text-violet-500', unknown: 'text-slate-400 dark:text-muted-foreground',
}
function fileIcon(doc?: string | null) { return GROUP_ICON[citationFileKind(doc).group] }
function fileIconClass(doc?: string | null) { return GROUP_ICON_CLASS[citationFileKind(doc).group] }

const renderedContent = computed(() => {
  if (!props.data.content) return ''
  // Đang stream: render markdown THÔ + con trỏ nhấp nháy, CHƯA inject pill (citation chưa có).
  // Cùng node với bản cuối -> khi xong chỉ patch ([N] thành pill) chứ không remount -> không flash.
  if (props.data.streaming) {
    // Strip [N] khỏi content lúc stream -> không hiện marker thô "[1][4]" (kì); pill render khi xong.
    const html = streamingRenderer.toHtml(props.data.content.replace(/\[\d+\]/g, ''))
    return html.replace(/(<\/(?:p|li|h[1-6]|pre|blockquote)>)\s*$/, '<span class="streaming-cursor"></span>$1')
  }
  const rawHtml = md.render(props.data.content)
  const { refToNumber } = citationSources.value
  const esc = (t: string) => t.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))
  // [N] liền nhau -> pill số gọn kiểu DeepSeek; dedup theo SỐ NGUỒN trong cùng run; đẩy dấu
  // câu RA TRƯỚC pill (pill đứng sau dấu chấm). data-ref = marker thô để mở đúng chunk đã trích.
  const withRefs = rawHtml.replace(/(\s*)((?:\[\d+\]\s*)+)([.,;:!?…]*)/g, (_m, lead, run, punct) => {
    const markers = [...run.matchAll(/\[(\d+)\]/g)].map(m => parseInt(m[1]))
    const seen = new Set<number>()
    const pills: string[] = []
    for (const marker of markers) {
      const cit = resolveRef(marker)
      const num = refToNumber[marker]
      // Bỏ ref LLM bịa (không khớp source) + dedup nguồn trùng trong cùng cụm.
      if (!cit || num === undefined || seen.has(num)) continue
      seen.add(num)
      const label = esc(`Nguồn ${num}: ${cit.document}`).replace(/"/g, '&quot;')
      pills.push(`<span class="citation-ref cursor-pointer select-none inline-flex items-center justify-center align-baseline min-w-[18px] h-[18px] mx-0.5 px-1 rounded-md bg-slate-100 dark:bg-white/10 text-[11px] font-semibold leading-none text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-white/20" role="button" tabindex="0" aria-label="${label}" data-ref="${marker}">${num}</span>`)
    }
    if (!pills.length) return punct  // toàn ref bịa -> bỏ marker, GIỮ dấu câu
    return `${punct}${lead || ' '}${pills.join('')}`
  })
  return DOMPurify.sanitize(withRefs, { ADD_ATTR: ['data-ref', 'role', 'tabindex', 'aria-label'] })
})

// Mở đúng chunk đã trích dẫn từ pill (data-ref = marker thô LLM phát).
function openMarker(el: HTMLElement) {
  const cit = resolveRef(parseInt(el.dataset.ref ?? ''))
  if (cit) emit('open-citation', cit)
}

function handleContentClick(e: MouseEvent) {
  const chip = (e.target as HTMLElement).closest('.citation-ref') as HTMLElement | null
  if (chip) openMarker(chip)
}

// Enter/Space mở citation khi pill đang focus (keyboard) — pill là role="button".
function handleContentKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter' && e.key !== ' ') return
  const chip = (e.target as HTMLElement).closest('.citation-ref') as HTMLElement | null
  if (!chip) return
  e.preventDefault()
  openMarker(chip)
}

function copyToClipboard() {
  if (!props.data.content) return
  void navigator.clipboard.writeText(props.data.content)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}
</script>

<template>
  <div class="overflow-hidden rounded-2xl bg-transparent">
    <!-- Server error banner (4xx/5xx) -->
    <div
      v-if="data.error"
      class="flex items-start gap-2 border-b border-rose-100 dark:border-rose-900/30 bg-rose-50/60 dark:bg-rose-900/10 px-5 py-3 text-[12.5px] text-rose-700 dark:text-rose-400"
    >
      <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
      {{ data.error }}
    </div>

    <div class="px-5 pb-5 pt-4 text-slate-900 dark:text-foreground">
      <!-- Bước agent đã làm (bền vững, thu gọn) — user xem lại agent đã nghĩ/làm gì -->
      <MessageSteps
        v-if="data.trace?.length || data.models?.length || data.thoughts?.length || data.plan?.steps?.length"
        :trace="data.trace ?? []"
        :models="data.models"
        :thoughts="data.thoughts"
        :plan="data.plan"
      />
      <div
        v-if="data.content"
        data-bot-answer
        :data-message-id="data.id"
        class="ai-response-markdown prose prose-base prose-slate dark:prose-invert max-w-none text-slate-900 dark:text-foreground prose-p:leading-relaxed prose-li:leading-relaxed prose-headings:font-semibold prose-headings:tracking-tight prose-strong:font-semibold prose-pre:bg-slate-50 dark:prose-pre:bg-background/50 prose-pre:border prose-pre:border-slate-200 dark:prose-pre:border-white/5 [overflow-wrap:anywhere]"
        v-html="renderedContent"
        @click="handleContentClick"
        @keydown="handleContentKeydown"
      />
      <!-- Network interruption — ChatGPT style: no content received, show subtle placeholder -->
      <p
        v-else-if="data.interrupted"
        class="text-sm text-slate-400 dark:text-muted-foreground italic"
      >
        Kết nối bị gián đoạn.
      </p>
      <template v-for="(act, i) in data.actions" :key="act.idempotency_key || i">
        <ApprovalReviewCard v-if="act.action_type === 'review_leave_approvals'" />
        <ProactiveSuggestionCard v-else-if="act.action_type === 'proactive_doc_suggestion'" :action="act" />
        <ActionableCard v-else :action="act" :message-id="data.id" />
      </template>
    </div>

    <!-- Nguồn: CHỈ tài liệu được trích trong câu trả lời (citedSources), không liệt kê hết chunk -->
    <div v-if="!data.streaming && citedSources.length" class="px-5 pb-1">
      <button
        type="button"
        class="group inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[13px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
        :aria-expanded="sourcesOpen"
        @click="sourcesOpen = !sourcesOpen"
      >
        <ChevronDown class="src-chevron h-3.5 w-3.5 transition-transform" :class="sourcesOpen && 'rotate-180'" aria-hidden="true" />
        <span>Tài liệu liên quan · {{ citedSources.length }} nguồn</span>
      </button>

      <div v-show="sourcesOpen" class="mt-1.5 flex flex-col gap-1">
        <button
          v-for="s in citedSources"
          :key="s.number"
          type="button"
          class="group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-slate-100 dark:hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
          :aria-label="`Nguồn ${s.number}: ${s.citation.document}`"
          @click="emit('open-citation', s.citation)"
        >
          <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-slate-100 text-[11px] font-semibold text-slate-500 dark:bg-white/10 dark:text-slate-300">{{ s.number }}</span>
          <component :is="fileIcon(s.citation.document)" class="h-4 w-4 shrink-0" :class="fileIconClass(s.citation.document)" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-700 dark:text-foreground/90">{{ s.citation.document }}</span>
        </button>
      </div>
    </div>

    <div v-if="!data.streaming" class="flex items-center gap-1 px-5 py-2">
      <!-- Retry button — only shown for interrupted (network) messages -->
      <Tooltip v-if="data.interrupted">
        <TooltipTrigger as-child>
          <button
            class="rounded-md p-1.5 text-slate-500 cursor-pointer transition-all duration-200 hover:bg-slate-100 hover:text-slate-900 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground"
            @click="emit('retry', data.id)"
          >
            <RefreshCw class="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" :side-offset="8" class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900">
          Thử lại
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger as-child>
          <button
            class="rounded-md p-1.5 text-slate-500 cursor-pointer transition-all duration-200 hover:bg-slate-100 hover:text-slate-900 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground"
            @click="copyToClipboard"
          >
            <Check v-if="copied" class="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
            <Copy v-else class="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" :side-offset="8" class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900">
          Sao chép
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger as-child>
          <button
            :disabled="!data.sessionId"
            :class="cn(
              'rounded-md p-1.5 text-slate-500 cursor-pointer transition-all duration-200 hover:bg-slate-100 hover:text-slate-900 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground disabled:opacity-40',
              data.feedback === 1 && 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400',
            )"
            @click="emit('feedback', data.id, 1)"
          >
            <ThumbsUp class="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" :side-offset="8" class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900">
          Thích
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger as-child>
          <button
            :disabled="!data.sessionId"
            :class="cn(
              'rounded-md p-1.5 text-slate-500 cursor-pointer transition-all duration-200 hover:bg-slate-100 hover:text-slate-900 dark:text-muted-foreground dark:hover:bg-white/5 dark:hover:text-foreground disabled:opacity-40',
              data.feedback === -1 && 'bg-rose-50 text-rose-600 dark:bg-rose-900/20 dark:text-rose-400',
            )"
            @click="emit('feedback', data.id, -1)"
          >
            <ThumbsDown class="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" :side-offset="8" class="bg-slate-900 text-[11px] font-medium text-white dark:bg-slate-100 dark:text-slate-900">
          Không thích
        </TooltipContent>
      </Tooltip>
    </div>
  </div>
</template>

<style scoped>
/* Con trỏ stream — chèn qua v-html nên cần :deep(). Giữ y hệt StreamingBlock cũ. */
:deep(.streaming-cursor) {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: middle;
  border-radius: 9999px;
  background-color: rgb(59 130 246);
  animation: streaming-blink 0.9s steps(1, end) infinite;
  box-shadow: 0 0 0.65rem rgb(59 130 246 / 0.35);
}

@keyframes streaming-blink {
  0%,
  45% {
    opacity: 1;
  }
  55%,
  100% {
    opacity: 0;
  }
}

.ai-response-markdown {
  --tw-prose-body: var(--foreground);
  --tw-prose-headings: var(--foreground);
  --tw-prose-lead: var(--foreground);
  --tw-prose-links: var(--primary);
  --tw-prose-bold: var(--foreground);
  /* Marker list dịu (DeepSeek-style) — không cùng độ đậm với chữ. */
  --tw-prose-counters: var(--muted-foreground);
  --tw-prose-bullets: var(--muted-foreground);
  --tw-prose-quotes: var(--muted-foreground);
  --tw-prose-captions: var(--muted-foreground);
  --tw-prose-kbd: var(--foreground);
  --tw-prose-code: var(--foreground);
  --tw-prose-pre-code: var(--foreground);
}

/* Focus bàn phím (Tab) phải nhìn thấy rõ — pill là role="button". */
.ai-response-markdown :deep(.citation-ref:focus-visible) {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
.ai-response-markdown :deep(.citation-ref:focus:not(:focus-visible)) {
  outline: none;
}

/* Chevron disclosure nguồn — bỏ animation khi người dùng yêu cầu giảm chuyển động. */
@media (prefers-reduced-motion: reduce) {
  .src-chevron {
    transition: none;
  }
}
</style>
