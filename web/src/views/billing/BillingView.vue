<template>
  <div class="page-wrap">
    <div class="page-head">
      <div>
        <h1 class="page-title">额度与账单</h1>
        <p class="page-sub">
          预付费点数：管理员确认充值后入账，余额与流水以 append-only 账本为准。
        </p>
      </div>
      <div class="page-actions">
        <v-chip variant="tonal" color="primary" prepend-icon="mdi-flask-outline">
          内测 · 人工充值
        </v-chip>
        <v-btn variant="outlined" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="load">
          刷新
        </v-btn>
      </div>
    </div>

    <v-row>
      <v-col cols="12" md="7">
        <v-card elevation="0" class="pa-6 h-100 balance-card">
          <div class="text-caption muted mb-1">当前余额</div>
          <div class="d-flex align-baseline ga-2">
            <div class="balance-number">{{ formatNumber(wallet?.balance ?? 0) }}</div>
            <div class="text-body-2 muted">点</div>
          </div>
          <div class="text-caption muted mt-1">
            账本重算余额 {{ formatNumber(wallet?.ledger_total ?? wallet?.balance ?? 0) }} ·
            近 30 天扣减 {{ formatNumber(usage?.total_out ?? 0) }} 点
          </div>

          <v-progress-linear :model-value="usagePercent" height="8" rounded color="primary" class="my-5" />

          <v-row dense>
            <v-col v-for="insight in insights" :key="insight.label" cols="4">
              <div class="text-caption muted">{{ insight.label }}</div>
              <div class="text-body-1 font-weight-bold">{{ insight.value }}</div>
            </v-col>
          </v-row>
        </v-card>
      </v-col>

      <v-col cols="12" md="5">
        <v-card elevation="0" class="pa-6 h-100">
          <div class="text-subtitle-1 font-weight-bold mb-1">充值说明</div>
          <p class="text-caption muted mb-4">
            当前为邀请制内测，额度由平台管理员统一发放；不提供在线支付与自动充值。
          </p>
          <ul class="notice-list text-body-2">
            <li><v-icon size="16" color="primary">mdi-check-circle-outline</v-icon> 联系管理员手动充值，确认后写入账本</li>
            <li><v-icon size="16" color="primary">mdi-check-circle-outline</v-icon> 同一外部单号 / 幂等键不会重复入账</li>
            <li><v-icon size="16" color="primary">mdi-check-circle-outline</v-icon> 余额与流水随时可对账，删除账号即停止计费</li>
          </ul>
          <v-divider class="my-4" />
          <div class="d-flex align-center text-caption muted">
            <v-icon size="16" class="mr-2">mdi-information-outline</v-icon>
            合规说明：暂不接入自动充值，避免未经许可的代收代付。
          </div>
        </v-card>
      </v-col>
    </v-row>

    <v-card elevation="0" class="pa-5 mt-4">
      <div class="chart-head">
        <div>
          <div class="text-subtitle-1 font-weight-bold">余额变化</div>
          <div class="text-caption muted">平台点数账本 · 近 {{ usage?.days ?? 30 }} 天（不是上游模型账户余额）</div>
        </div>
        <v-spacer />
        <div class="chart-totals text-caption">
          <span class="text-success">+{{ formatNumber(usage?.total_in ?? 0) }} 入账</span>
          <span class="text-error">-{{ formatNumber(usage?.total_out ?? 0) }} 扣减</span>
        </div>
      </div>
      <LoadingSkeleton v-if="loading && !usage" variant="card" :rows="1" />
      <UsageChart v-else :points="usage?.points ?? []" :height="210" />
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
        description="管理员确认充值单或手动调整后，这里会出现明细。"
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
import { getWallet, getWalletLedger, getWalletUsage } from '@/api/wallet'
import { useAuthStore } from '@/stores/auth'
import type { LedgerEntry, Wallet, WalletUsage } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const wallet = ref<Wallet | null>(null)
const usage = ref<WalletUsage | null>(null)
const items = ref<LedgerEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')

const usagePercent = computed(() => {
  const out = usage.value?.total_out ?? 0
  const balance = wallet.value?.balance ?? 0
  const totalPoints = out + balance
  if (totalPoints <= 0) return 0
  return Math.min(100, Math.round((out / totalPoints) * 100))
})

const insights = computed(() => [
  { label: '累计充值', value: `${formatNumber(usage.value?.total_in ?? 0)} 点` },
  { label: '近 30 天扣减', value: `${formatNumber(usage.value?.total_out ?? 0)} 点` },
  { label: '可用额度', value: `${formatNumber(wallet.value?.balance ?? 0)} 点` },
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
    const [walletResult, ledgerResult, usageResult] = await Promise.all([
      getWallet(),
      getWalletLedger(page.value, pageSize.value),
      getWalletUsage(30),
    ])
    wallet.value = walletResult
    usage.value = usageResult
    items.value = ledgerResult.items ?? []
    total.value = ledgerResult.total ?? 0
    page.value = ledgerResult.page ?? page.value
    pageSize.value = ledgerResult.page_size ?? pageSize.value
  } catch (err) {
    error.value = (err as Error).message || '加载失败'
  } finally {
    loading.value = false
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
  font-size: 44px;
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

.chart-totals {
  display: flex;
  gap: 14px;
  white-space: nowrap;
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
</style>
