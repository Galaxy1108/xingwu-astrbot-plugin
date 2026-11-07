/**
 * 统一 API client。
 *
 * 约定（docs/API.md §0）：
 * - 同源 `/api`，`credentials: 'include'`，会话只走 HttpOnly Cookie，前端不存 token；
 * - 写请求自动带 `X-CSRF-Token`（读非 HttpOnly 的 `csrf` Cookie）；
 * - 统一错误对象 `{ status, code, message, field }`；
 * - 401：通知全局处理器（清 store → 跳登录）；403：只提示，不登出；
 * - GET 失败重试 1 次，写请求不重试。
 */

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface ApiErrorInit {
  status: number
  code: string
  message: string
  field?: string | null
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly field: string | null

  constructor(init: ApiErrorInit) {
    super(init.message)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.field = init.field ?? null
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/** 把任意异常收敛成 ApiError，页面只处理一种错误形状。 */
export function toApiError(error: unknown): ApiError {
  if (isApiError(error)) return error
  if (error instanceof Error) {
    return new ApiError({ status: 0, code: 'network_error', message: error.message || '网络错误' })
  }
  return new ApiError({ status: 0, code: 'unknown_error', message: '未知错误' })
}

export interface ApiEnvelope<T> {
  ok?: boolean
  data?: T
  error?: {
    code?: string
    message?: string
    field?: string | null
  } | null
}

export interface RequestOptions {
  method?: HttpMethod
  body?: unknown
  query?: Record<string, string | number | boolean | null | undefined>
  headers?: Record<string, string>
  signal?: AbortSignal
}

type UnauthorizedHandler = () => void
type ForbiddenHandler = (error: ApiError) => void

let unauthorizedHandler: UnauthorizedHandler | null = null
let forbiddenHandler: ForbiddenHandler | null = null

/** 注册全局 401 处理器（清 store + 跳登录）。 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

/** 注册全局 403 处理器（仅提示无权限，不登出）。 */
export function setForbiddenHandler(handler: ForbiddenHandler | null): void {
  forbiddenHandler = handler
}

const WRITE_METHODS: ReadonlySet<HttpMethod> = new Set<HttpMethod>(['POST', 'PUT', 'PATCH', 'DELETE'])

/** 读 Cookie（仅 csrf 这类非 HttpOnly Cookie 前端可见）。 */
export function readCookie(name: string): string | null {
  if (typeof document === 'undefined' || !document.cookie) return null
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const item = part.trim()
    if (item.startsWith(prefix)) {
      const raw = item.slice(prefix.length)
      try {
        return decodeURIComponent(raw)
      } catch {
        return raw
      }
    }
  }
  return null
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const base = path.startsWith('/api') ? path : `/api${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return base
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.append(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

function defaultMessage(status: number): string {
  switch (status) {
    case 400:
      return '请求参数有误'
    case 401:
      return '登录已过期，请重新登录'
    case 403:
      return '没有权限执行该操作'
    case 404:
      return '资源不存在'
    case 409:
      return '操作冲突，请刷新后重试'
    case 410:
      return '该资源已失效'
    case 429:
      return '操作过于频繁，请稍后再试'
    case 501:
      return '该功能尚未开放'
    case 502:
    case 503:
    case 504:
      return '服务暂时不可用，请稍后重试'
    default:
      return status >= 500 ? '服务端错误，请稍后重试' : '请求失败'
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function fetchOnce<T>(path: string, options: RequestOptions): Promise<T> {
  const method = options.method ?? 'GET'
  const isWrite = WRITE_METHODS.has(method)
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...options.headers,
  }

  if (isWrite) {
    const csrf = readCookie('csrf')
    if (csrf) headers['X-CSRF-Token'] = csrf
  }

  let body: BodyInit | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json; charset=utf-8'
    body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body,
      credentials: 'include',
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError({ status: 0, code: 'aborted', message: '请求已取消' })
    }
    throw new ApiError({ status: 0, code: 'network_error', message: '网络连接失败，请检查网络后重试' })
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  const envelope = (payload ?? null) as ApiEnvelope<T> | null

  if (!response.ok) {
    const code =
      envelope?.error?.code ?? (response.status === 401 ? 'unauthorized' : response.status === 403 ? 'forbidden' : 'http_error')
    const message = envelope?.error?.message || defaultMessage(response.status)
    const error = new ApiError({ status: response.status, code, message, field: envelope?.error?.field ?? null })
    if (response.status === 401) {
      unauthorizedHandler?.()
    } else if (response.status === 403) {
      forbiddenHandler?.(error)
    }
    throw error
  }

  if (envelope && typeof envelope === 'object' && envelope.ok === true && 'data' in envelope) {
    return envelope.data as T
  }
  return payload as T
}

/**
 * 发请求并解包 `{ ok, data }`（若后端直接返回裸对象也兼容）。
 * GET 遇到网络错误 / 5xx 自动重试 1 次；写请求不重试。
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const attempts = WRITE_METHODS.has(method) ? 1 : 2
  let lastError: ApiError | null = null

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fetchOnce<T>(path, options)
    } catch (error) {
      const apiError = toApiError(error)
      lastError = apiError
      const retryable =
        attempt < attempts - 1 && (apiError.status === 0 || apiError.status >= 500)
      if (!retryable) throw apiError
      await sleep(150)
    }
  }

  throw lastError ?? new ApiError({ status: 0, code: 'network_error', message: '网络连接失败' })
}

export const api = {
  get<T>(path: string, query?: RequestOptions['query'], signal?: AbortSignal) {
    return request<T>(path, { method: 'GET', query, signal })
  },
  post<T>(path: string, body?: unknown, query?: RequestOptions['query']) {
    return request<T>(path, { method: 'POST', body, query })
  },
  put<T>(path: string, body?: unknown) {
    return request<T>(path, { method: 'PUT', body })
  },
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, { method: 'PATCH', body })
  },
  delete<T>(path: string, body?: unknown) {
    return request<T>(path, { method: 'DELETE', body })
  },
}
