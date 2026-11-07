/**
 * 记忆 API 设置的表单模型 / 掩码合并 / 校验。
 *
 * 契约（docs/API.md 待补）：
 * - `api_key` 返回掩码 `••••••••`；PUT 时传掩码或省略表示「不修改」，传空串表示「清除」。
 * - 因此表单永远从空输入开始，用 `has_api_key` 显示「已配置」，用 `clear_api_key` 显式清除。
 */

import type {
  MemoryBehaviorConfig,
  MemoryEmbeddingConfig,
  MemoryRerankConfig,
  MemorySettings,
  MemorySettingsPatch,
} from '@/types'

export const MASKED_API_KEY = '••••••••'

export interface ProviderFormState {
  enabled: boolean
  base_url: string
  api_key: string
  has_api_key: boolean
  clear_api_key: boolean
  model: string
}

export interface EmbeddingFormState extends ProviderFormState {
  dimensions: number
  timeout_seconds: number
  batch_size: number
}

export interface RerankFormState extends ProviderFormState {
  top_n: number
  timeout_seconds: number
}

export interface BehaviorFormState {
  vector_candidate_limit: number
  rerank_candidate_limit: number
  rrf_k: number
  recall_top_k: number
}

export type FormErrors = Record<string, string>

export const defaultEmbedding: MemoryEmbeddingConfig = {
  enabled: false,
  base_url: '',
  api_key: '',
  model: '',
  dimensions: 1536,
  timeout_seconds: 20,
  batch_size: 32,
  has_api_key: false,
}

export const defaultRerank: MemoryRerankConfig = {
  enabled: false,
  base_url: '',
  api_key: '',
  model: '',
  top_n: 10,
  timeout_seconds: 20,
  has_api_key: false,
}

export const defaultBehavior: MemoryBehaviorConfig = {
  vector_candidate_limit: 50,
  rerank_candidate_limit: 30,
  rrf_k: 60,
  recall_top_k: 5,
}

function toInt(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback
}

function toBool(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function hasStoredKey(config: { api_key?: string; has_api_key?: boolean }): boolean {
  if (typeof config.has_api_key === 'boolean') return config.has_api_key
  return Boolean(config.api_key && config.api_key !== '')
}

/** 服务端可能省略 section；在页面内统一补齐，避免表单 undefined。 */
export function normalizeMemorySettings(data: Partial<MemorySettings> | null | undefined): MemorySettings {
  const embedding = data?.embedding ?? defaultEmbedding
  const rerank = data?.rerank ?? defaultRerank
  const behavior = data?.behavior ?? defaultBehavior
  return {
    embedding: {
      ...defaultEmbedding,
      ...embedding,
      has_api_key: hasStoredKey(embedding),
    },
    rerank: {
      ...defaultRerank,
      ...rerank,
      has_api_key: hasStoredKey(rerank),
    },
    behavior: { ...defaultBehavior, ...behavior },
  }
}

export function embeddingFormFrom(config: MemoryEmbeddingConfig): EmbeddingFormState {
  return {
    enabled: toBool(config.enabled),
    base_url: config.base_url ?? '',
    // 掩码不回填到输入框：留空 = 不修改
    api_key: '',
    has_api_key: hasStoredKey(config),
    clear_api_key: false,
    model: config.model ?? '',
    dimensions: toInt(config.dimensions, defaultEmbedding.dimensions),
    timeout_seconds: toInt(config.timeout_seconds, defaultEmbedding.timeout_seconds),
    batch_size: toInt(config.batch_size, defaultEmbedding.batch_size),
  }
}

export function rerankFormFrom(config: MemoryRerankConfig): RerankFormState {
  return {
    enabled: toBool(config.enabled),
    base_url: config.base_url ?? '',
    api_key: '',
    has_api_key: hasStoredKey(config),
    clear_api_key: false,
    model: config.model ?? '',
    top_n: toInt(config.top_n, defaultRerank.top_n),
    timeout_seconds: toInt(config.timeout_seconds, defaultRerank.timeout_seconds),
  }
}

export function behaviorFormFrom(config: MemoryBehaviorConfig): BehaviorFormState {
  return {
    vector_candidate_limit: toInt(
      config.vector_candidate_limit,
      defaultBehavior.vector_candidate_limit,
    ),
    rerank_candidate_limit: toInt(
      config.rerank_candidate_limit,
      defaultBehavior.rerank_candidate_limit,
    ),
    rrf_k: toInt(config.rrf_k, defaultBehavior.rrf_k),
    recall_top_k: toInt(config.recall_top_k, defaultBehavior.recall_top_k),
  }
}

interface ApiKeySource {
  api_key: string
  has_api_key: boolean
  clear_api_key: boolean
}

/**
 * 合并 api_key 三态：
 * - 勾选清除 → `''`
 * - 输入了新值（且不是掩码）→ 新值
 * - 其余 → 省略（后端保持原值）
 */
function applyApiKey<T extends object>(target: T, form: ApiKeySource): T & { api_key?: string } {
  const result = { ...target } as T & { api_key?: string }
  if (form.clear_api_key) {
    result.api_key = ''
  } else {
    const typed = form.api_key.trim()
    if (typed && typed !== MASKED_API_KEY) result.api_key = typed
  }
  return result
}

export function buildEmbeddingPayload(
  form: EmbeddingFormState,
): Partial<MemoryEmbeddingConfig> {
  return applyApiKey(
    {
      enabled: form.enabled,
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      dimensions: toInt(form.dimensions, defaultEmbedding.dimensions),
      timeout_seconds: toInt(form.timeout_seconds, defaultEmbedding.timeout_seconds),
      batch_size: toInt(form.batch_size, defaultEmbedding.batch_size),
    },
    form,
  )
}

export function buildRerankPayload(form: RerankFormState): Partial<MemoryRerankConfig> {
  return applyApiKey(
    {
      enabled: form.enabled,
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      top_n: toInt(form.top_n, defaultRerank.top_n),
      timeout_seconds: toInt(form.timeout_seconds, defaultRerank.timeout_seconds),
    },
    form,
  )
}

export function buildBehaviorPayload(form: BehaviorFormState): MemoryBehaviorConfig {
  return {
    vector_candidate_limit: toInt(
      form.vector_candidate_limit,
      defaultBehavior.vector_candidate_limit,
    ),
    rerank_candidate_limit: toInt(
      form.rerank_candidate_limit,
      defaultBehavior.rerank_candidate_limit,
    ),
    rrf_k: toInt(form.rrf_k, defaultBehavior.rrf_k),
    recall_top_k: toInt(form.recall_top_k, defaultBehavior.recall_top_k),
  }
}

export function buildMemorySettingsPatch(
  parts: {
    embedding?: EmbeddingFormState
    rerank?: RerankFormState
    behavior?: BehaviorFormState
  },
): MemorySettingsPatch {
  const patch: MemorySettingsPatch = {}
  if (parts.embedding) patch.embedding = buildEmbeddingPayload(parts.embedding)
  if (parts.rerank) patch.rerank = buildRerankPayload(parts.rerank)
  if (parts.behavior) patch.behavior = buildBehaviorPayload(parts.behavior)
  return patch
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

function validateInt(
  errors: FormErrors,
  key: string,
  value: number,
  min: number,
  max: number,
  label: string,
): void {
  if (!Number.isInteger(value) || value < min || value > max) {
    errors[key] = `${label}需为 ${min}–${max} 的整数`
  }
}

export function validateEmbeddingForm(form: EmbeddingFormState): FormErrors {
  const errors: FormErrors = {}
  if (!validateUrl(form.base_url.trim())) errors.base_url = '请输入合法的 http(s) 地址'
  validateInt(errors, 'dimensions', Number(form.dimensions), 1, 8192, '向量维度')
  validateInt(errors, 'timeout_seconds', Number(form.timeout_seconds), 1, 120, '超时时间')
  validateInt(errors, 'batch_size', Number(form.batch_size), 1, 256, '批大小')
  return errors
}

export function validateRerankForm(form: RerankFormState): FormErrors {
  const errors: FormErrors = {}
  if (!validateUrl(form.base_url.trim())) errors.base_url = '请输入合法的 http(s) 地址'
  validateInt(errors, 'top_n', Number(form.top_n), 1, 100, '重排条数')
  validateInt(errors, 'timeout_seconds', Number(form.timeout_seconds), 1, 120, '超时时间')
  return errors
}

export function validateBehaviorForm(form: BehaviorFormState): FormErrors {
  const errors: FormErrors = {}
  validateInt(
    errors,
    'vector_candidate_limit',
    Number(form.vector_candidate_limit),
    1,
    1000,
    '向量候选数',
  )
  validateInt(
    errors,
    'rerank_candidate_limit',
    Number(form.rerank_candidate_limit),
    1,
    1000,
    '重排候选数',
  )
  validateInt(errors, 'rrf_k', Number(form.rrf_k), 1, 100, 'RRF k 值')
  validateInt(errors, 'recall_top_k', Number(form.recall_top_k), 1, 50, '召回条数')
  return errors
}

/** 测试连接结果里的延迟展示。 */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`
}
