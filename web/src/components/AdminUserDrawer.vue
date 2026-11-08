<template>
  <v-navigation-drawer
    v-if="open"
    v-model="open"
    location="right"
    temporary
    :width="isNarrow ? '100%' : 720"
    class="admin-user-drawer"
    data-testid="admin-user-drawer"
  >
    <div class="drawer-shell">
      <header class="drawer-head">
        <div>
          <h2 class="drawer-title">用户详情</h2>
          <p class="drawer-sub text-muted">
            {{ detail?.display_name || user?.display_name || user?.email || '—' }}
            <template v-if="detail?.email || user?.email"> · {{ detail?.email || user?.email }}</template>
          </p>
        </div>
        <v-btn icon variant="text" aria-label="关闭用户详情" @click="close">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </header>

      <div class="drawer-body">
        <v-alert v-if="loadError" type="error" variant="tonal" class="mb-3">
          <div class="alert-row">
            <span>{{ loadError }}</span>
            <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
          </div>
        </v-alert>

        <LoadingSkeleton v-if="loading && !detail" variant="detail" />

        <template v-else-if="detail">
          <div class="identity-row">
            <v-avatar color="primary" variant="tonal" size="44">
              <span class="avatar-text">{{ (detail.display_name || detail.email).slice(0, 1).toUpperCase() }}</span>
            </v-avatar>
            <div class="identity-main">
              <div class="identity-name">{{ detail.display_name || detail.email.split('@')[0] }}</div>
              <div class="identity-email text-muted">{{ detail.email }}</div>
            </div>
            <div class="identity-chips">
              <v-chip size="small" variant="tonal" :color="detail.role === 'admin' ? 'primary' : 'default'">
                {{ detail.role === 'admin' ? '管理员' : '普通用户' }}
              </v-chip>
              <StatusChip :status="detail.status" kind="user" />
              <StatusChip :status="detail.encryption?.state || 'encrypted'" kind="encryption" />
            </div>
          </div>

          <v-row class="summary-row" dense>
            <v-col cols="6" sm="3">
              <div class="summary-card">
                <div class="summary-label text-muted">余额</div>
                <div class="summary-value">{{ formatNumber(detail.balance) }} 点</div>
              </div>
            </v-col>
            <v-col cols="6" sm="3">
              <div class="summary-card">
                <div class="summary-label text-muted">Bot 数</div>
                <div class="summary-value">{{ detail.bot_count ?? bots.length }}</div>
              </div>
            </v-col>
            <v-col cols="6" sm="3">
              <div class="summary-card">
                <div class="summary-label text-muted">近 30 天消耗</div>
                <div class="summary-value">{{ formatNumber(usageSummary.points) }} 点</div>
              </div>
            </v-col>
            <v-col cols="6" sm="3">
              <div class="summary-card">
                <div class="summary-label text-muted">Tokens / 请求</div>
                <div class="summary-value summary-value--small">
                  {{ formatNumber(usageSummary.tokens) }} / {{ formatNumber(usageSummary.requests) }}
                </div>
              </div>
            </v-col>
          </v-row>

          <v-card class="section-card">
            <div class="section-head">
              <div>
                <div class="section-title">配额</div>
                <div class="section-desc text-muted">调整对用户立即生效；请根据实际使用情况谨慎设置。</div>
              </div>
              <v-btn
                color="primary"
                variant="tonal"
                size="small"
                :loading="quotaSaving"
                data-testid="admin-user-quota-save"
                @click="saveQuota"
              >
                保存配额
              </v-btn>
            </div>
            <v-alert v-if="quotaError" type="error" variant="tonal" density="compact" class="mb-3">
              {{ quotaError }}
            </v-alert>
            <v-row dense>
              <v-col cols="12" sm="4">
                <v-text-field v-model.number="quotaForm.max_bots" label="Bot 上限" type="number" min="0" density="compact" hide-details />
              </v-col>
              <v-col cols="12" sm="4">
                <v-text-field v-model.number="quotaForm.max_memories" label="记忆条数上限" type="number" min="0" density="compact" hide-details />
              </v-col>
              <v-col cols="12" sm="4">
                <v-text-field v-model.number="quotaForm.monthly_tokens" label="每月 Token" type="number" min="0" density="compact" hide-details />
              </v-col>
            </v-row>
          </v-card>

          <v-card class="section-card">
            <div class="section-title">名下 Bot</div>
            <LoadingSkeleton v-if="botsLoading" variant="list" :rows="2" />
            <div v-else-if="bots.length === 0" class="section-empty text-muted">该用户还没有 Bot。</div>
            <v-list v-else density="compact" class="bot-list">
              <v-list-item
                v-for="bot in bots"
                :key="bot.id"
                :title="bot.name"
                :subtitle="`${platformLabel(bot.platform)} · ${bot.id}`"
              >
                <template #append>
                  <StatusChip :status="bot.status" />
                </template>
              </v-list-item>
            </v-list>
          </v-card>

          <v-card class="section-card">
            <div class="section-head">
              <div>
                <div class="section-title">近 30 天用量</div>
                <div class="section-desc text-muted">按 Bot / 日期维度的点数与 Token 用量汇总。</div>
              </div>
              <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="usageLoading" @click="loadUsage(usagePage)">
                刷新
              </v-btn>
            </div>
            <v-alert v-if="usageError" type="error" variant="tonal" density="compact" class="mb-3">
              {{ usageError }}
            </v-alert>
            <EmptyState
              v-if="!usageLoading && usageItems.length === 0"
              icon="mdi-chart-line"
              title="暂无用量"
              description="该用户还没有产生模型调用用量。"
            />
            <template v-else-if="usageItems.length">
              <div class="table-scroll">
                <v-table density="comfortable" class="usage-table">
                  <thead>
                    <tr>
                      <th>{{ usageHasDate ? '日期' : 'Bot' }}</th>
                      <th class="text-right">点数</th>
                      <th class="text-right">Tokens</th>
                      <th class="text-right">请求</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(item, index) in usageItems" :key="`${item.bot_id || item.date || index}`">
                      <td>{{ usageHasDate ? item.date : item.bot_name || item.bot_id || '未关联 Bot' }}</td>
                      <td class="text-right">{{ formatNumber(item.points) }}</td>
                      <td class="text-right">{{ formatNumber(item.tokens) }}</td>
                      <td class="text-right">{{ formatNumber(item.requests) }}</td>
                    </tr>
                  </tbody>
                </v-table>
              </div>
              <div v-if="usageTotal > usagePageSize" class="pager">
                <v-pagination
                  :model-value="usagePage"
                  :length="Math.max(1, Math.ceil(usageTotal / usagePageSize))"
                  :total-visible="5"
                  density="compact"
                  @update:model-value="loadUsage"
                />
              </div>
            </template>
          </v-card>

          <v-card class="section-card">
            <div class="section-title">最近流水</div>
            <div v-if="ledger.length === 0" class="section-empty text-muted">
              暂无流水；用户充值/兑换或产生用量后会显示在这里。
            </div>
            <v-table v-else density="comfortable" class="ledger-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>类型</th>
                  <th>说明</th>
                  <th class="text-right">变动</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="entry in ledger" :key="String(entry.id)">
                  <td class="nowrap">{{ formatDateTime(entry.created_at) }}</td>
                  <td>{{ ledgerTypeLabel(entry.type) }}</td>
                  <td class="note-cell" :title="entry.note || ''">{{ entry.note || entry.reason || '—' }}</td>
                  <td class="text-right" :class="deltaValue(entry) >= 0 ? 'delta-plus' : 'delta-minus'">
                    {{ deltaValue(entry) >= 0 ? '+' : '' }}{{ formatNumber(deltaValue(entry)) }}
                  </td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </template>
      </div>
    </div>
  </v-navigation-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import StatusChip from '@/components/StatusChip.vue'
import { useAdminStore } from '@/stores/admin'
import { useUiStore } from '@/stores/ui'
import {
  getAdminUser,
  getAdminUserUsage,
  listAdminBots,
} from '@/api/admin'
import { toApiError } from '@/api/client'
import type {
  AdminBot,
  AdminUser,
  AdminUserDetail,
  AdminUserUsageItem,
  LedgerEntry,
  Quota,
} from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatNumber, platformLabel } from '@/utils/format'

const props = defineProps<{
  modelValue: boolean
  user: AdminUser | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  updated: []
}>()

const admin = useAdminStore()
const ui = useUiStore()
const { smAndDown } = useDisplay()

const isNarrow = computed(() => smAndDown.value)
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const detail = ref<AdminUserDetail | null>(null)
const loading = ref(false)
const loadError = ref('')
const bots = ref<AdminBot[]>([])
const botsLoading = ref(false)

const quotaForm = reactive<Quota>({ max_bots: 0, max_memories: 0, monthly_tokens: 0 })
const quotaSaving = ref(false)
const quotaError = ref('')

const usageItems = ref<AdminUserUsageItem[]>([])
const usagePage = ref(1)
const usagePageSize = ref(20)
const usageTotal = ref(0)
const usageLoading = ref(false)
const usageError = ref('')
const usageSummary = reactive({ points: 0, tokens: 0, requests: 0 })

const usageHasDate = computed(() => usageItems.value.some((item) => Boolean(item.date)))

const ledger = computed<LedgerEntry[]>(
  () => detail.value?.recent_ledger ?? detail.value?.ledger ?? [],
)

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) void initialize()
  },
  { immediate: true },
)

watch(
  () => props.user?.id,
  () => {
    if (props.modelValue) void initialize()
  },
)

async function initialize(): Promise<void> {
  if (!props.user?.id) return
  detail.value = null
  loadError.value = ''
  bots.value = []
  usageItems.value = []
  usagePage.value = 1
  usageError.value = ''
  await Promise.all([loadDetail(), loadUsage(1), loadBots()])
}

async function loadDetail(): Promise<void> {
  if (!props.user?.id) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await getAdminUser(props.user.id)
    const data = 'user' in result ? result.user : result
    detail.value = data
    quotaForm.max_bots = Number(data.quota?.max_bots ?? 0)
    quotaForm.max_memories = Number(data.quota?.max_memories ?? 0)
    quotaForm.monthly_tokens = Number(data.quota?.monthly_tokens ?? 0)
  } catch (error) {
    const apiError = toApiError(error)
    loadError.value =
      apiError.status === 404 || apiError.status === 405 || apiError.status === 501
        ? '用户详情接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载用户详情失败')
  } finally {
    loading.value = false
  }
}

async function loadBots(): Promise<void> {
  if (!props.user?.id) return
  botsLoading.value = true
  try {
    if (detail.value?.bots?.length) {
      bots.value = detail.value.bots
      return
    }
    const result = await listAdminBots()
    bots.value = (result.items ?? []).filter(
      (bot) => bot.user_id === props.user?.id || bot.owner_email === props.user?.email,
    )
  } catch {
    bots.value = []
  } finally {
    botsLoading.value = false
  }
}

async function loadUsage(page = 1): Promise<void> {
  if (!props.user?.id) return
  usageLoading.value = true
  usageError.value = ''
  try {
    const result = await getAdminUserUsage(props.user.id, page, usagePageSize.value)
    const items = result.items ?? result.by_bot ?? []
    usageItems.value = items
    usageTotal.value = result.total ?? items.length
    usagePage.value = result.page ?? page
    usagePageSize.value = result.page_size ?? usagePageSize.value
    const summary = result.summary
    usageSummary.points = Number(summary?.points ?? items.reduce((sum, item) => sum + Number(item.points ?? 0), 0))
    usageSummary.tokens = Number(summary?.tokens ?? items.reduce((sum, item) => sum + Number(item.tokens ?? 0), 0))
    usageSummary.requests = Number(summary?.requests ?? items.reduce((sum, item) => sum + Number(item.requests ?? 0), 0))
  } catch (error) {
    const apiError = toApiError(error)
    usageError.value =
      apiError.status === 404 || apiError.status === 405 || apiError.status === 501
        ? '用户用量接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载用户用量失败')
  } finally {
    usageLoading.value = false
  }
}

async function saveQuota(): Promise<void> {
  if (!detail.value) return
  quotaError.value = ''
  for (const key of ['max_bots', 'max_memories', 'monthly_tokens'] as const) {
    const value = Number(quotaForm[key])
    if (!Number.isInteger(value) || value < 0) {
      quotaError.value = '配额必须是非负整数'
      return
    }
  }
  quotaSaving.value = true
  try {
    const updated = await admin.updateUserQuota(detail.value.id, { ...quotaForm })
    detail.value = { ...detail.value, ...updated }
    ui.notify('配额已更新', 'success')
    emit('updated')
  } catch (error) {
    quotaError.value = errorMessage(error, '保存配额失败')
  } finally {
    quotaSaving.value = false
  }
}

function close(): void {
  open.value = false
}

function reload(): void {
  void Promise.all([loadDetail(), loadUsage(usagePage.value), loadBots()])
}

function deltaValue(entry: LedgerEntry): number {
  return Number(entry.delta ?? entry.amount ?? 0)
}

function ledgerTypeLabel(type?: string): string {
  const labels: Record<string, string> = {
    grant: '充值',
    adjust: '调整',
    consume: '消耗',
    redeem: '兑换',
  }
  return type ? labels[type] ?? type : '变更'
}
</script>

<style scoped>
.admin-user-drawer {
  border-left: 1px solid var(--console-border);
  max-width: 100vw;
}

.drawer-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px 10px;
  border-bottom: 1px solid var(--console-border);
}

.drawer-title {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}

.drawer-sub {
  margin: 3px 0 0;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 24px;
}

.identity-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.avatar-text {
  font-size: 18px;
  font-weight: 600;
}

.identity-main {
  min-width: 0;
}

.identity-name {
  font-size: 16px;
  font-weight: 650;
}

.identity-email {
  font-size: 12.5px;
  overflow-wrap: anywhere;
}

.identity-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-left: auto;
}

.summary-row {
  margin-bottom: 6px;
}

.summary-card {
  height: 100%;
  padding: 10px 12px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
}

.summary-label {
  font-size: 11.5px;
}

.summary-value {
  margin-top: 2px;
  font-size: 18px;
  font-weight: 650;
}

.summary-value--small {
  font-size: 14px;
}

.section-card {
  padding: 14px 16px;
  margin-top: 12px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.section-title {
  font-size: 14px;
  font-weight: 650;
}

.section-desc {
  font-size: 11.5px;
  margin-top: 2px;
  line-height: 1.5;
}

.section-empty {
  padding: 10px 0;
  font-size: 12.5px;
}

.bot-list {
  margin: 0 -8px;
}

.table-scroll {
  overflow-x: auto;
}

.usage-table,
.ledger-table {
  min-width: 520px;
}

.usage-table :deep(th),
.ledger-table :deep(th) {
  white-space: nowrap;
}

.note-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--console-text-muted);
}

.nowrap {
  white-space: nowrap;
}

.delta-plus {
  color: #2e7d32;
  font-weight: 600;
}

.delta-minus {
  color: var(--console-danger);
  font-weight: 600;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 10px;
}

@media (max-width: 599px) {
  .drawer-head,
  .drawer-body {
    padding-left: 14px;
    padding-right: 14px;
  }

  .identity-chips {
    margin-left: 0;
  }
}
</style>
