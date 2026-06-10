import axiosClient from './axiosClient'
import userService from './userService'
import type { AuditLogItem, AuditLogListResponse, AuditLogSource } from '~/types'

interface AuditLogApiItem {
  id: string
  actor_id: string
  actor_role: string
  action: string
  resource_type: string | null
  resource_id: string | null
  detail: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

interface AuditLogApiResponse {
  items: AuditLogApiItem[]
  total: number
}

const MAX_USER_LOOKUP = 200

const auditService = {
  async listAuditLogs(params?: { limit?: number; offset?: number }): Promise<AuditLogListResponse> {
    const limit = params?.limit ?? 50
    const offset = params?.offset ?? 0
    const fetchLimit = Math.min(limit + offset, 200)

    const [userAudit, documentAudit, users] = await Promise.all([
      axiosClient.get<AuditLogApiResponse>('/audit-logs', {
        params: { limit: fetchLimit, offset: 0 },
        service: 'user',
      }),
      axiosClient.get<AuditLogApiResponse>('/audit-logs', {
        params: { limit: fetchLimit, offset: 0 },
        service: 'document',
      }),
      userService.listUsers({ limit: MAX_USER_LOOKUP, offset: 0 }),
    ])

    const usersById = new Map(users.items.map((user) => [user.id, user.email]))
    const merged = [
      ...userAudit.data.items.map((item) => normalizeAuditItem(item, 'user-service', usersById)),
      ...documentAudit.data.items.map((item) => normalizeAuditItem(item, 'document-service', usersById)),
    ].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))

    return {
      items: merged.slice(offset, offset + limit),
      total: userAudit.data.total + documentAudit.data.total,
    }
  },
}

function normalizeAuditItem(
  item: AuditLogApiItem,
  source: AuditLogSource,
  usersById: Map<string, string>,
): AuditLogItem {
  const action = item.resource_type ? `${item.resource_type}.${item.action}` : item.action
  return {
    id: `${source}:${item.id}`,
    source,
    actor_id: item.actor_id,
    actor_email: usersById.get(item.actor_id) ?? item.actor_id,
    actor_role: item.actor_role,
    action,
    resource: formatResource(item),
    status: inferStatus(item.action),
    ip_address: item.ip_address,
    detail: item.detail,
    created_at: item.created_at,
  }
}

function formatResource(item: AuditLogApiItem): string {
  const detail = item.detail ?? {}
  if (typeof detail.name === 'string' && detail.name.trim().length > 0) {
    return detail.name
  }
  if (typeof detail.gcs_key === 'string' && detail.gcs_key.trim().length > 0) {
    return detail.gcs_key
  }
  if (item.resource_type === 'user') {
    return item.resource_id ?? item.actor_id
  }
  if (item.resource_type === 'document') {
    return item.resource_id ?? 'document'
  }
  return item.resource_type ?? 'system'
}

function inferStatus(action: string): AuditLogItem['status'] {
  if (action.includes('failed') || action.includes('error')) {
    return 'error'
  }
  if (action.includes('locked') || action.includes('denied')) {
    return 'denied'
  }
  return 'success'
}

export default auditService
