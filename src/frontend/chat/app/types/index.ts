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
  refresh_token: string
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
}

export interface QueryRequest {
  question: string
  user_id: string
}

export interface QuerySource {
  document_id: string
  document_name: string
  caption: string
  heading_path: string[]
  score: number
  source_gcs_uri: string
  page_number?: number | null
}

// Add File related response types
export interface DocumentFileResponse {
  url: string
  file_type: string
  expires_in: number
}

export interface QueryTokenEvent {
  token: string
  phase?: 'thinking' | 'acting' | 'observing' | 'generating'
}

export interface QueryDoneEvent {
  done: true
  sources: QuerySource[]
  session_id: string
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
  action_type: 'create_leave_request'
  parameters: {
    leave_type: string
    start_date: string
    end_date: string
    reason: string
  }
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  citations?: Citation[]
  sessionId?: string
  feedback?: 1 | -1
  timestamp: string
  attachments?: MessageAttachment[]
  error?: string
  action?: HRActionPayload
}

export interface Conversation {
  id: string
  title: string
  updatedAt: string
  bucket: 'today' | 'yesterday' | 'previous7' | 'older'
  messages: ChatMessage[]
}

export interface ConversationHistoryMessage {
  role: 'user' | 'assistant'
  content: string
  created_at: string
  sources?: QuerySource[]
}

export interface ConversationHistoryResponse {
  messages: ConversationHistoryMessage[]
}

export interface PipelineStage {
  label: string
  icon: any
}
