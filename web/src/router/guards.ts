import type { RouteLocationRaw, Router } from 'vue-router'

export interface AuthSnapshot {
  ready: boolean
  isAuthenticated: boolean
  role: string | null
}

export interface GuardTarget {
  fullPath: string
  meta: {
    requiresAuth?: unknown
    guestOnly?: unknown
    role?: unknown
  }
}

/**
 * 纯函数守卫：方便单测覆盖 401/403 行为。
 * - requiresAuth 且未登录 → /login?redirect=...
 * - meta.role 与当前角色不符 → /403（不静默跳首页）
 * - guestOnly 且已登录 → /
 */
export function resolveNavigation(to: GuardTarget, auth: AuthSnapshot): true | RouteLocationRaw {
  const requiresAuth = to.meta.requiresAuth === true

  if (requiresAuth && !auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  const requiredRole = typeof to.meta.role === 'string' ? to.meta.role : null
  if (requiredRole && auth.isAuthenticated && auth.role !== requiredRole) {
    return { path: '/403' }
  }

  if (to.meta.guestOnly === true && auth.isAuthenticated) {
    return { path: '/' }
  }

  return true
}

export function installGuards(
  router: Router,
  getAuth: () => AuthSnapshot,
  ensureLoaded: () => Promise<void>,
): void {
  router.beforeEach(async (to) => {
    try {
      await ensureLoaded()
    } catch {
      // 网络异常时按未登录处理，由登录页展示重试入口
    }
    return resolveNavigation(to, getAuth())
  })

  router.afterEach((to) => {
    const title = typeof to.meta.title === 'string' ? to.meta.title : ''
    document.title = title ? `${title} · AstrBot 控制台` : 'AstrBot 控制台'
  })
}
