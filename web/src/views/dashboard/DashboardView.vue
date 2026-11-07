<template>
  <div class="page-wrap">
    <div class="page-head">
      <div>
        <h1 class="page-title">总览</h1>
        <p class="page-sub">
          {{ auth.user?.email || '—' }} · {{ auth.isAdmin ? '管理员' : '普通用户' }} ·
          {{ bots.items.length }} 个 Bot
        </p>
      </div>
      <div class="page-actions">
        <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="reload">
          刷新
        </v-btn>
        <v-btn color="primary" variant="tonal" size="small" prepend-icon="mdi-qrcode-scan" to="/connect">
          扫码接入
        </v-btn>
      </div>
    </div>

    <EmptyState
      v-if="!bots.loading && !bots.error && bots.items.length === 0"
      icon="mdi-robot-outline"
      title="还没有 Bot"
      description="扫码接入一个微信或 QQ 机器人，几分钟内即可上线。"
      :actions="[
        { label: '扫码接入', to: '/connect' },
        { label: '我的 Bot', to: '/bots', variant: 'tonal' },
      ]"
      class="mb-6"
    />

    <v-row class="stats-row">
      <v-col v-for="stat in stats" :key="stat.label" cols="6" md="3">
        <v-card elevation="0" class="stat-card pa-4">
          <div class="stat-label">
            <v-icon size="18" class="mr-2">{{ stat.icon }}</v-icon>
            <span class="text-caption muted">{{ stat.label }}</span>
          </div>
          <div class="stat-number">{{ stat.value }}</div>
          <div class="stat-hint text-caption muted">{{ stat.hint }}</div>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-1">
      <v-col cols="12">
        <v-card elevation="0" class="pa-5 h-100">
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
          <LoadingSkeleton v-if="dailyLoading && !daily" variant="card" :rows="1" />
          <UsageChart v-else :points="daily?.points ?? []" value-label="消耗" unit="点" :height="210" />
          <div class="chart-foot text-caption muted">
            <span>近 {{ daily?.days ?? 30 }} 天消耗 <strong>{{ formatNumber(daily?.total_points ?? 0) }}</strong> 点</span>
            <span>请求 {{ formatNumber(daily?.total_requests ?? 0) }} 次</span>
            <span>剩余 {{ formatNumber(wallet?.balance ?? 0) }} 点</span>
          </div>
        </v-card>
      </v-col>

    </v-row>

    <v-card elevation="0" class="mt-4">
      <div class="section-head">
        <div class="text-subtitle-1 font-weight-bold">最近流水</div>
        <v-spacer />
        <v-btn variant="text" size="small" to="/billing" append-icon="mdi-arrow-right">查看全部</v-btn>
      </div>
      <v-table density="comfortable" class="recent-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>说明</th>
            <th class="text-right">变动</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in recentLedger" :key="String(entry.id)">
            <td class="text-caption muted nowrap">{{ formatDateTime(entry.created_at) }}</td>
            <td>
              <v-chip size="x-small" variant="tonal" :color="entry.delta && entry.delta > 0 ? 'success' : 'default'">
                {{ ledgerTypeLabel(entry.type) }}
              </v-chip>
            </td>
            <td class="entry-note">{{ entry.note || '—' }}</td>
            <td class="text-right font-weight-medium" :class="entry.delta && entry.delta > 0 ? 'text-success' : ''">
              {{ signedNumber(entry.delta) }}
            </td>
          </tr>
          <tr v-if="!recentLedger.length">
            <td colspan="4" class="text-center muted pa-6">暂无流水</td>
          </tr>
        </tbody>
      </v-table>
    </v-card>

    <v-alert v-if="bots.error" type="error" variant="tonal" class="mt-4">
      <div class="alert-row">
        <span>{{ bots.error.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import UsageChart from '@/components/UsageChart.vue'
import { useAuthStore } from '@/stores/auth'
import { useBotsStore } from '@/stores/bots'
import { getDailyUsage, getUsageByBot, getWallet, getWalletLedger } from '@/api/wallet'
import type { LedgerEntry, UsageByBot, UsageDaily, Wallet } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'

const auth = useAuthStore()
const bots = useBotsStore()

const wallet = ref<Wallet | null>(null)
const daily = ref<UsageDaily | null>(null)
const byBot = ref<UsageByBot[]>([])
const recentLedger = ref<LedgerEntry[]>([])
const dailyLoading = ref(false)
const loading = ref(false)
const range = ref<'30' | '7'>('30')
const botFilter = ref('')

const botOptions = computed(() => [
  { title: '全部 Bot', value: '' },
  ...byBot.value
    .filter((item) => Boolean(item.bot_id))
    .map((item) => ({ title: item.bot_name || item.bot_id, value: item.bot_id })),
])

const stats = computed(() => [
  {
    label: '可用额度',
    value: `${formatNumber(wallet.value?.balance ?? 0)} 点`,
    hint: '剩余可用点数',
    icon: 'mdi-wallet-outline',
  },
  {
    label: '近 30 天消耗',
    value: `${formatNumber(daily.value?.total_points ?? 0)} 点`,
    hint: `请求 ${formatNumber(daily.value?.total_requests ?? 0)} 次`,
    icon: 'mdi-chart-line',
  },
  {
    label: 'Bot 数量',
    value: String(bots.items.length),
    hint: `配额上限 ${auth.limits?.max_bots ?? '—'} 个`,
    icon: 'mdi-robot-outline',
  },
  {
    label: '运行中',
    value: String(bots.readyBots.length),
    hint: `共 ${bots.items.length} 个 Bot`,
    icon: 'mdi-play-circle-outline',
  },
])

onMounted(() => {
  void reload()
})

async function reload(): Promise<void> {
  loading.value = true
  try {
    await Promise.all([bots.fetchBots(), loadWallet(), loadDaily(), loadByBot(), loadLedger()])
  } finally {
    loading.value = false
  }
}

async function loadWallet(): Promise<void> {
  try {
    wallet.value = await getWallet()
  } catch {
    /* 由页面空白提示兜底 */
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
    byBot.value = (await getUsageByBot(30)).items ?? []
  } catch {
    byBot.value = []
  }
}

async function loadLedger(): Promise<void> {
  try {
    const result = await getWalletLedger(1, 5)
    recentLedger.value = result.items ?? []
  } catch {
    recentLedger.value = []
  }
}

function ledgerTypeLabel(type?: string): string {
  switch (type) {
    case 'grant':
      return '充值'
    case 'adjust':
      return '调整'
    case 'consume':
      return '消耗'
    default:
      return type || '变动'
  }
}

function signedNumber(value?: number): string {
  const delta = Number(value ?? 0)
  return delta > 0 ? `+${formatNumber(delta)}` : formatNumber(delta)
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
  gap: 8px;
  margin-left: auto;
}

.stats-row {
  margin-bottom: 4px;
}

.stat-card {
  border: 1px solid var(--console-border);
  transition: border-color 0.15s ease;
}

.stat-card:hover {
  border-color: rgba(60, 150, 202, 0.45);
}

.stat-label {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  color: var(--console-text-muted);
}

.stat-number {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
}

.stat-hint {
  margin-top: 2px;
}

.chart-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 4px;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bot-filter {
  width: 150px;
}

.chart-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 6px;
}

.section-head {
  display: flex;
  align-items: center;
  padding: 18px 20px 4px;
}

.recent-table {
  background: transparent;
}

.recent-table :deep(th) {
  font-size: 12px;
  font-weight: 600;
  color: var(--console-text-muted);
}

.entry-note {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
