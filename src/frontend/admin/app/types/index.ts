export type Role = 'admin' | 'user'

export type DocumentStatus = 'queued' | 'processing' | 'indexed' | 'failed'
export type Classification = 'public' | 'internal' | 'secret' | 'top_secret'
export type AuditLogSource = 'user-service' | 'document-service'
export type AuditLogStatus = 'success' | 'denied' | 'error'

export interface User {
  id: string
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

export interface DocumentItem {
  id: string
  name: string
  file_type: string
  status: DocumentStatus
  classification: Classification
  uploaded_by: string
  chunk_count: number
  created_at: string
}

export interface DocumentDetail extends DocumentItem {
  error_message: string | null
  allowed_departments: string[]
  allowed_user_ids: string[]
}

export interface DocumentListResponse {
  items: DocumentItem[]
  total: number
}

export interface UploadResponse {
  document_id: string
  status: 'queued'
  message: string
}

export interface DocumentFileResponse {
  url: string
  file_type: string
  expires_in: number
}

export interface SupportedFormatsResponse {
  extensions: string[]
  max_file_bytes: number
}

export interface MessageResponse {
  message: string
}

export interface AdminMetrics {
  total_questions: number
  by_day: Array<{ date: string; count: number }>
  feedback: { up: number; down: number; rate: number }
  top_questions: Array<{ question: string; count: number }>
}

export interface AuditLogItem {
  id: string
  source: AuditLogSource
  actor_id: string
  actor_email: string
  actor_role: string
  action: string
  resource: string
  status: AuditLogStatus
  ip_address: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

export interface AuditLogListResponse {
  items: AuditLogItem[]
  total: number
}
