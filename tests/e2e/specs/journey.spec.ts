import { test, expect } from '@playwright/test'
import {
  botIdFromUrl,
  createInvite,
  csrfHeaders,
  deleteBotApi,
  getBot,
  navLink,
  newAdminApi,
  shot,
  uiLogin,
  uniqueEmail,
  waitForBotStatus,
} from '../helpers/api'

/**
 * E：完整用户旅程（浏览器）
 * 登录（OTP，dev_code 页面提示）→ 我的 Bot → 新建（模板/平台/名称）→ 详情
 * → 扫码页（生成二维码 → 模拟扫码 → finalize → ready）→ 改名 → 禁用/启用
 * → 删除（输入 Bot 名）→ 审计出现记录。
 */
test('完整用户旅程：登录 → 建 Bot → 扫码上线 → 改名 → 启停 → 删除 → 审计', async ({ browser }) => {
  const admin = await newAdminApi()
  const invite = await createInvite(admin)
  const email = uniqueEmail('journey')
  const stamp = Date.now().toString().slice(-6)
  const botName = `QA旅程-${stamp}`
  const newName = `${botName}-改名`
  const context = await browser.newContext()
  const page = await context.newPage()
  let botId = ''

  try {
    // ---- 1. 登录（首次注册：邀请码 + OTP，dev_code 由页面提示展示）
    await uiLogin(page, email, invite)
    await expect(navLink(page, '我的 Bot')).toBeVisible()
    await shot(page, '01-dashboard-after-login')

    // ---- 2. 我的 Bot 列表
    await navLink(page, '我的 Bot').click()
    await expect(page).toHaveURL(/\/console\/bots$/)
    await expect(page.getByRole('heading', { name: '我的 Bot' })).toBeVisible()
    await expect(page.getByText('还没有 Bot')).toBeVisible()

    // ---- 3. 扫码接入：命名 + 模板 + 创建并生成二维码（入口统一到「扫码接入」）
    await page.getByRole('link', { name: '添加机器人' }).first().click()
    await expect(page).toHaveURL(/\/console\/connect$/)
    await page.getByLabel('Bot 名称').fill(botName)
    await expect(page.getByText('默认陪伴').first()).toBeVisible({ timeout: 20_000 })
    const sessionResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/qr/sessions') &&
        response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '创建并生成二维码' }).click()
    const sessionBody = await (await sessionResponse).json()
    const sessionId = sessionBody?.data?.session?.id
    expect(sessionId).toBeTruthy()

    await expect(page.getByRole('img', { name: '扫码登录二维码' }).first()).toBeVisible({ timeout: 25_000 })
    await expect(page.getByText('等待扫码', { exact: true })).toBeVisible()
    await shot(page, '02-connect-qr')

    // ---- 4. 后端直接完成扫码确认（不依赖 dev 面板）
    const scanHeaders = await csrfHeaders(context.request)
    await context.request.post(`/api/dev/qr-sessions/${sessionId}/scanned`, {
      data: {},
      headers: scanHeaders,
    })
    await context.request.post(`/api/dev/qr-sessions/${sessionId}/confirm`, {
      data: {},
      headers: scanHeaders,
    })
    await expect(page.getByRole('heading', { name: '已接入' })).toBeVisible({ timeout: 40_000 })
    const detailHref = await page.getByRole('link', { name: '查看 Bot 详情' }).getAttribute('href')
    expect(detailHref).toBeTruthy()
    await page.goto(detailHref!)
    await expect(page).toHaveURL(/\/console\/bots\/b_[0-9a-f]+/, { timeout: 25_000 })
    botId = botIdFromUrl(page.url())
    await expect(page.getByRole('heading', { name: botName })).toBeVisible()
    // ---- 4. 模拟扫码（dev_mode）→ 手机确认 → 前端轮询到 created 后自动 finalize
    const readyBot = await waitForBotStatus(context.request, botId, 'ready')
    expect(readyBot.bound).toBe(true)
    expect(readyBot.enabled).toBe(true)
    await shot(page, '03-bot-ready')

    // ---- 5. 改名（设置 tab inline，不弹窗）：只改展示名，技术字段不变
    const confIdBefore = readyBot.conf_id
    await page.getByTestId('bot-tab-overview').waitFor({ state: 'visible' })
    await page.getByTestId('bot-settings').click()
    const settingsName = page.getByTestId('bot-settings-name').locator('input')
    await settingsName.waitFor({ state: 'visible' })
    await settingsName.fill(newName)
    await page.getByTestId('bot-settings-save').click()
    await expect(page.getByRole('heading', { name: newName })).toBeVisible({ timeout: 20_000 })
    await page.getByTestId('bot-tab-overview').click()
    const renamedBot = (await getBot(context.request, botId)).bot
    expect(renamedBot.name).toBe(newName)
    expect(renamedBot.conf_id).toBe(confIdBefore)
    expect(renamedBot.memory_db).toBe(readyBot.memory_db)
    await shot(page, '04-bot-renamed')

    // ---- 6. 禁用 / 启用（平台实例开关）
    const switchInput = page.locator('.switch-row input[type="checkbox"]')
    await expect(switchInput).toBeChecked()
    await page.locator('.switch-row .v-switch').click()
    await waitForBotStatus(context.request, botId, 'disabled')
    await expect(page.getByText('已停用', { exact: true })).toBeVisible({ timeout: 20_000 })

    await page.locator('.switch-row .v-switch').click()
    await waitForBotStatus(context.request, botId, 'ready')
    await expect(page.getByText('运行中', { exact: true })).toBeVisible({ timeout: 20_000 })

    // ---- 7. 删除：危险区二次确认，必须输入 Bot 名
    await page.getByRole('button', { name: '删除 Bot' }).click()
    const confirmDialog = page.getByRole('dialog')
    await expect(confirmDialog).toBeVisible()
    await confirmDialog.getByTestId('confirm-input').fill(newName)
    await confirmDialog.getByTestId('confirm-submit').click()
    await expect(page).toHaveURL(/\/console\/bots$/, { timeout: 25_000 })
    await expect(page.getByText('Bot 已删除')).toBeVisible()
    const gone = await getBot(context.request, botId)
    expect(gone.status).toBe(404)
    await shot(page, '05-bots-after-delete')

    // ---- 8. 审计出现完整记录（管理端 API）
    const auditResponse = await admin.get(`/api/admin/audit?target_id=${botId}&page_size=100`)
    expect(auditResponse.ok()).toBe(true)
    const auditBody = await auditResponse.json()
    const actions = new Set<string>((auditBody.data.items as any[]).map((item) => item.action))
    for (const required of [
      'bot.created',
      'qr_session.finalized',
      'bot.renamed',
      'bot.disabled',
      'bot.enabled',
      'bot.deleted',
    ]) {
      expect(actions, `审计缺少 ${required}，实际 ${[...actions].join(',')}`).toContain(required)
    }
  } finally {
    // 失败时清理残留 Bot，保证可重复执行
    if (botId) {
      try {
        const current = await getBot(context.request, botId)
        if (current.bot) {
          if (current.bot.status === 'disabled') {
            await context.request.patch(`/api/bots/${botId}`, {
              data: { enabled: true },
              headers: await csrfHeaders(context.request),
            })
          }
          await deleteBotApi(context.request, botId, current.bot.name)
        }
      } catch {
        /* best effort */
      }
    }
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await admin.dispose()
  }
})
