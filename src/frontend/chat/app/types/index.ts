export type Role = 'admin' | 'user'

export interface User {
  id?: string
  name?: string
  email: string
  department?: string
  role: Role
  initials?: string
  is_active?: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface ApiError {
  detail: string | Array<{
    loc: Array<string | number>
    msg: string
    type: string
  }>
}

export interface LoginCredentials {
  email: string
  password: string
}

export interface TokenCredentials {
  username: string
  password: string
}

export interface Citation {
  id: string
  document_id: string
  document: string
  caption: string
  heading_path: string[]
  page_number?: number | null
  ref?: number
}

export interface QueryRequest {
  question: string
  user_id: string
  conversation_id?: string
  trace_session?: string
  conversation_title?: string
  document_ids?: string[] | null
}

export interface QuerySource {
  document_id?: string
  document_name: string
  caption: string
  heading_path: string[]
  score: number
  source_gcs_uri?: string
  page_number?: number | null
  ref?: number
}

// Add File related response types
export interface DocumentFileResponse {
  url: string
  file_type: string
  expires_in: number
}

export interface TraceEntry {
  tool: string
  args: Record<string, unknown>
  iteration: number
  resultCount?: number
  resultDocs?: string[]
  resultRaw?: string
  pending: boolean
}

export interface QueryTokenEvent {
  token?: string
  phase?: 'thinking' | 'acting' | 'observing' | 'generating'
  status?: string
  node?: string
  tool?: string
  tool_args?: Record<string, unknown>
  tool_result_summary?: { count?: number; docs?: string[]; raw?: string }
  iterations?: number
}

export interface QueryDoneEvent {
  done: true
  sources: QuerySource[]
  session_id: string
  trace_id?: string
  cached?: true
  fallback?: true
}

export interface NotificationEvent {
  type: 'notify'
  event: 'doc_new'
  id: string
  message: string
  doc_id: string | null
  is_read: boolean
  created_at: string
}

export interface NotificationItem {
  id: string
  event: string
  message: string
  doc_id: string | null
  is_read: boolean
  created_at: string
}

export interface NotificationList {
  items: NotificationItem[]
  total: number
}

export interface MessageAttachment {
  name: string
  size: number
  type: string
  url?: string
}

export interface HRActionPayload {
  // 'create_leave_request': thẻ tạo đơn (có parameters).
  // 'review_leave_approvals': thẻ duyệt — FE tự nạp hàng đợi live, không cần parameters.
  // 'proactive_doc_suggestion': bot gợi ý hỏi về tài liệu mới.
  action_type: 'create_leave_request' | 'review_leave_approvals' | 'proactive_doc_suggestion'
  parameters?: {
    leave_type: string
    start_date: string
    end_date: string
    reason: string
  }
  // Sinh 1 lần khi tạo card (FE) -> chống tạo trùng nếu user bấm Confirm 2 lần / retry.
  idempotency_key?: string
  // proactive_doc_suggestion fields
  document_name?: string
  doc_id?: string | null
  suggestions?: Array<{ label: string; query: string }>
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  citations?: Citation[]
  sessionId?: string
  feedback?: 1 | -1
  traceId?: string
  timestamp: string
  attachments?: MessageAttachment[]
  error?: string
  // Nhiều đơn 1 lượt -> mỗi phần tử là 1 form xác nhận riêng.
  actions?: HRActionPayload[]
}

export interface Conversation {
  id: string
  title: string
  updatedAt: string
  bucket: 'today' | 'yesterday' | 'previous7' | 'older'
  messages: ChatMessage[]
}

export interface ConversationHistoryMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  session_id?: string | null
  sources?: QuerySource[]
  feedback?: 1 | -1 | null
}

export interface ConversationSummaryResponse {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationListResponse {
  conversations: ConversationSummaryResponse[]
}

export interface ConversationDetailResponse extends ConversationSummaryResponse {
  messages: ConversationHistoryMessage[]
}

export interface PipelineStage {
  label: string
  icon: any
}
