<script setup lang="ts">
import { computed } from 'vue'
import { File, FileText } from '@lucide/vue'
import type { MessageAttachment } from '~/types'

const props = defineProps<{
  text: string
  attachments?: MessageAttachment[]
}>()

// Tin nhắn trích dẫn (reply): buildQuotedContent gắn đoạn bot đang trả lời thành blockquote
// "> ..." ở ĐẦU content (vẫn gửi BE để có ngữ cảnh). Tách ra -> hiện thành KHỐI trích dẫn riêng
// phía trên câu hỏi, không lẫn dấu ">" vào câu hỏi. Chạy cho cả tin mới lẫn tin load lại.
const parsed = computed(() => {
  const lines = props.text.split('\n')
  let i = 0
  const quoted: string[] = []
  while (i < lines.length && lines[i].startsWith('>')) {
    quoted.push(lines[i].replace(/^>\s?/, ''))
    i++
  }
  if (!quoted.length) return { quote: '', body: props.text }
  while (i < lines.length && lines[i].trim() === '') i++ // bỏ dòng trống ngăn cách
  return { quote: quoted.join('\n').trim(), body: lines.slice(i).join('\n') }
})

const formatSize = (bytes: number) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}
</script>

<template>
  <div class="flex flex-col items-end gap-2">
    <div class="max-w-[80%] rounded-2xl rounded-br-sm border border-blue-200/50 dark:border-white/5 bg-blue-500/10 dark:bg-chat-user px-4 py-3 text-[16px] font-medium leading-relaxed text-slate-900 dark:text-chat-user-foreground shadow-sm flex flex-col gap-3">
      <!-- Attachments -->
      <div v-if="attachments && attachments.length > 0" class="flex flex-col gap-2">
        <div 
          v-for="(file, i) in attachments" 
          :key="i"
          class="flex items-center gap-3 p-2 rounded-lg bg-white/50 dark:bg-background/50 border border-blue-100/50 dark:border-white/5"
        >
          <!-- Image Preview -->
          <div v-if="file.type.startsWith('image/')" class="h-10 w-10 rounded border border-slate-200 dark:border-white/10 overflow-hidden shrink-0 bg-white dark:bg-background">
            <img 
              v-if="file.url"
              :src="file.url" 
              class="h-full w-full object-cover" 
              alt="attachment" 
            />
          </div>
          
          <!-- File Icon -->
          <div v-else class="h-10 w-10 rounded bg-blue-100 dark:bg-white/5 flex items-center justify-center shrink-0">
            <FileText v-if="file.type.includes('pdf')" class="h-5 w-5 text-blue-600 dark:text-muted-foreground" />
            <File v-else class="h-5 w-5 text-blue-600 dark:text-muted-foreground" />
          </div>

          <!-- File Info -->
          <div class="flex flex-col min-w-0">
            <span class="text-[12px] font-medium text-slate-700 dark:text-foreground/90 truncate [overflow-wrap:anywhere] [word-break:break-all]">
              {{ file.name }}
            </span>
            <span class="text-[10px] font-medium text-slate-500 dark:text-muted-foreground">{{ formatSize(file.size) }}</span>
          </div>
        </div>
      </div>

      <!-- Trích dẫn: đoạn bot đang được trả lời — khối riêng (viền trái, mờ, cắt 3 dòng) -->
      <div
        v-if="parsed.quote"
        class="border-l-2 border-blue-400/60 dark:border-white/20 pl-2.5 text-[13px] leading-snug text-slate-600 dark:text-chat-user-foreground/60 line-clamp-3 whitespace-pre-wrap [overflow-wrap:anywhere]"
      >
        {{ parsed.quote }}
      </div>

      <!-- Câu hỏi của người dùng -->
      <div v-if="parsed.body" class="whitespace-pre-wrap [overflow-wrap:anywhere] [word-break:break-word]">
        {{ parsed.body }}
      </div>
    </div>
  </div>
</template>
