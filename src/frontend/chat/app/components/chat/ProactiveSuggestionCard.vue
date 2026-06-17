<script setup lang="ts">
import { FileText } from '@lucide/vue'
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
  <div class="mt-3 flex flex-wrap gap-2">
    <button
      v-if="action.doc_id"
      class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white dark:bg-card dark:border-white/10 px-3 py-1.5 text-sm font-medium text-slate-700 dark:text-foreground hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
      @click="openDocument"
    >
      <FileText class="h-3.5 w-3.5" />
      Xem tài liệu
    </button>
    <button
      v-for="s in action.suggestions"
      :key="s.label"
      class="rounded-lg border border-indigo-200 bg-indigo-50 dark:bg-indigo-900/20 px-3 py-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/40 transition-colors"
      @click="chat.ask(s.query, [], action.doc_id ? [action.doc_id] : undefined)"
    >
      {{ s.label }}
    </button>
  </div>
</template>
