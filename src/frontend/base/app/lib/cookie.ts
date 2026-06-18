// ⚠️ DEPRECATED — layer base không được dùng/import (xem frontend/base/README.md).
// Tên cookie ở đây KHÁC chat/admin: dùng nhầm sẽ đọc/ghi sai cookie. Auth thật nằm ở
// frontend/chat & frontend/admin (app/lib/cookie.ts + app/lib/api/authRefresh.ts).
export const ACCESS_TOKEN_COOKIE = 'access_token'
export const SESSION_COOKIE = 'eka.session.user'

export function getClientCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'))
  if (match) return match[2]
  return null
}

export function setClientCookie(name: string, value: string, maxAgeSeconds: number = 2592000) {
  if (typeof document !== 'undefined') {
    document.cookie = `${name}=${value}; path=/; max-age=${maxAgeSeconds}; SameSite=Lax`
  }
}

export function removeClientCookie(name: string) {
  if (typeof document !== 'undefined') {
    document.cookie = `${name}=; path=/; max-age=0; SameSite=Lax`
  }
}
