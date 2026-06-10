import type { AdminMetrics } from '~/types'
import { ACCESS_TOKEN_COOKIE, getClientCookie } from '../cookie'

function authHeaders(): Record<string, string> {
  const token = getClientCookie(ACCESS_TOKEN_COOKIE)
  if (!token) {
    throw new Error('Not authenticated')
  }
  return { Authorization: `Bearer ${token}` }
}

export function useQueryService() {
  const config = useRuntimeConfig()
  const gatewayUrl = String(config.public.apiGatewayUrl || '').replace(/\/$/, '')
  const queryPath = config.public.queryServicePath || '/api/query'
  const baseUrl = `${gatewayUrl}${queryPath}`

  async function getAdminMetrics(from?: string, to?: string) {
    return await $fetch<AdminMetrics>(`${baseUrl}/admin/metrics`, {
      headers: authHeaders(),
      query: {
        ...(from ? { from } : {}),
        ...(to ? { to } : {}),
      },
    })
  }

  return { getAdminMetrics }
}
