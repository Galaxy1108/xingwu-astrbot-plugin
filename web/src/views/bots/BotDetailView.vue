<template>
  <div>
    <PageHeader
      :title="bot?.name || 'Bot 详情'"
      :description="bot ? `${platformLabel(bot.platform)} · ${bot.template_name || '自定义模板'}` : '查看与维护 Bot 的基础信息、运行状态与设置。'"
      back-to="/bots"
    >
      <template #actions>
        <StatusChip v-if="bot" :status="bot.status" />
        <v-btn
          icon
          variant="text"
          aria-label="刷新"
          title="刷新"
          :loading="loading"
          @click="reload"
        >
          <v-icon>mdi-refresh</v-icon>
        </v-btn>
      </template>
    </PageHeader>

    <BotTabs :bot-id="botId" :active="activeTab" />

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
      <v-alert
        v-if="bot.admin_disabled"
        type="error"
        variant="tonal"
        class="mb-4"
        icon="mdi-cancel"
      >
        <div class="alert-row">
          <div>
            <strong>该 Bot 已被管理员停用</strong>
            <div class="admin-stop-reason">
              原因：{{ bot.admin_disabled_reason || '管理员未填写原因' }}
            </div>
          </div>
          <v-btn
            color="error"
            variant="tonal"
            size="small"
            :disabled="appealSubmitted"
            @click="appealOpen = true"
          >
            {{ appealSubmitted ? '申诉已提交' : '申请启用' }}
          </v-btn>
        </div>
      </v-alert>

      <template v-if="activeTab === 'settings'">
        <v-alert v-if="settingsError" type="error" variant="tonal" class="mb-4">
          {{ settingsError }}
        </v-alert>

        <v-card class="panel settings-panel">
          <h2 class="section-title">基础设置</h2>
          <v-text-field
            v-model.trim="settingsName"
            label="名称"
            counter="32"
            maxlength="32"
            class="mb-3"
            data-testid="bot-settings-name"
          />
          <v-select
            v-model="settingsModelId"
            :items="modelOptions"
            item-title="title"
            item-value="value"
            label="模型配置"
            :loading="modelsLoading"
            no-data-text="暂无可用模型配置"
            hint="来自管理端「模型与定价」；留空表示沿用模板 / 基础配置"
            persistent-hint
            class="mb-5"
          />
          <div class="switch-row">
            <div>
              <div class="switch-label">启用平台实例</div>
              <div class="text-muted switch-hint">
                {{
                  bot.admin_disabled
                    ? '管理员已停用该 Bot，需先申诉恢复后才能操作。'
                    : bot.status === 'pending_qr'
                      ? '待扫码状态下不能启用，请先完成扫码接入。'
                      : '关闭后平台实例停止接收消息。'
                }}
              </div>
            </div>
            <v-switch
              v-model="settingsEnabled"
              :disabled="bot.status === 'pending_qr' || Boolean(bot.admin_disabled)"
              color="primary"
              hide-details
              inset
            />
          </div>
          <div class="switch-row">
            <div>
              <div class="switch-label">流式输出（streaming）</div>
              <div class="text-muted switch-hint">
                在平台支持时逐段输出回复（如 QQ 官方机器人）；不支持时会自动回退整段发送。
              </div>
            </div>
            <v-switch
              v-model="settingsStreaming"
              color="primary"
              hide-details
              inset
              data-testid="bot-settings-streaming"
            />
          </div>
        </v-card>

        <v-card class="panel settings-panel mt-4">
          <button type="button" class="advanced-toggle" @click="advancedOpen = !advancedOpen">
            <v-icon size="18">mdi-tune-variant</v-icon>
            <span class="advanced-title">高级设置</span>
            <span class="text-muted advanced-sub">上下文压缩与轮次</span>
            <v-spacer />
            <v-icon size="20">{{ advancedOpen ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
          </button>
          <div v-if="advancedOpen" class="advanced-body">
            <v-row dense>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="settingsCompressionMaxTurns"
                  label="上下文压缩阈值（轮次）"
                  type="number"
                  min="1"
                  max="100"
                  hint="1–100；超过该轮次后触发上下文压缩"
                  persistent-hint
                  data-testid="bot-settings-compression-turns"
                />
              </v-col>
              <v-col cols="12" sm="6">
                <v-select
                  v-model="settingsCompressionStrategy"
                  :items="compressionStrategies"
                  item-title="title"
                  item-value="value"
                  label="压缩策略"
                  data-testid="bot-settings-compression-strategy"
                />
              </v-col>
            </v-row>
            <p class="advanced-note text-muted">
              truncate_by_turns 按轮次截断较早消息；llm_compress 会调用模型总结较早对话，可能产生额外 Token 消耗。
            </p>
          </div>
        </v-card>

        <div class="settings-actions">
          <v-btn
            color="primary"
            variant="tonal"
            :loading="settingsSaving"
            data-testid="bot-settings-save"
            @click="saveSettings"
          >
            保存设置
          </v-btn>
        </div>
      </template>

      <template v-else>
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
                  bot.admin_disabled
                    ? '管理员已停用该 Bot，需先申诉恢复后才能操作。'
                    : bot.status === 'pending_qr'
                      ? '待扫码状态下不能启用，请先完成扫码接入。'
                      : bot.enabled
                      ? '平台实例运行中，可接收消息。'
                      : '平台实例已停用，不处理消息。'
                }}
              </div>
            </div>
            <v-switch
              :model-value="bot.enabled"
              :disabled="bot.status === 'pending_qr' || bot.admin_disabled || toggling"
              :loading="toggling"
              color="primary"
              hide-details
              inset
              @update:model-value="onToggleEnabled"
            />
          </div>

        </v-card>
      </div>

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
    </template>

    <ReasonDialog
      v-model="appealOpen"
      :title="`申请启用「${bot?.name || ''}」？`"
      message="管理员会看到该 Bot 的停用原因与你的申诉说明；处理结果可在账号申诉记录中查看。"
      label="申诉说明"
      placeholder="请说明需要恢复该 Bot 的原因"
      confirm-text="提交申诉"
      :loading="appealing"
      @confirm="submitBotAppeal"
      @cancel="appealOpen = false"
    />

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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ReasonDialog from '@/components/ReasonDialog.vue'
import BotTabs from '@/components/BotTabs.vue'
import { useBotsStore } from '@/stores/bots'
import { useUiStore } from '@/stores/ui'
import { useClipboard } from '@/composables/useClipboard'
import { submitAppeal } from '@/api/appeals'
import { listModels } from '@/api/models'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatRelative, platformLabel } from '@/utils/format'
import type { ModelProfile } from '@/types'

const route = useRoute()
const router = useRouter()
const bots = useBotsStore()
const ui = useUiStore()
const { copied, copy } = useClipboard()

const botId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const bot = computed(() => (bots.current?.id === botId.value ? bots.current : null))
const activeTab = computed<'overview' | 'settings'>(() =>
  route.query.tab === 'settings' ? 'settings' : 'overview',
)

const modelOptions = computed(() => [
  { title: '沿用模板 / 基础配置', value: '' },
  ...models.value.map((model) => ({
    title: `${model.name} · ${model.model || model.provider}`,
    value: model.id,
  })),
])
const loading = computed(() => bots.currentLoading)
const loadError = ref('')

const toggling = ref(false)

const deleteOpen = ref(false)
const deleting = ref(false)

const settingsName = ref('')
const settingsModelId = ref('')
const settingsEnabled = ref(false)
const settingsStreaming = ref(false)
const settingsCompressionMaxTurns = ref(10)
const settingsCompressionStrategy = ref('truncate_by_turns')
const advancedOpen = ref(false)
const settingsSaving = ref(false)
const settingsError = ref('')
const models = ref<ModelProfile[]>([])
const modelsLoading = ref(false)

const compressionStrategies = [
  { title: '按轮次截断（truncate_by_turns）', value: 'truncate_by_turns' },
  { title: 'LLM 总结压缩（llm_compress）', value: 'llm_compress' },
]

const appealOpen = ref(false)
const appealing = ref(false)
const appealSubmitted = ref(false)

onMounted(async () => {
  await reload()
  if (activeTab.value === 'settings') await enterSettings()
})

watch(activeTab, async (tab) => {
  if (tab === 'settings') await enterSettings()
})

async function reload(): Promise<void> {
  if (!botId.value) return
  loadError.value = ''
  try {
    await bots.loadBot(botId.value, true)
  } catch (error) {
    loadError.value = errorMessage(error, '加载 Bot 详情失败')
  }
}

async function onToggleEnabled(value: boolean | null): Promise<void> {
  if (!bot.value || toggling.value) return
  if (bot.value.admin_disabled) {
    ui.notifyError('管理员已停用该 Bot，需先申诉恢复后才能操作。')
    return
  }
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

async function enterSettings(): Promise<void> {
  if (!bot.value) return
  hydrateSettings()
  if (models.value.length) return
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

function hydrateSettings(): void {
  if (!bot.value) return
  settingsName.value = bot.value.name
  settingsModelId.value = bot.value.model_profile_id || ''
  settingsEnabled.value = bot.value.enabled
  settingsStreaming.value = bot.value.settings?.streaming ?? false
  settingsCompressionMaxTurns.value = bot.value.settings?.compression_max_turns ?? 10
  settingsCompressionStrategy.value =
    bot.value.settings?.compression_overflow_strategy || 'truncate_by_turns'
  settingsError.value = ''
  advancedOpen.value = false
}

async function saveSettings(): Promise<void> {
  if (!bot.value) return
  settingsError.value = ''
  const name = settingsName.value.trim()
  if (!name) {
    settingsError.value = '名称不能为空'
    return
  }
  if (name.length > 32) {
    settingsError.value = '名称最多 32 个字符'
    return
  }
  const turns = Number(settingsCompressionMaxTurns.value)
  if (!Number.isInteger(turns) || turns < 1 || turns > 100) {
    settingsError.value = '上下文压缩阈值需为 1–100 的整数'
    advancedOpen.value = true
    return
  }
  settingsSaving.value = true
  try {
    await bots.updateBot(bot.value.id, {
      name,
      model_profile_id: settingsModelId.value,
      enabled: settingsEnabled.value,
      settings: {
        streaming: settingsStreaming.value,
        compression_max_turns: turns,
        compression_overflow_strategy: settingsCompressionStrategy.value,
      },
    })
    hydrateSettings()
    ui.notify('Bot 设置已保存', 'success')
  } catch (error) {
    settingsError.value = errorMessage(error, '保存 Bot 设置失败')
  } finally {
    settingsSaving.value = false
  }
}

async function submitBotAppeal(reason: string): Promise<void> {
  if (!bot.value) return
  appealing.value = true
  try {
    await submitAppeal({ target_type: 'bot', target_id: bot.value.id, reason })
    appealOpen.value = false
    appealSubmitted.value = true
    ui.notify('Bot 启用申诉已提交，等待管理员处理', 'success')
  } catch (error) {
    ui.notifyError(errorMessage(error, '提交申诉失败'))
  } finally {
    appealing.value = false
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
.bot-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 40px;
  margin: -8px 0 20px;
  border-bottom: 1px solid var(--console-border);
  overflow-x: auto;
  scrollbar-width: none;
}

.bot-tabs::-webkit-scrollbar {
  display: none;
}

.bot-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 14px;
  border: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--console-text-muted);
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.bot-tab:hover {
  color: var(--console-text);
  background: rgba(60, 150, 202, 0.06);
}

.bot-tab:focus-visible {
  outline: 2px solid var(--console-primary);
  outline-offset: -2px;
}

.bot-tab--active {
  color: rgb(var(--v-theme-primary));
  background: rgba(60, 150, 202, 0.12);
  box-shadow: inset 0 -2px 0 rgb(var(--v-theme-primary));
}

.settings-panel {
  padding: 20px;
}

.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 40px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--console-text);
  font: inherit;
  cursor: pointer;
}

.advanced-title {
  font-size: 15px;
  font-weight: 650;
}

.advanced-sub {
  font-size: 12px;
}

.advanced-body {
  padding-top: 14px;
}

.advanced-note {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.55;
}

.settings-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

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

.settings-note {
  margin: 6px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
}

.rescan-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.rescan-title {
  font-size: 0.86rem;
  font-weight: 600;
}

.rescan-desc {
  margin-top: 2px;
  font-size: 0.75rem;
  line-height: 1.5;
  max-width: 330px;
}

.admin-stop-reason {
  margin-top: 4px;
  font-size: 0.8rem;
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
  background: rgba(244, 67, 54, 0.07);
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
  .bot-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 40px;
  margin: -8px 0 20px;
  border-bottom: 1px solid var(--console-border);
  overflow-x: auto;
  scrollbar-width: none;
}

.bot-tabs::-webkit-scrollbar {
  display: none;
}

.bot-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 14px;
  border: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--console-text-muted);
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.bot-tab:hover {
  color: var(--console-text);
  background: rgba(60, 150, 202, 0.06);
}

.bot-tab:focus-visible {
  outline: 2px solid var(--console-primary);
  outline-offset: -2px;
}

.bot-tab--active {
  color: rgb(var(--v-theme-primary));
  background: rgba(60, 150, 202, 0.12);
  box-shadow: inset 0 -2px 0 rgb(var(--v-theme-primary));
}

.settings-panel {
  padding: 20px;
}

.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 40px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--console-text);
  font: inherit;
  cursor: pointer;
}

.advanced-title {
  font-size: 15px;
  font-weight: 650;
}

.advanced-sub {
  font-size: 12px;
}

.advanced-body {
  padding-top: 14px;
}

.advanced-note {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.55;
}

.settings-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
