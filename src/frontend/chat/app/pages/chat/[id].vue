<script setup lang="ts">
import { AlertTriangle, BookOpen, Database, Search, Wand2 } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { useDebounceFn } from '@vueuse/core'
import { useSessionStore } from '~/stores/session'
import { useChatStore } from '~/stores/chat'
import { cn } from '~/lib/utils'
import SourcePanel from '~/components/SourcePanel.vue'
import ChatMessages from '~/components/chat/ChatMessages.vue'
import ChatInput from '~/components/chat/ChatInput.vue'
import LandingState from '~/components/chat/LandingState.vue'

const PIPELINE_STAGES = [
  { label: 'Searching knowledge base', icon: Search },
  { label: 'Retrieving relevant documents', icon: Database },
  { label: 'Building context', icon: BookOpen },
  { label: 'Generating response', icon: Wand2 },
]

const session = useSessionStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()
const scrollRef = ref<HTMLDivElement | null>(null)
const hasConversation = computed(() => chat.messages.length > 0 || chat.pipeline >= 0)
let scrollRafId: number | null = null

function scrollToBottom(behavior: ScrollBehavior) {
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior })
}

const smoothScrollToBottom = useDebounceFn(() => {
  if (scrollRafId || chat.isHistoryLoading) return
  scrollToBottom('smooth')
}, 16)

function scheduleInstantScroll() {
  if (!import.meta.client) return
  if (scrollRafId) cancelAnimationFrame(scrollRafId)
  scrollRafId = requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      scrollToBottom('auto')
      scrollRafId = null
    })
  })
}

async function submitFeedback(messageId: string, score: 1 | -1) {
  try {
    await chat.submitFeedback(messageId, score)
  } catch {
    toast.error('Could not save feedback. Please try again.')
  }
}

onMounted(async () => {
  ;(window as Window & { __chatReady?: boolean }).__chatReady = true
  if (!session.user) { void router.push('/login'); return }

  const id = route.params.id as string
  const [synced] = await Promise.all([
    chat.syncHistory(),
    chat.loadConversation(id),
  ])
  chat.flushProactiveMessage()
  if (!synced) {
    toast.warning('Không thể tải lịch sử từ server. Đang sử dụng bản lưu tạm trên thiết bị.')
  }
})

// User click conversation khác trong sidebar → URL thay đổi, trang không remount
watch(() => route.params.id, async (newId) => {
  if (!newId) return
  // Bỏ qua nếu ask() vừa navigate đến đây (messages đã có sẵn)
  if (chat.currentConversationId === newId && chat.messages.length > 0) return
  await chat.loadConversation(newId as string)
})

watch(
  () => chat.isHistoryLoading,
  (isLoading) => { if (!isLoading) scheduleInstantScroll() },
  { flush: 'sync' },
)

watch(
  () => chat.currentConversationId,
  () => scheduleInstantScroll(),
  { flush: 'sync' },
)

watch([() => chat.messages.length, () => chat.pipeline, () => chat.streamingText], () => {
  if (chat.isHistoryLoading) { scheduleInstantScroll(); return }
  nextTick(smoothScrollToBottom)
})
</script>

<template>
  <div class="flex h-screen w-full overflow-hidden">
    <div
      :class="cn('relative flex h-full flex-1 flex-col', chat.isPanelOpen && 'lg:pr-[min(40vw,480px)]')"
    >
      <div ref="scrollRef" class="flex-1 overflow-y-auto custom-scrollbar">
        <div class="mx-auto flex min-h-full w-full max-w-[860px] flex-col px-8 pb-32 pt-4">
          <div
            v-if="(chat.isHistoryLoading || chat.isConversationLoading) && !hasConversation"
            class="flex flex-1 flex-col items-center justify-center gap-3 text-slate-400 dark:text-muted-foreground"
          >
            <div class="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-slate-500 dark:border-muted dark:border-t-muted-foreground" />
            <span class="text-sm">Đang tải cuộc trò chuyện...</span>
          </div>
          <div
            v-if="chat.conversationLoadError === 'error'"
            class="mb-4 flex items-center gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800/30 dark:bg-amber-900/10 dark:text-amber-400"
          >
            <AlertTriangle class="h-4 w-4 shrink-0" />
            <span>
              Không tải được toàn bộ cuộc trò chuyện.
              <button
                class="ml-1 cursor-pointer font-medium underline hover:no-underline"
                @click="() => location.reload()"
              >Hãy thử tải lại trang này.</button>
            </span>
          </div>
          <ChatMessages
            v-if="hasConversation"
            :messages="chat.messages"
            :pipeline="chat.pipeline"
            :pipeline-stages="PIPELINE_STAGES"
            :streaming-text="chat.streamingText"
            :thinking-status="chat.thinkingStatus"
            :trace-log="chat.traceLog"
            @open-citation="chat.handleOpenCitation"
            @feedback="submitFeedback"
          />
          <div v-else class="flex flex-1 flex-col items-center justify-center">
            <LandingState />
          </div>
        </div>
      </div>

      <div class="pointer-events-none absolute bottom-0 left-0 right-0 z-20 h-40 bg-gradient-to-t from-background/80 to-transparent" />
      <div class="relative z-30 px-6 pb-6">
        <ChatInput
          :input="chat.input"
          :is-processing="chat.pipeline >= 0"
          @update:input="chat.setInput"
          @send="question => chat.ask(question, PIPELINE_STAGES)"
        />
      </div>
    </div>

    <aside
      :class="cn(
        'fixed inset-y-0 right-0 z-50 h-full w-full border-l border-slate-200 dark:border-border bg-white dark:bg-background transition-transform duration-300 ease-out lg:w-[min(40vw,480px)]',
        chat.isPanelOpen ? 'translate-x-0' : 'translate-x-full',
      )"
    >
      <SourcePanel :citation="chat.panelCitation" @close="chat.handleCloseCitation" />
    </aside>
  </div>
</template>
