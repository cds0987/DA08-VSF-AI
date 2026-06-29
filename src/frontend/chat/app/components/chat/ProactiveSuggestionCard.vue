<script setup lang="ts">
import { FileText, Sparkles } from '@lucide/vue'
import type { Citation, HRActionPayload } from '~/types'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{ action: HRActionPayload }>()
const chat = useChatStore()

function openDocument() {
  if (!props.action.doc_id) return
  const citation: Citation = {
    id: props.action.doc_id,
    document_id: props.action.doc_id,
    document: props.action.document_name || '',
    caption: '',
    heading_path: [],
  }
  chat.handleOpenCitation(citation)
}
</script>

<template>
  <!-- Card gợi ý chủ động: tự chứa (icon + nhãn + tên tài liệu + chips) -> đứng riêng, rõ là
       nhắc cập nhật tài liệu chứ không phải câu trả lời thường. -->
  <div class="proactive-enter max-w-[640px] rounded-2xl border border-indigo-200/70 bg-indigo-50/60 p-4 dark:border-indigo-400/20 dark:bg-indigo-500/10">
    <div class="flex items-start gap-3">
      <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300">
        <Sparkles class="h-[18px] w-[18px]" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-[12px] font-semibold uppercase tracking-wide text-indigo-600 dark:text-indigo-300">
          Tài liệu vừa cập nhật
        </p>
        <p class="mt-0.5 text-[15px] font-medium leading-relaxed text-slate-800 dark:text-foreground [overflow-wrap:anywhere]">
          <span class="font-semibold">{{ action.document_name }}</span> — mình có thể giúp gì cho bạn?
        </p>
      </div>
    </div>

    <div class="mt-3 flex flex-wrap gap-2 pl-12">
      <button
        v-if="action.doc_id"
        class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:border-white/10 dark:bg-card dark:text-foreground dark:hover:bg-white/5"
        @click="openDocument"
      >
        <FileText class="h-3.5 w-3.5" />
        Xem tài liệu
      </button>
      <button
        v-for="s in action.suggestions"
        :key="s.label"
        class="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:border-indigo-400/20 dark:bg-indigo-900/20 dark:text-indigo-300 dark:hover:bg-indigo-900/40"
        @click="chat.ask(s.query, [], action.doc_id ? [action.doc_id] : undefined)"
      >
        {{ s.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Vào mềm khi card được chèn (từ chuông thông báo) -> người dùng nhận ra ngay. */
@keyframes proactive-enter {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.proactive-enter { animation: proactive-enter 280ms ease-out both; }
@media (prefers-reduced-motion: reduce) {
  .proactive-enter { animation: none; }
}
</style>
