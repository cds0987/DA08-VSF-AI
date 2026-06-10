import { useSessionStore } from '~/stores/session'

export default defineNuxtRouteMiddleware(async (to) => {
  const session = useSessionStore()

  // Khởi tạo session từ server nếu chưa có (lần đầu vào app)
  // Bỏ qua nếu đang ở trang login để tránh loop
  if (!session.isInitialized && import.meta.client && to.path !== '/login') {
    try {
      await session.fetchMe()
    } catch (e) {
      // Bỏ qua lỗi, session store sẽ tự clear user
    }
  }

  if (to.path === '/login') {
    if (session.isAdmin) {
      return navigateTo('/')
    }
    return
  }

  if (!session.isAuthenticated) {
    return navigateTo('/login')
  }

  if (!session.isAdmin) {
    session.signOut()
    return navigateTo('/login?error=forbidden')
  }
})
