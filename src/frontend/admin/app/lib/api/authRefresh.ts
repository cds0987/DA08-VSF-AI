import axios from 'axios'
import type { LoginResponse } from '~/types'
import {
  ACCESS_TOKEN_COOKIE,
  SESSION_COOKIE,
  removeClientCookie,
  setClientCookie,
} from '../cookie'

// Helper refresh-token DÙNG CHUNG cho admin app (song song với bản chat) — gom mọi đường
// request về MỘT chính sách refresh. Admin dùng endpoint + cookie RIÊNG để độc lập hoàn
// toàn với chat (xem _ADMIN_REFRESH_COOKIE / /auth/admin/refresh ở user-service).

/**
 * Đọc HTTP status từ nhiều shape lỗi khác nhau: axios (`response.status`/`status`),
 * ofetch FetchError (`status`/`statusCode`), *ServiceError (`.status`). Trả undefined
 * nếu không xác định được — KHÔNG đoán 401.
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

// Dedup các lệnh refresh đồng thời: nhiều request 401 cùng lúc chỉ nên gọi
// /auth/admin/refresh MỘT lần — gọi nhiều lần dễ đua nhau rotate refresh token và làm
// request đến sau fail oan -> logout giả.
let refreshPromise: Promise<string | null> | null = null

/**
 * Gọi /auth/admin/refresh (dedup). Thành công: lưu access token mới vào cookie admin và
 * trả token; thất bại: trả null (KHÔNG tự logout — caller quyết định).
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

        // Browser tự gửi HttpOnly cookie eka.admin.refresh_token nhờ withCredentials.
        const res = await axios.post<LoginResponse>(
          `${gatewayUrl}${userPrefix}/auth/admin/refresh`,
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

// Đường dẫn /login phải tôn trọng NUXT_APP_BASE_URL (admin deploy ở /admin/) — '/login'
// tuyệt đối sẽ nhảy ra ngoài base path và bị nginx route catch-all sang app chat.
function getLoginPath(): string {
  const base = useRuntimeConfig().app.baseURL || '/'
  return `${base.replace(/\/$/, '')}/login`
}

/**
 * Refresh thất bại THẬT SỰ -> logout: xóa cookie admin và chuyển về login. Chỉ gọi ở
 * nhánh refresh-fail, KHÔNG logout khi refresh token còn hợp lệ.
 */
export function handleRefreshFailure(): void {
  if (!import.meta.client) return
  removeClientCookie(ACCESS_TOKEN_COOKIE)
  removeClientCookie(SESSION_COOKIE)
  const loginPath = getLoginPath()
  if (window.location.pathname !== loginPath) {
    window.location.href = loginPath
  }
}

/**
 * Bọc một lời gọi $fetch/ofetch: nếu 401, refresh một lần rồi retry. Nếu refresh thất
 * bại -> logout và ném lại lỗi gốc.
 */
export async function withTokenRefresh<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (error) {
    if (getErrorStatus(error) !== 401) throw error
    const token = await refreshAccessToken()
    if (!token) {
      handleRefreshFailure()
      throw error
    }
    return fn()
  }
}
