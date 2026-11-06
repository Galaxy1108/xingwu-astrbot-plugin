import { test, expect } from '@playwright/test'
import { newAdminApi } from '../helpers/api'

/**
 * M2 记忆页冒烟：使用 devdata 中预置的「记忆演示Bot」（6 条记忆）。
 * 该 Bot 由 lead 在独立 dev server 数据目录里种下；不存在时跳过，避免误报。
 */
const BOT_ID = process.env.E2E_MEMORY_BOT || 'b_e5787db71aad4817b1547d564d37e0f2'
const BOT_NAME = '记忆演示Bot'

test('记忆页：列表 / kind 筛选 / 搜索 / 编辑 / 删除 / 导出', async ({ browser }) => {
  const admin = await newAdminApi()
  const bots = await admin.get('/api/bots')
  if (!bots.ok()) test.skip(true, 'admin API 不可用')
  const body = await bots.json()
  const bot = (body?.data?.items ?? []).find((item: any) => item.id === BOT_ID)
  if (!bot) test.skip(true, `预置 Bot ${BOT_ID} 不存在`)

  const context = await browser.newContext({ storageState: await admin.storageState() })
  const page = await context.newPage()
  const requests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/bots/') && request.url().includes('/memories')) {
      requests.push(`${request.method()} ${request.url()}`)
    }
  })
  try {
    await page.goto(`/console/bots/${BOT_ID}/memory`)
    await expect(page.getByRole('heading', { name: new RegExp(BOT_NAME) })).toBeVisible({
      timeout: 20_000,
    })

    const rows = page.getByTestId('memory-row')
    await expect(rows.first()).toBeVisible()
    // ≥5：首次运行会删除一条并验证 DELETE，重复运行保持幂等。
    expect(await rows.count()).toBeGreaterThanOrEqual(5)

    // kind=preference → 2 条（含置顶）
    await page.getByRole('combobox').first().click()
    await page.getByRole('option', { name: '偏好' }).click()
    await expect(page).toHaveURL(/kind=preference/)
    await expect
      .poll(async () => rows.count(), { timeout: 15_000 })
      .toBe(2)

    // 关键字搜索「杭州」→ 1 条（先重置 kind 筛选）
    await page.getByRole('button', { name: '重置' }).click()
    await page.getByLabel('关键字').fill('杭州')
    await page.getByRole('button', { name: '筛选' }).click()
    await expect(page).toHaveURL(/q=%E6%9D%AD%E5%B7%9E|q=杭州/)
    await expect.poll(async () => rows.count(), { timeout: 15_000 }).toBe(1)

    // 编辑第一条
    await page.getByTestId('memory-edit').first().click()
    const editor = page.getByRole('textbox').filter({ hasText: '' }).last()
    await expect(page.getByTestId('memory-save')).toBeVisible()
    await page.getByTestId('memory-save').click()
    await expect(page.getByText('已保存')).toBeVisible({ timeout: 15_000 })

    // 导出 JSON
    const downloadPromise = page.waitForEvent('download')
    await page.getByTestId('memory-export').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/memories.*\.json/)

    // 清空筛选后删除一条（用专用于删除测试的 2026-11-01 event 记忆，避免影响其它断言）
    await page.getByRole('button', { name: '重置' }).click()
    await page.getByRole('textbox', { name: '关键字' }).fill('健身')
    await page.getByRole('button', { name: '筛选' }).click()
    await expect
      .poll(async () => rows.count(), { timeout: 15_000 })
      .toBeLessThanOrEqual(1)
    let deletedOne = false
    if ((await rows.count()) === 1) {
      await page.getByTestId('memory-delete').first().click()
      await page.getByTestId('confirm-submit').click()
      await expect.poll(async () => rows.count(), { timeout: 15_000 }).toBe(0)
      deletedOne = true
    }

    expect(requests.some((item) => item.startsWith('PATCH'))).toBeTruthy()
    if (deletedOne) {
      expect(requests.some((item) => item.startsWith('DELETE'))).toBeTruthy()
    }
  } finally {
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await admin.dispose()
  }
})
