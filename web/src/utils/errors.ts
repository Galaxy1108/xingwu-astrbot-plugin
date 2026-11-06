import { isApiError } from '@/api/client'

/** 把错误转为可直接展示的文案。 */
export function errorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  if (isApiError(error)) return error.message || fallback
  if (error instanceof Error) return error.message || fallback
  if (typeof error === 'string' && error) return error
  return fallback
}

/** 表单字段错误（用于 VTextField 的 error-messages）。 */
export function fieldError(error: unknown, field: string): string | null {
  if (isApiError(error) && error.field === field) return error.message
  return null
}

export function isFieldError(error: unknown, field: string): boolean {
  return isApiError(error) && error.field === field
}

export function errorCode(error: unknown): string | null {
  return isApiError(error) ? error.code : null
}
