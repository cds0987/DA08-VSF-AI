import { defineStore } from 'pinia'
import type { User } from '~/types'
import { SESSION_COOKIE } from '~/lib/cookie'
import authService from '~/lib/api/authService'

export const useSessionStore = defineStore('session', () => {
  const user = useCookie<User | null>(SESSION_COOKIE, {
    default: () => null,
    watch: true,
    sameSite: 'lax',
    path: '/',
    // Persistent (không phải session-cookie) -> còn đăng nhập sau khi đóng browser.
    // Khớp TTL refresh token (REFRESH_TOKEN_TTL_DAYS=30); watch:true gia hạn sliding mỗi fetchMe.
    maxAge: 60 * 60 * 24 * 30,
  })
  const isLoading = ref(false)
  const isInitialized = ref(false)

  const isAuthenticated = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function fetchMe() {
    if (isLoading.value) return
    
    isLoading.value = true
    try {
      const userData = await authService.getMe()
      user.value = userData
      return userData
    } catch (error) {
      user.value = null
      throw error
    } finally {
      isLoading.value = false
      isInitialized.value = true
    }
  }

  function signIn(userData: User) {
    user.value = userData
  }

  function signOut() {
    user.value = null
    authService.logout(true)
  }

  return {
    user,
    isLoading,
    isInitialized,
    isAuthenticated,
    isAdmin,
    fetchMe,
    signIn,
    signOut,
  }
})
