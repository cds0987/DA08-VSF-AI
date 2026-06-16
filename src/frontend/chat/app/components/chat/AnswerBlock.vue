<script setup lang="ts">
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  FileText,
  ThumbsDown,
  ThumbsUp,
} from '@lucide/vue'
import { citationHeadingPath, cn, formatRelevance } from '~/lib/utils'
import type { ChatMessage, Citation } from '~/types'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import ActionableCard from './ActionableCard.vue'
import ApprovalReviewCard from './ApprovalReviewCard.vue'

const props = defineProps<{ data: ChatMessage }>()
const emit = defineEmits<{
  (e: 'open-citation', citation: Citation): void
  (e: 'feedback', messageId: string, score: 1 | -1): void
}>()

const copied = ref(false)
const isSourcesOpen = ref(false)
const selectedSourceId = ref<string | null>(null)

const md = new MarkdownIt({ html: true, breaks: true, linkify: true })

const renderedContent = computed(() => {
  if (!props.data.content) return ''
  const rawHtml = md.render(props.data.content)
  const withRefs = rawHtml.replace(
    /\[(\d+)\]/g,
    (_, n) => `<sup class="citation-ref cursor-pointer select-none rounded bg-blue-100 dark:bg-blue-900/40 px-0.5 text-[10px] font-bold text-blue-600 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-800/60" data-ref="${n}">[${n}]</sup>`,
  )
  return DOMPurify.sanitize(withRefs, { ADD_ATTR: ['data-ref'] })
})

function handleContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target.classList.contains('citation-ref')) {
    const refN = parseInt(target.dataset.ref ?? '0')
    const citation = props.data.citations?.find(c => c.ref === refN)
      ?? props.data.citations?.[refN - 1]
    if (citation) {
      isSourcesOpen.value = true
      selectSource(citation)
    }
  }
}

function copyToClipboard() {
  if (!props.data.content) return
  void navigator.clipboard.writeText(props.data.content)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}

function selectSource(citation: Citation) {
  selectedSourceId.value = citation.id
  emit('open-citation', citation)
}
</script>

<template>
  <div class="overflow-hidden rounded-2xl bg-transparent">
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
      />
      <template v-for="(act, i) in data.actions" :key="act.idempotency_key || i">
        <ApprovalReviewCard v-if="act.action_type === 'review_leave_approvals'" />
        <ActionableCard v-else :action="act" />
      </template>
    </div>

    <div v-if="data.citations?.length" class="border-t border-slate-100 dark:border-white/5 bg-slate-50/20 dark:bg-background/10">
      <button
        class="flex w-full items-center justify-between px-5 py-3 text-[12.5px] font-medium text-slate-800 dark:text-foreground/80 hover:bg-slate-100/80 dark:hover:bg-white/5"
        @click="isSourcesOpen = !isSourcesOpen"
      >
        <span class="inline-flex items-center gap-2">
          <ChevronRight :class="cn('h-3.5 w-3.5 text-slate-400 dark:text-muted-foreground transition-transform', isSourcesOpen && 'rotate-90')" />
          {{ data.citations.length }} Sources
        </span>
        <span class="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-muted-foreground">Transparency</span>
      </button>
      <div v-if="isSourcesOpen" class="grid gap-2 border-t border-slate-100 dark:border-white/5 bg-slate-50/40 dark:bg-background/40 p-3 sm:grid-cols-2">
        <button
          v-for="(citation, index) in data.citations"
          :key="citation.id"
          :class="cn(
            'rounded-xl border p-3 text-left transition-colors',
            selectedSourceId === citation.id ? 'border-blue-200 dark:border-blue-900 bg-blue-50/80 dark:bg-blue-900/20' : 'border-slate-200 dark:border-white/10 bg-white dark:bg-card hover:border-slate-300 dark:hover:border-white/20',
          )"
          @click="selectSource(citation)"
        >
          <div class="flex items-start gap-2">
            <div class="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-900 dark:text-foreground">
              {{ citation.ref ?? (index + 1) }}. {{ citation.caption || citation.document }}
            </div>
            <span
              v-if="formatRelevance(citation.score)"
              class="shrink-0 rounded-full bg-blue-50 dark:bg-blue-900/30 px-1.5 py-0.5 text-[10px] font-semibold text-blue-600 dark:text-blue-300"
              title="Độ liên quan"
            >
              {{ formatRelevance(citation.score) }}
            </span>
          </div>
          <div class="mt-1 flex items-center gap-1 truncate text-[11px] font-medium text-slate-700 dark:text-muted-foreground">
            <FileText class="h-3 w-3 shrink-0 text-slate-400 dark:text-muted-foreground/70" />
            <span class="truncate">{{ citation.document }}</span>
          </div>
          <div v-if="citationHeadingPath(citation.heading_path, citation.document).length" class="mt-1 truncate text-[11px] font-medium text-slate-600 dark:text-muted-foreground/70">
            {{ citationHeadingPath(citation.heading_path, citation.document).join(' › ') }}
          </div>
          <p v-if="citation.snippet" class="mt-1.5 line-clamp-2 border-l-2 border-slate-200 dark:border-white/10 pl-2 text-[11px] italic leading-snug text-slate-500 dark:text-muted-foreground/80">
            {{ citation.snippet }}
          </p>
        </button>
      </div>
    </div>

    <div class="flex items-center gap-1 px-5 py-2">
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
