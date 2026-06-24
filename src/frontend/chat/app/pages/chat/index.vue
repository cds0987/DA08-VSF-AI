<script setup lang="ts">
import { AlertTriangle, BookOpen, Database, Search, Wand2 } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { useChatAutoScroll } from '~/composables/useChatAutoScroll'
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
const hasConversation = computed(() => chat.messages.length > 0 || chat.pipeline >= 0)
const { scrollRef, scheduleAutoScroll, scheduleInstantScroll } = useChatAutoScroll(
  computed(() => chat.isHistoryLoading),
)

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

  chat.clear()
  await chat.syncHistory()
  chat.flushProactiveMessage()
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
  nextTick(() => scheduleAutoScroll())
})

function handleSend(question: string) {
  chat.ask(question, PIPELINE_STAGES)
  scheduleInstantScroll()
}
</script>

<template>
  <div class="flex h-dvh w-full overflow-hidden">
    <div
      :class="cn('relative flex h-full flex-1 flex-col', chat.isPanelOpen && 'lg:pr-[min(40vw,480px)]')"
    >
      <div ref="scrollRef" class="flex-1 overflow-y-auto custom-scrollbar">
        <div class="mx-auto flex min-h-full w-full max-w-[860px] flex-col px-4 pb-32 pt-4 sm:px-6 lg:px-8">
          <div
            v-if="chat.isHistoryLoading && !hasConversation"
            class="flex flex-1 flex-col items-center justify-center gap-3 text-slate-400 dark:text-muted-foreground"
          >
            <div class="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-slate-500 dark:border-muted dark:border-t-muted-foreground" />
            <span class="text-sm">Đang tải lịch sử...</span>
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
            :streaming-turn-key="chat.pendingAssistantId"
            :thinking-status="chat.thinkingStatus"
            :trace-log="chat.traceLog"
            :models-used="chat.modelsUsed"
            :thoughts="chat.thoughts"
            :plan="chat.plan"
            @open-citation="chat.handleOpenCitation"
            @feedback="submitFeedback"
            @retry="messageId => chat.retryMessage(messageId, PIPELINE_STAGES)"
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
          :show-quick-actions="!hasConversation"
          @update:input="chat.setInput"
          @send="handleSend"
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
