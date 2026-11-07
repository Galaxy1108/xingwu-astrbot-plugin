<template>
  <div class="page-wrap">
    <div class="page-head">
      <div>
        <h1 class="page-title">额度与账单</h1>
        <p class="page-sub">
          预付费点数：使用管理员发放的兑换码入账，消费按模型用量扣减；余额与流水以 append-only 账本为准。
        </p>
      </div>
      <div class="page-actions">
        <v-chip variant="tonal" color="primary" prepend-icon="mdi-ticket-percent-outline">
          内测 · 仅支持兑换码
        </v-chip>
        <v-btn variant="outlined" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="load">
          刷新
        </v-btn>
      </div>
    </div>

    <v-row>
      <v-col cols="12" md="5">
        <v-card elevation="0" class="pa-6 h-100 balance-card">
          <div class="text-caption muted mb-1">剩余点数</div>
          <div class="d-flex align-baseline ga-2">
            <div class="balance-number">{{ formatNumber(wallet?.balance ?? 0) }}</div>
            <div class="text-body-2 muted">点</div>
          </div>
          <div class="text-caption muted mt-2">
            近 30 天消耗 {{ formatNumber(daily?.total_points ?? 0) }} 点 · 请求
            {{ formatNumber(daily?.total_requests ?? 0) }} 次
          </div>
        </v-card>
      </v-col>

      <v-col cols="12" md="7">
        <v-card elevation="0" class="pa-6 h-100 redeem-card">
          <div class="d-flex align-center mb-1">
            <div class="text-subtitle-1 font-weight-bold">兑换码</div>
            <v-chip size="x-small" variant="tonal" color="primary" class="ml-2">内测</v-chip>
          </div>
          <p class="text-caption muted mb-3">
            输入管理员发放的兑换码增加点数；同一兑换码仅可使用一次（以服务端校验为准）。
          </p>
          <form class="redeem-form" @submit.prevent="redeem">
            <v-text-field
              v-model.trim="redeemInput"
              placeholder="SAAS-XXXX-XXXX"
              prepend-inner-icon="mdi-ticket-outline"
              density="compact"
              hide-details
              :disabled="redeeming"
              data-testid="redeem-code"
              class="redeem-input"
            />
            <v-btn
              type="submit"
              color="primary"
              variant="tonal"
              :loading="redeeming"
              :disabled="!redeemInput || redeeming"
              data-testid="redeem-submit"
            >
              兑换
            </v-btn>
          </form>
          <v-alert v-if="redeemError" type="error" variant="tonal" density="compact" class="mt-3">
            {{ redeemError }}
          </v-alert>
          <v-alert v-if="redeemSuccess" type="success" variant="tonal" density="compact" class="mt-3">
            {{ redeemSuccess }}
          </v-alert>
          <div class="d-flex align-center text-caption muted mt-4">
            <v-icon size="16" class="mr-2">mdi-information-outline</v-icon>
            内测仅支持兑换码，不提供在线支付与自动充值。
          </div>
        </v-card>
      </v-col>
    </v-row>

    <v-card elevation="0" class="pa-5 mt-4">
      <div class="chart-head">
        <div>
          <div class="text-subtitle-1 font-weight-bold">点数消耗</div>
          <div class="text-caption muted">按日统计 · 来自模型调用用量（非余额变化）</div>
        </div>
        <v-spacer />
        <div class="chart-controls">
          <v-select
            v-model="botFilter"
            :items="botOptions"
            item-title="title"
            item-value="value"
            density="compact"
            variant="outlined"
            hide-details
            class="bot-filter"
            @update:model-value="loadDaily"
          />
          <v-btn-toggle v-model="range" density="compact" variant="text" divided mandatory>
            <v-btn value="30" size="small" @click="loadDaily">30 天</v-btn>
            <v-btn value="7" size="small" @click="loadDaily">7 天</v-btn>
          </v-btn-toggle>
        </div>
      </div>
      <div class="chart-totals text-caption">
        <span>近 {{ daily?.days ?? range }} 天消耗 <strong>{{ formatNumber(daily?.total_points ?? 0) }}</strong> 点</span>
        <span class="muted">请求 {{ formatNumber(daily?.total_requests ?? 0) }} 次 · Tokens {{ formatNumber(daily?.total_tokens ?? 0) }}</span>
      </div>
      <LoadingSkeleton v-if="dailyLoading && !daily" variant="card" :rows="1" />
      <UsageChart
        v-else
        :points="daily?.points ?? []"
        value-label="消耗"
        unit="点"
        :height="230"
      />
    </v-card>

    <v-card elevation="0" class="pa-5 mt-4 payment-card">
      <div class="text-subtitle-1 font-weight-bold mb-1">支付方式</div>
      <p class="text-caption muted mb-4">内测仅支持兑换码；以下支付方式暂未开放，不产生任何扣款。</p>
      <div class="payment-grid">
        <div v-for="method in paymentMethods" :key="method.name" class="payment-item">
          <v-icon size="20">{{ method.icon }}</v-icon>
          <span class="payment-name">{{ method.name }}</span>
          <v-chip size="x-small" variant="outlined" color="default">暂不支持</v-chip>
        </div>
      </div>
    </v-card>

    <v-card elevation="0" class="mt-4">
      <div class="section-head">
        <div class="text-subtitle-1 font-weight-bold">流水</div>
        <v-spacer />
        <span class="text-caption muted">共 {{ total }} 条</span>
      </div>

      <v-alert v-if="error" type="error" variant="tonal" class="mx-5 mb-3">
        <div class="alert-row">
          <span>{{ error }}</span>
          <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
        </div>
      </v-alert>

      <LoadingSkeleton v-else-if="loading" variant="table" :rows="3" />

      <EmptyState
        v-else-if="items.length === 0"
        icon="mdi-wallet-outline"
        title="暂无流水"
        description="管理员确认充值单、手动调整或产生模型用量后，这里会出现明细。"
      />

      <template v-else>
        <div class="table-scroll">
          <v-table hover density="comfortable" class="ledger-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>类型</th>
                <th>说明</th>
                <th class="text-right">变动</th>
                <th class="text-right">余额</th>
                <th>关联</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(entry, index) in items" :key="String(entry.id)">
                <td class="text-caption muted nowrap">{{ formatDateTime(entry.created_at) }}</td>
                <td>
                  <v-chip size="x-small" variant="tonal" :color="chipColor(entry.type)">
                    {{ ledgerTypeLabel(entry.type) }}
                  </v-chip>
                </td>
                <td class="note-cell">{{ entry.note || entry.reason || '—' }}</td>
                <td class="text-right font-weight-medium" :class="deltaClass(entry)">
                  {{ signedNumber(entry) }}
                </td>
                <td class="text-right muted">{{ formatNumber(balanceAfter(index)) }}</td>
                <td class="text-mono ref-cell" :title="entry.ref || ''">{{ entry.ref || '—' }}</td>
              </tr>
            </tbody>
          </v-table>
        </div>
        <div v-if="total > pageSize" class="pager">
          <v-pagination
            :model-value="page"
            :length="pageCount"
            :total-visible="5"
            density="comfortable"
            @update:model-value="onPage"
          />
        </div>
      </template>
    </v-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import UsageChart from '@/components/UsageChart.vue'
import { getDailyUsage, getUsageByBot, getWallet, getWalletLedger, redeemCode } from '@/api/wallet'
import type { LedgerEntry, UsageByBot, UsageDaily, Wallet } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'
import { useUiStore } from '@/stores/ui'
import { isApiError } from '@/api/client'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

const wallet = ref<Wallet | null>(null)
const daily = ref<UsageDaily | null>(null)
const byBot = ref<UsageByBot[]>([])
const items = ref<LedgerEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const dailyLoading = ref(false)
const error = ref('')
const range = ref<'30' | '7'>('30')
const botFilter = ref('')

const redeemInput = ref('')
const redeeming = ref(false)
const redeemError = ref('')
const redeemSuccess = ref('')

const paymentMethods = [
  { name: '支付宝', icon: 'mdi-alpha-a-circle-outline' },
  { name: '微信支付', icon: 'mdi-wechat' },
  { name: '银行卡', icon: 'mdi-credit-card-outline' },
]

const botOptions = computed(() => [
  { title: '全部 Bot', value: '' },
  ...byBot.value
    .filter((item) => Boolean(item.bot_id))
    .map((item) => ({
      title: item.bot_name || item.bot_id,
      value: item.bot_id,
    })),
])

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

onMounted(() => {
  page.value = readPage()
  void load()
})

function readPage(): number {
  const raw = route.query.page
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [walletResult, ledgerResult] = await Promise.all([
      getWallet(),
      getWalletLedger(page.value, pageSize.value),
    ])
    wallet.value = walletResult
    items.value = ledgerResult.items ?? []
    total.value = ledgerResult.total ?? 0
    page.value = ledgerResult.page ?? page.value
    pageSize.value = ledgerResult.page_size ?? pageSize.value
    await Promise.all([loadDaily(), loadByBot()])
  } catch (err) {
    error.value = (err as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadDaily(): Promise<void> {
  dailyLoading.value = true
  try {
    daily.value = await getDailyUsage(Number(range.value), botFilter.value || undefined)
  } catch {
    daily.value = null
  } finally {
    dailyLoading.value = false
  }
}

async function loadByBot(): Promise<void> {
  try {
    const result = await getUsageByBot(30)
    byBot.value = result.items ?? []
  } catch {
    byBot.value = []
  }
}

function redeemErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.status === 404 || error.code === 'not_found' || error.code === 'http_error') {
      return '兑换码功能暂未开放（后端接口未就绪），请稍后再试。'
    }
    switch (error.code) {
      case 'already_redeemed':
        return '该兑换码已被使用，不能重复兑换。'
      case 'expired':
        return '兑换码已过期，请联系管理员重新发放。'
      case 'invalid':
        return '兑换码无效，请检查后重试。'
      default:
        return error.message || '兑换失败，请稍后重试。'
    }
  }
  return '兑换失败，请稍后重试。'
}

async function redeem(): Promise<void> {
  const code = redeemInput.value.trim()
  redeemError.value = ''
  redeemSuccess.value = ''
  if (!code) {
    redeemError.value = '请输入兑换码'
    return
  }
  redeeming.value = true
  try {
    const result = await redeemCode(code)
    const credits = Number(result.credits ?? 0)
    redeemSuccess.value = credits > 0
      ? `兑换成功：+${formatNumber(credits)} 点，已入账。`
      : '兑换成功，点数已入账。'
    redeemInput.value = ''
    ui.notify(redeemSuccess.value, 'success', 5000)
    await load()
  } catch (err) {
    redeemError.value = redeemErrorMessage(err)
  } finally {
    redeeming.value = false
  }
}

async function onPage(next: number): Promise<void> {
  page.value = next
  await router.replace({ query: { ...route.query, page: String(next) } })
}

function deltaValue(entry: LedgerEntry): number {
  return Number(entry.delta ?? entry.amount ?? 0)
}

function signedNumber(entry: LedgerEntry): string {
  const delta = deltaValue(entry)
  return delta > 0 ? `+${formatNumber(delta)}` : formatNumber(delta)
}

function deltaClass(entry: LedgerEntry): string {
  return deltaValue(entry) >= 0 ? 'text-success' : 'text-error'
}

/** 当前余额是第 0 条之后的余额；回推每条的期后余额。 */
function balanceAfter(index: number): number {
  let balance = wallet.value?.balance ?? 0
  for (let i = 0; i < index; i += 1) balance -= deltaValue(items.value[i])
  return balance
}

function ledgerTypeLabel(type?: string): string {
  switch (type) {
    case 'grant':
      return '充值'
    case 'adjust':
      return '调整'
    case 'consume':
      return '消耗'
    case 'refund':
      return '退款'
    default:
      return type || '变动'
  }
}

function chipColor(type?: string): string {
  switch (type) {
    case 'grant':
      return 'success'
    case 'adjust':
      return 'warning'
    case 'consume':
      return 'default'
    default:
      return 'primary'
  }
}
</script>

<style scoped>
.page-wrap {
  width: 100%;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--console-text-muted);
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.balance-card {
  background: linear-gradient(160deg, rgba(60, 150, 202, 0.12), rgba(60, 150, 202, 0.02) 60%);
  border: 1px solid rgba(60, 150, 202, 0.24) !important;
}

.balance-number {
  font-size: 46px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -1px;
}

.notice-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notice-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--console-text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.chart-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bot-filter {
  width: 160px;
}

.chart-totals {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin: 4px 0 2px;
  color: var(--console-text-muted);
}

.section-head {
  display: flex;
  align-items: center;
  padding: 18px 20px 4px;
}

.ledger-table {
  background: transparent;
}

.ledger-table :deep(th) {
  font-size: 12px;
  font-weight: 600;
  color: var(--console-text-muted);
}

.note-cell {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.table-scroll {
  overflow-x: auto;
}

.redeem-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.redeem-input {
  flex: 1 1 220px;
  min-width: 180px;
}

.payment-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.payment-item {
  flex: 1 1 180px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
  color: var(--console-text-muted);
}

.payment-name {
  flex: 1;
  font-size: 13px;
}
</style>
