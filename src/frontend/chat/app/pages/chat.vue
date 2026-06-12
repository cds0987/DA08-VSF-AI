<script setup lang="ts">
import { BookOpen, Database, Search, Wand2 } from '@lucide/vue'
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
const scrollRef = ref<HTMLDivElement | null>(null)
const hasConversation = computed(() => chat.messages.length > 0 || chat.pipeline >= 0)
let requiresInstantScroll = false
let instantScrollScheduled = false

function scrollToBottom(behavior: ScrollBehavior) {
  scrollRef.value?.scrollTo({
    top: scrollRef.value.scrollHeight,
    behavior,
  })
}

const smoothScrollToBottom = useDebounceFn(() => {
  if (requiresInstantScroll || chat.isHistoryLoading) return
  scrollToBottom("smooth")
}, 16)

function markForInstantScroll() {
  requiresInstantScroll = true
}

function scheduleInstantScroll() {
  markForInstantScroll()
  if (!import.meta.client || instantScrollScheduled) return

  instantScrollScheduled = true
  // Double rAF to ensure browser has updated DOM and height is available
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      scrollToBottom("auto")
      // Short delay to wait for any trailing reactive updates
      setTimeout(() => {
        requiresInstantScroll = false
        instantScrollScheduled = false
      }, 50)
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

  if (!session.user) {
    void router.push('/login')
    return
  }

  const synced = await chat.syncHistory()
  if (!synced) {
    toast.warning('Không thể tải lịch sử từ server. Đang sử dụng bản lưu tạm trên thiết bị.')
  }
})

watch(
  () => chat.isHistoryLoading,
  (isLoading) => {
    if (isLoading) {
      markForInstantScroll()
      return
    }

    if (requiresInstantScroll) scheduleInstantScroll()
  },
  { flush: "sync" },
)

watch(
  () => chat.currentConversationId,
  () => scheduleInstantScroll(),
  { flush: "sync" },
)

watch([() => chat.messages.length, () => chat.pipeline, () => chat.streamingText], () => {
  if (requiresInstantScroll || chat.isHistoryLoading) {
    scheduleInstantScroll()
    return
  }

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
