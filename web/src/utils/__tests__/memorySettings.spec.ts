import { describe, expect, it } from 'vitest'
import {
  MASKED_API_KEY,
  buildBehaviorPayload,
  buildEmbeddingPayload,
  buildMemorySettingsPatch,
  buildRerankPayload,
  behaviorFormFrom,
  embeddingFormFrom,
  formatDuration,
  normalizeMemorySettings,
  rerankFormFrom,
  validateBehaviorForm,
  validateEmbeddingForm,
  validateRerankForm,
} from '../memorySettings'
import type { MemorySettings } from '@/types'

const settings: MemorySettings = {
  embedding: {
    enabled: true,
    base_url: 'https://api.example.com/v1',
    api_key: MASKED_API_KEY,
    model: 'embed-small',
    dimensions: 1024,
    timeout_seconds: 15,
    batch_size: 16,
    has_api_key: true,
  },
  rerank: {
    enabled: false,
    base_url: '',
    api_key: '',
    model: '',
    top_n: 8,
    timeout_seconds: 20,
    has_api_key: false,
  },
  behavior: {
    vector_candidate_limit: 40,
    rerank_candidate_limit: 20,
    rrf_k: 60,
    recall_top_k: 5,
  },
}

describe('记忆 API 设置 · 掩码合并', () => {
  it('把掩码转成「已配置」且输入框留空', () => {
    const form = embeddingFormFrom(settings.embedding)
    expect(form.api_key).toBe('')
    expect(form.has_api_key).toBe(true)
    expect(form.dimensions).toBe(1024)
  })

  it('留空不修改：payload 省略 api_key', () => {
    const form = embeddingFormFrom(settings.embedding)
    const payload = buildEmbeddingPayload(form)
    expect(payload.api_key).toBeUndefined()
    expect(payload.enabled).toBe(true)
    expect(payload.base_url).toBe('https://api.example.com/v1')
  })

  it('输入自定义掩码不会覆盖真实密钥', () => {
    const form = embeddingFormFrom(settings.embedding)
    form.api_key = MASKED_API_KEY
    expect(buildEmbeddingPayload(form).api_key).toBeUndefined()
  })

  it('输入新密钥时提交新值', () => {
    const form = embeddingFormFrom(settings.embedding)
    form.api_key = 'sk-new'
    expect(buildEmbeddingPayload(form).api_key).toBe('sk-new')
  })

  it('勾选清除时提交空字符串', () => {
    const form = rerankFormFrom({
      ...settings.rerank,
      api_key: MASKED_API_KEY,
      has_api_key: true,
    })
    form.clear_api_key = true
    expect(buildRerankPayload(form).api_key).toBe('')
  })

  it('新配置（无已保存密钥）留空时也不发送 api_key', () => {
    const form = rerankFormFrom({ ...settings.rerank, has_api_key: false })
    expect(buildRerankPayload(form).api_key).toBeUndefined()
  })

  it('部分更新只包含传入的 section', () => {
    const patch = buildMemorySettingsPatch({
      embedding: embeddingFormFrom(settings.embedding),
    })
    expect(Object.keys(patch)).toEqual(['embedding'])
    expect(patch.rerank).toBeUndefined()
    expect(patch.behavior).toBeUndefined()
  })

  it('behavior 字段转为整数并构造完整 payload', () => {
    const form = behaviorFormFrom(settings.behavior)
    form.rrf_k = 42
    expect(buildBehaviorPayload(form)).toEqual({
      vector_candidate_limit: 40,
      rerank_candidate_limit: 20,
      rrf_k: 42,
      recall_top_k: 5,
      auto_inject: true,
      auto_extract: true,
    })
  })

  it('缺省 section 用默认值补齐', () => {
    const normalized = normalizeMemorySettings({})
    expect(normalized.embedding.dimensions).toBeGreaterThan(0)
    expect(normalized.rerank.top_n).toBeGreaterThan(0)
    expect(normalized.behavior.rrf_k).toBeGreaterThan(0)
    expect(normalized.embedding.has_api_key).toBe(false)
  })
})

describe('记忆 API 设置 · 校验', () => {
  it('维度越界 / 非法 URL 会报错', () => {
    const form = embeddingFormFrom(settings.embedding)
    form.dimensions = 0
    form.base_url = 'not-a-url'
    const errors = validateEmbeddingForm(form)
    expect(errors.dimensions).toBeTruthy()
    expect(errors.base_url).toBeTruthy()
  })

  it('合法配置无错误', () => {
    expect(validateEmbeddingForm(embeddingFormFrom(settings.embedding))).toEqual({})
    expect(validateRerankForm(rerankFormFrom(settings.rerank))).toEqual({})
    expect(validateBehaviorForm(behaviorFormFrom(settings.behavior))).toEqual({})
  })

  it('top_n / 超时越界报错', () => {
    const form = rerankFormFrom(settings.rerank)
    form.top_n = 0
    form.timeout_seconds = 999
    const errors = validateRerankForm(form)
    expect(errors.top_n).toBeTruthy()
    expect(errors.timeout_seconds).toBeTruthy()
  })

  it('延迟格式化', () => {
    expect(formatDuration(42.4)).toBe('42 ms')
    expect(formatDuration(1500)).toBe('1.50 s')
    expect(formatDuration(Number.NaN)).toBe('—')
  })
})
