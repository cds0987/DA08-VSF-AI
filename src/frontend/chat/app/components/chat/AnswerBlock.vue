<script setup lang="ts">
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  ThumbsDown,
  ThumbsUp,
} from '@lucide/vue'
import { cn } from '~/lib/utils'
import type { ChatMessage, Citation } from '~/types'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import ActionableCard from './ActionableCard.vue'

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
  return DOMPurify.sanitize(rawHtml)
})

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
  <div class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div
      v-if="data.error"
      class="flex items-start gap-2 border-b border-rose-100 bg-rose-50/60 px-5 py-3 text-[12.5px] text-rose-700"
    >
      <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
      {{ data.error }}
    </div>

    <div class="px-5 pb-5 pt-4 text-slate-800">
      <div 
        v-if="data.content"
        class="prose prose-sm prose-slate max-w-none prose-p:leading-relaxed prose-pre:bg-slate-50 prose-pre:text-slate-800 prose-pre:border prose-pre:border-slate-200 [overflow-wrap:anywhere]"
        v-html="renderedContent"
      />
      <ActionableCard v-if="data.action" :action="data.action" />
    </div>

    <div v-if="data.citations?.length" class="border-t border-slate-100">
      <button
        class="flex w-full items-center justify-between px-5 py-3 text-[12.5px] font-medium text-slate-600 hover:bg-slate-100/80"
        @click="isSourcesOpen = !isSourcesOpen"
      >
        <span class="inline-flex items-center gap-2">
          <ChevronRight :class="cn('h-3.5 w-3.5 text-slate-400 transition-transform', isSourcesOpen && 'rotate-90')" />
          {{ data.citations.length }} Sources
        </span>
        <span class="text-[10px] font-bold uppercase tracking-widest text-slate-400">Transparency</span>
      </button>
      <div v-if="isSourcesOpen" class="grid gap-2 border-t border-slate-100 bg-slate-50/40 p-3 sm:grid-cols-2">
        <button
          v-for="(citation, index) in data.citations"
          :key="citation.id"
          :class="cn(
            'rounded-xl border p-3 text-left transition-colors',
            selectedSourceId === citation.id ? 'border-blue-200 bg-blue-50/80' : 'border-slate-200 bg-white hover:border-slate-300',
          )"
          @click="selectSource(citation)"
        >
          <div class="truncate text-[13px] font-semibold text-slate-900">
            {{ index + 1 }}. {{ citation.caption || citation.document }}
          </div>
          <div class="mt-1 truncate text-[11px] font-medium text-slate-500">
            {{ citation.document }}
          </div>
          <div v-if="citation.heading_path.length" class="mt-1 truncate text-[11px] text-slate-400">
            {{ citation.heading_path.join(' › ') }}
          </div>
        </button>
      </div>
    </div>

    <div class="flex items-center justify-between border-t border-slate-100 bg-slate-50/30 px-5 py-2.5">
      <div class="flex items-center gap-2">
        <button
          :disabled="!data.sessionId"
          :class="cn('rounded-md p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-40', data.feedback === 1 && 'bg-emerald-50 text-emerald-600')"
          title="Helpful"
          @click="emit('feedback', data.id, 1)"
        >
          <ThumbsUp class="h-4 w-4" />
        </button>
        <button
          :disabled="!data.sessionId"
          :class="cn('rounded-md p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-40', data.feedback === -1 && 'bg-rose-50 text-rose-600')"
          title="Not helpful"
          @click="emit('feedback', data.id, -1)"
        >
          <ThumbsDown class="h-4 w-4" />
        </button>
      </div>
      <button class="rounded-md p-2 text-slate-500 hover:bg-slate-100" @click="copyToClipboard">
        <Check v-if="copied" class="h-4 w-4 text-emerald-600" />
        <Copy v-else class="h-4 w-4" />
      </button>
    </div>
  </div>
</template>
