import type { ApiError } from '~/types'
import { ACCESS_TOKEN_COOKIE, getClientCookie } from '../cookie'

export class HRServiceError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
    this.name = 'HRServiceError'
  }
}

export function getHRServiceAuthHeaders(): Record<string, string> {
  const token = getClientCookie(ACCESS_TOKEN_COOKIE)
  if (!token) {
    throw new HRServiceError('Not authenticated', 401)
  }
  return { Authorization: `Bearer ${token}` }
}

export function useHRService() {
  const config = useRuntimeConfig()
  const gatewayUrl = String(config.public.apiGatewayUrl).replace(/\/$/, '')
  // ĐI QUA query-service (xác thực JWT -> inject user_id) thay vì gọi thẳng hr-service:
  // hr-service chỉ nhận X-Internal-Token, KHÔNG xác thực user. Path = /api/query/leave-requests.
  const queryPath = String(config.public.queryServicePath || '/api/query').replace(/\/$/, '')
  const baseUrl = `${gatewayUrl}${queryPath}/leave-requests`

  async function createLeaveRequest(payload: {
    leave_type: string
    start_date: string
    end_date: string
    reason: string
    idempotency_key?: string
  }) {
    return await $fetch<{ id: string; status: string; approver_user_id?: string; days_count?: number }>(
      baseUrl,
      { method: 'POST', headers: getHRServiceAuthHeaders(), body: payload },
    )
  }

  async function cancelLeaveRequest(id: string) {
    return await $fetch<{ id: string; status: string }>(
      `${baseUrl}/${encodeURIComponent(id)}/cancel`,
      { method: 'POST', headers: getHRServiceAuthHeaders() },
    )
  }

  async function fetchPendingApprovals() {
    const res = await $fetch<{ items: any[]; count: number }>(`${baseUrl}/pending-approval`, {
      headers: getHRServiceAuthHeaders(),
    })
    return res.items ?? []
  }

  async function approveLeaveRequest(id: string) {
    return await $fetch<{ id: string; status: string }>(
      `${baseUrl}/${encodeURIComponent(id)}/approve`,
      { method: 'POST', headers: getHRServiceAuthHeaders() },
    )
  }

  async function rejectLeaveRequest(id: string, reason = '') {
    return await $fetch<{ id: string; status: string }>(
      `${baseUrl}/${encodeURIComponent(id)}/reject`,
      { method: 'POST', headers: getHRServiceAuthHeaders(), body: { reason } },
    )
  }

  return {
    createLeaveRequest,
    cancelLeaveRequest,
    fetchPendingApprovals,
    approveLeaveRequest,
    rejectLeaveRequest,
  }
}
