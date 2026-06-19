<script setup lang="ts">
import {
  AlertTriangle,
  Check,
  Copy,
  FileText,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from '@lucide/vue'
import { citationHeadingPath, citationTeaser, cn, formatRelevance } from '~/lib/utils'
import type { ChatMessage, Citation } from '~/types'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
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

const popoverCitations = ref<Citation[]>([])   // nhóm nguồn của chip đang hover
const popoverIndex = ref(0)                    // trang carousel hiện tại
const popoverStyle = ref({ top: '0px', left: '0px' })
let hideTimer: ReturnType<typeof setTimeout> | null = null

const activeCite = computed(() => popoverCitations.value[popoverIndex.value] ?? null)

const md = new MarkdownIt({ html: true, breaks: true, linkify: true })

function resolveRef(n: number): Citation | undefined {
  return props.data.citations?.find(x => x.ref === n) ?? props.data.citations?.[n - 1]
}

const renderedContent = computed(() => {
  if (!props.data.content) return ''
  const rawHtml = md.render(props.data.content)
  const esc = (t: string) => t.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))
  // Gộp run [N] liền nhau -> 1 chip logo VSF. Đẩy dấu câu cuối câu RA TRƯỚC chip
  // (chip đứng SAU dấu chấm, không phải trước).
  const withRefs = rawHtml.replace(/(\s*)((?:\[\d+\]\s*)+)([.,;:!?…]*)/g, (_m, lead, run, punct) => {
    const refs = [...run.matchAll(/\[(\d+)\]/g)]
      .map(m => parseInt(m[1]))
      .filter(n => resolveRef(n))  // bỏ ref LLM bịa (không khớp source)
    if (!refs.length) return punct  // ref bịa -> bỏ marker, GIỮ dấu câu
    const first = resolveRef(refs[0])!
    const teaser = esc(citationTeaser(first.caption || first.snippet))
    const extra = refs.length > 1
      ? `<span class="ml-0.5 text-[10px] font-semibold text-slate-500 dark:text-slate-400">+${refs.length - 1}</span>`
      : ''
    const chip = `<span class="citation-ref cursor-pointer select-none inline-flex items-center gap-1 align-baseline rounded-full bg-slate-100 dark:bg-white/10 pl-0.5 pr-1.5 py-0.5 mx-0.5 hover:bg-slate-200 dark:hover:bg-white/20" data-refs="${refs.join(',')}"><img src="/logo.png" alt="" class="h-3.5 w-3.5 rounded-full object-cover"/><span class="text-[11px] font-medium text-slate-600 dark:text-slate-300">${teaser}</span>${extra}</span>`
    return `${punct}${lead || ' '}${chip}`
  })
  return DOMPurify.sanitize(withRefs, { ADD_ATTR: ['data-refs'] })
})

function refsFromChip(chip: HTMLElement): Citation[] {
  return (chip.dataset.refs ?? '')
    .split(',')
    .map(s => resolveRef(parseInt(s)))
    .filter((c): c is Citation => Boolean(c))
}

function handleContentClick(e: MouseEvent) {
  // closest: click có thể trúng <img>/"+N" con bên trong chip
  const chip = (e.target as HTMLElement).closest('.citation-ref') as HTMLElement | null
  if (!chip) return
  const list = refsFromChip(chip)
  const citation = list[popoverIndex.value] ?? list[0]
  if (citation) emit('open-citation', citation)
}

function copyToClipboard() {
  if (!props.data.content) return
  void navigator.clipboard.writeText(props.data.content)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}

function handleContentMouseOver(e: MouseEvent) {
  const chip = (e.target as HTMLElement).closest('.citation-ref') as HTMLElement | null
  if (!chip) return
  if (hideTimer) { clearTimeout(hideTimer); hideTimer = null }
  const list = refsFromChip(chip)
  if (!list.length) return
  const rect = chip.getBoundingClientRect()
  popoverStyle.value = {
    top: `${rect.bottom + window.scrollY + 6}px`,
    left: `${Math.min(rect.left + window.scrollX, window.innerWidth - 332)}px`,
  }
  popoverCitations.value = list
  popoverIndex.value = 0
}

function handleContentMouseLeave() {
  hideTimer = setTimeout(() => { popoverCitations.value = [] }, 200)
}

function keepPopover() {
  if (hideTimer) { clearTimeout(hideTimer); hideTimer = null }
}

function leavePopover() {
  hideTimer = setTimeout(() => { popoverCitations.value = [] }, 200)
}

function prevCite() {
  if (popoverIndex.value > 0) popoverIndex.value--
}

function nextCite() {
  if (popoverIndex.value < popoverCitations.value.length - 1) popoverIndex.value++
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
        v-if="data.trace?.length || data.models?.length || data.thoughts?.length"
        :trace="data.trace ?? []"
        :models="data.models"
        :thoughts="data.thoughts"
      />
      <div
        v-if="data.content"
        class="ai-response-markdown prose prose-base prose-slate dark:prose-invert max-w-none font-medium text-slate-900 dark:text-foreground prose-p:font-medium prose-p:leading-relaxed prose-pre:bg-slate-50 dark:prose-pre:bg-background/50 prose-pre:border prose-pre:border-slate-200 dark:prose-pre:border-white/5 [overflow-wrap:anywhere]"
        v-html="renderedContent"
        @click="handleContentClick"
        @mouseover="handleContentMouseOver"
        @mouseleave="handleContentMouseLeave"
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

    <div class="flex items-center gap-1 px-5 py-2">
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

    <Teleport to="body">
      <div
        v-if="activeCite"
        :style="{ position: 'absolute', zIndex: '9999', width: '320px', top: popoverStyle.top, left: popoverStyle.left }"
        class="rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-card shadow-lg p-3 pointer-events-auto"
        @mouseenter="keepPopover"
        @mouseleave="leavePopover"
      >
        <!-- Header: điều hướng carousel (chỉ khi >1 nguồn) + score -->
        <div class="flex items-center justify-between mb-1.5">
          <div class="flex items-center gap-1">
            <template v-if="popoverCitations.length > 1">
              <button
                class="flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30 dark:hover:bg-white/10 dark:hover:text-foreground"
                :disabled="popoverIndex === 0"
                @click="prevCite"
              >‹</button>
              <button
                class="flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30 dark:hover:bg-white/10 dark:hover:text-foreground"
                :disabled="popoverIndex === popoverCitations.length - 1"
                @click="nextCite"
              >›</button>
              <span class="text-[10px] text-slate-400">{{ popoverIndex + 1 }}/{{ popoverCitations.length }}</span>
            </template>
          </div>
          <span
            v-if="formatRelevance(activeCite.score)"
            class="rounded-full bg-blue-50 dark:bg-blue-900/30 px-1.5 py-0.5 text-[10px] font-semibold text-blue-600 dark:text-blue-300"
          >{{ formatRelevance(activeCite.score) }}</span>
        </div>
        <!-- Title: logo VSF + tên tài liệu -->
        <div class="flex items-center gap-1.5 mb-1">
          <img src="/logo.png" alt="" class="h-4 w-4 rounded-full object-cover shrink-0" />
          <span class="truncate text-[12px] font-semibold text-slate-800 dark:text-foreground">{{ activeCite.document }}</span>
        </div>
        <!-- Snippet -->
        <p class="line-clamp-3 text-[12px] leading-snug text-slate-600 dark:text-muted-foreground mb-1">
          {{ activeCite.snippet || activeCite.caption }}
        </p>
        <!-- Breadcrumb section (nếu có heading) -->
        <div
          v-if="citationHeadingPath(activeCite.heading_path, activeCite.document).length"
          class="flex items-center gap-1 text-[11px] text-slate-400"
        >
          <FileText class="h-3 w-3 shrink-0" />
          <span class="truncate">{{ citationHeadingPath(activeCite.heading_path, activeCite.document).join(' › ') }}</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.ai-response-markdown {
  --tw-prose-body: var(--foreground);
  --tw-prose-headings: var(--foreground);
  --tw-prose-lead: var(--foreground);
  --tw-prose-links: var(--primary);
  --tw-prose-bold: var(--foreground);
  --tw-prose-counters: var(--foreground);
  --tw-prose-bullets: var(--foreground);
  --tw-prose-quotes: var(--foreground);
  --tw-prose-captions: var(--muted-foreground);
  --tw-prose-kbd: var(--foreground);
  --tw-prose-code: var(--foreground);
  --tw-prose-pre-code: var(--foreground);
}

/* Chip render qua v-html nên scoped CSS cần :deep(). Prose ép img -> block + margin
 * dọc lớn làm chip kéo cao thành viên nang; override về inline để chip gọn. */
.ai-response-markdown :deep(.citation-ref img) {
  display: inline-block;
  margin: 0;
  vertical-align: middle;
}
</style>
