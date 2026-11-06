<template>
  <div>
    <PageHeader
      :title="bot?.name || 'Bot 详情'"
      :description="bot ? `${platformLabel(bot.platform)} · ${bot.template_name || '自定义模板'}` : '查看与维护 Bot 的基础信息、绑定状态与扫码会话。'"
      back-to="/bots"
    >
      <template #actions>
        <StatusChip v-if="bot" :status="bot.status" />
        <v-btn
          v-if="bot"
          variant="tonal"
          prepend-icon="mdi-brain"
          :to="`/bots/${botId}/memory`"
        >
          记忆
        </v-btn>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="reload">刷新</v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="loadError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ loadError }}</span>
        <div class="alert-actions">
          <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
          <v-btn size="small" variant="text" to="/bots">返回列表</v-btn>
        </div>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !bot" variant="detail" />

    <template v-else-if="bot">
      <div class="detail-grid">
        <v-card class="panel">
          <h2 class="section-title">基础信息</h2>
          <dl class="info-list">
            <div class="info-row"><dt>Bot ID</dt><dd class="text-mono">{{ bot.id }}</dd></div>
            <div class="info-row"><dt>平台</dt><dd>{{ platformLabel(bot.platform) }}</dd></div>
            <div class="info-row"><dt>模板</dt><dd>{{ bot.template_name || '—' }}</dd></div>
            <div class="info-row"><dt>人格</dt><dd>{{ bot.persona_name || '—' }}</dd></div>
            <div class="info-row">
              <dt>绑定状态</dt>
              <dd>
                <v-chip v-if="bot.bound" color="success" size="small" variant="tonal" prepend-icon="mdi-link-variant">
                  已绑定
                </v-chip>
                <v-chip v-else color="default" size="small" variant="tonal">未绑定</v-chip>
              </dd>
            </div>
            <div class="info-row">
              <dt>配置 ID</dt>
              <dd class="conf-id">
                <span class="text-mono">{{ bot.conf_id || '—' }}</span>
                <v-btn
                  v-if="bot.conf_id"
                  icon
                  size="x-small"
                  variant="text"
                  :title="copied ? '已复制' : '复制'"
                  @click="copy(bot.conf_id)"
                >
                  <v-icon size="16">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
                </v-btn>
              </dd>
            </div>
            <div class="info-row"><dt>创建时间</dt><dd>{{ formatDateTime(bot.created_at) }}</dd></div>
            <div class="info-row"><dt>更新时间</dt><dd>{{ formatDateTime(bot.updated_at) }}</dd></div>
            <div class="info-row"><dt>最近活跃</dt><dd>{{ bot.last_active_at ? formatRelative(bot.last_active_at) : '—' }}</dd></div>
          </dl>
        </v-card>

        <v-card class="panel">
          <h2 class="section-title">运行状态</h2>
          <div class="switch-row">
            <div>
              <div class="switch-label">启用平台实例</div>
              <div class="text-muted switch-hint">
                {{
                  bot.status === 'pending_qr'
                    ? '待扫码状态下不能启用，请先完成扫码接入。'
                    : bot.enabled
                      ? '平台实例运行中，可接收消息。'
                      : '平台实例已停用，不处理消息。'
                }}
              </div>
            </div>
            <v-switch
              :model-value="bot.enabled"
              :disabled="bot.status === 'pending_qr' || toggling"
              :loading="toggling"
              color="primary"
              hide-details
              inset
              @update:model-value="onToggleEnabled"
            />
          </div>

          <v-divider class="my-4" />

          <div class="action-stack">
            <v-btn variant="tonal" prepend-icon="mdi-pencil" block @click="openRename">修改名称</v-btn>
            <v-btn
              variant="tonal"
              color="primary"
              prepend-icon="mdi-qrcode-scan"
              block
              :loading="qrBusy"
              @click="startQr"
            >
              {{ bot.bound ? '重新扫码' : '开始扫码接入' }}
            </v-btn>
          </div>
          <p class="text-muted action-note">
            重新扫码会重新走平台登录流程；当前契约未提供独立的解绑接口，若状态不允许会给出提示。
          </p>
        </v-card>
      </div>

      <v-card class="panel mt-4">
        <div class="qr-head">
          <h2 class="section-title">扫码接入</h2>
          <span v-if="qr" class="text-muted qr-meta">会话 {{ qr.id }}</span>
        </div>

        <QrPanel
          v-if="qr"
          :status="qr.status"
          :image="qr.qr_image"
          :expires-at="qr.expires_at"
          :refresh-count="qr.refresh_count"
          :message="qrMessage"
          :error="qrErrorText"
          :busy="qrBusy"
          @regenerate="startQr"
        />

        <v-alert
          v-if="devMode && qr"
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

        <EmptyState
          v-else
          icon="mdi-qrcode"
          title="尚未生成二维码"
          description="生成二维码后，请使用对应平台 App 扫码并在手机上确认；二维码有效期 60 秒，过期会自动刷新（最多 3 次）。"
        >
          <template #actions>
            <v-btn color="primary" :loading="qrBusy" @click="startQr">生成二维码</v-btn>
          </template>
        </EmptyState>
      </v-card>

      <v-card class="danger-zone mt-4">
        <h2 class="danger-title">危险区</h2>
        <p class="danger-desc">
          删除 Bot 会停止运行中的实例、解除绑定，并删除专属配置与记忆库，操作不可恢复。
        </p>
        <v-btn color="error" variant="outlined" prepend-icon="mdi-delete-outline" @click="deleteOpen = true">
          删除 Bot
        </v-btn>
      </v-card>
    </template>

    <v-dialog v-model="renameOpen" max-width="460" persistent>
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">修改 Bot 名称</v-card-title>
        <v-card-text>
          <v-alert v-if="renameError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ renameError }}
          </v-alert>
          <v-text-field
            v-model.trim="renameName"
            label="新名称"
            counter="32"
            maxlength="32"
            autofocus
            @keyup.enter="submitRename"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="renameSaving" @click="renameOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="renameSaving" @click="submitRename">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="deleteOpen"
      :title="`删除「${bot?.name || ''}」？`"
      :message="`该操作会停止平台实例、解除绑定并删除记忆库，且不可恢复。请输入 Bot 名称「${bot?.name || ''}」以确认。`"
      confirm-text="永久删除"
      danger
      :loading="deleting"
      :type-to-confirm="bot?.name || ''"
      @confirm="onDelete"
      @cancel="deleteOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import QrPanel from '@/components/QrPanel.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useBotsStore } from '@/stores/bots'
import { useUiStore } from '@/stores/ui'
import { usePolling } from '@/composables/usePolling'
import { useClipboard } from '@/composables/useClipboard'
import { toApiError } from '@/api/client'
import { getVersion } from '@/api/system'
import { devQrAction, type DevQrAction } from '@/api/dev'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatRelative, platformLabel } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const bots = useBotsStore()
const ui = useUiStore()
const { copied, copy } = useClipboard()

const botId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const bot = computed(() => (bots.current?.id === botId.value ? bots.current : null))
const loading = computed(() => bots.currentLoading)
const loadError = ref('')

const toggling = ref(false)
const qrBusy = ref(false)
const qrMessage = ref('')
const qrErrorText = ref('')
const qr = computed(() => (bot.value?.qr ?? bots.qr) || null)

const renameOpen = ref(false)
const renameName = ref('')
const renameError = ref('')
const renameSaving = ref(false)

const deleteOpen = ref(false)
const deleting = ref(false)
const finalizing = ref(false)
const devMode = ref(false)

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

onMounted(async () => {
  void loadVersion()
  await reload()
  if (bots.current?.qr) {
    startPolling()
  } else if (route.query.qr === '1' && bots.current?.status === 'pending_qr') {
    await startQr()
  }
})

onBeforeUnmount(() => {
  stopPolling()
})

async function loadVersion(): Promise<void> {
  try {
    const version = await getVersion()
    devMode.value = version.dev_mode === true
  } catch {
    devMode.value = false
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
    if (result.qr.status === 'created') {
      stopPolling()
      await finalize()
    } else if (result.qr.status === 'expired') {
      stopPolling()
    }
  } catch (error) {
    qrErrorText.value = errorMessage(error, '开发模式模拟失败')
  }
}

async function reload(): Promise<void> {
  if (!botId.value) return
  loadError.value = ''
  try {
    await bots.loadBot(botId.value, true)
  } catch (error) {
    loadError.value = errorMessage(error, '加载 Bot 详情失败')
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
    } else if (apiError.code === 'bot_state_invalid') {
      qrErrorText.value = '当前 Bot 状态不支持发起扫码；请稍后刷新或联系管理员。'
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
    await bots.finalizeQr(botId.value)
    qrMessage.value = ''
    ui.notify('扫码成功，Bot 已上线', 'success')
    await reload()
  } catch (error) {
    qrErrorText.value = errorMessage(error, '完成接入失败，请重试')
  } finally {
    finalizing.value = false
  }
}

async function onToggleEnabled(value: boolean | null): Promise<void> {
  if (!bot.value || toggling.value) return
  toggling.value = true
  try {
    const updated = await bots.updateBot(bot.value.id, { enabled: value === true })
    ui.notify(updated.enabled ? '已启用平台实例' : '已停用平台实例', 'success')
  } catch (error) {
    ui.notifyError(errorMessage(error, '切换运行状态失败'))
  } finally {
    toggling.value = false
  }
}

function openRename(): void {
  renameName.value = bot.value?.name ?? ''
  renameError.value = ''
  renameOpen.value = true
}

async function submitRename(): Promise<void> {
  if (!bot.value) return
  const name = renameName.value.trim()
  if (!name) {
    renameError.value = '名称不能为空'
    return
  }
  if (name.length > 32) {
    renameError.value = '名称最多 32 个字符'
    return
  }
  renameSaving.value = true
  renameError.value = ''
  try {
    await bots.updateBot(bot.value.id, { name })
    renameOpen.value = false
    ui.notify('名称已更新', 'success')
  } catch (error) {
    renameError.value = errorMessage(error, '改名失败')
  } finally {
    renameSaving.value = false
  }
}

async function onDelete(): Promise<void> {
  if (!bot.value) return
  deleting.value = true
  try {
    await bots.removeBot(bot.value.id, bot.value.name)
    deleteOpen.value = false
    ui.notify('Bot 已删除', 'success')
    await router.replace('/bots')
  } catch (error) {
    deleteOpen.value = false
    ui.notifyError(errorMessage(error, '删除失败'))
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: 16px;
}

.panel {
  padding: 20px;
}

.info-list {
  margin: 0;
}

.info-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-bottom: 1px dashed #eef1f4;
  font-size: 0.85rem;
}

.info-row:last-child {
  border-bottom: none;
}

.info-row dt {
  color: var(--console-text-muted);
  flex: 0 0 auto;
}

.info-row dd {
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
}

.conf-id {
  display: flex;
  align-items: center;
  gap: 4px;
}

.switch-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.switch-label {
  font-weight: 600;
  font-size: 0.9rem;
}

.switch-hint {
  margin-top: 4px;
  font-size: 0.8rem;
  line-height: 1.6;
  max-width: 320px;
}

.action-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-note {
  margin: 12px 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
}

.qr-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.qr-meta {
  font-size: 0.75rem;
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

.danger-zone {
  padding: 20px;
  border: 1px solid #f2c6c6;
  background: #fffafa;
}

.danger-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
  color: #c62828;
}

.danger-desc {
  margin: 6px 0 14px;
  color: var(--console-text-muted);
  font-size: 0.84rem;
  line-height: 1.6;
  max-width: 640px;
}

.dialog-card {
  padding: 8px;
}

.dialog-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
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
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
