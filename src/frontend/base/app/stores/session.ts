import { defineStore } from 'pinia'
import type { User } from '~/types'
import authService from '../lib/api/authService'

const STORAGE_KEY = 'eka.session.user'

export const useSessionStore = defineStore('session', () => {
  const user = useCookie<User | null>(STORAGE_KEY, {
    default: () => null,
    watch: true,
    sameSite: 'lax',
    path: '/',
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
    authService.logout()
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
