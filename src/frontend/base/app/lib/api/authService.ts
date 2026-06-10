import axiosClient from './axiosClient'
import type {
  LoginCredentials,
  LoginResponse,
  TokenCredentials,
  User,
} from '~/types'
import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  SESSION_COOKIE,
  getClientCookie,
  removeClientCookie,
  setClientCookie,
} from '../cookie'

const authService = {
  async login(credentials: LoginCredentials): Promise<LoginResponse> {
    const response = await axiosClient.post<LoginResponse>(
      '/auth/login',
      credentials,
      { service: 'user' }
    )

    if (process.client && response.data.access_token) {
      setClientCookie(ACCESS_TOKEN_COOKIE, response.data.access_token)
      if (response.data.refresh_token) {
        setClientCookie(REFRESH_TOKEN_COOKIE, response.data.refresh_token)
      }
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
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        service: 'user'
      },
    )

    if (process.client && response.data.access_token) {
      setClientCookie(ACCESS_TOKEN_COOKIE, response.data.access_token)
      if (response.data.refresh_token) {
        setClientCookie(REFRESH_TOKEN_COOKIE, response.data.refresh_token)
      }
    }

    return response.data
  },

  async getMe(): Promise<User> {
    const response = await axiosClient.get<User>('/auth/me', { service: 'user' })
    return response.data
  },

  logout(): void {
    if (process.client) {
      removeClientCookie(ACCESS_TOKEN_COOKIE)
      removeClientCookie(REFRESH_TOKEN_COOKIE)
      removeClientCookie(SESSION_COOKIE)
      window.location.href = '/login'
    }
  },

  isAuthenticated(): boolean {
    if (typeof window === 'undefined') return false
    return !!getClientCookie(ACCESS_TOKEN_COOKIE)
  },
}

export default authService
