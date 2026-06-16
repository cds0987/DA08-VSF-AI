<script setup lang="ts">
import { Send } from '@lucide/vue'
import { cn } from '~/lib/utils'

interface Props {
  input: string
  isProcessing: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:input', val: string): void
  (e: 'send', q: string): void
}>()

const isMultiline = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function handleInput(event: Event) {
  const value = (event.target as HTMLTextAreaElement).value
  emit('update:input', value)
}

function sendMessage() {
  if (!props.input.trim() || props.isProcessing) return
  emit('send', props.input)
}

function handleKeyDown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

function adjustHeight() {
  const textarea = textareaRef.value
  if (!textarea) return
  textarea.style.height = '0px'                        // reset về 0 để scrollHeight co lại đúng
  const next = textarea.scrollHeight
  textarea.style.height = `${next}px`
  isMultiline.value = next > 44
}

watch(() => props.input, (value) => {
  if (!value) {
    // input bị clear (sau khi send) — reset hoàn toàn
    const textarea = textareaRef.value
    if (!textarea) return
    textarea.style.height = ''
    isMultiline.value = false
    return
  }
  requestAnimationFrame(adjustHeight)
})
</script>

<template>
  <div class="mx-auto max-w-[860px]">
    <form
      @submit.prevent="sendMessage"
      :class="cn(
        'flex w-full rounded-2xl border border-slate-200 dark:border-white/5 bg-white dark:bg-chat-input shadow-lg focus-within:border-blue-400/50 dark:focus-within:border-blue-500/30 focus-within:ring-2 focus-within:ring-blue-100 dark:focus-within:ring-blue-900/20',
        isMultiline ? 'flex-col' : 'flex-row items-center gap-2 p-2',
      )"
    >
      <textarea
        ref="textareaRef"
        :value="input"
        @input="handleInput"
        @keydown="handleKeyDown"
        :rows="1"
        maxlength="500"
        placeholder="Ask a question about FeatureMind policies, procedures, or knowledge..."
        :class="cn(
          'max-h-[200px] w-full resize-none overflow-hidden bg-transparent text-[16px] text-slate-800 dark:text-foreground outline-none placeholder:text-slate-400 dark:placeholder:text-chat-placeholder',
          isMultiline ? 'min-h-[60px] px-4 pb-2 pt-4' : 'min-h-[36px] flex-1 px-3 py-2',
        )"
      />
      <div :class="cn(isMultiline && 'flex justify-end border-t border-slate-50 dark:border-white/5 p-2')">
        <button
          type="submit"
          :disabled="!input.trim() || isProcessing"
          :class="cn(
            'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full disabled:cursor-not-allowed',
            input.trim() && !isProcessing
              ? 'bg-purple-600 dark:bg-blue-600 text-white shadow-lg shadow-purple-500/20 dark:shadow-blue-500/10 hover:bg-purple-700 dark:hover:bg-blue-500'
              : 'bg-slate-200 dark:bg-white/5 text-slate-400 dark:text-muted-foreground/40',
          )"
          aria-label="Send"
        >
          <Send class="h-4 w-4" />
        </button>
      </div>
    </form>
    <div class="mt-2 text-center text-[11px] text-slate-400 dark:text-muted-foreground/60">
      Questions are limited to 500 characters. File attachments are not supported.
    </div>
  </div>
</template>
