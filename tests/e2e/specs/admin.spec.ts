import { test, expect } from '@playwright/test'
import {
  ADMIN_EMAIL,
  adminBrowserContext,
  createInvite,
  createReadyBot,
  csrfHeaders,
  deleteBotApi,
  navLink,
  newAdminApi,
  registerUserApi,
  saveContextCookies,
  uiLogin,
} from '../helpers/api'

/**
 * F：管理端（浏览器 + API）
 * - 管理员 OTP 登录
 * - 用户列表 / Bot 列表 / 审计列表可见
 * - 管理员不能强制关闭加密（PUT enabled=false -> 403）
 */
// 管理端页面用例只使用“本次运行中真实 UI 登录”得到的会话，不复用 artifacts 缓存。
let adminStorageState: any = null

test.describe('管理端', () => {
  test('管理员 UI OTP 登录后可进入管理后台', async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()
    try {
      await uiLogin(page, ADMIN_EMAIL)
      await expect(navLink(page, '管理后台')).toBeVisible()
      await navLink(page, '管理后台').click()
      await expect(page).toHaveURL(/\/console\/admin\/templates$/, { timeout: 20_000 })
      await expect(page.getByRole('heading', { name: '模板管理' })).toBeVisible()
      // 记录本次真实 UI 登录的会话：同文件后续用例复用，但不跨运行复用缓存
      adminStorageState = await context.storageState()
      await saveContextCookies(context)
    } finally {
      await page.close().catch(() => {})
      await context.close().catch(() => {})
    }
  })

  test('用户列表、Bot 列表、审计列表可见', async ({ browser }) => {
    const admin = await newAdminApi()
    const invite = await createInvite(admin)
    const user = await registerUserApi(invite)
    const botName = `QA管理-${Date.now().toString().slice(-6)}`
    const bot = await createReadyBot(user.api, botName)
    const context = adminStorageState
      ? await browser.newContext({ storageState: adminStorageState })
      : await adminBrowserContext(browser)
    const page = await context.newPage()
    try {
      // 用户列表
      await page.goto('/console/admin/users')
      await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
      await expect(page.getByText(user.email)).toBeVisible()
      await expect(page.getByText('管理员').first()).toBeVisible()

      // Bot 列表：新 Bot + 归属用户
      await page.goto('/console/admin/bots')
      await expect(page.getByRole('heading', { name: 'Bot 管理' })).toBeVisible()
      const botRow = page.locator('tbody tr', { hasText: botName })
      await expect(botRow).toBeVisible()
      await expect(botRow).toContainText(user.email)

      // 审计列表：刚发生的 bot.created
      await page.goto('/console/admin/audit')
      await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible()
      await expect(page.getByText('bot.created').first()).toBeVisible()
    } finally {
      try {
        await deleteBotApi(user.api, bot.id, bot.name)
      } catch {
        /* best effort */
      }
      await page.close().catch(() => {})
      await context.close().catch(() => {})
      await user.api.dispose()
      await admin.dispose()
    }
  })

  test('管理员不能强制关闭用户加密（403 forbidden），强制开启允许', async () => {
    const admin = await newAdminApi()
    try {
      const me = await admin.get('/api/me')
      const adminId = (await me.json()).data.user.id
      const headers = await csrfHeaders(admin)

      const denied = await admin.put(`/api/admin/users/${adminId}/encryption`, {
        data: { enabled: false },
        headers,
      })
      expect(denied.status()).toBe(403)
      const deniedBody = await denied.json()
      expect(deniedBody.error.code).toBe('forbidden')

      const allowed = await admin.put(`/api/admin/users/${adminId}/encryption`, {
        data: { enabled: true },
        headers,
      })
      expect(allowed.status()).toBe(200)
      const state = await admin.get(`/api/admin/users/${adminId}/encryption`)
      expect((await state.json()).data.enabled).toBe(true)
    } finally {
      await admin.dispose()
    }
  })
})
