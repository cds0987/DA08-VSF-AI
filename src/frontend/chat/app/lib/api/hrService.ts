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
  const baseUrl = `${gatewayUrl}/api/hr`

  async function createLeaveRequest(payload: {
    leave_type: string
    start_date: string
    end_date: string
    reason: string
  }) {
    return await $fetch<{ id: string; status: string }>(`${baseUrl}/internal/hr/leave-requests`, {
      method: 'POST',
      headers: getHRServiceAuthHeaders(),
      body: payload,
    })
  }

  async function fetchPendingApprovals() {
    return await $fetch<any[]>(`${baseUrl}/internal/hr/leave-requests/pending-approval`, {
      headers: getHRServiceAuthHeaders(),
    })
  }

  async function approveLeaveRequest(id: string) {
    return await $fetch<{ message: string }>(`${baseUrl}/internal/hr/leave-requests/${encodeURIComponent(id)}/approve`, {
      method: 'POST',
      headers: getHRServiceAuthHeaders(),
    })
  }

  async function rejectLeaveRequest(id: string) {
    return await $fetch<{ message: string }>(`${baseUrl}/internal/hr/leave-requests/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
      headers: getHRServiceAuthHeaders(),
    })
  }

  return {
    createLeaveRequest,
    fetchPendingApprovals,
    approveLeaveRequest,
    rejectLeaveRequest,
  }
}
