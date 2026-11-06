import { test, expect } from '@playwright/test'
import { ADMIN_EMAIL, csrfHeaders, newAdminApi } from '../helpers/api'

/**
 * M3 切片：手动额度（建单 → 确认到账）+ 用户端账本可见。
 * 直接打 6180 dev server；每次用唯一 external_ref 保证可重复执行。
 */
test('管理端建单确认到账，用户端余额与流水可见', async ({ browser }) => {
  const admin = await newAdminApi()
  const usersResponse = await admin.get(
    `/api/admin/users?q=${encodeURIComponent(ADMIN_EMAIL)}&page_size=100`,
  )
  const users = (await usersResponse.json())?.data?.items ?? []
  const target = users.find((item: any) => item.email === ADMIN_EMAIL)
  if (!target) test.skip(true, '管理员用户不在列表')

  const externalRef = `E2E-TOPUP-${Date.now()}`
  const headers = await csrfHeaders(admin)
  const created = await admin.post('/api/admin/orders', {
    data: { user_id: target.id, credits: 3, amount_cny: 0.03, external_ref: externalRef, note: 'e2e' },
    headers,
  })
  expect(created.status()).toBe(201)
  const order = (await created.json()).data.order
  expect(order.status).toBe('pending')

  // 重复 external_ref → 幂等返回同一订单
  const duplicate = await admin.post('/api/admin/orders', {
    data: { user_id: target.id, credits: 3, external_ref: externalRef },
    headers,
  })
  expect(duplicate.status()).toBe(200)
  expect((await duplicate.json()).data.idempotent).toBe(true)

  const context = await browser.newContext({ storageState: await admin.storageState() })
  const page = await context.newPage()
  try {
    await page.goto('/console/admin/orders')
    await expect(page.getByRole('heading', { name: '手动充值' })).toBeVisible()
    const row = page.locator('[data-testid="order-row"]', { hasText: externalRef })
    await expect(row).toBeVisible({ timeout: 20_000 })
    await expect(row).toContainText('待确认')

    await row.getByTestId('order-confirm').click()
    await expect(page.getByText('确认到账？')).toBeVisible()
    await page.getByTestId('confirm-submit').click()
    await expect(row).toContainText('已到账', { timeout: 20_000 })

    // 重复确认走 API：幂等，不重复入账
    const before = (await (await admin.get('/api/wallet')).json()).data.balance
    const confirmAgain = await admin.post(`/api/admin/orders/${order.id}/confirm`, {
      data: {},
      headers,
    })
    expect(confirmAgain.status()).toBe(200)
    expect((await confirmAgain.json()).data.already_paid).toBe(true)
    const after = (await (await admin.get('/api/wallet')).json()).data.balance
    expect(after).toBe(before)

    // 用户端账本
    await page.goto('/console/billing')
    await expect(page.getByRole('heading', { name: '额度' })).toBeVisible()
    await expect(page.getByText(/流水|账本/).first()).toBeVisible()
  } finally {
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await admin.dispose()
  }
})
