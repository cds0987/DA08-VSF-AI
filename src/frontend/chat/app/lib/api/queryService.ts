import type {
  ApiError,
  ConversationHistoryResponse,
  NotificationItem,
  NotificationList,
} from '~/types'
import { ACCESS_TOKEN_COOKIE, getClientCookie } from '../cookie'

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
    return await $fetch<NotificationList>(`${baseUrl}/notifications/history`, {
      headers: getQueryServiceAuthHeaders(),
      query: { limit, offset, unread_only: unreadOnly, since },
    })
  }

  async function fetchUnreadCount() {
    return await $fetch<{ unread: number }>(`${baseUrl}/notifications/unread-count`, {
      headers: getQueryServiceAuthHeaders(),
    })
  }

  async function markNotificationRead(id: string) {
    return await $fetch<NotificationItem>(
      `${baseUrl}/notifications/${encodeURIComponent(id)}/read`,
      {
        method: 'POST',
        headers: getQueryServiceAuthHeaders(),
      },
    )
  }

  async function submitFeedback(sessionId: string, score: 1 | -1) {
    return await $fetch<{ message: string }>(`${baseUrl}/feedback`, {
      method: 'POST',
      headers: getQueryServiceAuthHeaders(),
      body: { session_id: sessionId, score },
    })
  }

  async function fetchConversations(limit = 500, offset = 0) {
    return await $fetch<ConversationHistoryResponse>(`${baseUrl}/conversations`, {
      headers: getQueryServiceAuthHeaders(),
      query: { limit, offset },
    })
  }

  async function clearConversations() {
    return await $fetch<{ message: string }>(`${baseUrl}/conversations`, {
      method: 'DELETE',
      headers: getQueryServiceAuthHeaders(),
    })
  }

  async function renameConversation(id: string, newTitle: string) {
    return await $fetch<{ message: string }>(`${baseUrl}/conversations/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: getQueryServiceAuthHeaders(),
      body: { title: newTitle },
    })
  }

  return {
    baseUrl,
    fetchHistory,
    fetchUnreadCount,
    markNotificationRead,
    submitFeedback,
    fetchConversations,
    clearConversations,
    renameConversation,
  }
}
