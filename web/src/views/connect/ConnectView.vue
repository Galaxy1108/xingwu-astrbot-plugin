<template>
  <div>
    <PageHeader
      title="扫码接入"
      description="选择平台并命名，生成二维码后用对应 App 扫码确认；成功后 Bot 会自动上线。"
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

      <v-btn
        color="primary"
        size="large"
        block
        class="mt-6"
        :loading="creating"
        :disabled="templates.length === 0"
        @click="onCreate"
      >
        创建并生成二维码
      </v-btn>
      <p class="form-note text-muted">
        创建后会生成一个禁用态的 Bot；扫码成功后自动启用。若中途取消，可到「我的 Bot」删除。
      </p>
    </v-card>

    <v-card v-else-if="step === 'qr'" class="panel">
      <div class="qr-summary">
        <div>
          <h2 class="section-title">扫码接入</h2>
          <p class="text-muted qr-summary-line">
            {{ createdBot?.name || name }} · {{ platformShortLabel(platform) }} · {{ selectedTemplateName }}
          </p>
        </div>
        <StatusChip v-if="qr" :status="qr.status" kind="qr" />
      </div>

      <v-alert v-if="qrErrorText" type="error" variant="tonal" class="mb-4">
        <div class="alert-row">
          <span>{{ qrErrorText }}</span>
          <div class="alert-actions">
            <v-btn size="small" variant="text" color="error" :loading="qrBusy" @click="startQr">
              重试
            </v-btn>
            <v-btn v-if="botId" size="small" variant="text" :to="`/bots/${botId}`">查看 Bot</v-btn>
          </div>
        </div>
      </v-alert>

      <QrPanel
        v-if="qr"
        :status="qr.status"
        :image="qr.qr_image"
        :expires-at="qr.expires_at"
        :refresh-count="qr.refresh_count"
        :message="qrMessage"
        :busy="qrBusy"
        @regenerate="startQr"
      />

      <div v-else-if="!qrErrorText" class="qr-loading">
        <v-progress-circular indeterminate color="primary" />
        <span class="text-muted">正在生成二维码…</span>
      </div>

      <v-alert
        v-if="devMode && botId && qr"
        type="info"
        variant="tonal"
        density="compact"
        class="mt-4"
      >
        <div class="dev-box">
          <span>开发模式：模拟扫码状态机（仅 dev server 可见）</span>
          <div class="dev-actions">
            <v-btn size="small" variant="tonal" @click="simulate('scanned')">模拟已扫码</v-btn>
            <v-btn size="small" variant="tonal" color="success" @click="simulate('confirm')">
              模拟确认登录
            </v-btn>
            <v-btn size="small" variant="tonal" color="warning" @click="simulate('expire')">
              模拟过期
            </v-btn>
          </div>
        </div>
      </v-alert>

      <div class="qr-footer">
        <v-btn variant="text" @click="cancelFlow">取消并返回列表</v-btn>
      </div>
    </v-card>

    <v-card v-else class="panel done-panel">
      <v-icon size="64" color="success">mdi-check-decagram-outline</v-icon>
      <h2 class="done-title">已接入</h2>
      <p class="text-muted done-desc">
        「{{ finishedBot?.name || createdBot?.name || name }}」已完成扫码，正在上线（通常 5 秒内生效）。
      </p>
      <div class="done-actions">
        <v-btn color="primary" :to="finishedBot ? `/bots/${finishedBot.id}` : '/bots'">
          查看 Bot 详情
        </v-btn>
        <v-btn variant="tonal" to="/bots">返回列表</v-btn>
      </div>
    </v-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import QrPanel from '@/components/QrPanel.vue'
import { usePolling } from '@/composables/usePolling'
import { useBotsStore } from '@/stores/bots'
import { useUiStore } from '@/stores/ui'
import { listTemplates } from '@/api/wallet'
import { getVersion } from '@/api/system'
import { devQrAction, type DevQrAction } from '@/api/dev'
import { toApiError } from '@/api/client'
import type { Bot, Platform, Template } from '@/types'
import { errorMessage, fieldError } from '@/utils/errors'
import { platformShortLabel } from '@/utils/format'

const router = useRouter()
const bots = useBotsStore()
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

const botId = ref('')
const createdBot = ref<Bot | null>(null)
const finishedBot = ref<Bot | null>(null)
const qrBusy = ref(false)
const qrMessage = ref('')
const qrErrorText = ref('')
const finalizing = ref(false)
const devMode = ref(false)

const qr = computed(() => bots.qr)
const selectedTemplate = computed(() => templates.value.find((item) => item.id === templateId.value))
const selectedTemplateName = computed(
  () => selectedTemplate.value?.name || createdBot.value?.template_name || '—',
)

const platformOptions: Array<{
  value: Platform
  title: string
  description: string
  icon: string
}> = [
  {
    value: 'weixin_oc',
    title: '微信（个人号 · 官方接口）',
    description: '通过官方接口登录微信个人号，扫码后在手机确认。',
    icon: 'mdi-wechat',
  },
  {
    value: 'qq_official',
    title: 'QQ 官方机器人',
    description: '使用 QQ 官方机器人开放平台，扫码授权接入。',
    icon: 'mdi-qqchat',
  },
]

let redirectTimer: ReturnType<typeof setTimeout> | null = null

const { start: startPolling, stop: stopPolling } = usePolling(
  async () => {
    if (!botId.value) return true
    try {
      const result = await bots.pollQr(botId.value)
      qrMessage.value = result.message ?? ''
      if (result.qr.status === 'created') {
        await finalize()
        return true
      }
      if (result.qr.status === 'expired') return true
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
  void loadVersion()
})

onBeforeUnmount(() => {
  stopPolling()
  if (redirectTimer !== null) clearTimeout(redirectTimer)
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

async function loadVersion(): Promise<void> {
  try {
    const version = await getVersion()
    devMode.value = version.dev_mode === true
  } catch {
    devMode.value = false
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
    const bot = await bots.createBot({
      name: botName,
      template_id: templateId.value,
      platform: platform.value,
    })
    createdBot.value = bot
    botId.value = bot.id
    step.value = 'qr'
    await startQr()
  } catch (error) {
    const apiError = toApiError(error)
    if (fieldError(apiError, 'name')) nameError.value = apiError.message
    formError.value = apiError.message
  } finally {
    creating.value = false
  }
}

async function startQr(): Promise<void> {
  if (!botId.value || qrBusy.value) return
  qrBusy.value = true
  qrErrorText.value = ''
  qrMessage.value = ''
  try {
    await bots.startQr(botId.value)
    startPolling()
  } catch (error) {
    const apiError = toApiError(error)
    if (apiError.code === 'qr_session_exists') {
      try {
        const result = await bots.pollQr(botId.value)
        qrMessage.value = result.message ?? ''
        startPolling()
      } catch (pollError) {
        qrErrorText.value = errorMessage(pollError, '恢复扫码会话失败')
      }
    } else {
      qrErrorText.value = apiError.message
    }
  } finally {
    qrBusy.value = false
  }
}

async function finalize(): Promise<void> {
  if (!botId.value || finalizing.value) return
  finalizing.value = true
  try {
    const bot = await bots.finalizeQr(botId.value)
    finishedBot.value = bot
    step.value = 'done'
    ui.notify('扫码成功，Bot 已上线', 'success')
    redirectTimer = setTimeout(() => {
      void router.push(`/bots/${bot.id}`)
    }, 2000)
  } catch (error) {
    qrErrorText.value = errorMessage(error, '完成接入失败，请重试')
  } finally {
    finalizing.value = false
  }
}

async function simulate(action: DevQrAction): Promise<void> {
  if (!botId.value) return
  try {
    await devQrAction(action, botId.value)
    const labels: Record<DevQrAction, string> = {
      scanned: '已模拟扫码',
      confirm: '已模拟确认',
      expire: '已模拟过期（下次轮询将自动刷新）',
    }
    ui.notify(labels[action], 'info')
    const result = await bots.pollQr(botId.value)
    qrMessage.value = result.message ?? ''
  } catch (error) {
    qrErrorText.value = errorMessage(error, '开发模式模拟失败')
  }
}

function cancelFlow(): void {
  stopPolling()
  void router.push('/bots')
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
  background: #fff;
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

.panel {
  padding: 20px;
  max-width: 720px;
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
  background: #fff;
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

@media (max-width: 599px) {
  .platform-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .panel {
    padding: 16px;
  }
}
</style>
