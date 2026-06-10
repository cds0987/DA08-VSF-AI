import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import type { ApiError, LoginResponse } from '~/types'
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
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
  timeout: 30000, // Increase timeout for uploads
})

axiosClient.interceptors.request.use(
  (config: CustomInternalAxiosRequestConfig) => {
    const runtimeConfig = useRuntimeConfig()
    const gatewayUrl = String(runtimeConfig.public.apiGatewayUrl || '').replace(/\/$/, '')
    config.baseURL = gatewayUrl

    // Tự động ghép đúng Base URL với các path prefix của từng service
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

    // Thêm Trace ID cho mỗi request (Quan trọng cho Observability)
    const requestId = crypto.randomUUID?.() || Math.random().toString(36).substring(2)
    config.headers['X-Request-ID'] = requestId

    // Đảm bảo gửi kèm Authorization-Gateway cho Nginx
    const gatewayAuth = runtimeConfig.public.gatewayBasicAuth
    if (gatewayAuth) {
      config.headers['Authorization-Gateway'] = gatewayAuth
    }

    if (import.meta.client) {
      // KHÔNG gửi token cũ vào các endpoint auth
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
  (error) => {
    return Promise.reject(error)
  },
)

axiosClient.interceptors.response.use(
  (response) => {
    return response
  },
  async (error: AxiosError<ApiError>) => {
    const originalRequest = error.config as CustomInternalAxiosRequestConfig
    const status = error.response?.status
    const detail = error.response?.data?.detail || 'Đã có lỗi xảy ra'

    // Tự động Refresh Token khi gặp lỗi 401
    if (status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/auth/login') && !originalRequest.url?.includes('/auth/refresh')) {
      originalRequest._retry = true
      
      const refreshToken = getClientCookie(REFRESH_TOKEN_COOKIE)
      if (refreshToken) {
        try {
          const runtimeConfig = useRuntimeConfig()
          const gatewayUrl = String(runtimeConfig.public.apiGatewayUrl || '').replace(/\/$/, '')
          const userPrefix = runtimeConfig.public.userServicePath || '/api/user'
          
          const refreshHeaders: Record<string, string> = {}
          const gatewayAuth = runtimeConfig.public.gatewayBasicAuth
          if (gatewayAuth) {
            refreshHeaders['Authorization-Gateway'] = gatewayAuth
          }
          
          const refreshRes = await axios.post<LoginResponse>(`${gatewayUrl}${userPrefix}/auth/refresh`, {
            refresh_token: refreshToken,
          }, {
            headers: refreshHeaders
          })

          const { access_token, refresh_token: new_refresh_token } = refreshRes.data
          
          if (access_token) {
            setClientCookie(ACCESS_TOKEN_COOKIE, access_token)
            if (new_refresh_token) {
              setClientCookie(REFRESH_TOKEN_COOKIE, new_refresh_token)
            }

            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${access_token}`
            }
            return axiosClient(originalRequest)
          }
        } catch (refreshError) {
          console.error('Refresh token failed:', refreshError)
        }
      }

      // Nếu không có refresh token hoặc refresh thất bại
      if (import.meta.client) {
        removeClientCookie(ACCESS_TOKEN_COOKIE)
        removeClientCookie(REFRESH_TOKEN_COOKIE)
        removeClientCookie(SESSION_COOKIE)
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
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
