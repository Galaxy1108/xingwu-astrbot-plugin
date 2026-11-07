import { describe, expect, it } from 'vitest'
import {
  MASKED_API_KEY,
  buildModelPayload,
  canSubmitModelForm,
  emptyModelForm,
  formatPoints,
  modelFormFrom,
  normalizeModelList,
  providerLabel,
  validateModelForm,
} from '../modelProfiles'
import type { ModelProfile } from '@/types'

const model: ModelProfile = {
  id: 'm_1',
  name: 'GPT-4o mini',
  provider: 'openai',
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4o-mini',
  api_key: MASKED_API_KEY,
  has_api_key: true,
  points_per_1k_input: 1.5,
  points_per_1k_output: 6,
  currency: 'CNY',
  enabled: true,
  note: '默认模型',
  created_at: 1,
  updated_at: 2,
}

describe('模型与定价 · 表单校验', () => {
  it('空表单缺少名称与模型标识', () => {
    const errors = validateModelForm(emptyModelForm())
    expect(errors.name).toBeTruthy()
    expect(errors.model).toBeTruthy()
    expect(canSubmitModelForm(emptyModelForm())).toBe(false)
  })

  it('名称为空白字符视为未填写', () => {
    const form = { ...emptyModelForm(), name: '   ', model: 'gpt-4o-mini' }
    expect(validateModelForm(form).name).toBeTruthy()
  })

  it('单价不能为负数', () => {
    const form = {
      ...emptyModelForm(),
      name: '模型 A',
      model: 'm',
      points_per_1k_input: -1,
      points_per_1k_output: 0,
    }
    const errors = validateModelForm(form)
    expect(errors.points_per_1k_input).toBeTruthy()
    expect(errors.points_per_1k_output).toBeUndefined()
  })

  it('非法 Base URL 报错，合法 http(s) 通过', () => {
    const form = {
      ...emptyModelForm(),
      name: '模型 A',
      model: 'm',
      base_url: 'ftp://example.com',
    }
    expect(validateModelForm(form).base_url).toBeTruthy()
    expect(validateModelForm({ ...form, base_url: 'https://example.com/v1' }).base_url).toBeUndefined()
  })

  it('完整合法表单可提交', () => {
    const form = modelFormFrom(model)
    expect(validateModelForm(form)).toEqual({})
    expect(canSubmitModelForm(form)).toBe(true)
  })
})

describe('模型与定价 · API Key 掩码合并与 payload', () => {
  it('掩码不回显到表单', () => {
    const form = modelFormFrom(model)
    expect(form.api_key).toBe('')
    expect(form.has_api_key).toBe(true)
  })

  it('编辑时留空不修改 API Key（payload 省略字段）', () => {
    const payload = buildModelPayload(modelFormFrom(model))
    expect('api_key' in payload).toBe(false)
    expect(payload.name).toBe('GPT-4o mini')
    expect(payload.points_per_1k_output).toBe(6)
  })

  it('输入新 API Key 时提交新值', () => {
    const form = modelFormFrom(model)
    form.api_key = 'sk-123'
    expect(buildModelPayload(form).api_key).toBe('sk-123')
  })

  it('粘贴掩码不会覆盖真实密钥', () => {
    const form = modelFormFrom(model)
    form.api_key = MASKED_API_KEY
    expect('api_key' in buildModelPayload(form)).toBe(false)
  })

  it('勾选清除时提交空字符串', () => {
    const form = modelFormFrom(model)
    form.clear_api_key = true
    expect(buildModelPayload(form).api_key).toBe('')
  })

  it('数字字段输出为 number 并 trim 文本', () => {
    const form = modelFormFrom(model)
    form.name = '  模型 B  '
    form.model = '  m-2  '
    form.points_per_1k_input = 0.25
    const payload = buildModelPayload(form)
    expect(payload.name).toBe('模型 B')
    expect(payload.model).toBe('m-2')
    expect(payload.points_per_1k_input).toBe(0.25)
  })
})

describe('模型与定价 · 列表兼容与展示', () => {
  it('兼容 {items} 与裸数组', () => {
    expect(normalizeModelList({ items: [model] })).toHaveLength(1)
    expect(normalizeModelList([model])).toHaveLength(1)
    expect(normalizeModelList(null)).toEqual([])
  })

  it('provider / 点数展示', () => {
    expect(providerLabel('openai')).toBe('OpenAI')
    expect(providerLabel('custom-x')).toBe('custom-x')
    expect(formatPoints(1.23456)).toBe('1.2346')
    expect(formatPoints(undefined)).toBe('—')
  })
})
