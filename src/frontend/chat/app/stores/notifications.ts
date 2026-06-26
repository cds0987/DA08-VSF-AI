import { defineStore } from 'pinia'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { toast } from 'vue-sonner'
import type { NotificationEvent, NotificationItem } from '~/types'
import { useSessionStore } from './session'
import { ACCESS_TOKEN_COOKIE, getClientCookie } from '~/lib/cookie'
import {
  QueryServiceError,
  assertQueryServiceResponse,
  getQueryServiceAuthHeaders,
  useQueryService,
} from '~/lib/api/queryService'
import { handleRefreshFailure, refreshAccessToken } from '~/lib/api/authRefresh'

const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000]

function logNotificationError(context: string, error: unknown) {
  if (error instanceof QueryServiceError && error.status === 401) return
  console.error(context, error instanceof Error ? error.message : String(error))
}

function isNotificationEvent(value: unknown): value is NotificationEvent {
  const event = value as Partial<NotificationEvent>
  return typeof value === 'object'
    && value !== null
    && event.type === 'notify'
    && ['doc_new', 'leave_request_new', 'leave_approved', 'leave_rejected', 'leave_cancelled'].includes(event.event ?? '')
    && typeof event.message === 'string'
}

export const useNotificationStore = defineStore('notifications', () => {
  const queryService = useQueryService()
  const session = useSessionStore()
  const isConnected = ref(false)
  const items = ref<NotificationItem[]>([])
  const unreadCount = ref(0)
  const total = ref(0)
  const isLoading = ref(false)
  let controller: AbortController | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempt = 0
  let stopped = true
  let started = false

  async function fetchHistory(limit = 20, offset = 0, unreadOnly = false) {
    isLoading.value = true
    try {
      const data = await queryService.fetchHistory(limit, offset, unreadOnly)
      items.value = data.items.filter(item => !dismissedIds.has(item.id))
      total.value = data.total
    } finally {
      isLoading.value = false
    }
  }

  async function fetchUnreadCount() {
    const data = await queryService.fetchUnreadCount()
    unreadCount.value = data.unread
  }

  async function markAsRead(id: string) {
    const index = items.value.findIndex((item) => item.id === id)
    const previous = index >= 0 ? items.value[index] : undefined
    if (previous?.is_read) return

    if (previous) {
      items.value[index] = { ...previous, is_read: true }
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }

    try {
      const updated = await queryService.markNotificationRead(id)
      if (index >= 0) items.value[index] = updated
      await fetchUnreadCount()
    } catch (error) {
      if (previous && index >= 0) items.value[index] = previous
      await fetchUnreadCount().catch(() => undefined)
      throw error
    }
  }

  function scheduleReconnect() {
    if (stopped || !session.user || reconnectTimer) return
    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)]
    reconnectAttempt += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      void connect()
    }, delay)
  }

  async function reconcileNotification(event: NotificationEvent) {
    // Check for duplicates
    if (items.value.some((item) => item.id === event.id)) return

    toast.info(event.message, {
      description: 'Tài liệu đã được cập nhật vào hệ thống.',
      duration: 5000,
    })

    const newItem: NotificationItem = {
      id: event.id,
      event: event.event,
      message: event.message,
      doc_id: event.doc_id,
      is_read: event.is_read,
      created_at: event.created_at,
    }

    // Add to the beginning of the list
    items.value.unshift(newItem)
    total.value += 1
    if (!newItem.is_read) {
      unreadCount.value += 1
    }
  }

  async function fetchMissingNotifications() {
    if (!session.user || isFetchingMissing) return
    isFetchingMissing = true
    
    // Find the latest timestamp we have
    const lastSeenTimestamp = items.value.length > 0 
      ? items.value[0].created_at 
      : undefined

    try {
      // Fetch only notifications created AFTER our latest one
      const data = await queryService.fetchHistory(100, 0, false, lastSeenTimestamp)
      
      if (data.items.length > 0) {
        // Filter out any items we might already have (safety check)
        const existingIds = new Set(items.value.map(i => i.id))
        const newItems = data.items.filter(item => !existingIds.has(item.id) && !dismissedIds.has(item.id))
        
        if (newItems.length > 0) {
          // Add new items to the beginning and sort by date descending
          items.value = [...newItems, ...items.value].sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )
        }
        
        // Refresh unread count
        await fetchUnreadCount()
      }
    } catch (error) {
      logNotificationError('Failed to fetch missing notifications:', error)
    } finally {
      isFetchingMissing = false
    }
  }

  const handleOnline = () => {
    // Hủy timer đang chờ và reconnect ngay — không cần đợi delay khi biết mạng đã về.
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    reconnectAttempt = 0
    void fetchMissingNotifications()
    if (!controller) void connect()
  }

  const handleOffline = () => {
    isConnected.value = false
  }

  async function connect() {
    if (stopped || controller || !session.user) return

    const currentController = new AbortController()
    controller = currentController
    try {
      await fetchEventSource(`${queryService.baseUrl}/notifications`, {
        method: 'GET',
        headers: getQueryServiceAuthHeaders(),
        signal: currentController.signal,
        openWhenHidden: true,
        async onopen(response) {
          await assertQueryServiceResponse(response)
          isConnected.value = true
          reconnectAttempt = 0
          // Trigger sync on every connection open as well
          void fetchMissingNotifications()
        },
        onmessage(message) {
          if (!message.data) return
          const payload: unknown = JSON.parse(message.data)
          if (isNotificationEvent(payload)) {
            void reconcileNotification(payload).catch((error) => {
              logNotificationError('Failed to reconcile notification:', error)
            })
          }
        },
        onclose() {
          if (!currentController.signal.aborted) scheduleReconnect()
        },
        onerror(error) {
          throw error
        },
      })
    } catch (error) {
      if (!currentController.signal.aborted) {
        if (error instanceof QueryServiceError && error.status === 401) {
          // Access token hết hạn: thử refresh MỘT lần (dedup chung toàn app). Nếu được
          // thì reconnect (connect() đọc lại token mới từ cookie); nếu refresh thất bại
          // thật sự mới logout — tránh để notification stream chết oan khi refresh token
          // còn hợp lệ.
          const token = await refreshAccessToken()
          if (token) {
            scheduleReconnect()
          } else {
            started = false
            stopped = true
            await handleRefreshFailure()
          }
        } else {
          scheduleReconnect()
        }
      }
    } finally {
      if (controller === currentController) controller = null
      isConnected.value = false
    }
  }

  const dismissedIds = new Set<string>()
  let initRetryCount = 0
  let initRetryTimer: ReturnType<typeof setTimeout> | null = null
  let isFetchingMissing = false

  async function init() {
    if (!import.meta.client || !session.user) {
      initRetryCount = 0
      return
    }
    if (started) return

    const token = getClientCookie(ACCESS_TOKEN_COOKIE)
    if (!token) {
      if (initRetryCount < 3 && !initRetryTimer) {
        initRetryCount++
        initRetryTimer = setTimeout(() => {
          initRetryTimer = null
          void init()
        }, 500)
      }
      return
    }

    initRetryCount = 0
    started = true
    stopped = false
    items.value = []
    unreadCount.value = 0

    if (import.meta.client) {
      window.addEventListener('online', handleOnline)
      window.addEventListener('offline', handleOffline)
    }
    
    await Promise.all([
      fetchHistory().catch((error) => {
        logNotificationError('Failed to fetch notification history:', error)
      }),
      fetchUnreadCount().catch((error) => {
        logNotificationError('Failed to fetch unread count:', error)
      }),
    ])
    await connect()
  }

  function stop() {
    started = false
    stopped = true
    controller?.abort()
    controller = null
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = null
    if (initRetryTimer) clearTimeout(initRetryTimer)
    initRetryTimer = null
    initRetryCount = 0
    reconnectAttempt = 0
    isFetchingMissing = false
    isConnected.value = false
    items.value = []
    unreadCount.value = 0
    dismissedIds.clear()

    if (import.meta.client) {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }

  function removeItem(id: string) {
    dismissedIds.add(id)
    items.value = items.value.filter((item) => item.id !== id)
  }

  return {
    isConnected,
    items,
    unreadCount,
    total,
    isLoading,
    init,
    stop,
    fetchHistory,
    fetchUnreadCount,
    markAsRead,
    removeItem,
  }
})
