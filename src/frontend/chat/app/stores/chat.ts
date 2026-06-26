import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useDebounceFn, useLocalStorage } from '@vueuse/core'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useSessionStore } from './session'
import type {
  AgentPlan,
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
import { SSE_DONE_REQUIRED } from '~/types/sse-contract.gen'
import { handleRefreshFailure, refreshAccessToken } from '~/lib/api/authRefresh'
import { buildQuotedContent } from '~/lib/quote'
import type { Quote } from '~/lib/quote'
import { createStreamBuffer } from '~/lib/streamBuffer'
import { createRafScheduler } from '~/lib/rafScheduler'
import { buildHistorySnapshot } from '~/lib/historyPersist'

const HISTORY_KEY = 'eka.chat.conversations'

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

// Hash tất định (cyrb53) -> dùng dựng idempotency_key BỀN qua reload. Trước đây key
// random sinh lại mỗi lần rehydrate lịch sử -> idempotency vô tác dụng sau khi load lại
// trang và card "Xác nhận đơn nghỉ" hiện lại như chưa gửi. Hash theo NỘI DUNG đơn ->
// cùng đơn = cùng key qua mọi lần reload.
function cyrb53(str: string): string {
  let h1 = 0xdeadbeef
  let h2 = 0x41c6ce57
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i)
    h1 = Math.imul(h1 ^ ch, 2654435761)
    h2 = Math.imul(h2 ^ ch, 1597334677)
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909)
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909)
  return (h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0')
}

// idempotency_key TẤT ĐỊNH cho 1 đơn nghỉ. PHẢI gồm user_id vì cột idempotency_key là
// UNIQUE TOÀN CỤC (uq_leave_req_idempotency_key) -> nếu thiếu, 2 user cùng loại+ngày sẽ
// đụng key và nhận nhầm đơn của nhau. <= 64 ký tự (giới hạn cột String(64)).
function stableLeaveKey(userId: string | undefined, p: any): string {
  const seed = [p?.leave_type, p?.start_date, p?.end_date, p?.reason ?? ''].join('|')
  return `lv-${(userId || 'anon').slice(0, 36)}-${cyrb53(seed)}`
}

// Quét các JSON object top-level (cân bằng ngoặc) trong 1 chuỗi. Model yếu (nano) thỉnh
// thoảng in tham số tool-call ra text rồi mới nối action JSON thật ->
//   {"kind":"absolute",...}\n{"action_type":...}
// JSON.parse cả chuỗi sẽ throw. Hàm này tách từng object để ta nhặt đúng object action,
// tránh fallback đổ raw JSON ra cho user.
function scanTopLevelJsonObjects(text: string): any[] {
  const out: any[] = []
  let depth = 0
  let start = -1
  let inStr = false
  let escaped = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inStr) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === '"') inStr = false
      continue
    }
    if (ch === '"') { inStr = true; continue }
    if (ch === '{') { if (depth === 0) start = i; depth++ }
    else if (ch === '}') {
      depth--
      if (depth === 0 && start >= 0) {
        try { out.push(JSON.parse(text.slice(start, i + 1))) }
        catch { /* object hỏng -> bỏ qua */ }
        start = -1
      }
    }
  }
  return out
}

// Dựng actions từ 1 parsed object có action_type. Trả null nếu không phải object action.
function actionsFromParsed(parsed: any, userId?: string): any[] | null {
  if (!parsed || typeof parsed !== 'object' || !parsed.action_type) return null
  // Thẻ duyệt: không cần items/parameters — FE tự nạp hàng đợi live.
  if (parsed.action_type === 'review_leave_approvals') {
    return [{ action_type: 'review_leave_approvals', idempotency_key: newIdempotencyKey() }]
  }
  const rawItems: any[] = Array.isArray(parsed.items)
    ? parsed.items
    : (parsed.parameters ? [parsed.parameters] : [])
  if (!rawItems.length) return []
  // idempotency_key TẤT ĐỊNH theo nội dung đơn -> bền qua reload (xem stableLeaveKey).
  // Cùng đơn = cùng key: bấm Confirm nhiều lần / reload rồi gửi lại đều dedupe ở server,
  // và card biết "đã gửi" nhờ key này.
  return rawItems.map(p => ({
    action_type: parsed.action_type,
    parameters: p,
    idempotency_key: stableLeaveKey(userId, p),
  }))
}

// Tách action JSON ra khỏi content thô của trợ lý. Dùng CHUNG cho cả luồng stream
// (lần đầu) lẫn rehydrate từ lịch sử (toChatMessage) -> reload không bị lòi raw JSON.
// Hỗ trợ NHIỀU đơn 1 lượt: model xuất {action_type, items:[{...},...]} -> mỗi item là
// 1 form riêng. Vẫn nhận format cũ {action_type, parameters:{...}} (1 đơn).
// ROBUST với model leak: nếu content có lẫn JSON rác (vd tham số resolve_date) trước
// action JSON, vẫn nhặt đúng object action thay vì đổ raw cho user.
// Trả { actions, content }: actions = danh sách payload; content = câu dẫn nhập.
function extractAction(rawContent: string, userId?: string): { actions?: any[]; content: string } {
  const trimmed = (rawContent || '').trim()
  if (!trimmed.includes('{') || !trimmed.includes('}')) return { content: rawContent }

  // Đường nhanh: cả chuỗi là 1 JSON object hợp lệ.
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const actions = actionsFromParsed(JSON.parse(trimmed), userId)
      if (actions && actions.length) return { actions, content: buildActionIntro(actions) }
      if (actions) return { content: 'Mình đã xử lý yêu cầu của bạn. Bạn có thể hỏi thêm nếu cần nhé.' }
    } catch { /* rơi xuống nhánh quét nhiều object */ }
  }

  // Đường robust: model leak nhiều JSON object -> nhặt object action CUỐI CÙNG.
  const objs = scanTopLevelJsonObjects(trimmed)
  const actionObj = [...objs].reverse().find(o => o && o.action_type)
  if (actionObj) {
    const actions = actionsFromParsed(actionObj, userId)
    if (actions && actions.length) return { actions, content: buildActionIntro(actions) }
    return { content: 'Mình đã xử lý yêu cầu của bạn. Bạn có thể hỏi thêm nếu cần nhé.' }
  }

  // Không có object action: nếu content trông như JSON rác (chỉ gồm các object), đừng đổ
  // raw cho user; ngược lại giữ nguyên văn (text thường).
  if (trimmed.startsWith('{') && objs.length) {
    return { content: 'Mình đã xử lý yêu cầu của bạn. Bạn có thể hỏi thêm nếu cần nhé.' }
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
    snippet: source.snippet,
    score: source.score,
    heading_path: source.heading_path,
    page_number: source.page_number,
    ref: source.ref,
  }
}

function toChatMessage(message: ConversationHistoryMessage, userId?: string): ChatMessage {
  const createdAt = new Date(message.created_at)
  // Trợ lý có thể đã lưu raw JSON action -> parse lại để render form khi reload lịch sử.
  const extracted = message.role === 'assistant'
    ? extractAction(message.content, userId)
    : { content: message.content, actions: undefined as any }
  // Gắn trạng thái thực thi (server là nguồn sự thật) vào từng action theo idempotency_key
  // -> card render "đã gửi" sau reload thay vì form. (B2 — docs/leave-action-state-b2.md)
  const actionStates = message.metadata?.actions
  const actions = extracted.actions?.map((a: any) => {
    const st = a.idempotency_key ? actionStates?.[a.idempotency_key] : undefined
    return st ? { ...a, status: st.status, request_id: st.request_id, leave_status: st.leave_status } : a
  })
  // Khối "suy nghĩ của agent" server lưu kèm (metadata.agent) -> hiện lại sau reload/đa
  // thiết bị, không phụ thuộc cache localStorage. Chỉ gắn field có dữ liệu.
  const agent = message.metadata?.agent
  return {
    id: message.id,
    role: message.role,
    content: extracted.content,
    actions,
    citations: message.sources?.map((source, index) => toCitation(
      source,
      message.id + '-source-' + index,
    )),
    sessionId: message.session_id || undefined,
    feedback: message.feedback || undefined,
    timestamp: Number.isNaN(createdAt.getTime())
      ? message.created_at
      : createdAt.toLocaleString(),
    thoughts: agent?.thoughts?.length ? agent.thoughts : undefined,
    plan: agent?.plan?.steps?.length ? agent.plan : undefined,
    trace: agent?.trace?.length ? agent.trace : undefined,
    models: agent?.models?.length ? agent.models : undefined,
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
  const quote = ref<Quote | null>(null)
  const files = ref<File[]>([])
  const messages = ref<ChatMessage[]>([])
  const conversations = ref<Conversation[]>([])
  const router = useRouter()
  const storageSuffix = sessionStore.user?.id || 'anonymous'
  const fallbackStorageKey = HISTORY_KEY + '.' + storageSuffix
  const fallbackConversations = useLocalStorage<Conversation[]>(fallbackStorageKey, [])
  // URL là source of truth cho conversation hiện tại — không cần persist localStorage.
  const currentConversationId = ref<string | null>(null)
  const isHistoryLoading = ref(false)
  const isHistoryClearing = ref(false)
  const isConversationLoading = ref(false)
  const isUsingHistoryFallback = ref(false)
  const conversationLoadError = ref<'error' | null>(null)
  const pipeline = ref<number>(-1)
  const streamingText = ref('')
  // Key ổn định cho lượt trả lời đang chạy: placeholder-stream và message-cuối dùng chung
  // -> Vue patch cùng node AnswerBlock thay vì remount (hết flash lúc stream xong).
  const pendingAssistantId = ref('')
  const thinkingStatus = ref('')
  const traceLog = ref<TraceEntry[]>([])
  const modelsUsed = ref<{ node: string; model: string }[]>([])
  const thoughts = ref<{ node: string; text: string }[]>([])
  const plan = ref<AgentPlan | null>(null)
  const panelCitation = ref<Citation | null>(null)
  const isPanelOpen = ref(false)
  const pendingProactiveDoc = ref<{ name: string; docId: string | null } | null>(null)
  let abortController: AbortController | null = null
  // Giữ citation tới khi panel trượt hết ra (khớp transition 300ms) để tránh flash
  // nội dung trống trong lúc animation đóng.
  let closePanelTimer: ReturnType<typeof setTimeout> | null = null

  function setInput(val: string) {
    input.value = val
  }

  function setQuote(q: Quote) {
    quote.value = q
  }
  function clearQuote() {
    quote.value = null
  }

  function addFiles(newFiles: File[]) {
    files.value = [...files.value, ...newFiles]
  }

  function removeFile(index: number) {
    files.value = files.value.filter((_, i) => i !== index)
  }

  function handleOpenCitation(citation: Citation) {
    if (closePanelTimer) { clearTimeout(closePanelTimer); closePanelTimer = null }
    panelCitation.value = citation
    isPanelOpen.value = true
  }

  function handleCloseCitation() {
    isPanelOpen.value = false
    if (closePanelTimer) clearTimeout(closePanelTimer)
    // Xóa sau khi animation trượt ra xong; nếu user mở citation khác trong lúc đó,
    // handleOpenCitation đã hủy timer này nên không xóa nhầm.
    closePanelTimer = setTimeout(() => {
      panelCitation.value = null
      closePanelTimer = null
    }, 300)
  }

  function clear() {
    abortController?.abort()
    abortController = null
    currentConversationId.value = null
    messages.value = []
    pipeline.value = -1
    streamingText.value = ''
    traceLog.value = []
    plan.value = null
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
    persistFallbackHistory()
  }

  function ensureConversationId() {
    if (!currentConversationId.value) {
      currentConversationId.value = createConversationId()
    }
  }

  // Ghi snapshot xuống localStorage; nuốt QuotaExceededError (storage đầy -> giữ in-memory).
  function writeSnapshot(next: Conversation[]) {
    try {
      fallbackConversations.value = next
    } catch (err) {
      if (err instanceof DOMException && err.name === 'QuotaExceededError') return
      throw err
    }
  }

  // Ghi ĐẦY ĐỦ tức thì: clone toàn bộ. Dùng khi NHIỀU conversation đổi (load/sync/delete).
  function persistAllNow() {
    writeSnapshot(conversations.value.map((item) => ({
      ...item,
      messages: item.messages.map((message) => ({ ...message })),
    })))
  }

  // Ghi TĂNG DẦN: clone CHỈ conversation hiện tại, tái dùng phần còn lại từ snapshot cũ.
  function flushCurrent() {
    writeSnapshot(buildHistorySnapshot(
      conversations.value, currentConversationId.value, fallbackConversations.value,
    ))
  }

  // Gom burst ghi ra khỏi critical path của click gửi.
  const debouncedPersist = useDebounceFn(flushCurrent, 400)

  // Hot path (chỉ conversation hiện tại đổi: send/done/feedback) -> debounce tăng dần.
  function persistFallbackHistory() {
    debouncedPersist()
  }

  // Đóng/ẩn tab -> flush ngay để không mất write cuối còn trong cửa sổ debounce.
  if (import.meta.client) {
    window.addEventListener('pagehide', flushCurrent)
    document.addEventListener('visibilitychange', () => { if (document.hidden) flushCurrent() })
  }

  function activateConversation(conversation: Conversation) {
    conversationLoadError.value = null
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
    const cached = conversations.value.find((item) => item.id === id)

    // Hiện ngay cached data (hoặc empty state) trước khi fetch server.
    if (cached) {
      activateConversation(cached)
    } else {
      conversationLoadError.value = null
      abortController?.abort()
      abortController = null
      currentConversationId.value = id
      messages.value = []
      pipeline.value = -1
      streamingText.value = ''
      isPanelOpen.value = false
      panelCitation.value = null
      input.value = ''
      files.value = []
    }

    isConversationLoading.value = true
    try {
      const detail = await queryService.fetchConversation(id)
      const updatedAt = detail.updated_at
      const serverMsgs = detail.messages.map(m => toChatMessage(m, sessionStore.user?.id))
      // `trace` (các bước agent) + `reasoning` chỉ sống ở client — backend history KHÔNG lưu.
      // Khôi phục từ cache localStorage theo vị trí + content -> mở lại/đổi hội thoại KHÔNG
      // mất "Agent đã thực hiện N bước" của các câu trả lời cũ.
      const cachedMsgs = fallbackConversations.value.find((c) => c.id === id)?.messages ?? []
      // Map message-id -> cached message, gom TỪ MỌI hội thoại cache. id message do server cấp
      // (ổn định) -> khôi phục được kể cả khi conversation id client ≠ server (hội thoại mới).
      const cachedById = new Map<string, ChatMessage>()
      for (const conv of fallbackConversations.value)
        for (const m of (conv.messages || []) as ChatMessage[])
          if (m.id) cachedById.set(m.id, m)
      // "có dữ liệu agent client-only" = trace HOẶC reasoning HOẶC thoughts/plan/models
      // (câu trả lời orchestrator chỉ có thoughts+plan, KHÔNG có trace/reasoning -> trước đây
      // bị bỏ sót ở fallback content-match nên mất khối "Agent" sau khi nạp lại).
      const hasAgentTrace = (m?: ChatMessage) => !!(m && (
        m.trace?.length || m.reasoning || m.thoughts?.length || m.plan?.steps?.length || m.models?.length
      ))
      serverMsgs.forEach((s, i) => {
        if (s.role !== 'assistant') return
        // Ưu tiên match theo id (chắc chắn nhất), rồi cùng slot+content, rồi content+có-agent-trace.
        let c: ChatMessage | undefined = (s.id ? cachedById.get(s.id) : undefined)
        if (!hasAgentTrace(c)) {
          const slot = cachedMsgs[i]
          if (slot?.role === 'assistant' && slot.content === s.content && hasAgentTrace(slot)) c = slot
        }
        if (!hasAgentTrace(c)) {
          c = (cachedMsgs as ChatMessage[]).find((m: ChatMessage) => m.role === 'assistant' && m.content === s.content && hasAgentTrace(m)) || c
        }
        if (c?.trace?.length) s.trace = c.trace
        if (c?.reasoning) s.reasoning = c.reasoning
        if (c?.models?.length) s.models = c.models
        if (c?.thoughts?.length) s.thoughts = c.thoughts
        if (c?.plan?.steps?.length) s.plan = c.plan
      })
      const synced: Conversation = {
        id: detail.id,
        title: detail.title,
        updatedAt,
        bucket: getBucket(new Date(updatedAt)),
        messages: serverMsgs,
      }
      const index = conversations.value.findIndex((item) => item.id === id)
      if (index >= 0) conversations.value.splice(index, 1, synced)
      if (currentConversationId.value === id) activateConversation(synced)
      persistAllNow()
      isUsingHistoryFallback.value = false
      return true
    } catch (err: any) {
      if (err?.response?.status === 404) {
        conversations.value = conversations.value.filter((item) => item.id !== id)
        persistAllNow()
        currentConversationId.value = null
        messages.value = []
        void router.replace('/chat')
        return false
      }
      isUsingHistoryFallback.value = true
      conversationLoadError.value = 'error'
      return false
    } finally {
      isConversationLoading.value = false
    }
  }

  function restoreFallbackHistory() {
    conversations.value = fallbackConversations.value.map((item) => ({
      ...item,
      id: isConversationId(item.id) ? item.id : createConversationId(),
      messages: item.messages.map((message) => ({ ...message })),
    }))
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

      isUsingHistoryFallback.value = false
      persistAllNow()
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
      void router.push('/chat')
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
    persistAllNow()
    if (currentConversationId.value !== id) return

    currentConversationId.value = null
    messages.value = []
    const nextConversation = conversations.value[0]
    if (nextConversation) {
      void router.push('/chat/' + nextConversation.id)
    } else {
      void router.push('/chat')
    }
  }

  async function renameConversation(id: string, newTitle: string) {
    const title = newTitle.trim()
    if (!title) return

    const conv = conversations.value.find((c) => c.id === id)
    if (!conv) return

    const previousTitle = conv.title
    conv.title = title
    persistAllNow()

    try {
      await queryService.renameConversation(id, title)
    } catch (error) {
      conv.title = previousTitle
      persistAllNow()
      throw error
    }
  }

  async function ask(q: string, pipelineStages: PipelineStage[], docIds?: string[] | null) {
    const question = q.trim()
    // Cho gửi khi có câu hỏi HOẶC khi đang có trích dẫn (gửi chỉ riêng đoạn quote cũng được).
    if ((!question && !quote.value) || pipeline.value >= 0) return
    // Nếu user đã trích dẫn một đoạn bot answer, prepend thành blockquote vào nội dung gửi.
    const content = buildQuotedContent(quote.value, question)

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
    quote.value = null
    files.value = []

    const wasNew = !currentConversationId.value
    ensureConversationId()
    messages.value.push({
      id: `m-${Date.now()}`,
      role: 'user',
      content,
      timestamp: new Date().toLocaleString(),
    })
    cacheCurrentConversation()

    // Cập nhật URL ngay (giống ChatGPT) trước khi stream bắt đầu.
    if (wasNew && import.meta.client) {
      void router.push('/chat/' + currentConversationId.value)
    }

    streamingText.value = ''
    // Cấp key lượt MỚI ngay đầu lượt -> placeholder-stream và message-cuối khớp key.
    pendingAssistantId.value = 'a-' + Date.now()
    thinkingStatus.value = ''
    traceLog.value = []
    modelsUsed.value = []
    thoughts.value = []
    plan.value = null
    pipeline.value = 0
    let fullContent = ''
    const buffer = createStreamBuffer({
      commit: (delta) => { streamingText.value += delta },
      ...createRafScheduler(),
    })
    let completed = false
    let hasStartedStreaming = false
    let donePayload: QueryDoneEvent | null = null
    const conversationTitle = conversations.value.find(c => c.id === currentConversationId.value)?.title
    const request: QueryRequest = {
      question: content,
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

    // Tách thân stream ra hàm riêng để có thể retry MỘT lần khi 401 xảy ra TRƯỚC khi
    // stream bắt đầu. getQueryServiceAuthHeaders() được đọc lại mỗi lần gọi nên sau khi
    // refresh (cookie mới) retry sẽ dùng token mới.
    const runStream = () => fetchEventSource(`${queryService.baseUrl}/query`, {
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
          let payload: unknown
          try {
            payload = JSON.parse(message.data)
          } catch {
            return
          }
          if (isTokenEvent(payload)) {
            if (payload.token) {
              hasStartedStreaming = true
              fullContent += payload.token
              buffer.push(payload.token)
              pipeline.value = pipelineStages.length
              thinkingStatus.value = ''
            }

            // model_used: ghi nhận model THẬT từng node đã chạy. Xử lý TRƯỚC guard
            // hasStartedStreaming vì model_used của answer node phát SAU khi token bắt đầu.
            if (payload.phase === 'model_used' && payload.node && payload.model) {
              const m = { node: payload.node, model: payload.model }
              if (!modelsUsed.value.some(x => x.node === m.node && x.model === m.model)) {
                modelsUsed.value.push(m)
              }
              return
            }

            // thought: model nghĩ gì / quyết định gì. think token-stream -> gộp vào dòng
            // think hiện tại; triage reason -> 1 dòng riêng.
            if (payload.phase === 'thought' && payload.node && payload.text) {
              // Reasoning stream token-by-token (think/verify/answer...) -> GỘP các mảnh LIÊN
              // TIẾP cùng node vào 1 dòng (tránh mỗi token 1 box = vỡ vụn). Node đổi -> dòng mới.
              const last = thoughts.value[thoughts.value.length - 1]
              if (last && last.node === payload.node) last.text += payload.text
              else thoughts.value.push({ node: payload.node, text: payload.text })
              return
            }

            // plan: orchestrator phát kế hoạch -> dựng node (pending) cho FE vẽ lane song song.
            if (payload.phase === 'plan' && Array.isArray(payload.steps)) {
              plan.value = {
                route: payload.route ?? 'heavy',
                steps: payload.steps.map(s => ({ ...s, status: 'pending' as const })),
              }
              return
            }
            // step: 1 node đổi trạng thái (running/ok/error). Xử lý TRƯỚC guard vì node synth
            // báo "done" SAU khi token answer đã bắt đầu.
            if (payload.phase === 'step' && payload.step_id != null && plan.value) {
              const st = plan.value.steps.find(s => s.id === payload.step_id)
              if (st && payload.status) st.status = payload.status as typeof st.status
              return
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
          // done-event thiếu/sai field bắt buộc -> KHÔNG drop ÂM THẦM (trước đây thiếu field
          // => tin nhắn treo, không rõ vì sao). Cảnh báo kèm field thiếu để chẩn nhanh; hợp
          // đồng nguồn: query-service sse_contract.py (DONE_REQUIRED) -> sse-contract.gen.ts.
          if ((payload as any)?.done === true && !isDoneEvent(payload)) {
            const miss = SSE_DONE_REQUIRED.filter(f => !(f in (payload as Record<string, unknown>)))
            console.warn('[sse] done-event không hợp lệ (thiếu/sai field):', miss.length ? miss : 'kiểu sai',
              '-> tin nhắn có thể treo. Hợp đồng: sse_contract.py')
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

    try {
      try {
        await runStream()
      } catch (error) {
        // CHỈ retry khi 401 xảy ra TRƯỚC khi stream phát token đầu tiên — không bao giờ
        // replay giữa chừng vì sẽ duplicate câu trả lời / trạng thái conversation.
        if (
          error instanceof QueryServiceError
          && error.status === 401
          && !hasStartedStreaming
          && !completed
          && !controller.signal.aborted
        ) {
          const token = await refreshAccessToken()
          if (!token) {
            await handleRefreshFailure()
            throw error
          }
          await runStream()
        } else {
          throw error
        }
      }

      if (donePayload) {
        await nextTick()
        const result = donePayload as QueryDoneEvent
        
        // Tách action JSON khỏi content (dùng chung helper với rehydrate lịch sử).
        const extracted = extractAction(fullContent, userId ? String(userId) : undefined)

        const assistant: ChatMessage = {
          // Ưu tiên id row server (ổn định qua reload -> patch được trạng thái action);
          // fallback id cục bộ khi done event không kèm message_id.
          id: result.message_id || ('a-' + Date.now()),
          // Cùng turnKey với placeholder-stream -> Vue giữ nguyên node AnswerBlock, chỉ patch
          // (bỏ cursor, [N]->chip, hiện toolbar) thay vì remount -> không flash.
          turnKey: pendingAssistantId.value || undefined,
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
          // Gắn các bước agent đã làm (đã loại pending) -> hiển thị bền vững dưới câu trả lời.
          trace: traceLog.value.length ? traceLog.value.map(e => ({ ...e })) : undefined,
          // Model thật từng node đã chạy (minh bạch vận hành).
          models: modelsUsed.value.length ? modelsUsed.value.map(m => ({ ...m })) : undefined,
          // Dòng suy nghĩ/quyết định của model.
          thoughts: thoughts.value.length ? thoughts.value.map(t => ({ ...t })) : undefined,
          // Kế hoạch orchestrator-workers (node + song song) — lưu để xem lại.
          plan: plan.value ? { route: plan.value.route, steps: plan.value.steps.map(s => ({ ...s })) } : undefined,
        }
        assistant.fallback = result.fallback === true

        messages.value.push(assistant)
        buffer.dispose()
        streamingText.value = ''
        pipeline.value = -1
        cacheCurrentConversation()
        isUsingHistoryFallback.value = false
      }
    } catch (error) {
      if (!controller.signal.aborted && !completed) {
        if (error instanceof QueryServiceError) {
          // Server error (4xx/5xx) — show specific error banner
          const message = errorMessage(error)
          messages.value.push({
            id: `err-${Date.now()}`,
            role: 'assistant',
            content: fullContent || message,
            error: message,
            timestamp: new Date().toLocaleString(),
          })
        } else {
          // Network interruption (ERR_NETWORK_CHANGED, stream closed early, etc.)
          // ChatGPT-style: keep partial content, show retry button — no error banner
          messages.value.push({
            id: `err-${Date.now()}`,
            role: 'assistant',
            content: fullContent,
            interrupted: true,
            timestamp: new Date().toLocaleString(),
          })
        }
        cacheCurrentConversation()
        isUsingHistoryFallback.value = true
      }
    } finally {
      if (abortController === controller) abortController = null
      buffer.dispose()
      streamingText.value = ''
      thinkingStatus.value = ''
      pipeline.value = -1
    }
  }

  async function retryMessage(messageId: string, pipelineStages: PipelineStage[]) {
    const msgIndex = messages.value.findIndex(m => m.id === messageId)
    if (msgIndex === -1) return
    const userMsg = [...messages.value].slice(0, msgIndex).reverse().find(m => m.role === 'user')
    if (!userMsg) return
    messages.value.splice(msgIndex, 1)
    await ask(userMsg.content, pipelineStages)
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
    quote,
    files,
    messages,
    conversations,
    currentConversationId,
    isHistoryLoading,
    isHistoryClearing,
    isConversationLoading,
    isUsingHistoryFallback,
    conversationLoadError,
    pipeline,
    streamingText,
    pendingAssistantId,
    thinkingStatus,
    traceLog,
    modelsUsed,
    thoughts,
    plan,
    panelCitation,
    isPanelOpen,
    setInput,
    setQuote,
    clearQuote,
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
    retryMessage,
    submitFeedback,
    injectProactiveMessage,
    queueProactiveMessage,
    flushProactiveMessage,
  }
})
