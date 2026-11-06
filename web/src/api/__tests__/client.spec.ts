import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type ClientModule = typeof import('../client')

interface FakeResponse {
  status: number
  ok: boolean
  text: () => Promise<string>
}

function fakeResponse(body: unknown, status = 200): Response {
  const payload: FakeResponse = {
    status,
    ok: status >= 200 && status < 300,
    text: async () => (body === undefined ? '' : JSON.stringify(body)),
  }
  return payload as unknown as Response
}

let client: ClientModule

beforeEach(async () => {
  vi.resetModules()
  client = await import('../client')
  document.cookie = 'csrf=test-csrf-token; path=/'
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.cookie = 'csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})

describe('api client · CSRF 与请求约定', () => {
  it('写请求带 X-CSRF-Token、credentials=include 和 JSON body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await client.request('/auth/logout', { method: 'POST' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/auth/logout')
    expect(init.credentials).toBe('include')
    expect(init.method).toBe('POST')
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('test-csrf-token')
  })

  it('GET 请求不带 CSRF 头', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true, data: { items: [] } }))
    vi.stubGlobal('fetch', fetchMock)

    await client.request('/bots')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBeUndefined()
  })

  it('CSRF cookie 缺失时不带空头', async () => {
    document.cookie = 'csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await client.request('/bots', { method: 'POST', body: { name: '小明' } })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBeUndefined()
  })

  it('query 参数拼接且忽略空值', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true, data: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await client.request('/admin/users', { query: { page: 2, q: '', status: undefined } })

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/admin/users?page=2')
  })
})

describe('api client · 响应解包与错误归一化', () => {
  it('解包 { ok: true, data } 包络', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        fakeResponse({ ok: true, data: { sent: true, resend_after: 60, dev_code: '123456' } }),
      ),
    )

    const result = await client.request<{ dev_code: string }>('/auth/otp/request', {
      method: 'POST',
      body: { email: 'a@b.com' },
    })

    expect(result.dev_code).toBe('123456')
  })

  it('兼容后端直接返回裸对象（API.md 示例写法）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse({ items: [{ id: 'b_1' }] })))

    const result = await client.request<{ items: Array<{ id: string }> }>('/bots')

    expect(result.items[0].id).toBe('b_1')
  })

  it('把错误包络归一化为 { status, code, message, field }', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        fakeResponse(
          { ok: false, error: { code: 'invite_exhausted', message: '邀请码已被使用', field: 'invite' } },
          410,
        ),
      ),
    )

    const error = await client
      .request('/auth/otp/verify', { method: 'POST', body: {} })
      .catch((err: unknown) => err)

    expect(error).toBeInstanceOf(client.ApiError)
    const apiError = error as InstanceType<ClientModule['ApiError']>
    expect(apiError.status).toBe(410)
    expect(apiError.code).toBe('invite_exhausted')
    expect(apiError.message).toBe('邀请码已被使用')
    expect(apiError.field).toBe('invite')
  })

  it('无错误体时按 HTTP 状态给出兜底文案', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse(undefined, 500)))

    const error = (await client.request('/bots').catch((err: unknown) => err)) as InstanceType<
      ClientModule['ApiError']
    >

    expect(error.status).toBe(500)
    expect(error.code).toBe('http_error')
    expect(error.message).toContain('服务端错误')
  })
})

describe('api client · 重试策略', () => {
  it('GET 遇到网络错误自动重试 1 次并成功', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(fakeResponse({ ok: true, data: { items: [] } }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await client.request<{ items: unknown[] }>('/bots')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.items).toEqual([])
  })

  it('GET 两次都失败后抛 network_error', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network down'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client.request('/bots')).rejects.toMatchObject({
      status: 0,
      code: 'network_error',
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('写请求失败不重试', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network down'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(client.request('/bots', { method: 'POST', body: { name: 'x' } })).rejects.toMatchObject({
      status: 0,
      code: 'network_error',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('GET 的 4xx 错误不重试', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      fakeResponse({ ok: false, error: { code: 'not_found', message: '资源不存在' } }, 404),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(client.request('/bots/b_x')).rejects.toMatchObject({ status: 404, code: 'not_found' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('api client · 401/403 处理', () => {
  it('401 触发全局跳登录处理器，且不重试', async () => {
    const unauthorized = vi.fn()
    client.setUnauthorizedHandler(unauthorized)
    const fetchMock = vi.fn().mockResolvedValue(
      fakeResponse({ ok: false, error: { code: 'unauthorized', message: '未登录' } }, 401),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(client.request('/me')).rejects.toMatchObject({ status: 401, code: 'unauthorized' })

    expect(unauthorized).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('403 只触发无权限提示，不触发登出', async () => {
    const unauthorized = vi.fn()
    const forbidden = vi.fn()
    client.setUnauthorizedHandler(unauthorized)
    client.setForbiddenHandler(forbidden)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        fakeResponse({ ok: false, error: { code: 'forbidden', message: '无权限' } }, 403),
      ),
    )

    await expect(client.request('/admin/users')).rejects.toMatchObject({ status: 403, code: 'forbidden' })

    expect(forbidden).toHaveBeenCalledTimes(1)
    expect(unauthorized).not.toHaveBeenCalled()
  })
})
