<template>
  <div>
    <PageHeader
      title="添加机器人"
      description="选择平台、命名并生成二维码，用对应 App 扫码确认；成功后机器人会自动上线。"
      back-to="/bots"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-robot-outline" to="/bots">我的 Bot</v-btn>
      </template>
    </PageHeader>

    <div class="steps" aria-label="接入步骤">
      <div class="step" :class="{ 'step--active': step === 'form', 'step--done': step !== 'form' }">
        <span class="step-index">{{ step === 'form' ? 1 : '✓' }}</span>
        <span>选择平台与名称</span>
      </div>
      <div class="step-line" />
      <div class="step" :class="{ 'step--active': step === 'qr', 'step--done': step === 'done' }">
        <span class="step-index">2</span>
        <span>扫码确认</span>
      </div>
      <div class="step-line" />
      <div class="step" :class="{ 'step--active': step === 'done' }">
        <span class="step-index">3</span>
        <span>完成接入</span>
      </div>
    </div>

    <div class="connect-layout">
      <div class="connect-main">
        <v-card v-if="step === 'form'" class="panel">
      <h2 class="section-title">1. 选择平台</h2>
      <div class="platform-grid" role="radiogroup" aria-label="平台">
        <div
          v-for="option in platformOptions"
          :key="option.value"
          class="platform-card"
          :class="{ 'platform-card--selected': platform === option.value }"
          role="radio"
          :aria-checked="platform === option.value"
          tabindex="0"
          @click="platform = option.value"
          @keydown.enter.prevent="platform = option.value"
          @keydown.space.prevent="platform = option.value"
        >
          <v-icon size="28" :color="platform === option.value ? 'primary' : undefined">
            {{ option.icon }}
          </v-icon>
          <div class="platform-copy">
            <div class="platform-title">{{ option.title }}</div>
            <div class="platform-desc">{{ option.description }}</div>
          </div>
          <v-icon v-if="platform === option.value" color="primary" size="20">mdi-check-circle</v-icon>
        </div>
      </div>

      <v-alert
        v-if="templatesError"
        type="warning"
        variant="tonal"
        density="compact"
        class="mt-4"
      >
        <div class="alert-row">
          <span>{{ templatesError }}</span>
          <v-btn size="small" variant="text" @click="loadTemplates">重试</v-btn>
        </div>
      </v-alert>

      <v-alert v-if="formError" type="error" variant="tonal" density="compact" class="mt-4">
        {{ formError }}
      </v-alert>

      <h2 class="section-title mt-6">2. 命名与模板</h2>
      <v-text-field
        v-model.trim="name"
        label="Bot 名称"
        hint="1–32 个字符，仅作为展示名"
        counter="32"
        maxlength="32"
        :error-messages="nameError"
        persistent-hint
      />
      <v-select
        v-model="templateId"
        label="模板"
        :items="templates"
        item-title="name"
        item-value="id"
        :loading="templatesLoading"
        no-data-text="暂无可用模板（请联系管理员）"
        class="mt-4"
      >
        <template #append-item>
          <div v-if="selectedTemplate?.description" class="template-hint text-muted">
            {{ selectedTemplate.description }}
          </div>
        </template>
      </v-select>
      <p class="template-copy-note text-muted">
        创建时会复制所选模板的配置，之后可在 Bot 设置中调整，不影响模板本身。
      </p>
      <v-select
        v-model="modelId"
        :items="modelOptions"
        item-title="title"
        item-value="value"
        label="模型配置（可选）"
        :loading="modelsLoading"
        clearable
        no-data-text="暂无可用模型配置"
        hint="不同模型点数单价不同，之后可在 Bot 设置修改"
        persistent-hint
        class="mt-4"
      />

      <v-btn
        color="primary"
        size="large"
        block
        class="mt-6"
        :loading="creating"
        :disabled="templates.length === 0"
        @click="onCreate"
       variant="tonal">
        创建并生成二维码
      </v-btn>
      <p class="form-note text-muted">
        扫码成功前不会创建机器人；中途退出会取消本次扫码会话，不会留下未配置的 Bot。
      </p>
    </v-card>

        <v-card
          v-else-if="step === 'qr'"
          class="panel"
          :class="{ 'panel--modal': isMobile }"
        >
          <div v-if="isMobile" class="qr-modal-head">
            <span class="qr-modal-title">扫码接入</span>
            <v-btn icon variant="text" aria-label="关闭扫码" @click="cancelFlow">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </div>
          <div class="qr-summary">
            <div>
              <h2 class="section-title qr-summary-title">扫码接入</h2>
              <p class="text-muted qr-summary-line">
                {{ name }} · {{ platformShortLabel(platform) }} · {{ selectedTemplateName }}
              </p>
            </div>
          </div>

      <v-alert v-if="qrErrorText" type="error" variant="tonal" class="mb-4">
        <div class="alert-row">
          <span>{{ qrErrorText }}</span>
          <div class="alert-actions">
            <v-btn size="small" variant="text" color="error" :loading="qrBusy" @click="regenerate">
              重试
            </v-btn>
          </div>
        </div>
      </v-alert>

      <QrPanel
        v-if="qr"
        :status="qrPanelStatus"
        :image="qr.qr_image"
        :expires-at="qr.expires_at"
        :refresh-count="qr.refresh_count"
        :message="qrMessage"
        :busy="qrBusy"
        @regenerate="regenerate"
      />

      <div v-else-if="!qrErrorText" class="qr-loading">
        <v-progress-circular indeterminate color="primary" />
        <span class="text-muted">正在生成二维码…</span>
      </div>

      <div class="qr-footer">
        <v-btn variant="text" @click="cancelFlow">取消并返回列表</v-btn>
      </div>
    </v-card>

        <v-card v-else class="panel done-panel">
          <v-icon size="64" color="success">mdi-check-decagram-outline</v-icon>
          <h2 class="done-title">已接入</h2>
          <p class="text-muted done-desc">
            「{{ finishedBot?.name || name }}」已完成扫码，正在上线（通常 5 秒内生效）。
          </p>
          <div class="done-actions">
            <v-btn color="primary" :to="finishedBot ? `/bots/${finishedBot.id}` : '/bots'" variant="tonal">
              查看 Bot 详情
            </v-btn>
            <v-btn variant="text" to="/bots">返回列表</v-btn>
          </div>
        </v-card>
      </div>

      <aside v-if="!isMobile" class="connect-aside">
        <v-card class="aside-card">
          <h3 class="aside-title">接入后会得到</h3>
          <ul class="aside-list">
            <li><v-icon size="16" color="primary">mdi-account-details-outline</v-icon> 独立人格与模型配置快照</li>
            <li><v-icon size="16" color="primary">mdi-database-lock-outline</v-icon> 每 Bot 一个 SQLCipher 加密记忆库</li>
            <li><v-icon size="16" color="primary">mdi-qrcode-scan</v-icon> 扫码凭据加密保存，可随时重新扫码</li>
          </ul>
        </v-card>
        <v-card class="aside-card">
          <h3 class="aside-title">安全与隐私</h3>
          <p class="aside-text">
            记忆与凭据均加密存储，管理员访问会留痕。删除 Bot 时会同时清理记忆库、绑定与平台实例。
          </p>
        </v-card>
        <v-card class="aside-card aside-card--muted">
          <h3 class="aside-title">需要帮助？</h3>
          <p class="aside-text">没有可用模板或邀请码，请联系平台管理员开通。</p>
        </v-card>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import PageHeader from '@/components/PageHeader.vue'
import QrPanel from '@/components/QrPanel.vue'
import { usePolling } from '@/composables/usePolling'
import { useUiStore } from '@/stores/ui'
import { listTemplates } from '@/api/wallet'
import { listModels } from '@/api/models'
import {
  cancelQrSession,
  createQrSession,
  finalizeQrSession,
  pollQrSession,
} from '@/api/qr'
import { toApiError } from '@/api/client'
import type { Bot, ModelProfile, Platform, QrConnectSession, QrStatus, Template } from '@/types'
import { errorMessage } from '@/utils/errors'
import { platformShortLabel } from '@/utils/format'

const router = useRouter()
const { smAndDown: isMobile } = useDisplay()
const ui = useUiStore()

const step = ref<'form' | 'qr' | 'done'>('form')
const platform = ref<Platform>('weixin_oc')
const name = ref('')
const templateId = ref('')
const formError = ref('')
const nameError = ref('')
const creating = ref(false)

const templates = ref<Template[]>([])
const templatesLoading = ref(false)
const templatesError = ref('')
const models = ref<ModelProfile[]>([])
const modelsLoading = ref(false)
const modelId = ref('')

const session = ref<QrConnectSession | null>(null)
const finishedBot = ref<Bot | null>(null)
const qrBusy = ref(false)
const qrMessage = ref('')
const qrErrorText = ref('')
const finalizing = ref(false)

const qr = computed(() => session.value?.qr ?? null)
const qrPanelStatus = computed<QrStatus>(() => {
  if (session.value?.status === 'confirmed') return 'created'
  return (session.value?.status ?? 'pending') as QrStatus
})
const selectedTemplate = computed(() => templates.value.find((item) => item.id === templateId.value))
const selectedTemplateName = computed(() => selectedTemplate.value?.name || '—')
const modelOptions = computed(() =>
  models.value.map((model) => ({
    title: `${model.name} · ${model.model || model.provider}`,
    value: model.id,
  })),
)

const platformOptions: Array<{
  value: Platform
  title: string
  description: string
  icon: string
}> = [
  {
    value: 'weixin_oc',
    title: '微信（官方机器人）',
    description: '通过微信官方机器人接口接入，扫码后在手机确认。',
    icon: 'mdi-wechat',
  },
  {
    value: 'qq_official',
    title: 'QQ 官方机器人',
    description: '使用 QQ 官方机器人开放平台，扫码授权接入。',
    icon: 'mdi-qqchat',
  },
]

const { start: startPolling, stop: stopPolling } = usePolling(
  async () => {
    if (!session.value) return true
    try {
      const result = await pollQrSession(session.value.id)
      session.value = result.session
      qrMessage.value = result.session.message ?? ''
      if (result.session.status === 'confirmed') {
        await finalize()
        return true
      }
      if (result.session.status === 'expired') return true
      return false
    } catch (error) {
      qrErrorText.value = errorMessage(error, '轮询扫码状态失败')
      return true
    }
  },
  { interval: 2000, immediate: false },
)

onMounted(() => {
  void loadTemplates()
  void loadModels()
})

onBeforeUnmount(() => {
  stopPolling()
  if (session.value) void cancelQrSession(session.value.id).catch(() => undefined)
})

async function loadTemplates(): Promise<void> {
  templatesLoading.value = true
  templatesError.value = ''
  try {
    const result = await listTemplates()
    templates.value = result.items ?? []
    if (!templateId.value && templates.value.length > 0) {
      templateId.value = templates.value[0].id
    }
  } catch (error) {
    templatesError.value = errorMessage(error, '加载模板失败')
  } finally {
    templatesLoading.value = false
  }
}

async function loadModels(): Promise<void> {
  modelsLoading.value = true
  try {
    const result = await listModels()
    models.value = result.items ?? []
  } catch {
    models.value = []
  } finally {
    modelsLoading.value = false
  }
}

async function onCreate(): Promise<void> {
  formError.value = ''
  nameError.value = ''
  const botName = name.value.trim()
  if (!botName) {
    nameError.value = '请输入 Bot 名称'
    return
  }
  if (botName.length > 32) {
    nameError.value = '名称最多 32 个字符'
    return
  }
  if (!templateId.value) {
    formError.value = '请选择模板'
    return
  }

  creating.value = true
  try {
    const result = await createQrSession({
      platform: platform.value,
      name: botName,
      template_id: templateId.value,
      model_profile_id: modelId.value || undefined,
    })
    session.value = result.session
    step.value = 'qr'
    startPolling()
  } catch (error) {
    const apiError = toApiError(error)
    formError.value =
      apiError.status === 404 || apiError.status === 405
        ? '添加机器人功能暂未开放（后端接口未就绪），请稍后再试。'
        : errorMessage(apiError, '创建扫码会话失败')
  } finally {
    creating.value = false
  }
}

async function regenerate(): Promise<void> {
  if (qrBusy.value) return
  if (session.value) {
    const current = session.value.id
    session.value = null
    stopPolling()
    try {
      await cancelQrSession(current)
    } catch {
      /* ignore */
    }
  }
  step.value = 'form'
  await onCreate()
}

async function finalize(): Promise<void> {
  if (!session.value || finalizing.value) return
  finalizing.value = true
  qrBusy.value = true
  try {
    const result = await finalizeQrSession(session.value.id)
    finishedBot.value = result.bot
    session.value = null
    step.value = 'done'
    stopPolling()
    ui.notify('扫码成功，机器人已上线', 'success')
    setTimeout(() => {
      void router.push(`/bots/${result.bot.id}`)
    }, 2000)
  } catch (error) {
    qrErrorText.value = errorMessage(error, '完成接入失败，请重试')
  } finally {
    finalizing.value = false
    qrBusy.value = false
  }
}

async function cancelFlow(): Promise<void> {
  stopPolling()
  if (session.value) {
    const current = session.value.id
    session.value = null
    await cancelQrSession(current).catch(() => undefined)
  }
  await router.push('/bots')
}
</script>

<style scoped>
.steps {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.step {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--console-text-muted);
  font-size: 0.82rem;
  white-space: nowrap;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid var(--console-border);
  font-size: 0.72rem;
  background: var(--console-surface);
}

.step--active {
  color: var(--console-primary);
  font-weight: 600;
}

.step--active .step-index {
  border-color: var(--console-primary);
  background: var(--console-primary);
  color: #fff;
}

.step--done .step-index {
  border-color: #2e7d32;
  background: #2e7d32;
  color: #fff;
}

.step-line {
  flex: 1 1 24px;
  min-width: 16px;
  height: 1px;
  background: var(--console-border);
}

.connect-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.connect-main {
  min-width: 0;
}

.panel {
  padding: 20px;
  max-width: none;
}

.connect-aside {
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: sticky;
  top: 80px;
}

.aside-card {
  padding: 16px;
}

.aside-title {
  margin: 0 0 8px;
  font-size: 0.92rem;
  font-weight: 600;
}

.aside-text {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.7;
  color: var(--console-text-muted);
}

.aside-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--console-text-muted);
}

.aside-list li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.aside-card--muted {
  background: var(--console-surface-variant);
}

@media (min-width: 960px) {
  .connect-layout {
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: 20px;
    align-items: start;
  }
}

.qr-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -4px 0 8px;
}

.qr-modal-title {
  font-size: 0.95rem;
  font-weight: 600;
}

.platform-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.platform-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--console-border);
  border-radius: var(--console-radius);
  cursor: pointer;
  background: var(--console-surface);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.platform-card:hover,
.platform-card:focus-visible {
  border-color: var(--console-primary);
  outline: none;
  box-shadow: 0 0 0 3px rgba(60, 150, 202, 0.12);
}

.platform-card--selected {
  border-color: var(--console-primary);
  background: var(--console-primary-soft);
}

.platform-copy {
  flex: 1;
  min-width: 0;
}

.platform-title {
  font-size: 0.9rem;
  font-weight: 600;
}

.platform-desc {
  margin-top: 4px;
  font-size: 0.78rem;
  color: var(--console-text-muted);
  line-height: 1.55;
}

.template-copy-note {
  margin: 4px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
}

.template-hint {
  font-size: 0.78rem;
  padding: 4px 16px 8px;
  line-height: 1.5;
}

.form-note {
  margin: 12px 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
}

.qr-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.qr-summary-line {
  margin: 4px 0 0;
  font-size: 0.83rem;
}

.qr-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 24px;
  justify-content: center;
}

.qr-footer {
  margin-top: 16px;
  display: flex;
  justify-content: flex-start;
}

.dev-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dev-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.done-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 6px;
  padding: 40px 20px;
}

.done-title {
  margin: 8px 0 0;
  font-size: 1.2rem;
  font-weight: 650;
  color: #2e7d32;
}

.done-desc {
  margin: 0;
  max-width: 460px;
  font-size: 0.86rem;
  line-height: 1.6;
}

.done-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
  justify-content: center;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.alert-actions {
  display: flex;
  gap: 4px;
}

@media (max-width: 959px) {
  .qr-summary-title {
    display: none;
  }

  .panel--modal {
    position: fixed;
    inset: 0;
    z-index: 2400;
    margin: 0;
    padding: 16px;
    max-width: none;
    border-radius: 0;
    overflow-y: auto;
    background: var(--console-surface);
  }

  .panel--modal .qr-footer {
    padding-bottom: 16px;
  }
}

@media (max-width: 599px) {
  .platform-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .panel {
    padding: 16px;
  }
}
</style>
