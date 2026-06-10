import { useSessionStore } from '~/stores/session'

function joinAppUrl(baseUrl: unknown, path: string) {
  const base = String(baseUrl || '').replace(/\/$/, '')
  return base ? `${base}${path}` : path
}

export default defineNuxtRouteMiddleware((to) => {
  const session = useSessionStore()
  const config = useRuntimeConfig()
  const appKind = String(config.public.appKind || 'base')

  if (to.path === '/login') {
    if (!session.user) return

    if (session.user.role === 'admin') {
      const adminPath = '/'
      if (appKind === 'admin') return navigateTo(adminPath)
      return navigateTo(joinAppUrl(config.public.adminAppUrl, adminPath), { external: true })
    }

    const chatPath = '/chat'
    if (appKind === 'chat') return navigateTo(chatPath)
    return navigateTo(joinAppUrl(config.public.chatAppUrl, chatPath), { external: true })
  }

  if (!session.user) {
    return navigateTo('/login')
  }

  if (appKind === 'admin' && session.user.role !== 'admin') {
    return navigateTo(joinAppUrl(config.public.chatAppUrl, '/chat'), { external: true })
  }

  if (appKind === 'chat' && session.user.role === 'admin') {
    return navigateTo(joinAppUrl(config.public.adminAppUrl, '/'), { external: true })
  }
})
