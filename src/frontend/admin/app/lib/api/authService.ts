import axiosClient from './axiosClient'
import type {
  LoginCredentials,
  LoginResponse,
  TokenCredentials,
  User,
} from '~/types'
import {
  ACCESS_TOKEN_COOKIE,
  SESSION_COOKIE,
  getClientCookie,
  removeClientCookie,
  setClientCookie,
} from '../cookie'

const authService = {
  async login(credentials: LoginCredentials): Promise<LoginResponse> {
    const response = await axiosClient.post<LoginResponse>(
      '/auth/admin/login',
      credentials,
      { service: 'user', withCredentials: true }
    )

    if (import.meta.client && response.data.access_token) {
      setClientCookie(ACCESS_TOKEN_COOKIE, response.data.access_token)
    }

    return response.data
  },

  async loginOAuth2(credentials: TokenCredentials): Promise<LoginResponse> {
    const params = new URLSearchParams()
    params.append('username', credentials.username)
    params.append('password', credentials.password)

    const response = await axiosClient.post<LoginResponse>(
      '/auth/token',
      params,
      {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        service: 'user',
        withCredentials: true,
      },
    )

    if (import.meta.client && response.data.access_token) {
      setClientCookie(ACCESS_TOKEN_COOKIE, response.data.access_token)
    }

    return response.data
  },

  async getMe(): Promise<User> {
    const response = await axiosClient.get<User>('/auth/me', { service: 'user' })
    return response.data
  },

  async logout(redirect = true): Promise<void> {
    if (!import.meta.client) return
    try {
      await axiosClient.post('/auth/logout', {}, { service: 'user', withCredentials: true })
    } catch {
      // best-effort — clear cookies regardless
    }
    removeClientCookie(ACCESS_TOKEN_COOKIE)
    removeClientCookie(SESSION_COOKIE)
    if (redirect) window.location.href = '/login'
  },

  isAuthenticated(): boolean {
    if (typeof window === 'undefined') return false
    return !!getClientCookie(ACCESS_TOKEN_COOKIE)
  },
}

export default authService
