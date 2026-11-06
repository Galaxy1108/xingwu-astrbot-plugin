import { test, expect } from '@playwright/test'
import {
  ADMIN_EMAIL,
  createInvite,
  csrfHeaders,
  navLink,
  newAdminApi,
  shot,
  registerUserApi,
  uiLogin,
  uniqueEmail,
} from '../helpers/api'

/**
 * D（前端部分）：登录守卫 / 角色守卫 / 会话被禁用后的 401 处理。
 * E 的前半段：OTP 登录（dev_code 由登录页提示展示）。
 */
test.describe('认证与访问控制（浏览器）', () => {
  test('未登录直接访问 /console/bots 应跳转 /console/login 并带 redirect', async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()
    try {
      await page.goto('/console/bots')
      await expect(page).toHaveURL(/\/console\/login\?redirect=/, { timeout: 20_000 })
      await expect(page.getByRole('heading', { name: '登录控制台' })).toBeVisible()
      const url = new URL(page.url())
      expect(url.searchParams.get('redirect')).toBe('/bots')
      // 前端不得把会话/token 放进 localStorage
      const storageKeys = await page.evaluate(() => Object.keys(window.localStorage))
      expect(storageKeys).toEqual([])
    } finally {
      await context.close()
    }
  })

  test('普通用户访问 /console/admin/users 应到 /403（不静默跳首页）', async ({ browser }) => {
    const admin = await newAdminApi()
    const invite = await createInvite(admin)
    const user = await registerUserApi(invite)
    const context = await browser.newContext({ storageState: await user.api.storageState() })
    const page = await context.newPage()
    try {
      await page.goto('/console/admin/users')
      await expect(page).toHaveURL(/\/console\/403$/, { timeout: 20_000 })
      await expect(page.getByText('403 · 无权限')).toBeVisible()
      // 仍处于登录态（403 不应登出）
      await expect(page.getByRole('link', { name: '返回总览' })).toBeVisible()
      await shot(page, '13-forbidden-403')
    } finally {
      await context.close()
      await user.api.dispose()
      await admin.dispose()
    }
  })

  test('OTP 登录：页面展示 dev_code，注册并进入控制台', async ({ browser }) => {
    const admin = await newAdminApi()
    const invite = await createInvite(admin)
    const email = uniqueEmail('login')
    const context = await browser.newContext()
    const page = await context.newPage()
    try {
      await uiLogin(page, email, invite)
      await expect(navLink(page, '我的 Bot')).toBeVisible()
      await expect(navLink(page, '总览')).toBeVisible()
      // 登录成功后同样不应有 localStorage token
      const storageKeys = await page.evaluate(() => Object.keys(window.localStorage))
      expect(storageKeys).toEqual([])
    } finally {
      await context.close()
      await admin.dispose()
    }
  })

  test('会话被管理员禁用后：下一次 API 401 → 清状态并跳登录', async ({ browser }) => {
    const admin = await newAdminApi()
    const invite = await createInvite(admin)
    const user = await registerUserApi(invite)
    const context = await browser.newContext({ storageState: await user.api.storageState() })
    const page = await context.newPage()
    try {
      await page.goto('/console/bots')
      await expect(page.getByRole('heading', { name: '我的 Bot' })).toBeVisible()

      const disabled = await admin.patch(`/api/admin/users/${user.userId}`, {
        data: { status: 'disabled' },
        headers: await csrfHeaders(admin),
      })
      expect(disabled.status()).toBe(200)

      // 触发一次前端 API：整页重载 → auth store fetchMe 收到 401 → 清 store → /login
      await page.reload()
      await expect(page).toHaveURL(/\/console\/login/, { timeout: 20_000 })
      const storageKeys = await page.evaluate(() => Object.keys(window.localStorage))
      expect(storageKeys).toEqual([])
      await expect(page.getByRole('heading', { name: '登录控制台' })).toBeVisible()

      // 管理员侧恢复，避免影响后续手工使用
      await admin.patch(`/api/admin/users/${user.userId}`, {
        data: { status: 'active' },
        headers: await csrfHeaders(admin),
      })
    } finally {
      await context.close()
      await user.api.dispose()
      await admin.dispose()
    }
  })
})

test.describe('管理员登录入口', () => {
  test('管理员会话可见管理后台入口（复用已登录会话）', async ({ browser }) => {
    const admin = await newAdminApi()
    // 若缓存会话可用，这里直接验证管理后台入口；否则用真实 UI OTP 登录一次。
    const context = await browser.newContext({
      storageState: {
        cookies: (await admin.storageState()).cookies,
        origins: [],
      },
    })
    const page = await context.newPage()
    try {
      await page.goto('/console/')
      await expect(navLink(page, '管理后台')).toBeVisible()
      await expect(page.getByRole('heading', { name: /欢迎回来/ })).toBeVisible()
    } finally {
      await context.close()
      await admin.dispose()
    }
  })
})
