<script setup lang="ts">
import { computed } from 'vue'
import { Sparkles } from '@lucide/vue'
import { useAnswerSelection } from '~/composables/useAnswerSelection'

const emit = defineEmits<{
  (e: 'ask', payload: { messageId: string | null; text: string }): void
}>()

const { visible, rect, selectedText, messageId, hide } = useAnswerSelection()

const style = computed(() => {
  const r = rect.value
  if (!r) return {}
  return { top: `${r.top - 8}px`, left: `${r.left + r.width / 2}px` }
})

function onAsk() {
  emit('ask', { messageId: messageId.value, text: selectedText.value })
  window.getSelection()?.removeAllRanges()
  hide()
}
</script>

<template>
  <Teleport to="body">
    <button
      v-if="visible"
      type="button"
      :style="style"
      class="selection-ask-btn fixed z-[60] -translate-x-1/2 -translate-y-full inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-lg shadow-black/10 transition-opacity hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:border-white/10 dark:bg-zinc-800 dark:text-foreground dark:hover:bg-zinc-700"
      @mousedown.prevent
      @click="onAsk"
    >
      <Sparkles class="h-3.5 w-3.5 text-blue-500" />
      Hỏi FeatureMind
    </button>
  </Teleport>
</template>

<style scoped>
@media (prefers-reduced-motion: reduce) {
  .selection-ask-btn { transition: none; }
}
</style>
