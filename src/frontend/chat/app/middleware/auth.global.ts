import { useSessionStore } from '~/stores/session'

export default defineNuxtRouteMiddleware((to) => {
  const session = useSessionStore()

  if (to.path === '/login') {
    if (session.user) {
      return navigateTo('/chat')
    }
    return
  }

  if (!session.user) {
    return navigateTo('/login')
  }
})
