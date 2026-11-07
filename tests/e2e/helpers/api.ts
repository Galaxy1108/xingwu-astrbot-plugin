import fs from 'node:fs'
import path from 'node:path'
import {
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test'

export const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:6180'
export const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@example.com'
export const ARTIFACTS = process.env.E2E_ARTIFACTS_DIR || path.join(process.cwd(), 'artifacts')
export const ADMIN_CACHE = path.join(ARTIFACTS, 'admin_session.json')

export interface CookieShape {
  name: string
  value: string
  domain: string
  path: string
  expires: number
  httpOnly: boolean
  secure: boolean
  sameSite: 'Lax'
}

export function cookiesFromDict(dict: Record<string, string>): CookieShape[] {
  return Object.entries(dict).map(([name, value]) => ({
    name,
    value,
    domain: '127.0.0.1',
    path: '/',
    expires: -1,
    httpOnly: name === 'sid' || name === '__Host-sid',
    secure: false,
    sameSite: 'Lax',
  }))
}

export function readAdminCache(): Record<string, string> | null {
  try {
    if (!fs.existsSync(ADMIN_CACHE)) return null
    const parsed = JSON.parse(fs.readFileSync(ADMIN_CACHE, 'utf8'))
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : null
  } catch {
    return null
  }
}

export function writeAdminCache(dict: Record<string, string>): void {
  fs.mkdirSync(ARTIFACTS, { recursive: true })
  fs.writeFileSync(ADMIN_CACHE, JSON.stringify(dict), 'utf8')
}

/** 把浏览器 context 的 cookie 落成简单 dict，供下次复用（避免 OTP 60s 限流）。 */
export async function saveContextCookies(context: BrowserContext): Promise<void> {
  const state = await context.storageState()
  const dict: Record<string, string> = {}
  for (const cookie of state.cookies) dict[cookie.name] = cookie.value
  writeAdminCache(dict)
}

export function uniqueEmail(tag: string): string {
  const suffix = Math.random().toString(36).slice(2, 8)
  return `qa-e2e-${tag}-${Date.now()}-${suffix}@example.com`
}

/** 所有写请求都要带 X-CSRF-Token（值等于非 HttpOnly 的 csrf Cookie）。 */
export async function csrfHeaders(api: APIRequestContext): Promise<Record<string, string>> {
  const state = await api.storageState()
  const token = state.cookies.find((cookie) => cookie.name === 'csrf')?.value
  if (!token) throw new Error('缺少 csrf Cookie，无法发送写请求')
  return { 'X-CSRF-Token': token }
}

async function otpRequest(
  api: APIRequestContext,
  email: string,
  invite?: string,
): Promise<{ status: number; body: any }> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await api.post('/api/auth/otp/request', {
      data: invite ? { email, invite } : { email },
    })
    const body = await response.json().catch(() => ({}))
    if (response.status() !== 429) return { status: response.status(), body }
    const retryAfter = Number(body?.error?.retry_after ?? 5)
    await new Promise((resolve) => setTimeout(resolve, Math.min(retryAfter + 1, 65) * 1000))
  }
  throw new Error(`OTP 请求持续被限流：${email}`)
}

/**
 * 获取管理员 API 上下文：优先复用 api_acceptance.py 写下的会话缓存，
 * 失效时才真正走一次 OTP 登录（并回写缓存）。
 */
export async function newAdminApi(): Promise<APIRequestContext> {
  const cached = readAdminCache()
  const options = cached
    ? { baseURL: BASE_URL, storageState: { cookies: cookiesFromDict(cached), origins: [] } }
    : { baseURL: BASE_URL }
  const api = await playwrightRequest.newContext(options)
  const me = await api.get('/api/me')
  if (me.ok()) {
    const body = await me.json()
    if (body?.data?.user?.role === 'admin') return api
  }
  const requested = await otpRequest(api, ADMIN_EMAIL)
  if (requested.status !== 200) {
    throw new Error(`管理员 OTP 请求失败：${JSON.stringify(requested.body)}`)
  }
  const code = requested.body?.data?.dev_code
  if (!code) throw new Error('dev_mode 未返回 dev_code')
  const verified = await api.post('/api/auth/otp/verify', {
    data: { email: ADMIN_EMAIL, code },
  })
  if (!verified.ok()) throw new Error(`管理员 OTP 校验失败：${verified.status()}`)
  const state = await api.storageState()
  const dict: Record<string, string> = {}
  for (const cookie of state.cookies) dict[cookie.name] = cookie.value
  writeAdminCache(dict)
  return api
}

export async function createInvite(admin: APIRequestContext, maxUses = 1): Promise<string> {
  const response = await admin.post('/api/admin/invites', {
    data: { max_uses: maxUses, ttl_hours: 72 },
    headers: await csrfHeaders(admin),
  })
  if (!response.ok()) throw new Error(`创建邀请码失败：${response.status()}`)
  const body = await response.json()
  const code = body?.data?.invite?.code
  if (!code) throw new Error('邀请码响应缺少 code')
  return code as string
}

/** 纯 API 注册一个用户（用于需要“已存在用户”的场景，如 403/禁用会话）。 */
export async function registerUserApi(
  invite: string,
  email = uniqueEmail('api'),
): Promise<{ api: APIRequestContext; email: string; userId: string }> {
  const api = await playwrightRequest.newContext({ baseURL: BASE_URL })
  const requested = await otpRequest(api, email, invite)
  if (requested.status !== 200) throw new Error(`注册 OTP 失败：${JSON.stringify(requested.body)}`)
  const code = requested.body?.data?.dev_code
  const verified = await api.post('/api/auth/otp/verify', {
    data: { email, code, invite },
  })
  if (!verified.ok()) throw new Error(`注册失败：${verified.status()} ${await verified.text()}`)
  const body = await verified.json()
  return { api, email, userId: body?.data?.user?.id }
}

export async function listTemplates(api: APIRequestContext): Promise<any[]> {
  const response = await api.get('/api/templates')
  if (!response.ok()) throw new Error(`读取模板失败：${response.status()}`)
  const body = await response.json()
  return body?.data?.items ?? []
}

/** 走完整扫码状态机，把 Bot 变成 ready（dev_mode 专用）。 */
export async function createReadyBot(api: APIRequestContext, name: string): Promise<any> {
  const templates = await listTemplates(api)
  if (!templates.length) throw new Error('没有可用模板')
  const headers = await csrfHeaders(api)
  const created = await api.post('/api/bots', {
    data: { name, template_id: templates[0].id, platform: 'weixin_oc' },
    headers,
  })
  if (created.status() !== 201) {
    throw new Error(`创建 Bot 失败：${created.status()} ${await created.text()}`)
  }
  const bot = (await created.json()).data.bot
  const botId = bot.id
  try {
    const started = await api.post(`/api/bots/${botId}/qr/start`, { data: {}, headers })
    if (!started.ok()) throw new Error(`qr/start 失败：${started.status()}`)
    const scanned = await api.post(`/api/dev/qr/${botId}/scanned`, { data: {}, headers })
    if (!scanned.ok()) throw new Error(`模拟扫码失败：${scanned.status()}`)
    const confirmed = await api.post(`/api/dev/qr/${botId}/confirm`, { data: {}, headers })
    if (!confirmed.ok()) throw new Error(`模拟确认失败：${confirmed.status()}`)
    // finalize 要求服务端状态先变成 created（生产代码也会在 finalize 前自动 poll 一次）
    let polled = ''
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const poll = await api.get(`/api/bots/${botId}/qr/poll`)
      if (!poll.ok()) throw new Error(`qr/poll 失败：${poll.status()}`)
      polled = (await poll.json())?.data?.qr?.status
      if (polled === 'created') break
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
    if (polled !== 'created') throw new Error(`poll 未进入 created，最后状态：${polled}`)
    const finalized = await api.post(`/api/bots/${botId}/qr/finalize`, { data: {}, headers })
    if (!finalized.ok()) throw new Error(`finalize 失败：${finalized.status()}`)
    return (await finalized.json()).data.bot
  } catch (error) {
    // 失败时清理，保证用例可重复执行
    try {
      await deleteBotApi(api, botId, name)
    } catch {
      /* best effort */
    }
    throw error
  }
}

export async function deleteBotApi(
  api: APIRequestContext,
  botId: string,
  name: string,
): Promise<void> {
  const response = await api.delete(`/api/bots/${botId}`, {
    data: { confirm_name: name },
    headers: await csrfHeaders(api),
  })
  if (!response.ok()) throw new Error(`删除 Bot 失败：${response.status()}`)
}

export async function getBot(
  api: APIRequestContext,
  botId: string,
): Promise<{ status: number; bot?: any }> {
  const response = await api.get(`/api/bots/${botId}`)
  if (response.status() === 404) return { status: 404 }
  if (!response.ok()) throw new Error(`读取 Bot 失败：${response.status()}`)
  const body = await response.json()
  return { status: response.status(), bot: body?.data?.bot }
}

/** 轮询等待 Bot 状态，避免依赖固定 sleep。 */
export async function waitForBotStatus(
  api: APIRequestContext,
  botId: string,
  expected: string,
  timeoutMs = 20_000,
): Promise<any> {
  const deadline = Date.now() + timeoutMs
  let last: any = null
  while (Date.now() < deadline) {
    const result = await getBot(api, botId)
    last = result.bot
    if (last?.status === expected) return last
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error(`Bot ${botId} 未在 ${timeoutMs}ms 内进入 ${expected}，最后状态：${JSON.stringify(last)}`)
}

/** 从页面“开发环境验证码”提示里取 6 位码；限流时等待后重试一次。 */
export async function submitLoginRequest(page: Page, email: string): Promise<string> {
  const devCode = page.getByText('开发环境验证码')
  const rateLimited = page.getByText('验证码发送过于频繁')
  await page.getByTestId('login-request').click()
  await expect(devCode.or(rateLimited)).toBeVisible({ timeout: 20_000 })
  if (await rateLimited.isVisible()) {
    await page.waitForTimeout(61_000)
    await page.getByTestId('login-request').click()
    await expect(devCode).toBeVisible({ timeout: 20_000 })
  }
  const text = (await devCode.textContent()) || ''
  const match = text.match(/(\d{6})/)
  if (!match) throw new Error(`未能从页面读取 dev_code：${text}`)
  return match[1]
}

/**
 * UI 登录；invite 传入时同时覆盖“首次注册”流程。
 * 成功标准：跳转到 /console/（总览）。
 */
export async function uiLogin(page: Page, email: string, invite?: string): Promise<void> {
  await page.goto('/console/login')
  await expect(page.getByRole('heading', { name: '登录控制台' })).toBeVisible()
  // 默认可能是密码登录；切到验证码登录。
  const otpTab = page.getByRole('button', { name: '验证码登录' })
  if (await otpTab.isVisible().catch(() => false)) await otpTab.click()
  if (invite) {
    const otpRegister = page.getByRole('button', { name: '邮箱验证码注册' })
    if (await otpRegister.isVisible().catch(() => false)) await otpRegister.click()
    await expect(page.getByLabel(/邀请码/)).toBeVisible()
    await page.getByLabel(/邀请码/).fill(invite)
  }
  await page.getByLabel('邮箱').fill(email)
  const code = await submitLoginRequest(page, email)
  const firstCell = page.getByLabel('验证码第 1 位')
  await expect(firstCell).toBeVisible()
  await firstCell.click()
  await page.keyboard.type(code, { delay: 40 })
  // 6 位输满会自动提交；若因焦点问题没触发，再点一次按钮兜底。
  await page.waitForTimeout(400)
  if (page.url().includes('/login')) {
    await page.getByTestId('login-verify').click()
  }
  await expect(page).toHaveURL(/\/console\/?$/, { timeout: 25_000 })
}

/** 管理员 UI 上下文：优先复用缓存会话，缓存失效时走一次真实 UI OTP 登录。 */
export async function adminBrowserContext(browser: Browser): Promise<BrowserContext> {
  const cached = readAdminCache()
  if (cached) {
    const context = await browser.newContext({
      storageState: { cookies: cookiesFromDict(cached), origins: [] },
    })
    const me = await context.request.get('/api/me')
    if (me.ok()) {
      const body = await me.json()
      if (body?.data?.user?.role === 'admin') return context
    }
    await context.close()
  }
  const context = await browser.newContext()
  const page = await context.newPage()
  await uiLogin(page, ADMIN_EMAIL)
  await page.close()
  await saveContextCookies(context)
  return context
}

/** 保存验收截图到 artifacts/screenshots/（artifacts 已 gitignore）。 */
export async function shot(page: Page, name: string): Promise<void> {
  const dir = path.join(ARTIFACTS, 'screenshots')
  fs.mkdirSync(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true })
}

/** 侧边栏导航链接（避免与页面内同名按钮/空态 CTA 冲突）。 */
export function navLink(page: Page, name: string) {
  return page.getByRole('listbox').getByRole('link', { name, exact: true })
}

/** 从 /console/bots/<id> 或 /console/bots/<id>?qr=1 提取 bot id。 */
export function botIdFromUrl(url: string): string {
  const parsed = new URL(url)
  const match = parsed.pathname.match(/\/bots\/(b_[0-9a-f]+)/)
  if (!match) throw new Error(`URL 中未找到 bot id：${url}`)
  return match[1]
}
