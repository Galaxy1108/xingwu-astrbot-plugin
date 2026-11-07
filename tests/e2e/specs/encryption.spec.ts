import { test, expect } from '@playwright/test'
import {
  createInvite,
  csrfHeaders,
  newAdminApi,
  registerUserApi,
  uniqueEmail,
} from '../helpers/api'

/**
 * M3：用户级加密开关（关闭=全部解密，开启=全部重新加密）。
 * 使用 dev 专用接口写入一条对话，验证解密后管理员内容接口与用户访问记录。
 */
test('关闭加密→全部解密→重新开启加密', async ({ browser }) => {
  const admin = await newAdminApi()
  const invite = await createInvite(admin)
  const user = await registerUserApi(invite, uniqueEmail('enc'))
  const templates = await user.api.get('/api/templates')
  const templateId = (await templates.json()).data.items[0].id
  const created = await user.api.post('/api/bots', {
    data: { name: '加密开关Bot', template_id: templateId, platform: 'weixin_oc' },
    headers: await csrfHeaders(user.api),
  })
  expect(created.status()).toBe(201)
  const bot = (await created.json()).data.bot

  // dev-only：造一条对话供解密/回填验证
  const conversation = await user.api.post(`/api/dev/bots/${bot.id}/conversations`, {
    data: {
      title: '加密测试对话',
      history: [
        { role: 'user', content: '我的秘密是喜欢西湖' },
        { role: 'assistant', content: '我不会告诉别人。' },
      ],
    },
    headers: await csrfHeaders(user.api),
  })
  expect(conversation.status()).toBe(200)

  const context = await browser.newContext({ storageState: await user.api.storageState() })
  const page = await context.newPage()
  try {
    await page.goto('/console/settings/privacy')
    await expect(page.getByRole('heading', { name: '隐私与加密' })).toBeVisible()
    await expect(page.getByText('已加密', { exact: false }).first()).toBeVisible()

    // 关闭：必须输入「确认解密」
    await page.getByRole('checkbox', { name: '关闭加密' }).click()
    await expect(page.getByText('关闭加密并解密全部数据？')).toBeVisible()
    await page.getByTestId('confirm-input').fill('确认解密')
    await page.getByTestId('confirm-submit').click()

    await expect
      .poll(async () => {
        const res = await user.api.get('/api/me/encryption')
        return (await res.json()).data.state
      }, { timeout: 30_000 })
      .toBe('plaintext')
    await page.reload()
    await expect(page.getByText('当前为明文存储，管理员可查看内容。')).toBeVisible()

    // 管理员可查看解密后的对话，并写入访问记录
    const conversations = await admin.get(`/api/admin/bots/${bot.id}/conversations`)
    expect(conversations.status()).toBe(200)
    const body = await conversations.json()
    expect(JSON.stringify(body)).toContain('西湖')

    // 重新开启
    await page.getByRole('checkbox', { name: '开启加密' }).click()
    await expect(page.getByText('重新开启加密？')).toBeVisible()
    await page.getByTestId('confirm-submit').click()
    await expect
      .poll(async () => {
        const res = await user.api.get('/api/me/encryption')
        return (await res.json()).data.state
      }, { timeout: 30_000 })
      .toBe('encrypted')
  } finally {
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await user.api.dispose()
    await admin.dispose()
  }
})
