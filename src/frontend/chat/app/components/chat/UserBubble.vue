<script setup lang="ts">
import { File, FileText } from '@lucide/vue'
import type { MessageAttachment } from '~/types'

defineProps<{
  text: string
  attachments?: MessageAttachment[]
}>()

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
    <div class="max-w-[80%] rounded-2xl rounded-br-sm border border-blue-200/50 bg-blue-500/10 px-4 py-3 text-[14px] text-slate-800 shadow-sm flex flex-col gap-3">
      <!-- Attachments -->
      <div v-if="attachments && attachments.length > 0" class="flex flex-col gap-2">
        <div 
          v-for="(file, i) in attachments" 
          :key="i"
          class="flex items-center gap-3 p-2 rounded-lg bg-white/50 border border-blue-100/50"
        >
          <!-- Image Preview -->
          <div v-if="file.type.startsWith('image/')" class="h-10 w-10 rounded border border-slate-200 overflow-hidden shrink-0 bg-white">
            <img 
              v-if="file.url"
              :src="file.url" 
              class="h-full w-full object-cover" 
              alt="attachment" 
            />
          </div>
          
          <!-- File Icon -->
          <div v-else class="h-10 w-10 rounded bg-blue-100 flex items-center justify-center shrink-0">
            <FileText v-if="file.type.includes('pdf')" class="h-5 w-5 text-blue-600" />
            <File v-else class="h-5 w-5 text-blue-600" />
          </div>

          <!-- File Info -->
          <div class="flex flex-col min-w-0">
            <span class="text-[12px] font-medium text-slate-700 truncate [overflow-wrap:anywhere] [word-break:break-all]">
              {{ file.name }}
            </span>
            <span class="text-[10px] text-slate-500">{{ formatSize(file.size) }}</span>
          </div>
        </div>
      </div>

      <!-- Text Content -->
      <div v-if="text" class="whitespace-pre-wrap [overflow-wrap:anywhere] [word-break:break-word]">
        {{ text }}
      </div>
    </div>
  </div>
</template>
