import axios from 'axios'
import type { LoginResponse } from '~/types'
import {
  ACCESS_TOKEN_COOKIE,
  SESSION_COOKIE,
  removeClientCookie,
  setClientCookie,
} from '../cookie'

// Helper refresh-token DÙNG CHUNG cho mọi đường request KHÔNG đi qua interceptor của
// axiosClient (fetchEventSource cho /query và /notifications, $fetch trong queryService
// và hrService) — và cả chính axiosClient, để toàn app chỉ có MỘT chính sách refresh.

/**
 * Đọc HTTP status từ nhiều shape lỗi khác nhau:
 * - axios AxiosError: `response.status` (và đôi khi `status`)
 * - ofetch/$fetch FetchError: `status` và/hoặc `statusCode` (tùy version)
 * - QueryServiceError / HRServiceError: `.status`
 * Trả undefined nếu không xác định được — KHÔNG đoán 401.
 */
export function getErrorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined
  const e = error as {
    status?: unknown
    statusCode?: unknown
    response?: { status?: unknown }
  }
  const candidates = [e.status, e.statusCode, e.response?.status]
  for (const c of candidates) {
    if (typeof c === 'number') return c
  }
  return undefined
}

// Dedup các lệnh refresh đồng thời: nhiều request 401 cùng lúc (nhiều $fetch, SSE, axios
// song song) chỉ nên gọi /auth/refresh MỘT lần. Gọi nhiều lần dễ đua nhau làm rotate
// refresh token và khiến request đến sau fail oan -> logout giả.
let refreshPromise: Promise<string | null> | null = null

/**
 * Gọi /auth/refresh (tối đa một lần đồng thời nhờ dedup). Khi thành công lưu access token
 * mới vào cookie và trả về token đó. Khi thất bại trả null (KHÔNG tự logout — để caller
 * quyết định, vì nhánh refresh-fail mới là lúc logout thật, giống axiosClient).
 */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const config = useRuntimeConfig()
        const gatewayUrl = String(config.public.apiGatewayUrl || '').replace(/\/$/, '')
        const userPrefix = String(config.public.userServicePath || '/api/user')

        const headers: Record<string, string> = {}
        const gatewayAuth = config.public.gatewayBasicAuth
        if (gatewayAuth) headers['Authorization-Gateway'] = String(gatewayAuth)

        // Browser tự gửi HttpOnly refresh token cookie nhờ withCredentials.
        const res = await axios.post<LoginResponse>(
          `${gatewayUrl}${userPrefix}/auth/refresh`,
          {},
          { headers, withCredentials: true, timeout: 10000 },
        )
        const token = res.data.access_token || null
        if (token && import.meta.client) setClientCookie(ACCESS_TOKEN_COOKIE, token)
        return token
      } catch (error) {
        console.error('Refresh token failed:', error)
        return null
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

// Đường dẫn /login phải tôn trọng NUXT_APP_BASE_URL — '/login' tuyệt đối sẽ nhảy ra
// ngoài base path nếu app deploy dưới sub-path.
function getLoginPath(): string {
  const base = useRuntimeConfig().app.baseURL || '/'
  return `${base.replace(/\/$/, '')}/login`
}

/**
 * Refresh thất bại THẬT SỰ (refresh token hết hạn/invalid) -> logout: xóa cookie và chuyển
 * về login (giống axiosClient). Chỉ gọi ở nhánh refresh-fail, KHÔNG logout khi refresh
 * token còn hợp lệ.
 */
export async function handleRefreshFailure(): Promise<void> {
  if (!import.meta.client) return
  removeClientCookie(ACCESS_TOKEN_COOKIE)
  removeClientCookie(SESSION_COOKIE)
  const loginPath = getLoginPath()
  if (window.location.pathname !== loginPath) {
    // Thông báo trước khi redirect để user không bị mất trắng context.
    const { toast } = await import('vue-sonner')
    toast.warning('Phiên đăng nhập đã hết hạn. Đang chuyển về trang đăng nhập...')
    setTimeout(() => { window.location.href = loginPath }, 1500)
  }
}

/**
 * Bọc một lời gọi $fetch/ofetch: nếu gặp 401, refresh một lần rồi retry đúng MỘT lần.
 * Nếu refresh thất bại -> logout (handleRefreshFailure) và ném lại lỗi gốc.
 */
export async function withTokenRefresh<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (error) {
    if (getErrorStatus(error) !== 401) throw error
    const token = await refreshAccessToken()
    if (!token) {
      await handleRefreshFailure()
      throw error
    }
    return fn()
  }
}
