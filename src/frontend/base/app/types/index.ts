export type Role = 'admin' | 'user'

export interface User {
  id?: string
  name?: string
  email: string
  department?: string
  role: Role
  initials?: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface ApiError {
  detail: string
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
  document: string
  page: number
  section: string
  similarity: number
  chunkId: string
  preview: string
  precedingContext?: string
}

export interface MessageAttachment {
  name: string
  size: number
  type: string
  url?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  confidence?: number
  citations?: Citation[]
  latencyMs?: number
  queryId?: string
  timestamp: string
  attachments?: MessageAttachment[]
}

export interface Conversation {
  id: string
  title: string
  updatedAt: string
  bucket: 'today' | 'yesterday' | 'previous7' | 'older'
  messages: ChatMessage[]
}

export interface PipelineStage {
  label: string
  icon: any
}
