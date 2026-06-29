<script setup lang="ts">
import { computed } from 'vue'
import { FileText } from '@lucide/vue'
import type { Citation, HRActionPayload } from '~/types'
import { useChatStore } from '~/stores/chat'
import { truncateFilename } from '~/lib/timeline'

const props = defineProps<{ action: HRActionPayload }>()
const chat = useChatStore()

// Tên file rút gọn GIỮ đuôi (.pdf/.docx…) -> đọc được mà không tràn card; full ở title hover.
const shortName = computed(() => truncateFilename(props.action.document_name, 40))

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
  <!-- Card neutral gọn: nền token + viền mảnh, tên file là tiêu đề + badge "Mới cập nhật",
       dòng phụ mờ, 1 nút primary (Xem tài liệu) + chip secondary đồng nhất. -->
  <div class="proactive-enter max-w-[520px] rounded-2xl border border-slate-200 bg-card p-4 dark:border-white/10">
    <div class="flex items-center gap-3">
      <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-500 dark:bg-white/5 dark:text-muted-foreground">
        <FileText class="h-[18px] w-[18px]" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="truncate text-[15px] font-semibold text-slate-800 dark:text-foreground" :title="action.document_name">{{ shortName }}</span>
          <span class="inline-flex shrink-0 items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300">
            <span class="h-1.5 w-1.5 rounded-full bg-indigo-500" aria-hidden="true" />
            Mới cập nhật
          </span>
        </div>
        <p class="mt-0.5 text-[13.5px] text-slate-500 dark:text-muted-foreground">
          Mình có thể giúp gì với tài liệu này?
        </p>
      </div>
    </div>

    <div class="mt-3.5 flex flex-wrap gap-2">
      <button
        v-if="action.doc_id"
        class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-[13px] font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
        @click="openDocument"
      >
        <FileText class="h-3.5 w-3.5" />
        Xem tài liệu
      </button>
      <button
        v-for="s in action.suggestions"
        :key="s.label"
        class="rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] font-medium text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:border-white/10 dark:text-foreground/90 dark:hover:bg-white/5"
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
