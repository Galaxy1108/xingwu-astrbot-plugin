/** 管理端「模型与定价」表单：校验、掩码合并、payload 构造。 */

import type { ModelProfile, ModelProfileInput } from '@/types'

export const MASKED_API_KEY = '••••••••'

export const MODEL_PROVIDERS = [
  { title: 'OpenAI', value: 'openai' },
  { title: 'Anthropic', value: 'anthropic' },
  { title: 'DeepSeek', value: 'deepseek' },
  { title: 'Gemini', value: 'gemini' },
  { title: 'Azure OpenAI', value: 'azure' },
  { title: 'OpenAI 兼容', value: 'openai_compatible' },
  { title: '其他', value: 'other' },
]

export const MODEL_CURRENCIES = [
  { title: '人民币（CNY）', value: 'CNY' },
  { title: '美元（USD）', value: 'USD' },
  { title: '点数（points）', value: 'points' },
]

export interface ModelFormState {
  name: string
  provider: string
  base_url: string
  model: string
  api_key: string
  has_api_key: boolean
  clear_api_key: boolean
  points_per_1k_input: number
  points_per_1k_output: number
  currency: string
  enabled: boolean
  note: string
}

export type ModelFormErrors = Record<string, string>

export function emptyModelForm(): ModelFormState {
  return {
    name: '',
    provider: 'openai',
    base_url: '',
    model: '',
    api_key: '',
    has_api_key: false,
    clear_api_key: false,
    points_per_1k_input: 0,
    points_per_1k_output: 0,
    currency: 'CNY',
    enabled: true,
    note: '',
  }
}

export function modelFormFrom(model: ModelProfile | null | undefined): ModelFormState {
  if (!model) return emptyModelForm()
  return {
    name: model.name ?? '',
    provider: model.provider || 'openai',
    base_url: model.base_url ?? '',
    model: model.model ?? '',
    // 服务端只给掩码；输入框永远从空开始，留空 = 不修改
    api_key: '',
    has_api_key: Boolean(model.has_api_key || (model.api_key && model.api_key !== '')),
    clear_api_key: false,
    points_per_1k_input: Number(model.points_per_1k_input ?? 0),
    points_per_1k_output: Number(model.points_per_1k_output ?? 0),
    currency: model.currency || 'CNY',
    enabled: Boolean(model.enabled),
    note: model.note ?? '',
  }
}

function validateUrl(value: string): boolean {
  if (!value) return true
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function validatePoints(
  errors: ModelFormErrors,
  key: 'points_per_1k_input' | 'points_per_1k_output',
  value: number,
  label: string,
): void {
  if (!Number.isFinite(value) || value < 0) {
    errors[key] = `${label}必须是不小于 0 的数字`
    return
  }
  if (value > 1_000_000) errors[key] = `${label}过大（上限 1,000,000）`
}

export function validateModelForm(form: ModelFormState): ModelFormErrors {
  const errors: ModelFormErrors = {}
  const name = form.name.trim()
  if (!name) errors.name = '请输入模型名称'
  else if (name.length > 80) errors.name = '名称最多 80 个字符'

  if (!form.provider) errors.provider = '请选择提供商'
  if (!form.model.trim()) errors.model = '请填写上游模型标识（model）'
  if (!validateUrl(form.base_url.trim())) errors.base_url = '请输入合法的 http(s) 地址'
  if (!form.currency) errors.currency = '请选择币种'

  validatePoints(errors, 'points_per_1k_input', Number(form.points_per_1k_input), '输入单价')
  validatePoints(errors, 'points_per_1k_output', Number(form.points_per_1k_output), '输出单价')

  return errors
}

export function canSubmitModelForm(form: ModelFormState): boolean {
  return Object.keys(validateModelForm(form)).length === 0
}

/**
 * api_key 三态（与记忆设置一致）：
 * - 勾选清除 → `''`
 * - 输入非空且不是掩码 → 新值
 * - 否则省略字段（编辑时保持原值；新建时不设置）
 */
export function buildModelPayload(form: ModelFormState): ModelProfileInput {
  const payload: ModelProfileInput = {
    name: form.name.trim(),
    provider: form.provider,
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    points_per_1k_input: Number(form.points_per_1k_input),
    points_per_1k_output: Number(form.points_per_1k_output),
    currency: form.currency,
    enabled: form.enabled,
    note: form.note.trim(),
  }

  if (form.clear_api_key) {
    payload.api_key = ''
  } else {
    const typed = form.api_key.trim()
    if (typed && typed !== MASKED_API_KEY) payload.api_key = typed
  }
  return payload
}

/** 兼容 `{items}` 与裸数组两种列表返回。 */
export function normalizeModelList(
  data: { items?: ModelProfile[] } | ModelProfile[] | null | undefined,
): ModelProfile[] {
  if (Array.isArray(data)) return data
  return data?.items ?? []
}

export function providerLabel(value: string): string {
  return MODEL_PROVIDERS.find((item) => item.value === value)?.title || value || '—'
}

export function formatPoints(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}
