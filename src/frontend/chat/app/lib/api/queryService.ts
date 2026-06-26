import type {
  ApiError,
  ConversationDetailResponse,
  ConversationListResponse,
  NotificationItem,
  NotificationList,
} from '~/types'
import { ACCESS_TOKEN_COOKIE, getClientCookie } from '../cookie'
import { withTokenRefresh } from './authRefresh'

export class QueryServiceError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
    this.name = 'QueryServiceError'
  }
}

export function getQueryServiceAuthHeaders(): Record<string, string> {
  const token = getClientCookie(ACCESS_TOKEN_COOKIE)
  if (!token) {
    throw new QueryServiceError('Not authenticated', 401)
  }
  return { Authorization: `Bearer ${token}` }
}

export async function assertQueryServiceResponse(response: Response): Promise<void> {
  if (response.ok) return

  let message = `Query Service request failed (${response.status})`
  try {
    const body = await response.clone().json() as ApiError
    if (typeof body.detail === 'string') {
      message = body.detail
    }
  } catch {
    // Preserve the status-based fallback for non-JSON responses.
  }
  throw new QueryServiceError(message, response.status)
}

export function useQueryService() {
  const config = useRuntimeConfig()
  const gatewayUrl = String(config.public.apiGatewayUrl || '').replace(/\/$/, '')
  const queryPath = config.public.queryServicePath || '/api/query'
  const baseUrl = `${gatewayUrl}${queryPath}`

  async function fetchHistory(limit = 20, offset = 0, unreadOnly = false, since?: string) {
    return withTokenRefresh(() =>
      $fetch<NotificationList>(`${baseUrl}/notifications/history`, {
        headers: getQueryServiceAuthHeaders(),
        query: { limit, offset, unread_only: unreadOnly, since },
      })
    )
  }

  async function fetchUnreadCount() {
    return withTokenRefresh(() =>
      $fetch<{ unread: number }>(`${baseUrl}/notifications/unread-count`, {
        headers: getQueryServiceAuthHeaders(),
      })
    )
  }

  async function markNotificationRead(id: string) {
    return withTokenRefresh(() =>
      $fetch<NotificationItem>(
        `${baseUrl}/notifications/${encodeURIComponent(id)}/read`,
        {
          method: 'POST',
          headers: getQueryServiceAuthHeaders(),
        },
      )
    )
  }

  async function deleteNotification(id: string) {
    return withTokenRefresh(() =>
      $fetch<void>(
        `${baseUrl}/notifications/${encodeURIComponent(id)}`,
        {
          method: 'DELETE',
          headers: getQueryServiceAuthHeaders(),
        },
      )
    )
  }

  async function submitFeedback(sessionId: string, score: 1 | -1, traceId?: string) {
    return withTokenRefresh(() =>
      $fetch<{ message: string }>(`${baseUrl}/feedback`, {
        method: 'POST',
        headers: getQueryServiceAuthHeaders(),
        body: { session_id: sessionId, score, trace_id: traceId },
      })
    )
  }

  async function fetchConversations(limit = 100, offset = 0) {
    return withTokenRefresh(() =>
      $fetch<ConversationListResponse>(`${baseUrl}/conversations`, {
        headers: getQueryServiceAuthHeaders(),
        query: { limit, offset, include_legacy_messages: false },
      })
    )
  }

  async function fetchConversation(id: string, limit = 500, offset = 0) {
    return withTokenRefresh(() =>
      $fetch<ConversationDetailResponse>(
        `${baseUrl}/conversations/${encodeURIComponent(id)}`,
        {
          headers: getQueryServiceAuthHeaders(),
          query: { limit, offset },
        },
      )
    )
  }

  async function clearConversations() {
    return withTokenRefresh(() =>
      $fetch<{ message: string }>(`${baseUrl}/conversations`, {
        method: 'DELETE',
        headers: getQueryServiceAuthHeaders(),
      })
    )
  }

  async function deleteConversation(id: string) {
    return withTokenRefresh(() =>
      $fetch<{ message: string }>(
        `${baseUrl}/conversations/${encodeURIComponent(id)}`,
        {
          method: 'DELETE',
          headers: getQueryServiceAuthHeaders(),
        },
      )
    )
  }

  async function renameConversation(id: string, newTitle: string) {
    return withTokenRefresh(() =>
      $fetch<{ message: string }>(`${baseUrl}/conversations/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: getQueryServiceAuthHeaders(),
        body: { title: newTitle },
      })
    )
  }

  // Ghi trạng thái thực thi của 1 action (vd đơn nghỉ đã gửi) vào message -> bền qua
  // reload/đa thiết bị (xem docs/leave-action-state-b2.md).
  async function setMessageActionState(
    conversationId: string,
    messageId: string,
    payload: { idempotency_key: string; request_id?: string | null; status?: string; leave_status?: string | null },
  ) {
    return withTokenRefresh(() =>
      $fetch<{ message: string }>(
        `${baseUrl}/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/actions`,
        {
          method: 'POST',
          headers: getQueryServiceAuthHeaders(),
          body: payload,
        },
      )
    )
  }

  return {
    baseUrl,
    fetchHistory,
    fetchUnreadCount,
    markNotificationRead,
    deleteNotification,
    submitFeedback,
    fetchConversations,
    fetchConversation,
    clearConversations,
    deleteConversation,
    renameConversation,
    setMessageActionState,
  }
}
