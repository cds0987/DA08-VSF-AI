import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import type { ApiError } from '~/types'
import { ACCESS_TOKEN_COOKIE, getClientCookie, setClientCookie } from '../cookie'
import { handleRefreshFailure, refreshAccessToken } from './authRefresh'

export interface CustomInternalAxiosRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
  service?: 'user' | 'document' | 'query' | 'hr' | 'mcp'
}

const axiosClient: AxiosInstance = axios.create({
  timeout: 30000,
})

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

      // Refresh thất bại thật sự -> logout dùng chung với các đường request khác.
      await handleRefreshFailure()
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
