import { createHmac } from 'node:crypto'

type SessionUser = {
  id: string
  name: string
  email: string
  role: 'admin' | 'user'
  department: string
  initials: string
}

const ONE_HOUR_SECONDS = 60 * 60

function base64url(input: string | Buffer) {
  return Buffer.from(input).toString('base64url')
}

export function mintJwt(user: SessionUser, jwtSecret: string) {
  const now = Math.floor(Date.now() / 1000)
  const header = base64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = base64url(JSON.stringify({
    sub: user.id,
    email: user.email,
    role: user.role,
    department: user.department,
    is_active: true,
    exp: now + ONE_HOUR_SECONDS,
  }))
  const signature = createHmac('sha256', jwtSecret)
    .update(`${header}.${payload}`)
    .digest('base64url')
  return `${header}.${payload}.${signature}`
}

export function encodeSessionCookie(user: SessionUser) {
  return encodeURIComponent(JSON.stringify(user))
}

export const adminUser: SessionUser = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Cloud Admin',
  email: 'admin@company.com',
  role: 'admin',
  department: 'IT',
  initials: 'CA',
}

export const chatUser: SessionUser = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Cloud User',
  email: 'user@company.com',
  role: 'user',
  department: 'HR',
  initials: 'CU',
}
