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

function createConversationId() {
  return crypto.randomUUID()
}

const LEAVE_TYPE_LABEL: Record<string, string> = {
  annual: 'phép năm',
  personal: 'việc riêng',
  marriage: 'kết hôn',
  child_marriage: 'con kết hôn',
  bereavement: 'tang lễ',
  sick: 'nghỉ ốm',
  maternity: 'thai sản',
  unpaid: 'không lương',
}

function newIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

// Tách action JSON ra khỏi content thô của trợ lý. Dùng CHUNG cho cả luồng stream
// (lần đầu) lẫn rehydrate từ lịch sử (toChatMessage) -> reload không bị lòi raw JSON.
// Hỗ trợ NHIỀU đơn 1 lượt: model xuất {action_type, items:[{...},...]} -> mỗi item là
// 1 form riêng. Vẫn nhận format cũ {action_type, parameters:{...}} (1 đơn).
// Trả { actions, content }: actions = danh sách payload; content = câu dẫn nhập.
function extractAction(rawContent: string): { actions?: any[]; content: string } {
  const trimmed = (rawContent || '').trim()
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed)
      // Thẻ duyệt: không cần items/parameters — FE tự nạp hàng đợi live.
      if (parsed.action_type === 'review_leave_approvals') {
        const actions = [{ action_type: 'review_leave_approvals', idempotency_key: newIdempotencyKey() }]
        return { actions, content: buildActionIntro(actions) }
      }
      if (parsed.action_type) {
        const rawItems: any[] = Array.isArray(parsed.items)
          ? parsed.items
          : (parsed.parameters ? [parsed.parameters] : [])
        if (rawItems.length) {
          // Mỗi đơn 1 idempotency_key riêng (sinh 1 lần lúc dựng card) -> bấm Confirm
          // nhiều lần / nhiều đơn không tạo trùng nhau.
          const actions = rawItems.map(p => ({
            action_type: parsed.action_type,
            parameters: p,
            idempotency_key: newIdempotencyKey(),
          }))
          return { actions, content: buildActionIntro(actions) }
        }
      }
    } catch {
      // Không phải JSON hợp lệ / không phải action -> coi như text thường.
    }
  }
  return { content: rawContent }
}

function describeLeave(p: any): string {
  const typeLabel = LEAVE_TYPE_LABEL[p?.leave_type] || p?.leave_type || ''
  const range = p?.start_date === p?.end_date
    ? `ngày ${p?.start_date}`
    : `từ ${p?.start_date} đến ${p?.end_date}`
  return `nghỉ ${typeLabel} ${range}`.trim()
}

// Model chỉ trả PURE JSON cho action -> dựng câu dẫn nhập tiếng Việt thân thiện hiển
// thị phía trên (các) form xác nhận. 1 đơn -> 1 câu; nhiều đơn -> liệt kê.
function buildActionIntro(actions: { action_type?: string; parameters?: any }[]): string {
  if (actions.some(a => a.action_type === 'review_leave_approvals')) {
    return 'Đây là các đơn đang chờ bạn duyệt. Bạn xem rồi bấm **Duyệt** hoặc **Từ chối** cho từng đơn nhé.'
  }
  const leaves = actions.filter(a => a.action_type === 'create_leave_request')
  if (leaves.length === 1) {
    return `Mình đã chuẩn bị đơn ${describeLeave(leaves[0].parameters)}. Bạn kiểm tra, chỉnh sửa nếu cần rồi bấm **Xác nhận & Gửi** nhé.`
  }
  if (leaves.length > 1) {
    const lines = leaves.map((a, i) => `${i + 1}. ${describeLeave(a.parameters)}`).join('\n')
    return `Mình đã chuẩn bị ${leaves.length} đơn nghỉ:\n${lines}\n\nBạn kiểm tra từng đơn, chỉnh sửa nếu cần rồi bấm **Xác nhận & Gửi** cho mỗi đơn nhé.`
  }
  return 'Mình đã chuẩn bị thông tin bên dưới, bạn kiểm tra rồi xác nhận giúp mình nhé.'
}

function isConversationId(value: string | null | undefined) {
  return Boolean(value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value))
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

function toChatMessage(message: ConversationHistoryMessage): ChatMessage {
  const createdAt = new Date(message.created_at)
  // Trợ lý có thể đã lưu raw JSON action -> parse lại để render form khi reload lịch sử.
  const extracted = message.role === 'assistant'
    ? extractAction(message.content)
    : { content: message.content, actions: undefined as any }
  return {
    id: message.id,
    role: message.role,
    content: extracted.content,
    actions: extracted.actions,
    citations: message.sources?.map((source, index) => toCitation(
      source,
      message.id + '-source-' + index,
    )),
    sessionId: message.session_id || undefined,
    feedback: message.feedback || undefined,
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
  const storageSuffix = sessionStore.user?.id || 'anonymous'
  const fallbackStorageKey = HISTORY_KEY + '.' + storageSuffix
  const fallbackConversations = useLocalStorage<Conversation[]>(fallbackStorageKey, [])
  const currentConversationId = useLocalStorage<string | null>(
    CURRENT_CONVERSATION_KEY + '.' + storageSuffix,
    null,
  )
  const isHistoryLoading = ref(false)
  const isHistoryClearing = ref(false)
  const isUsingHistoryFallback = ref(false)
  const pipeline = ref<number>(-1)
  const streamingText = ref('')
  const thinkingStatus = ref('')
  const traceLog = ref<TraceEntry[]>([])
  const panelCitation = ref<Citation | null>(null)
  const isPanelOpen = ref(false)
  const pendingProactiveDoc = ref<{ name: string; docId: string | null } | null>(null)
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
      title: existingIndex >= 0
        ? conversations.value[existingIndex].title
        : createTitle(messages.value.find((m) => m.role === 'user' && m.content.trim())?.content || ''),
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

  function persistFallbackHistory() {
    fallbackConversations.value = conversations.value.map((item) => ({
      ...item,
      messages: item.messages.map((message) => ({ ...message })),
    }))
  }

  function activateConversation(conversation: Conversation) {
    abortController?.abort()
    abortController = null
    currentConversationId.value = conversation.id
    messages.value = [...conversation.messages]
    pipeline.value = -1
    streamingText.value = ''
    isPanelOpen.value = false
    panelCitation.value = null
    input.value = ''
    files.value = []
  }

  async function loadConversation(id: string) {
    const conversation = conversations.value.find((item) => item.id === id)
    if (!conversation) return false

    activateConversation(conversation)
    try {
      const detail = await queryService.fetchConversation(id)
      const updatedAt = detail.updated_at
      const synced: Conversation = {
        id: detail.id,
        title: detail.title,
        updatedAt,
        bucket: getBucket(new Date(updatedAt)),
        messages: detail.messages.map(toChatMessage),
      }
      const index = conversations.value.findIndex((item) => item.id === id)
      if (index >= 0) conversations.value.splice(index, 1, synced)
      if (currentConversationId.value === id) activateConversation(synced)
      persistFallbackHistory()
      isUsingHistoryFallback.value = false
      return true
    } catch {
      isUsingHistoryFallback.value = true
      return false
    }
  }

  function restoreFallbackHistory() {
    const stored = fallbackConversations.value
    const selectedIndex = currentConversationId.value
      ? stored.findIndex((item) => item.id === currentConversationId.value)
      : -1
    conversations.value = stored.map((item) => ({
      ...item,
      id: isConversationId(item.id) ? item.id : createConversationId(),
      messages: item.messages.map((message) => ({ ...message })),
    }))

    const conversation = selectedIndex >= 0
      ? conversations.value[selectedIndex]
      : conversations.value.find((item) => item.id === currentConversationId.value) || conversations.value[0]

    if (conversation) {
      activateConversation(conversation)
      persistFallbackHistory()
      return
    }

    currentConversationId.value = null
    messages.value = []
  }

  async function fetchAllConversations() {
    const pageSize = 100
    const items = []
    for (let offset = 0; ; offset += pageSize) {
      const page = await queryService.fetchConversations(pageSize, offset)
      items.push(...page.conversations)
      if (page.conversations.length < pageSize) return items
    }
  }

  async function syncHistory() {
    if (isHistoryLoading.value) return !isUsingHistoryFallback.value

    isHistoryLoading.value = true
    try {
      const history = await fetchAllConversations()
      const cachedById = new Map(
        fallbackConversations.value.map((conversation) => [conversation.id, conversation]),
      )
      const serverIds = new Set(history.map((item) => item.id))
      const serverConversations = history.map((item) => ({
        id: item.id,
        title: item.title,
        updatedAt: item.updated_at,
        bucket: getBucket(new Date(item.updated_at)),
        messages: cachedById.get(item.id)?.messages.map((message) => ({ ...message })) || [],
      }))
      const localOnly = fallbackConversations.value
        .filter((item) => !serverIds.has(item.id) && item.messages.length > 0)
        .map((item) => ({
          ...item,
          id: isConversationId(item.id) ? item.id : createConversationId(),
          messages: item.messages.map((message) => ({ ...message })),
        }))
      conversations.value = [...serverConversations, ...localOnly]
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())

      if (conversations.value.length === 0) {
        messages.value = []
        currentConversationId.value = null
        fallbackConversations.value = []
        isUsingHistoryFallback.value = false
        return true
      }

      const selected = (
        currentConversationId.value
          ? conversations.value.find((item) => item.id === currentConversationId.value)
          : null
      ) || conversations.value[0]
      if (!serverIds.has(selected.id)) {
        activateConversation(selected)
        persistFallbackHistory()
        isUsingHistoryFallback.value = true
        return true
      }
      const loaded = await loadConversation(selected.id)
      if (!loaded) throw new Error('Could not load selected conversation')
      persistFallbackHistory()
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
    abortController?.abort()
    abortController = null
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

  async function deleteConversation(id: string) {
    if (currentConversationId.value === id) {
      abortController?.abort()
      abortController = null
    }
    await queryService.deleteConversation(id)
    conversations.value = conversations.value.filter((conversation) => conversation.id !== id)
    persistFallbackHistory()
    if (currentConversationId.value !== id) return

    currentConversationId.value = null
    messages.value = []
    const nextConversation = conversations.value[0]
    if (nextConversation) await loadConversation(nextConversation.id)
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

  async function ask(q: string, pipelineStages: PipelineStage[], docIds?: string[] | null) {
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
      conversation_id: currentConversationId.value ?? undefined,
      trace_session: currentConversationId.value ?? undefined,
      conversation_title: conversationTitle,
      document_ids: docIds ?? undefined,
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
        
        // Tách action JSON khỏi content (dùng chung helper với rehydrate lịch sử).
        const extracted = extractAction(fullContent)

        const assistant: ChatMessage = {
          id: 'a-' + Date.now(),
          role: 'assistant',
          content: extracted.content, // intro nếu là action, raw JSON đã được ẩn
          actions: extracted.actions,
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

  function injectProactiveMessage(documentName: string, docId: string | null = null) {
    if (!currentConversationId.value) {
      currentConversationId.value = crypto.randomUUID()
    }
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: `Tài liệu **${documentName}** vừa được cập nhật. Mình có thể giúp gì cho bạn?`,
      timestamp: new Date().toISOString(),
      actions: [
        {
          action_type: 'proactive_doc_suggestion',
          document_name: documentName,
          doc_id: docId,
          suggestions: [
            { label: 'Tóm tắt tài liệu', query: `Tóm tắt nội dung tài liệu ${documentName}` },
            { label: 'Hỏi về tài liệu', query: `Tài liệu ${documentName} nói về điều gì?` },
            { label: 'Điểm mới so với tài liệu cũ', query: `So với các tài liệu trước, ${documentName} có gì mới không?` },
          ],
        },
      ],
    })
  }

  function queueProactiveMessage(documentName: string, docId: string | null) {
    pendingProactiveDoc.value = { name: documentName, docId }
  }

  function flushProactiveMessage() {
    if (!pendingProactiveDoc.value) return
    const { name, docId } = pendingProactiveDoc.value
    pendingProactiveDoc.value = null
    injectProactiveMessage(name, docId)
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
    injectProactiveMessage,
    queueProactiveMessage,
    flushProactiveMessage,
  }
})
