import axios from 'axios'
import type { ApiError } from '~/types'

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError<ApiError>(error)) return fallback

  const detail = error.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map(item => item.msg)
      .filter((message): message is string => typeof message === 'string' && message.length > 0)
    if (messages.length) return messages.join('; ')
  }
  return fallback
}

export function getApiStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined
}
