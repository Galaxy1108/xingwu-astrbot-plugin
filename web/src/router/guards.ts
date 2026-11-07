import type { RouteLocationRaw, Router } from 'vue-router'

export interface AuthSnapshot {
  ready: boolean
  isAuthenticated: boolean
  role: string | null
  status?: string | null
}

export interface GuardTarget {
  fullPath: string
  meta: {
    requiresAuth?: unknown
    guestOnly?: unknown
    role?: unknown
    public?: unknown
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

  // 被封禁用户：只允许 /banned 与 /login，其它页面一律回通知页
  if (auth.isAuthenticated && auth.status === 'disabled') {
    if (
      to.fullPath.startsWith('/banned') ||
      to.fullPath.startsWith('/login') ||
      to.fullPath.startsWith('/share/')
    ) {
      return true
    }
    return { path: '/banned' }
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
    // 公开分享页不探测会话，避免 401 把匿名访客带去登录页
    if (to.meta.public !== true) {
      try {
        await ensureLoaded()
      } catch {
        // 网络异常时按未登录处理，由登录页展示重试入口
      }
    }
    return resolveNavigation(to, getAuth())
  })

  router.afterEach((to) => {
    const title = typeof to.meta.title === 'string' ? to.meta.title : ''
    document.title = title ? `${title} · 栖语控制台` : '栖语控制台'
  })
}
