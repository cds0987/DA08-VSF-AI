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
import { citationChipLabel, citationHeadingPath, cn, formatRelevance } from '~/lib/utils'
import type { ChatMessage, Citation } from '~/types'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import ActionableCard from './ActionableCard.vue'
import ApprovalReviewCard from './ApprovalReviewCard.vue'
import ProactiveSuggestionCard from './ProactiveSuggestionCard.vue'

const props = defineProps<{ data: ChatMessage }>()
const emit = defineEmits<{
  (e: 'open-citation', citation: Citation): void
  (e: 'feedback', messageId: string, score: 1 | -1): void
  (e: 'retry', messageId: string): void
}>()

const copied = ref(false)

const hoveredCitation = ref<Citation | null>(null)
const popoverStyle = ref({ top: '0px', left: '0px' })
let hideTimer: ReturnType<typeof setTimeout> | null = null

const md = new MarkdownIt({ html: true, breaks: true, linkify: true })

const renderedContent = computed(() => {
  if (!props.data.content) return ''
  const rawHtml = md.render(props.data.content)
  const esc = (t: string) => t.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))
  const withRefs = rawHtml.replace(/\[(\d+)\]/g, (_, n) => {
    const refN = parseInt(n)
    const c = props.data.citations?.find(x => x.ref === refN) ?? props.data.citations?.[refN - 1]
    if (!c) return ''  // ref LLM bịa (không khớp source) -> bỏ marker khỏi text
    const label = esc(citationChipLabel(c.heading_path, c.document))
    return `<span class="citation-ref cursor-pointer select-none inline-flex items-center gap-1 align-baseline rounded-md bg-slate-100 dark:bg-white/10 px-1.5 py-0.5 mx-0.5 text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-white/20" data-ref="${refN}"><svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v5h5"/></svg>${label}</span>`
  })
  return DOMPurify.sanitize(withRefs, { ADD_ATTR: ['data-ref'] })
})

function handleContentClick(e: MouseEvent) {
  // closest: click có thể trúng <svg>/text con bên trong chip
  const chip = (e.target as HTMLElement).closest('.citation-ref') as HTMLElement | null
  if (!chip) return
  const refN = parseInt(chip.dataset.ref ?? '0')
  const citation = props.data.citations?.find(c => c.ref === refN)
    ?? props.data.citations?.[refN - 1]
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
  const refN = parseInt(chip.dataset.ref ?? '0')
  const citation = props.data.citations?.find(c => c.ref === refN)
    ?? props.data.citations?.[refN - 1]
  if (!citation) return
  const rect = chip.getBoundingClientRect()
  popoverStyle.value = {
    top: `${rect.bottom + window.scrollY + 6}px`,
    left: `${Math.min(rect.left + window.scrollX, window.innerWidth - 308)}px`,
  }
  hoveredCitation.value = citation
}

function handleContentMouseLeave() {
  hideTimer = setTimeout(() => { hoveredCitation.value = null }, 200)
}

function keepPopover() {
  if (hideTimer) { clearTimeout(hideTimer); hideTimer = null }
}

function leavePopover() {
  hideTimer = setTimeout(() => { hoveredCitation.value = null }, 200)
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
        <ActionableCard v-else :action="act" />
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
        v-if="hoveredCitation"
        :style="{ position: 'absolute', zIndex: '9999', width: '300px', top: popoverStyle.top, left: popoverStyle.left }"
        class="rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-card shadow-lg p-3 pointer-events-auto"
        @mouseenter="keepPopover"
        @mouseleave="leavePopover"
      >
        <div class="flex items-center justify-between mb-1.5">
          <span class="text-[10px] font-bold uppercase tracking-widest text-slate-400">Source {{ hoveredCitation.ref }}</span>
          <span
            v-if="formatRelevance(hoveredCitation.score)"
            class="rounded-full bg-blue-50 dark:bg-blue-900/30 px-1.5 py-0.5 text-[10px] font-semibold text-blue-600 dark:text-blue-300"
          >{{ formatRelevance(hoveredCitation.score) }}</span>
        </div>
        <p class="line-clamp-3 text-[12px] font-medium leading-snug text-slate-800 dark:text-foreground mb-1.5">
          {{ hoveredCitation.snippet || hoveredCitation.caption }}
        </p>
        <div class="flex items-center gap-1 text-[11px] text-slate-500 dark:text-muted-foreground">
          <FileText class="h-3 w-3 shrink-0" />
          <span class="truncate font-medium">{{ hoveredCitation.document }}</span>
          <template v-if="citationHeadingPath(hoveredCitation.heading_path, hoveredCitation.document).length">
            <span>›</span>
            <span class="truncate">{{ citationHeadingPath(hoveredCitation.heading_path, hoveredCitation.document).join(' › ') }}</span>
          </template>
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
</style>
