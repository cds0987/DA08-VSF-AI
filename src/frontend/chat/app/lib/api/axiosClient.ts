import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import type { ApiError, LoginResponse } from '~/types'
import {
  ACCESS_TOKEN_COOKIE,
  SESSION_COOKIE,
  getClientCookie,
  removeClientCookie,
  setClientCookie,
} from '../cookie'

export interface CustomInternalAxiosRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
  service?: 'user' | 'document' | 'query' | 'hr' | 'mcp'
}

const axiosClient: AxiosInstance = axios.create({
  timeout: 30000,
})

// Đường dẫn /login phải tôn trọng NUXT_APP_BASE_URL — window.location.href
// tuyệt đối '/login' sẽ nhảy ra ngoài base path nếu app deploy dưới sub-path.
function getLoginPath(): string {
  const base = useRuntimeConfig().app.baseURL || '/'
  return `${base.replace(/\/$/, '')}/login`
}

// Dedup các lệnh refresh-token đồng thời: nhiều request 401 cùng lúc (vd nhiều
// tab, hoặc nhiều API call song song khi access token hết hạn) chỉ nên gọi
// /auth/refresh một lần — gọi nhiều lần dễ đua nhau làm rotate refresh token
// và khiến request đến sau bị fail oan, dẫn tới logout giả.
let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const runtimeConfig = useRuntimeConfig()
        const gatewayUrl = String(runtimeConfig.public.apiGatewayUrl || '').replace(/\/$/, '')
        const userPrefix = runtimeConfig.public.userServicePath || '/api/user'

        const refreshHeaders: Record<string, string> = {}
        const gatewayAuth = runtimeConfig.public.gatewayBasicAuth
        if (gatewayAuth) {
          refreshHeaders['Authorization-Gateway'] = gatewayAuth
        }

        // Browser gửi HttpOnly refresh token cookie tự động nhờ withCredentials
        const refreshRes = await axios.post<LoginResponse>(
          `${gatewayUrl}${userPrefix}/auth/refresh`,
          {},
          { headers: refreshHeaders, withCredentials: true },
        )
        return refreshRes.data.access_token || null
      } catch (refreshError) {
        console.error('Refresh token failed:', refreshError)
        return null
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

axiosClient.interceptors.request.use(
  (config: CustomInternalAxiosRequestConfig) => {
    const runtimeConfig = useRuntimeConfig()
    const gatewayUrl = String(runtimeConfig.public.apiGatewayUrl || '').replace(/\/$/, '')
    config.baseURL = gatewayUrl

    if (config.service && config.url && !config.url.startsWith('/api/')) {
      let prefix = ''
      switch (config.service) {
        case 'user': prefix = runtimeConfig.public.userServicePath || '/api/user'; break
        case 'document': prefix = runtimeConfig.public.documentServicePath || '/api/documents'; break
        case 'query': prefix = runtimeConfig.public.queryServicePath || '/api/query'; break
        case 'hr': prefix = runtimeConfig.public.hrServicePath || '/api/hr'; break
        case 'mcp': prefix = runtimeConfig.public.mcpServicePath || '/api/mcp'; break
      }
      const cleanUrl = config.url.startsWith('/') ? config.url : `/${config.url}`
      config.url = `${prefix}${cleanUrl}`
    }

    const requestId = crypto.randomUUID?.() || Math.random().toString(36).substring(2)
    config.headers['X-Request-ID'] = requestId

    const gatewayAuth = runtimeConfig.public.gatewayBasicAuth
    if (gatewayAuth) {
      config.headers['Authorization-Gateway'] = gatewayAuth
    }

    if (import.meta.client) {
      const isAuthEndpoint = config.url?.includes('/auth/login') || config.url?.includes('/auth/refresh') || config.url?.includes('/auth/token')

      if (!isAuthEndpoint) {
        const token = getClientCookie(ACCESS_TOKEN_COOKIE)
        if (token && config.headers) {
          config.headers.Authorization = `Bearer ${token}`
        }
      }
    }
    return config
  },
  (error) => Promise.reject(error),
)

axiosClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    const originalRequest = error.config as CustomInternalAxiosRequestConfig
    const status = error.response?.status
    const detail = error.response?.data?.detail || 'Đã có lỗi xảy ra'

    if (status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/auth/login') && !originalRequest.url?.includes('/auth/refresh')) {
      originalRequest._retry = true

      const access_token = await refreshAccessToken()
      if (access_token) {
        setClientCookie(ACCESS_TOKEN_COOKIE, access_token)
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${access_token}`
        }
        return axiosClient(originalRequest)
      }

      if (import.meta.client) {
        removeClientCookie(ACCESS_TOKEN_COOKIE)
        removeClientCookie(SESSION_COOKIE)
        const loginPath = getLoginPath()
        if (window.location.pathname !== loginPath) {
          window.location.href = loginPath
        }
      }
    }

    switch (status) {
      case 403:
        console.error('Forbidden:', detail)
        break
      case 423:
        console.error('Account Locked:', detail)
        break
      default:
        console.error('API Error:', detail)
    }

    return Promise.reject(error)
  },
)

export default axiosClient
