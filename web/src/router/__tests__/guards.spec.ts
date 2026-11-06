import { describe, expect, it } from 'vitest'
import { resolveNavigation, type AuthSnapshot, type GuardTarget } from '../guards'

function target(meta: GuardTarget['meta'], fullPath = '/bots'): GuardTarget {
  return { fullPath, meta }
}

const anonymous: AuthSnapshot = { ready: true, isAuthenticated: false, role: null }
const user: AuthSnapshot = { ready: true, isAuthenticated: true, role: 'user' }
const admin: AuthSnapshot = { ready: true, isAuthenticated: true, role: 'admin' }

describe('路由守卫 · 未登录（401 后 store 已清空）', () => {
  it('访问受保护页面重定向到 /login 并携带 redirect', () => {
    const result = resolveNavigation(target({ requiresAuth: true }, '/bots/b_1?qr=1'), anonymous)
    expect(result).toEqual({ path: '/login', query: { redirect: '/bots/b_1?qr=1' } })
  })

  it('公开页面（登录页）直接放行', () => {
    expect(resolveNavigation(target({ guestOnly: true }, '/login'), anonymous)).toBe(true)
  })

  it('未登录访问 /admin 同样跳登录', () => {
    const result = resolveNavigation(target({ requiresAuth: true, role: 'admin' }, '/admin/users'), anonymous)
    expect(result).toEqual({ path: '/login', query: { redirect: '/admin/users' } })
  })
})

describe('路由守卫 · 角色（403）', () => {
  it('普通用户访问管理员页面 → /403（不静默跳首页）', () => {
    const result = resolveNavigation(target({ requiresAuth: true, role: 'admin' }, '/admin/templates'), user)
    expect(result).toEqual({ path: '/403' })
  })

  it('管理员访问管理员页面放行', () => {
    expect(resolveNavigation(target({ requiresAuth: true, role: 'admin' }, '/admin/templates'), admin)).toBe(true)
  })

  it('普通用户访问用户页面放行', () => {
    expect(resolveNavigation(target({ requiresAuth: true }, '/bots'), user)).toBe(true)
  })

  it('/403 页面本身不要求角色，普通用户可停留', () => {
    expect(resolveNavigation(target({ requiresAuth: true }, '/403'), user)).toBe(true)
  })

  it('管理员访问登录页（guestOnly）→ 首页', () => {
    expect(resolveNavigation(target({ guestOnly: true }, '/login'), admin)).toEqual({ path: '/' })
  })
})
