<script setup lang="ts">
import { ref, watch } from 'vue'
import { FileText, X } from '@lucide/vue'
import type { Citation } from '~/types'
import documentService from '~/lib/api/documentService'

const props = defineProps<{ citation: Citation | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const fileUrl = ref<string | null>(null)
const isLoading = ref(false)
const errorMsg = ref<string | null>(null)

watch(
  () => props.citation,
  async (newCitation) => {
    fileUrl.value = null
    errorMsg.value = null
    if (!newCitation || !newCitation.document_id) return

    isLoading.value = true
    try {
      const res = await documentService.getFileUrl(newCitation.document_id)
      
      // Calculate search snippet for highlighting
      let searchSnippet = ''
      if (newCitation.caption) {
        // Lấy khoảng 10-15 từ đầu tiên của caption để search trong PDF, tránh search quá dài PDF.js không nhận diện được
        searchSnippet = newCitation.caption.split(' ').slice(0, 15).join(' ')
      }
      
      let viewerUrl = '/pdfjs/web/viewer.html?file=' + encodeURIComponent(res.url)
      if (newCitation.page_number) {
        viewerUrl += `#page=${newCitation.page_number}`
      }
      if (searchSnippet) {
        viewerUrl += `${newCitation.page_number ? '&' : '#'}search=${encodeURIComponent(searchSnippet)}`
      }
      
      fileUrl.value = viewerUrl
    } catch (err: any) {
      console.error('Failed to get file URL:', err)
      errorMsg.value = 'Failed to load document preview'
    } finally {
      isLoading.value = false
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="flex h-full flex-col bg-slate-50/50">
    <div class="border-b border-slate-200/50 bg-white px-6 py-4 shrink-0">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600">
            <FileText class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <div class="truncate text-sm font-semibold text-slate-900">
              {{ citation?.caption || citation?.document || 'No source selected' }}
            </div>
            <div v-if="citation?.heading_path?.length" class="mt-1 text-xs font-medium text-slate-500">
              {{ citation.heading_path.join(' › ') }}
            </div>
            <div class="mt-1 truncate text-[11px] text-slate-400">
              {{ citation?.document || '—' }}
              <span v-if="citation?.page_number"> • Page {{ citation.page_number }}</span>
            </div>
          </div>
        </div>
        <button class="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-900" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>
    </div>

    <div v-if="citation" class="flex-1 overflow-hidden relative bg-slate-200">
      <div v-if="isLoading" class="absolute inset-0 flex items-center justify-center bg-white/50">
        <div class="text-sm text-slate-500">Loading document...</div>
      </div>
      <div v-else-if="errorMsg" class="absolute inset-0 flex items-center justify-center bg-white">
        <div class="text-sm text-red-500">{{ errorMsg }}</div>
      </div>
      <iframe 
        v-else-if="fileUrl"
        :src="fileUrl" 
        class="w-full h-full border-none"
        title="Document Viewer"
      ></iframe>
      <div v-else class="absolute inset-0 flex items-center justify-center bg-white text-sm text-slate-400">
        Preview not available
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center p-6 text-sm text-slate-400">
      Select a citation from an answer to inspect its metadata.
    </div>
  </div>
</template>
