<script setup lang="ts">
import { FileText, ListChecks, Send, ShieldCheck, Sparkles, Zap } from '@lucide/vue'
import { cn } from '~/lib/utils'

interface Props {
  input: string
  isProcessing: boolean
  showQuickActions?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showQuickActions: false,
})
const emit = defineEmits<{
  (e: 'update:input', val: string): void
  (e: 'send', q: string): void
}>()

const isMultiline = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// Chip gợi ý nhanh: bấm vào sẽ điền sẵn câu mở đầu để người dùng chỉnh rồi gửi.
const quickActions = [
  { label: 'Gợi ý nhanh', icon: Zap, prompt: 'Gợi ý cho tôi một vài câu hỏi hữu ích tôi có thể hỏi.' },
  { label: 'Tài liệu gần đây', icon: FileText, prompt: 'Cho tôi xem các tài liệu được cập nhật gần đây.' },
  { label: 'Chính sách', icon: ShieldCheck, prompt: 'Tóm tắt giúp tôi các chính sách nội bộ quan trọng.' },
  { label: 'Quy trình', icon: ListChecks, prompt: 'Hướng dẫn tôi các quy trình thường dùng trong công ty.' },
]

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

function pickQuickAction(prompt: string) {
  emit('update:input', prompt)
  nextTick(() => {
    const textarea = textareaRef.value
    if (!textarea) return
    textarea.focus()
    const len = textarea.value.length
    textarea.setSelectionRange(len, len)
  })
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
      class="flex w-full flex-col gap-3 rounded-3xl border border-slate-200/80 bg-white/95 p-3 shadow-xl shadow-blue-500/5 backdrop-blur-sm transition-colors focus-within:border-blue-400/60 focus-within:ring-4 focus-within:ring-blue-100/70 dark:border-white/10 dark:bg-chat-input dark:shadow-black/20 dark:focus-within:border-blue-500/30 dark:focus-within:ring-blue-900/20"
    >
      <div class="flex items-center gap-2.5">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-50 to-indigo-50 text-blue-500 dark:from-blue-900/30 dark:to-indigo-900/30 dark:text-blue-400"
        >
          <Sparkles class="h-4 w-4" />
        </div>
        <textarea
          ref="textareaRef"
          :value="input"
          @input="handleInput"
          @keydown="handleKeyDown"
          :rows="1"
          maxlength="500"
          placeholder="Hỏi về chính sách, quy trình, kiến thức nội bộ..."
          class="max-h-[200px] min-h-[36px] flex-1 resize-none overflow-hidden self-center bg-transparent py-2 text-[16px] text-slate-800 outline-none placeholder:text-slate-400 dark:text-foreground dark:placeholder:text-chat-placeholder"
        />
        <button
          type="submit"
          :disabled="!input.trim() || isProcessing"
          :class="cn(
            'inline-flex h-10 w-10 shrink-0 items-center justify-center self-end rounded-full transition-[transform,background-color] disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500',
            input.trim() && !isProcessing
              ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/25 hover:bg-blue-500 active:scale-[0.97]'
              : 'bg-slate-100 text-slate-400 dark:bg-white/5 dark:text-muted-foreground/40',
          )"
          aria-label="Gửi"
        >
          <Send class="h-4 w-4" />
        </button>
      </div>

      <div v-if="showQuickActions" class="flex flex-wrap gap-2 pl-0.5">
        <button
          v-for="qa in quickActions"
          :key="qa.label"
          type="button"
          class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 dark:border-white/10 dark:bg-white/5 dark:text-muted-foreground dark:hover:bg-white/10"
          @click="pickQuickAction(qa.prompt)"
        >
          <component :is="qa.icon" class="h-3.5 w-3.5" />
          {{ qa.label }}
        </button>
      </div>
    </form>
    <div class="mt-2 flex items-center justify-center gap-1.5 text-[11px] text-slate-400 dark:text-muted-foreground/60">
      <ShieldCheck class="h-3 w-3" />
      Câu hỏi được giới hạn 500 ký tự. Không hỗ trợ đính kèm tệp.
    </div>
  </div>
</template>
