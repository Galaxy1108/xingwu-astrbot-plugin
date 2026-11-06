import { test, expect } from '@playwright/test'
import {
  botIdFromUrl,
  createInvite,
  csrfHeaders,
  deleteBotApi,
  getBot,
  navLink,
  newAdminApi,
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

    // ---- 2. 我的 Bot 列表
    await navLink(page, '我的 Bot').click()
    await expect(page).toHaveURL(/\/console\/bots$/)
    await expect(page.getByRole('heading', { name: '我的 Bot' })).toBeVisible()
    await expect(page.getByText('还没有 Bot')).toBeVisible()

    // ---- 3. 新建 Bot：名称 + 平台（默认微信）+ 模板（默认第一个）
    await page.getByRole('button', { name: '新建 Bot' }).first().click()
    const createDialog = page.getByRole('dialog')
    await expect(createDialog).toBeVisible()
    await createDialog.getByLabel('Bot 名称').fill(botName)
    await expect(createDialog.getByText('默认陪伴').first()).toBeVisible({ timeout: 20_000 })
    await createDialog.getByRole('button', { name: '创建' }).click()

    // 创建成功 → 详情页 ?qr=1，自动生成二维码
    await expect(page).toHaveURL(/\/console\/bots\/b_[0-9a-f]+\?qr=1/, { timeout: 25_000 })
    botId = botIdFromUrl(page.url())
    await expect(page.getByRole('heading', { name: botName })).toBeVisible()
    await expect(page.getByAltText('扫码登录二维码')).toBeVisible({ timeout: 25_000 })
    await expect(page.getByText('等待扫码', { exact: true })).toBeVisible()

    // ---- 4. 模拟扫码（dev_mode）→ 手机确认 → 前端轮询到 created 后自动 finalize
    const headers = await csrfHeaders(context.request)
    const scanned = await context.request.post(`/api/dev/qr/${botId}/scanned`, {
      data: {},
      headers,
    })
    expect(scanned.status()).toBe(200)
    const pollScanned = await context.request.get(`/api/bots/${botId}/qr/poll`)
    expect((await pollScanned.json()).data.qr.status).toBe('scanned')

    const confirmed = await context.request.post(`/api/dev/qr/${botId}/confirm`, {
      data: {},
      headers,
    })
    expect(confirmed.status()).toBe(200)

    // finalize 后：状态 ready、已绑定，UI 显示“运行中”
    await expect(page.getByText('已绑定', { exact: true })).toBeVisible({ timeout: 40_000 })
    await expect(page.getByText('运行中', { exact: true })).toBeVisible({ timeout: 20_000 })
    const readyBot = await waitForBotStatus(context.request, botId, 'ready')
    expect(readyBot.bound).toBe(true)
    expect(readyBot.enabled).toBe(true)

    // ---- 5. 改名：只改展示名，技术字段不变
    const confIdBefore = readyBot.conf_id
    await page.getByRole('button', { name: '修改名称' }).click()
    const renameDialog = page.getByRole('dialog')
    await expect(renameDialog.getByLabel('新名称')).toBeVisible()
    await renameDialog.getByLabel('新名称').fill(newName)
    await renameDialog.getByRole('button', { name: '保存' }).click()
    await expect(page.getByRole('heading', { name: newName })).toBeVisible({ timeout: 20_000 })
    const renamedBot = (await getBot(context.request, botId)).bot
    expect(renamedBot.name).toBe(newName)
    expect(renamedBot.conf_id).toBe(confIdBefore)
    expect(renamedBot.memory_db).toBe(readyBot.memory_db)

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

    // ---- 8. 审计出现完整记录（管理端 API）
    const auditResponse = await admin.get(`/api/admin/audit?target_id=${botId}&page_size=100`)
    expect(auditResponse.ok()).toBe(true)
    const auditBody = await auditResponse.json()
    const actions = new Set<string>((auditBody.data.items as any[]).map((item) => item.action))
    for (const required of [
      'bot.created',
      'bot.qr_started',
      'bot.qr_finalized',
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
