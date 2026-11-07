<template>
  <div>
    <PageHeader
      title="记忆 API 设置"
      description="配置向量化（Embedding）与重排（Rerank）模型；未配置或调用失败时自动回退 FTS + 规则。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">
          刷新
        </v-btn>
      </template>
    </PageHeader>

    <v-alert type="info" variant="tonal" density="compact" icon="mdi-brain" class="mb-4">
      API Key 由服务端加密保存，页面只显示「已配置」；留空表示不修改，勾选「清除」才会删除。
      保存后测试连接使用的是服务端已保存的配置。
    </v-alert>

    <v-alert v-if="loadError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ loadError }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !settings" variant="table" :rows="5" />

    <template v-else-if="settings">
      <v-card class="settings-card status-card mb-4" data-testid="memory-settings-status">
        <div class="card-head">
          <div class="card-head__text">
            <h3 class="card-title">
              <v-icon color="primary" size="20">mdi-pulse</v-icon>
              运行状态
            </h3>
            <p class="card-sub text-muted">
              当前检索链路：向量化 / 重排是否可用，以及 FTS 兜底状态。
            </p>
          </div>
          <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="statusLoading" @click="loadStatus">
            刷新状态
          </v-btn>
        </div>
        <v-alert v-if="statusError" type="info" variant="tonal" density="compact" class="mb-3">
          {{ statusError }}
        </v-alert>
        <div class="status-grid">
          <div class="status-item">
            <div class="status-label text-muted">向量化</div>
            <v-chip :color="providerState(status?.embedding).color" variant="tonal" size="small">
              {{ providerState(status?.embedding).label }}
            </v-chip>
            <div class="status-meta text-muted">{{ providerMeta(status?.embedding) }}</div>
          </div>
          <div class="status-item">
            <div class="status-label text-muted">重排</div>
            <v-chip :color="providerState(status?.rerank).color" variant="tonal" size="small">
              {{ providerState(status?.rerank).label }}
            </v-chip>
            <div class="status-meta text-muted">{{ providerMeta(status?.rerank) }}</div>
          </div>
          <div class="status-item">
            <div class="status-label text-muted">FTS</div>
            <v-chip :color="status?.fts?.available === false ? 'error' : 'success'" variant="tonal" size="small">
              {{ status?.fts?.available === false ? '不可用' : '可用' }} · {{ status?.fts?.mode || 'BM25' }}
            </v-chip>
            <div class="status-meta text-muted">全文检索兜底链路</div>
          </div>
        </div>
        <v-alert
          v-if="status?.embedding?.state === 'degraded' || status?.rerank?.state === 'degraded'"
          type="error"
          variant="tonal"
          density="compact"
          class="mt-3"
        >
          检索已回退 FTS + 规则重排；请检查向量化/重排配置或查看错误信息。
        </v-alert>
      </v-card>

      <v-row dense>
        <!-- 向量化 -->
        <v-col cols="12" lg="6">
          <v-card class="settings-card" data-testid="memory-settings-embedding">
            <div class="card-head">
              <div class="card-head__text">
                <h3 class="card-title">
                  <v-icon color="primary" size="20">mdi-vector-polyline</v-icon>
                  向量化（Embedding）
                </h3>
                <p class="card-sub text-muted">把记忆文本转为向量，用于语义召回；失败自动回退 FTS。</p>
              </div>
              <v-switch
                v-model="embedding.enabled"
                color="primary"
                density="compact"
                hide-details
                :label="embedding.enabled ? '已启用' : '未启用'"
              />
            </div>

            <v-alert
              v-if="embeddingError"
              type="error"
              variant="tonal"
              density="compact"
              class="mb-3"
            >
              {{ embeddingError }}
            </v-alert>

            <v-text-field
              v-model.trim="embedding.base_url"
              label="Base URL"
              placeholder="https://api.openai.com/v1"
              :error-messages="embeddingFieldError('base_url')"
              class="mb-2"
            />
            <v-text-field
              v-model="embedding.api_key"
              label="API Key"
              type="password"
              autocomplete="new-password"
              :placeholder="embedding.has_api_key ? '已配置（留空不修改）' : '未配置'"
              :hint="embedding.has_api_key ? '已配置：留空表示不修改，勾选下方可清除' : '未配置：填写后保存并测试连接'"
              persistent-hint
              :error-messages="embeddingFieldError('api_key')"
              class="mb-1"
            />
            <v-checkbox
              v-if="embedding.has_api_key"
              v-model="embedding.clear_api_key"
              label="清除已配置的 API Key"
              density="compact"
              hide-details
              color="error"
              class="mb-2"
            />
            <v-text-field
              v-model.trim="embedding.model"
              label="模型"
              placeholder="text-embedding-3-small"
              class="mb-2"
            />
            <v-row dense>
              <v-col cols="4">
                <v-text-field
                  v-model.number="embedding.dimensions"
                  label="维度"
                  type="number"
                  min="1"
                  max="8192"
                  :error-messages="embeddingFieldError('dimensions')"
                />
              </v-col>
              <v-col cols="4">
                <v-text-field
                  v-model.number="embedding.timeout_seconds"
                  label="超时（秒）"
                  type="number"
                  min="1"
                  max="120"
                  :error-messages="embeddingFieldError('timeout_seconds')"
                />
              </v-col>
              <v-col cols="4">
                <v-text-field
                  v-model.number="embedding.batch_size"
                  label="批大小"
                  type="number"
                  min="1"
                  max="256"
                  :error-messages="embeddingFieldError('batch_size')"
                />
              </v-col>
            </v-row>

            <div class="card-actions">
              <v-btn
                color="primary"
                :loading="savingEmbedding"
                data-testid="memory-settings-save-embedding"
                @click="saveEmbedding"
               variant="tonal">
                保存
              </v-btn>
              <v-btn
                variant="tonal"
                prepend-icon="mdi-connection"
                :loading="testingEmbedding"
                data-testid="memory-settings-test-embedding"
                @click="testEmbedding"
              >
                测试连接
              </v-btn>
              <v-spacer />
              <span v-if="embedding.has_api_key" class="key-state text-muted">
                <v-icon size="14">mdi-lock-check-outline</v-icon>
                API Key 已配置
              </span>
            </div>

            <v-alert
              v-if="embeddingTest"
              :type="embeddingTest.ok ? 'success' : 'error'"
              variant="tonal"
              density="compact"
              class="mt-3"
              data-testid="memory-settings-test-result-embedding"
            >
              <div class="test-result">
                <span>{{ embeddingTest.message }}</span>
                <v-chip size="x-small" variant="tonal" :color="embeddingTest.ok ? 'success' : 'error'">
                  {{ embeddingTest.latency }}
                </v-chip>
              </div>
            </v-alert>
          </v-card>
        </v-col>

        <!-- 重排 -->
        <v-col cols="12" lg="6">
          <v-card class="settings-card" data-testid="memory-settings-rerank">
            <div class="card-head">
              <div class="card-head__text">
                <h3 class="card-title">
                  <v-icon color="primary" size="20">mdi-sort-variant</v-icon>
                  重排（Rerank）
                </h3>
                <p class="card-sub text-muted">对候选记忆重新打分排序；未配置时使用规则重排。</p>
              </div>
              <v-switch
                v-model="rerank.enabled"
                color="primary"
                density="compact"
                hide-details
                :label="rerank.enabled ? '已启用' : '未启用'"
              />
            </div>

            <v-alert v-if="rerankError" type="error" variant="tonal" density="compact" class="mb-3">
              {{ rerankError }}
            </v-alert>

            <v-text-field
              v-model.trim="rerank.base_url"
              label="Base URL"
              placeholder="https://api.cohere.com"
              :error-messages="rerankFieldError('base_url')"
              class="mb-2"
            />
            <v-text-field
              v-model="rerank.api_key"
              label="API Key"
              type="password"
              autocomplete="new-password"
              :placeholder="rerank.has_api_key ? '已配置（留空不修改）' : '未配置'"
              :hint="rerank.has_api_key ? '已配置：留空表示不修改，勾选下方可清除' : '未配置：填写后保存并测试连接'"
              persistent-hint
              :error-messages="rerankFieldError('api_key')"
              class="mb-1"
            />
            <v-checkbox
              v-if="rerank.has_api_key"
              v-model="rerank.clear_api_key"
              label="清除已配置的 API Key"
              density="compact"
              hide-details
              color="error"
              class="mb-2"
            />
            <v-text-field
              v-model.trim="rerank.model"
              label="模型"
              placeholder="rerank-multilingual-v3.0"
              class="mb-2"
            />
            <v-row dense>
              <v-col cols="6">
                <v-text-field
                  v-model.number="rerank.top_n"
                  label="重排条数（top_n）"
                  type="number"
                  min="1"
                  max="100"
                  :error-messages="rerankFieldError('top_n')"
                />
              </v-col>
              <v-col cols="6">
                <v-text-field
                  v-model.number="rerank.timeout_seconds"
                  label="超时（秒）"
                  type="number"
                  min="1"
                  max="120"
                  :error-messages="rerankFieldError('timeout_seconds')"
                />
              </v-col>
            </v-row>

            <div class="card-actions">
              <v-btn
                color="primary"
                :loading="savingRerank"
                data-testid="memory-settings-save-rerank"
                @click="saveRerank"
               variant="tonal">
                保存
              </v-btn>
              <v-btn
                variant="tonal"
                prepend-icon="mdi-connection"
                :loading="testingRerank"
                data-testid="memory-settings-test-rerank"
                @click="testRerank"
              >
                测试连接
              </v-btn>
              <v-spacer />
              <span v-if="rerank.has_api_key" class="key-state text-muted">
                <v-icon size="14">mdi-lock-check-outline</v-icon>
                API Key 已配置
              </span>
            </div>

            <v-alert
              v-if="rerankTest"
              :type="rerankTest.ok ? 'success' : 'error'"
              variant="tonal"
              density="compact"
              class="mt-3"
              data-testid="memory-settings-test-result-rerank"
            >
              <div class="test-result">
                <span>{{ rerankTest.message }}</span>
                <v-chip size="small" variant="tonal" :color="rerankTest.ok ? 'success' : 'error'">
                  {{ rerankTest.latency }}
                </v-chip>
              </div>
            </v-alert>
          </v-card>
        </v-col>
      </v-row>

      <!-- 检索行为 -->
      <v-card class="settings-card behavior-card" data-testid="memory-settings-behavior">
        <div class="card-head">
          <div class="card-head__text">
            <h3 class="card-title">
              <v-icon color="primary" size="20">mdi-tune-variant</v-icon>
              检索行为
            </h3>
            <p class="card-sub text-muted">
              控制候选数量与 RRF 融合参数；仅在启用向量化/重排时生效，未配置时按 FTS + 规则运行。
            </p>
          </div>
        </div>

        <v-alert v-if="behaviorError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ behaviorError }}
        </v-alert>

        <v-row dense>
          <v-col cols="12" sm="6" lg="3">
            <v-text-field
              v-model.number="behavior.vector_candidate_limit"
              label="向量候选数"
              type="number"
              min="1"
              max="1000"
              :error-messages="behaviorFieldError('vector_candidate_limit')"
            />
          </v-col>
          <v-col cols="12" sm="6" lg="3">
            <v-text-field
              v-model.number="behavior.rerank_candidate_limit"
              label="重排候选数"
              type="number"
              min="1"
              max="1000"
              :error-messages="behaviorFieldError('rerank_candidate_limit')"
            />
          </v-col>
          <v-col cols="12" sm="6" lg="3">
            <v-text-field
              v-model.number="behavior.rrf_k"
              label="RRF k 值"
              type="number"
              min="1"
              max="100"
              :error-messages="behaviorFieldError('rrf_k')"
            />
          </v-col>
          <v-col cols="12" sm="6" lg="3">
            <v-text-field
              v-model.number="behavior.recall_top_k"
              label="召回条数"
              type="number"
              min="1"
              max="50"
              :error-messages="behaviorFieldError('recall_top_k')"
            />
          </v-col>
        </v-row>

        <v-divider class="my-4" />
        <v-row dense>
          <v-col cols="12" md="6">
            <v-switch
              v-model="behavior.auto_inject"
              color="primary"
              density="compact"
              hide-details
              label="主动注入（auto_inject）"
              data-testid="memory-behavior-auto-inject"
            />
            <p class="behavior-note text-muted">
              每次对话按当前话题召回相关记忆，写入 system prompt；会使用更多上下文 Token。
            </p>
          </v-col>
          <v-col cols="12" md="6">
            <v-switch
              v-model="behavior.auto_extract"
              color="primary"
              density="compact"
              hide-details
              label="自动记忆（auto_extract）"
              data-testid="memory-behavior-auto-extract"
            />
            <p class="behavior-note text-muted">
              每轮后从用户消息提取长期偏好/事实并写入记忆；涉及隐私内容时请谨慎开启。
            </p>
          </v-col>
        </v-row>

        <div class="card-actions">
          <v-btn color="primary" :loading="savingBehavior" @click="saveBehavior" variant="tonal">保存检索行为</v-btn>
        </div>
      </v-card>

      <p class="page-note text-muted">
        未配置时：记忆检索使用 SQLite FTS（BM25）+ 规则重排（0.5 BM25 / 0.3 重要度 / 0.2 新近度）。
        向量化或重排调用失败不会影响基础检索，请求会回退并记录日志。
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useUiStore } from '@/stores/ui'
import { isApiError } from '@/api/client'
import {
  getMemorySettings,
  getMemorySettingsStatus,
  testMemorySettings,
  updateMemorySettings,
} from '@/api/admin'
import { errorMessage } from '@/utils/errors'
import {
  behaviorFormFrom,
  buildBehaviorPayload,
  buildEmbeddingPayload,
  buildRerankPayload,
  defaultBehavior,
  defaultEmbedding,
  defaultRerank,
  embeddingFormFrom,
  formatDuration,
  normalizeMemorySettings,
  rerankFormFrom,
  validateBehaviorForm,
  validateEmbeddingForm,
  validateRerankForm,
} from '@/utils/memorySettings'
import type {
  MemoryProviderStatus,
  MemorySettings,
  MemorySettingsStatus,
  MemorySettingsTestResult,
} from '@/types'

const ui = useUiStore()

const loading = ref(false)
const loadError = ref('')
const settings = ref<MemorySettings | null>(null)
const status = ref<MemorySettingsStatus | null>(null)
const statusLoading = ref(false)
const statusError = ref('')

const embedding = reactive(embeddingFormFrom(defaultEmbedding))
const rerank = reactive(rerankFormFrom(defaultRerank))
const behavior = reactive(behaviorFormFrom(defaultBehavior))

const embeddingErrors = reactive<Record<string, string>>({})
const rerankErrors = reactive<Record<string, string>>({})
const behaviorErrors = reactive<Record<string, string>>({})

const savingEmbedding = ref(false)
const savingRerank = ref(false)
const savingBehavior = ref(false)
const embeddingError = ref('')
const rerankError = ref('')
const behaviorError = ref('')

interface TestFeedback {
  ok: boolean
  message: string
  latency: string
}

const testingEmbedding = ref(false)
const testingRerank = ref(false)
const embeddingTest = ref<TestFeedback | null>(null)
const rerankTest = ref<TestFeedback | null>(null)

function friendlyError(error: unknown, fallback: string): string {
  if (isApiError(error) && (error.status === 404 || error.status === 501)) {
    return '后端接口尚未就绪（404/501），请稍后刷新重试。'
  }
  return errorMessage(error, fallback)
}

function clearErrors(target: Record<string, string>): void {
  for (const key of Object.keys(target)) delete target[key]
}

function embeddingFieldError(key: string): string | undefined {
  return embeddingErrors[key]
}

function rerankFieldError(key: string): string | undefined {
  return rerankErrors[key]
}

function behaviorFieldError(key: string): string | undefined {
  return behaviorErrors[key]
}

function applySettings(data: Partial<MemorySettings>): void {
  const normalized = normalizeMemorySettings(data)
  settings.value = normalized
  Object.assign(embedding, embeddingFormFrom(normalized.embedding))
  Object.assign(rerank, rerankFormFrom(normalized.rerank))
  Object.assign(behavior, behaviorFormFrom(normalized.behavior))
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  await Promise.allSettled([loadSettings(), loadStatus()])
  loading.value = false
}

async function loadSettings(): Promise<void> {
  try {
    const data = await getMemorySettings()
    applySettings(data)
  } catch (error) {
    loadError.value = friendlyError(error, '加载记忆 API 设置失败')
  }
}

async function loadStatus(): Promise<void> {
  statusLoading.value = true
  statusError.value = ''
  try {
    status.value = await getMemorySettingsStatus()
  } catch (error) {
    const apiError = isApiError(error) ? error : null
    statusError.value =
      apiError && (apiError.status === 404 || apiError.status === 405)
        ? '运行状态接口尚未就绪，请稍后刷新重试。'
        : friendlyError(error, '加载运行状态失败')
  } finally {
    statusLoading.value = false
  }
}

function providerState(provider?: MemoryProviderStatus): { label: string; color: string } {
  if (
    !provider ||
    provider.state === 'unconfigured' ||
    provider.configured === false ||
    provider.enabled === false
  ) {
    return { label: '未配置', color: 'default' }
  }
  if (provider.state === 'degraded') return { label: '已配置但降级', color: 'warning' }
  if (provider.state === 'ok') return { label: '已启用 · 正常', color: 'success' }
  return { label: provider.state || '未知', color: 'default' }
}

function providerMeta(provider?: MemoryProviderStatus): string {
  if (!provider) return '暂无状态'
  const last = provider.last_checked || provider.last_test_at || provider.last_tested_at
  const time = last ? new Date(last * 1000).toLocaleString('zh-CN') : '尚未测试'
  const latency = provider.latency_ms ? `（${provider.latency_ms}ms）` : ''
  if (provider.last_error) return `${time} · ${provider.last_error}`
  return provider.last_ok === false ? `${time} · 最近测试失败` : `最近测试：${time}${latency}`
}

async function saveEmbedding(): Promise<void> {
  clearErrors(embeddingErrors)
  embeddingError.value = ''
  const errors = validateEmbeddingForm(embedding)
  if (Object.keys(errors).length) {
    Object.assign(embeddingErrors, errors)
    return
  }

  savingEmbedding.value = true
  try {
    const result = await updateMemorySettings({
      embedding: buildEmbeddingPayload(embedding),
    })
    if (result?.embedding) applySettings(result)
    else await load()
    ui.notify('向量化设置已保存', 'success')
  } catch (error) {
    embeddingError.value = friendlyError(error, '保存向量化设置失败')
  } finally {
    savingEmbedding.value = false
  }
}

async function saveRerank(): Promise<void> {
  clearErrors(rerankErrors)
  rerankError.value = ''
  const errors = validateRerankForm(rerank)
  if (Object.keys(errors).length) {
    Object.assign(rerankErrors, errors)
    return
  }

  savingRerank.value = true
  try {
    const result = await updateMemorySettings({ rerank: buildRerankPayload(rerank) })
    if (result?.rerank) applySettings(result)
    else await load()
    ui.notify('重排设置已保存', 'success')
  } catch (error) {
    rerankError.value = friendlyError(error, '保存重排设置失败')
  } finally {
    savingRerank.value = false
  }
}

async function saveBehavior(): Promise<void> {
  clearErrors(behaviorErrors)
  behaviorError.value = ''
  const errors = validateBehaviorForm(behavior)
  if (Object.keys(errors).length) {
    Object.assign(behaviorErrors, errors)
    return
  }

  savingBehavior.value = true
  try {
    const result = await updateMemorySettings({ behavior: buildBehaviorPayload(behavior) })
    if (result?.behavior) applySettings(result)
    else await load()
    ui.notify('检索行为已保存', 'success')
  } catch (error) {
    behaviorError.value = friendlyError(error, '保存检索行为失败')
  } finally {
    savingBehavior.value = false
  }
}

function testSummary(kind: 'embedding' | 'rerank', result: MemorySettingsTestResult): string {
  const parts: string[] = []
  if (kind === 'embedding' && typeof result.dim === 'number') parts.push(`维度 ${result.dim}`)
  if (kind === 'rerank' && typeof result.count === 'number') parts.push(`返回 ${result.count} 条`)
  const base = result.message || (result.ok ? '连接成功' : '连接失败')
  return parts.length ? `${base}（${parts.join('，')}）` : base
}

async function testEmbedding(): Promise<void> {
  testingEmbedding.value = true
  embeddingTest.value = null
  const started = performance.now()
  try {
    const result = await testMemorySettings('embedding')
    embeddingTest.value = {
      ok: Boolean(result.ok),
      message: testSummary('embedding', result),
      latency: formatDuration(performance.now() - started),
    }
  } catch (error) {
    embeddingTest.value = {
      ok: false,
      message: friendlyError(error, '向量化连接测试失败'),
      latency: formatDuration(performance.now() - started),
    }
  } finally {
    testingEmbedding.value = false
  }
}

async function testRerank(): Promise<void> {
  testingRerank.value = true
  rerankTest.value = null
  const started = performance.now()
  try {
    const result = await testMemorySettings('rerank')
    rerankTest.value = {
      ok: Boolean(result.ok),
      message: testSummary('rerank', result),
      latency: formatDuration(performance.now() - started),
    }
  } catch (error) {
    rerankTest.value = {
      ok: false,
      message: friendlyError(error, '重排连接测试失败'),
      latency: formatDuration(performance.now() - started),
    }
  } finally {
    testingRerank.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.status-card {
  height: auto;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.status-item {
  padding: 10px 12px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
}

.status-label {
  font-size: 11.5px;
  margin-bottom: 5px;
}

.status-meta {
  margin-top: 6px;
  font-size: 11.5px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.behavior-note {
  margin: 2px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
}

.settings-card {
  padding: 18px;
  height: 100%;
}

.behavior-card {
  margin-top: 16px;
  height: auto;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 0.98rem;
  font-weight: 650;
}

.card-sub {
  margin: 4px 0 0;
  font-size: 0.76rem;
  line-height: 1.55;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.key-state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.74rem;
}

.test-result {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.page-note {
  margin: 16px 0 0;
  font-size: 0.76rem;
  line-height: 1.6;
}
</style>
