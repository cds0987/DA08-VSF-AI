import axios from 'axios'
import type {
  ApiError,
  ConversationDetailResponse,
  ConversationListResponse,
  LoginResponse,
  NotificationItem,
  NotificationList,
} from '~/types'
import { ACCESS_TOKEN_COOKIE, getClientCookie, setClientCookie } from '../cookie'

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

  async function doRefresh(): Promise<void> {
    const userPath = String(config.public.userServicePath || '/api/user')
    const headers: Record<string, string> = {}
    const gatewayAuth = config.public.gatewayBasicAuth
    if (gatewayAuth) headers['Authorization-Gateway'] = String(gatewayAuth)
    const res = await axios.post<LoginResponse>(
      `${gatewayUrl}${userPath}/auth/refresh`,
      {},
      { headers, withCredentials: true },
    )
    if (res.data.access_token) {
      setClientCookie(ACCESS_TOKEN_COOKIE, res.data.access_token)
    }
  }

  async function withTokenRefresh<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn()
    } catch (e: unknown) {
      if ((e as { status?: number })?.status === 401) {
        await doRefresh()
        return fn()
      }
      throw e
    }
  }

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
    return await $fetch<ConversationDetailResponse>(
      `${baseUrl}/conversations/${encodeURIComponent(id)}`,
      {
        headers: getQueryServiceAuthHeaders(),
        query: { limit, offset },
      },
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
    return await $fetch<{ message: string }>(
      `${baseUrl}/conversations/${encodeURIComponent(id)}`,
      {
        method: 'DELETE',
        headers: getQueryServiceAuthHeaders(),
      },
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

  return {
    baseUrl,
    fetchHistory,
    fetchUnreadCount,
    markNotificationRead,
    submitFeedback,
    fetchConversations,
    fetchConversation,
    clearConversations,
    deleteConversation,
    renameConversation,
  }
}
