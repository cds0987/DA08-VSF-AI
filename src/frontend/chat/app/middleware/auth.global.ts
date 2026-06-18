import { useSessionStore } from '~/stores/session'

export default defineNuxtRouteMiddleware(async (to) => {
  const session = useSessionStore()

  // Lần đầu vào app (client): verify session với server qua /auth/me thay vì chỉ tin
  // session cookie. fetchMe() đi qua axiosClient nên nếu access token hết hạn mà refresh
  // token còn hợp lệ, nó tự refresh; nếu fail thì session store tự clear user -> về login.
  // Tránh trạng thái còn session.user nhưng access token đã mất/invalid.
  if (!session.isInitialized && import.meta.client && to.path !== '/login') {
    try {
      await session.fetchMe()
    } catch {
      // Bỏ qua: session store đã tự clear user, redirect bên dưới sẽ xử lý.
    }
  }

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
