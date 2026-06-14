import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useSessionStore } from './session'
import type {
  ChatMessage,
  Citation,
  Conversation,
  ConversationHistoryMessage,
  PipelineStage,
  QueryDoneEvent,
  QueryRequest,
  QuerySource,
  QueryTokenEvent,
  TraceEntry,
} from '~/types'
import {
  QueryServiceError,
  assertQueryServiceResponse,
  getQueryServiceAuthHeaders,
  useQueryService,
} from '~/lib/api/queryService'

const HISTORY_KEY = 'eka.chat.conversations'
const CURRENT_CONVERSATION_KEY = 'eka.chat.current-conversation'
const BACKEND_CONVERSATION_ID = 'backend-conversation'

function createConversationId() {
  return 'conversation-' + crypto.randomUUID()
}

function getBucket(date: Date): Conversation['bucket'] {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const diffDays = Math.floor((startOfToday.getTime() - startOfDate.getTime()) / 86400000)

  if (diffDays <= 0) return 'today'
  if (diffDays === 1) return 'yesterday'
  if (diffDays <= 7) return 'previous7'
  return 'older'
}

function createTitle(text: string) {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (!normalized) return 'Untitled chat'
  return normalized.length > 48 ? `${normalized.slice(0, 48)}...` : normalized
}

function sourceDocumentId(source: QuerySource): string {
  const explicitId = source.document_id?.trim()
  if (explicitId) return explicitId

  const uri = source.source_gcs_uri || ''
  const marker = '/raw/'
  const markerIndex = uri.indexOf(marker)
  if (markerIndex < 0) return ''
  return uri.slice(markerIndex + marker.length).split('/')[0] || ''
}

function toCitation(source: QuerySource, id: string): Citation {
  return {
    id,
    document_id: sourceDocumentId(source),
    document: source.document_name,
    caption: source.caption,
    heading_path: source.heading_path,
    page_number: source.page_number,
    ref: source.ref,
  }
}

function toChatMessage(message: ConversationHistoryMessage, index: number): ChatMessage {
  const createdAt = new Date(message.created_at)
  return {
    id: 'history-' + createdAt.getTime() + '-' + index,
    role: message.role,
    content: message.content,
    citations: message.sources?.map((source, sIndex) => toCitation(
      source,
      'history-' + createdAt.getTime() + '-' + index + '-source-' + sIndex,
    )),
    timestamp: Number.isNaN(createdAt.getTime())
      ? message.created_at
      : createdAt.toLocaleString(),
  }
}

function isTokenEvent(value: unknown): value is QueryTokenEvent {
  const ev = value as Partial<QueryTokenEvent & QueryDoneEvent>
  return (
    typeof ev === 'object'
    && ev !== null
    && ev.done !== true
    && (typeof ev.token === 'string' || typeof ev.phase === 'string')
  )
}

function isDoneEvent(value: unknown): value is QueryDoneEvent {
  const event = value as Partial<QueryDoneEvent>
  return typeof value === 'object'
    && value !== null
    && event.done === true
    && typeof event.session_id === 'string'
    && Array.isArray(event.sources)
}

function errorMessage(error: unknown) {
  if (error instanceof QueryServiceError) {
    if (error.status === 401) return 'Your session has expired. Please sign in again.'
    if (error.status === 403) return 'Your user session does not match this request.'
    if (error.status === 422) return 'The question is invalid or exceeds 500 characters.'
    if (error.status === 429) return 'Too many questions were sent. Please wait and try again.'
    if (error.status === 503) return 'The AI service is temporarily unavailable.'
    return error.message
  }
  return 'The answer stream ended before it completed. Please try again.'
}

export const useChatStore = defineStore('chat', () => {
  const queryService = useQueryService()
  const sessionStore = useSessionStore()
  const input = ref('')
  const files = ref<File[]>([])
  const messages = ref<ChatMessage[]>([])
  const conversations = ref<Conversation[]>([])
  const fallbackStorageKey = HISTORY_KEY + '.' + (sessionStore.user?.id || 'anonymous')
  const fallbackConversations = useLocalStorage<Conversation[]>(fallbackStorageKey, [])
  const currentConversationId = useLocalStorage<string | null>(CURRENT_CONVERSATION_KEY, null)
  const isHistoryLoading = ref(false)
  const isHistoryClearing = ref(false)
  const isUsingHistoryFallback = ref(false)
  const pipeline = ref<number>(-1)
  const streamingText = ref('')
  const thinkingStatus = ref('')
  const traceLog = ref<TraceEntry[]>([])
  const panelCitation = ref<Citation | null>(null)
  const isPanelOpen = ref(false)
  let abortController: AbortController | null = null

  function setInput(val: string) {
    input.value = val
  }

  function addFiles(newFiles: File[]) {
    files.value = [...files.value, ...newFiles]
  }

  function removeFile(index: number) {
    files.value = files.value.filter((_, i) => i !== index)
  }

  function handleOpenCitation(citation: Citation) {
    panelCitation.value = citation
    isPanelOpen.value = true
  }

  function handleCloseCitation() {
    isPanelOpen.value = false
    panelCitation.value = null
  }

  function clear() {
    abortController?.abort()
    abortController = null
    currentConversationId.value = null
    messages.value = []
    pipeline.value = -1
    streamingText.value = ''
    traceLog.value = []
    isPanelOpen.value = false
    panelCitation.value = null
    input.value = ''
    files.value = []
  }

  function cacheCurrentConversation() {
    if (!currentConversationId.value || messages.value.length === 0) return

    const updatedAt = new Date()
    const existingIndex = conversations.value.findIndex((c) => c.id === currentConversationId.value)
    const conversation: Conversation = {
      id: currentConversationId.value,
      title: createTitle(messages.value.find((m) => m.role === 'user' && m.content.trim())?.content || ''),
      updatedAt: updatedAt.toISOString(),
      bucket: getBucket(updatedAt),
      messages: [...messages.value],
    }

    if (existingIndex >= 0) {
      conversations.value.splice(existingIndex, 1, conversation)
    } else {
      conversations.value.unshift(conversation)
    }
    conversations.value.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
    fallbackConversations.value = conversations.value.map((item) => ({
      ...item,
      messages: item.messages.map((message) => ({ ...message })),
    }))
  }

  function ensureConversationId() {
    if (!currentConversationId.value) {
      currentConversationId.value = createConversationId()
    }
  }

  function loadConversation(id: string) {
    const conversation = conversations.value.find((c) => c.id === id)
    if (!conversation) return

    abortController?.abort()
    abortController = null
    currentConversationId.value = id
    messages.value = [...conversation.messages]
    pipeline.value = -1
    streamingText.value = ''
    isPanelOpen.value = false
    panelCitation.value = null
    input.value = ''
    files.value = []
  }

  function restoreFallbackHistory() {
    conversations.value = fallbackConversations.value.map((item) => ({
      ...item,
      messages: item.messages.map((message) => ({ ...message })),
    }))

    const conversation = currentConversationId.value
      ? conversations.value.find((item) => item.id === currentConversationId.value)
      : conversations.value[0]

    if (conversation) {
      loadConversation(conversation.id)
      return
    }

    currentConversationId.value = null
  }

  async function syncHistory() {
    if (isHistoryLoading.value) return !isUsingHistoryFallback.value

    isHistoryLoading.value = true
    try {
      const history = await queryService.fetchConversations()
      const syncedMessages = history.messages.map(toChatMessage)

      if (syncedMessages.length === 0) {
        conversations.value = []
        messages.value = []
        currentConversationId.value = null
        fallbackConversations.value = []
      } else {
        const updatedAt = history.messages.at(-1)?.created_at || new Date().toISOString()
        const conversation: Conversation = {
          id: BACKEND_CONVERSATION_ID,
          title: createTitle(syncedMessages.find((message) => message.role === 'user')?.content || ''),
          updatedAt,
          bucket: getBucket(new Date(updatedAt)),
          messages: syncedMessages,
        }
        conversations.value = [conversation]
        messages.value = [...syncedMessages]
        currentConversationId.value = BACKEND_CONVERSATION_ID
        fallbackConversations.value = [{
          ...conversation,
          messages: conversation.messages.map((message) => ({ ...message })),
        }]
      }

      isUsingHistoryFallback.value = false
      return true
    } catch {
      restoreFallbackHistory()
      isUsingHistoryFallback.value = true
      return false
    } finally {
      isHistoryLoading.value = false
    }
  }

  async function clearHistory() {
    if (isHistoryClearing.value) return

    isHistoryClearing.value = true
    try {
      await queryService.clearConversations()
      clear()
      conversations.value = []
      fallbackConversations.value = []
      isUsingHistoryFallback.value = false
    } finally {
      isHistoryClearing.value = false
    }
  }

  function deleteConversation(id: string) {
    conversations.value = conversations.value.filter((c) => c.id !== id)
    fallbackConversations.value = conversations.value.map((item) => ({
      ...item,
      messages: item.messages.map((message) => ({ ...message })),
    }))
    if (currentConversationId.value === id) {
      clear()
    }
  }

  async function renameConversation(id: string, newTitle: string) {
    const title = newTitle.trim()
    if (!title) return

    const conv = conversations.value.find((c) => c.id === id)
    if (!conv) return

    const previousTitle = conv.title
    conv.title = title
    fallbackConversations.value = conversations.value.map((item) => ({
      ...item,
      messages: item.messages.map((message) => ({ ...message })),
    }))

    try {
      await queryService.renameConversation(id, title)
    } catch (error) {
      conv.title = previousTitle
      fallbackConversations.value = conversations.value.map((item) => ({
        ...item,
        messages: item.messages.map((message) => ({ ...message })),
      }))
      throw error
    }
  }

  async function ask(q: string, pipelineStages: PipelineStage[]) {
    const question = q.trim()
    if (!question || pipeline.value >= 0) return

    const userId = sessionStore.user?.id
    if (!userId) {
      messages.value.push({
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: 'Your user session is missing. Please sign in again.',
        error: 'Authentication required',
        timestamp: new Date().toLocaleString(),
      })
      return
    }

    abortController?.abort()
    const controller = new AbortController()
    abortController = controller
    input.value = ''
    files.value = []

    ensureConversationId()
    messages.value.push({
      id: `m-${Date.now()}`,
      role: 'user',
      content: question,
      timestamp: new Date().toLocaleString(),
    })
    cacheCurrentConversation()

    streamingText.value = ''
    thinkingStatus.value = ''
    traceLog.value = []
    pipeline.value = 0
    let fullContent = ''
    let completed = false
    let hasStartedStreaming = false
    let donePayload: QueryDoneEvent | null = null
    const conversationTitle = conversations.value.find(c => c.id === currentConversationId.value)?.title
    const request: QueryRequest = {
      question,
      user_id: String(userId),
      trace_session: currentConversationId.value ?? undefined,
      conversation_title: conversationTitle,
    }

    const PHASE_MAP: Record<string, number> = {
      thinking: 0,
      acting: 1,
      observing: 2,
      generating: 3,
    }

    try {
      await fetchEventSource(`${queryService.baseUrl}/query`, {
        method: 'POST',
        headers: {
          ...getQueryServiceAuthHeaders(),
          'Content-Type': 'application/json',
        },
        signal: controller.signal,
        body: JSON.stringify(request),
        openWhenHidden: true,
        async onopen(response) {
          await assertQueryServiceResponse(response)
          const contentType = response.headers.get('content-type') || ''
          if (!contentType.includes('text/event-stream')) {
            throw new QueryServiceError('Query Service returned a non-stream response', response.status)
          }
        },
        onmessage(message) {
          const payload: unknown = JSON.parse(message.data)
          if (isTokenEvent(payload)) {
            if (payload.token) {
              hasStartedStreaming = true
              fullContent += payload.token
              streamingText.value += payload.token
              pipeline.value = pipelineStages.length
              thinkingStatus.value = ''
            }

            // Once answer tokens start, late phase events must not switch the UI
            // back from the streaming answer to the thinking pipeline.
            if (hasStartedStreaming) return

            // Update thinking status for "AI thinking" display
            if (payload.status) {
              thinkingStatus.value = payload.status
            }
            // Build dynamic trace log from acting/observing events
            if (payload.phase === 'acting' && payload.tool) {
              traceLog.value.push({
                tool: payload.tool,
                args: payload.tool_args ?? {},
                iteration: payload.iterations ?? traceLog.value.length + 1,
                pending: true,
              })
            }
            if (payload.phase === 'observing' && payload.tool) {
              const entry = [...traceLog.value].reverse().find(e => e.tool === payload.tool && e.pending)
              if (entry) {
                entry.resultCount = payload.tool_result_summary?.count
                entry.resultDocs = payload.tool_result_summary?.docs
                entry.resultRaw = payload.tool_result_summary?.raw
                entry.pending = false
              }
            }
            // Update pipeline stage based on phase
            if (payload.phase && PHASE_MAP[payload.phase] !== undefined) {
              pipeline.value = PHASE_MAP[payload.phase]
            }
            return
          }
          if (!isDoneEvent(payload) || completed) return

          completed = true
          donePayload = payload
        },
        onclose() {
          if (!completed && !controller.signal.aborted) {
            throw new Error('Query stream closed before the done event')
          }
        },
        onerror(error) {
          throw error
        },
      })

      if (donePayload) {
        await nextTick()
        const result = donePayload as QueryDoneEvent
        
        // Attempt to extract JSON action from fullContent if it looks like JSON
        let actionPayload: any = undefined
        const trimmedContent = fullContent.trim()
        if (trimmedContent.startsWith('{') && trimmedContent.endsWith('}')) {
          try {
            const parsed = JSON.parse(trimmedContent)
            if (parsed.action_type && parsed.parameters) {
              actionPayload = parsed
            }
          } catch {
            // Not a valid JSON or not an action payload, treat as normal text
          }
        }

        const assistant: ChatMessage = {
          id: 'a-' + Date.now(),
          role: 'assistant',
          content: actionPayload ? '' : fullContent, // Hide raw JSON if it's an action
          action: actionPayload,
          citations: result.sources.map((source, index) => toCitation(
            source,
            result.session_id + '-source-' + index,
          )),
          sessionId: result.session_id,
          traceId: result.trace_id,
          timestamp: new Date().toLocaleString(),
        }
        assistant.fallback = result.fallback === true

        messages.value.push(assistant)
        streamingText.value = ''
        pipeline.value = -1
        cacheCurrentConversation()
        isUsingHistoryFallback.value = false
      }
    } catch (error) {
      if (!controller.signal.aborted && !completed) {
        const message = errorMessage(error)
        messages.value.push({
          id: `err-${Date.now()}`,
          role: 'assistant',
          content: fullContent || message,
          error: message,
          timestamp: new Date().toLocaleString(),
        })
        cacheCurrentConversation()
        isUsingHistoryFallback.value = true
      }
    } finally {
      if (abortController === controller) abortController = null
      streamingText.value = ''
      thinkingStatus.value = ''
      pipeline.value = -1
    }
  }

  async function submitFeedback(messageId: string, score: 1 | -1) {
    const message = messages.value.find((item) => item.id === messageId)
    if (!message?.sessionId || message.feedback === score) return

    const previous = message.feedback
    message.feedback = score
    cacheCurrentConversation()
    try {
      await queryService.submitFeedback(message.sessionId, score, message.traceId)
    } catch (error) {
      message.feedback = previous
      cacheCurrentConversation()
      throw error
    }
  }

  return {
    input,
    files,
    messages,
    conversations,
    currentConversationId,
    isHistoryLoading,
    isHistoryClearing,
    isUsingHistoryFallback,
    pipeline,
    streamingText,
    thinkingStatus,
    traceLog,
    panelCitation,
    isPanelOpen,
    setInput,
    addFiles,
    removeFile,
    handleOpenCitation,
    handleCloseCitation,
    clear,
    loadConversation,
    syncHistory,
    clearHistory,
    deleteConversation,
    renameConversation,
    ask,
    submitFeedback,
  }
})
