import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import type { ApiError } from '~/types'
import { getClientCookie, removeClientCookie } from '../cookie'

export interface CustomInternalAxiosRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
  service?: 'user' | 'document' | 'query' | 'hr' | 'mcp'
}

// Dynamically set baseURL
const getGatewayUrl = () => {
  if (import.meta.client) {
    // @ts-ignore
    return import.meta.env.VITE_API_GATEWAY_URL || ''
  }
  return process.env.NUXT_PUBLIC_API_GATEWAY_URL || ''
}

const getGatewayAuth = () => {
  if (import.meta.client) {
    // @ts-ignore
    return import.meta.env.VITE_GATEWAY_BASIC_AUTH || ''
  }
  return process.env.NUXT_PUBLIC_GATEWAY_BASIC_AUTH || ''
}

const getServicePrefix = (service: 'user' | 'document' | 'query' | 'hr' | 'mcp'): string => {
  if (import.meta.client) {
    // @ts-ignore
    switch (service) {
      case 'user': return import.meta.env.VITE_USER_SERVICE_PATH || '/api/user'
      case 'document': return import.meta.env.VITE_DOCUMENT_SERVICE_PATH || '/api/documents'
      case 'query': return import.meta.env.VITE_QUERY_SERVICE_PATH || '/api/query'
      case 'hr': return import.meta.env.VITE_HR_SERVICE_PATH || '/api/hr'
      case 'mcp': return import.meta.env.VITE_MCP_SERVICE_PATH || '/api/mcp'
    }
  }
  switch (service) {
    case 'user': return process.env.NUXT_PUBLIC_USER_SERVICE_PATH || '/api/user'
    case 'document': return process.env.NUXT_PUBLIC_DOCUMENT_SERVICE_PATH || '/api/documents'
    case 'query': return process.env.NUXT_PUBLIC_QUERY_SERVICE_PATH || '/api/query'
    case 'hr': return process.env.NUXT_PUBLIC_HR_SERVICE_PATH || '/api/hr'
    case 'mcp': return process.env.NUXT_PUBLIC_MCP_SERVICE_PATH || '/api/mcp'
  }
  return ''
}

const axiosClient: AxiosInstance = axios.create({
  baseURL: getGatewayUrl(),
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // Tăng timeout cho RAG tasks
})

axiosClient.interceptors.request.use(
  (config: CustomInternalAxiosRequestConfig) => {
    config.baseURL = getGatewayUrl()

    // Tự động ghép đúng Base URL với các path prefix của từng service
    if (config.service && config.url && !config.url.startsWith('/api/')) {
      const prefix = getServicePrefix(config.service)
      const cleanUrl = config.url.startsWith('/') ? config.url : `/${config.url}`
      config.url = `${prefix}${cleanUrl}`
    }

    // Thêm Trace ID cho mỗi request để dễ debug
    const requestId = crypto.randomUUID?.() || Math.random().toString(36).substring(2)
    config.headers['X-Request-ID'] = requestId

    // Gắn Basic Auth cho Gateway nếu có (Đọc từ ENV để bảo mật)
    const gatewayAuth = getGatewayAuth()
    if (gatewayAuth) {
      config.headers['Authorization-Gateway'] = gatewayAuth
    }

    if (process.client) {
      const token = getClientCookie('access_token')
      if (token && config.headers) {
        config.headers.Authorization = `Bearer ${token}`
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
  (error: AxiosError<ApiError>) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || 'Đã có lỗi xảy ra'

    switch (status) {
      case 401:
        if (process.client) {
          removeClientCookie('access_token')
          removeClientCookie('eka.session.user')
          if (window.location.pathname !== '/login') {
            window.location.href = '/login'
          }
        }
        break

      case 403:
      case 423:
        console.error('API Error:', detail)
        break

      default:
        console.error('API Error:', detail)
    }

    return Promise.reject(error)
  },
)

export default axiosClient
