<template>
  <div class="page-wrap">
    <div class="page-head">
      <div>
        <h1 class="page-title">总览</h1>
        <p class="page-sub">
          {{ auth.user?.display_name || auth.user?.email || '—' }} ·
          {{ auth.isAdmin ? '管理员' : '普通用户' }} · {{ bots.items.length }} 个 Bot
        </p>
      </div>
      <div class="page-actions">
        <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" @click="reload">
          刷新
        </v-btn>
        <v-btn color="primary" variant="tonal" size="small" prepend-icon="mdi-robot-outline" to="/connect">
          添加机器人
        </v-btn>
      </div>
    </div>

    <v-row class="stats-row">
      <v-col cols="12" sm="4">
        <v-card class="stat-card">
          <div class="stat-label"><v-icon size="18">mdi-wallet-outline</v-icon> 可用额度</div>
          <div class="stat-number">{{ formatNumber(wallet?.balance ?? 0) }}<span class="stat-unit">点</span></div>
          <div class="stat-hint text-muted">剩余可用点数</div>
        </v-card>
      </v-col>
      <v-col cols="6" sm="4">
        <v-card class="stat-card">
          <div class="stat-label"><v-icon size="18">mdi-robot-outline</v-icon> Bot 数量</div>
          <div class="stat-number">{{ bots.items.length }}</div>
          <div class="stat-hint text-muted">配额上限 {{ auth.limits?.max_bots ?? '—' }} 个</div>
        </v-card>
      </v-col>
      <v-col cols="6" sm="4">
        <v-card class="stat-card">
          <div class="stat-label"><v-icon size="18">mdi-play-circle-outline</v-icon> 运行中</div>
          <div class="stat-number">{{ bots.readyBots.length }}</div>
          <div class="stat-hint text-muted">共 {{ bots.items.length }} 个 Bot</div>
        </v-card>
      </v-col>
    </v-row>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !stats" variant="card" :rows="4" />

    <v-card v-else-if="isEmpty" class="empty-card">
      <EmptyState
        icon="mdi-chart-line"
        title="暂无消耗记录"
        description="产生模型调用后，这里会展示点数消耗趋势、模型排名与平台分布。"
      />
    </v-card>

    <template v-else>
      <v-row class="main-row">
        <v-col cols="12" lg="8">
          <v-card class="chart-card">
            <div class="card-head">
              <div>
                <h2 class="card-title">消息趋势</h2>
                <p class="card-sub text-muted">按日统计 Bot 消息量；点数见下方 AI 模型</p>
              </div>
              <div class="head-actions">
                <v-btn-toggle v-model="range" density="compact" variant="text" divided mandatory class="range-toggle">
                  <v-btn value="7" size="small" @click="load">7 天</v-btn>
                  <v-btn value="30" size="small" @click="load">30 天</v-btn>
                </v-btn-toggle>
                <div class="total-points">
                  <span class="text-muted">总消息</span>
                  <strong>{{ formatNumber(stats?.messages?.total ?? 0) }}</strong> 条
                </div>
              </div>
            </div>
            <transition name="page-fade" mode="out-in">
              <div :key="range" class="chart-body">
                <UsageChart :points="messagePoints" value-label="消息" unit="条" :height="230" />
              </div>
            </transition>
          </v-card>
        </v-col>

        <v-col cols="12" lg="4">
          <v-card class="rank-card">
            <div class="card-head">
              <div>
                <h2 class="card-title">模型用量排名</h2>
                <p class="card-sub text-muted">按点数 Top 5</p>
              </div>
              <v-icon color="primary">mdi-trophy-outline</v-icon>
            </div>
            <div v-if="topModels.length" class="rank-list">
              <div v-for="(item, index) in topModels" :key="item.model_id" class="rank-row">
                <span class="rank-index">{{ index + 1 }}</span>
                <div class="rank-main">
                  <div class="rank-name">{{ item.model_name || item.model_id || '未知模型' }}</div>
                  <div class="rank-sub text-muted">{{ formatNumber(item.tokens) }} Tokens</div>
                </div>
                <strong class="rank-points">{{ formatNumber(item.points) }} 点</strong>
              </div>
            </div>
            <p v-else class="empty-hint text-muted">暂无模型用量</p>
          </v-card>
        </v-col>
      </v-row>

      <div class="section-title">AI 模型</div>

      <v-row>
        <v-col cols="12" lg="8">
          <v-card class="chart-card">
            <div class="card-head">
              <div>
                <h2 class="card-title">调用趋势</h2>
                <p class="card-sub text-muted">按日点数 · 柱状图</p>
              </div>
              <span class="text-muted small-note">近 {{ stats?.days }} 天</span>
            </div>
            <UsageBarChart :points="stats?.points ?? []" :height="260" />
          </v-card>
        </v-col>

        <v-col cols="12" lg="4">
          <v-card class="usage-card">
            <div class="card-head">
              <div>
                <h2 class="card-title">最近 {{ stats?.days }} 天用量</h2>
                <p class="card-sub text-muted">点数为主指标</p>
              </div>
            </div>
            <div class="usage-numbers">
              <div class="usage-big">
                <strong>{{ formatNumber(stats?.total_points) }}</strong>
                <span>点</span>
              </div>
              <div class="usage-meta">
                <span>请求 <strong>{{ formatNumber(stats?.total_requests) }}</strong> 次</span>
                <span>Tokens <strong>{{ formatNumber(stats?.total_tokens) }}</strong></span>
              </div>
            </div>
            <v-divider class="my-4" />
            <div class="mini-section">
              <div class="mini-title text-muted">平台分布</div>
              <div v-if="platformRows.length" class="mini-list">
                <div v-for="item in platformRows" :key="item.platform" class="mini-row">
                  <span>{{ platformText(item.platform) }}</span>
                  <strong>{{ formatNumber(item.points) }} 点</strong>
                </div>
              </div>
              <p v-else class="empty-hint text-muted">暂无平台用量</p>
            </div>
            <div class="mini-section">
              <div class="mini-title text-muted">Bot 用量排名</div>
              <div v-if="topBots.length" class="mini-list">
                <div v-for="(item, index) in topBots" :key="item.bot_id" class="mini-row">
                  <span class="bot-rank-name">{{ index + 1 }}. {{ item.bot_name || item.bot_id }}</span>
                  <strong>{{ formatNumber(item.points) }} 点</strong>
                </div>
              </div>
              <p v-else class="empty-hint text-muted">暂无 Bot 用量</p>
            </div>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import UsageChart from '@/components/UsageChart.vue'
import UsageBarChart from '@/components/UsageBarChart.vue'
import { useAuthStore } from '@/stores/auth'
import { useBotsStore } from '@/stores/bots'
import { getMeStats, getWallet } from '@/api/wallet'
import type { MeStats, Wallet } from '@/types'
import { formatNumber, platformLabel } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const auth = useAuthStore()
const bots = useBotsStore()

const wallet = ref<Wallet | null>(null)
const stats = ref<MeStats | null>(null)
const loading = ref(false)
const error = ref('')
const range = ref<'30' | '7'>('30')

const isEmpty = computed(() => {
  if (!stats.value) return true
  return Number(stats.value.total_requests || 0) === 0 && Number(stats.value.total_points || 0) === 0
})

const topModels = computed(() =>
  [...(stats.value?.by_model ?? [])].sort((a, b) => b.points - a.points).slice(0, 5),
)
const platformRows = computed(() =>
  [...(stats.value?.by_platform ?? [])].filter((item) => item.platform).sort((a, b) => b.points - a.points),
)
const topBots = computed(() =>
  [...(stats.value?.by_bot ?? [])]
    .filter((item) => item.bot_id)
    .sort((a, b) => b.points - a.points)
    .slice(0, 5),
)
const messagePoints = computed(() =>
  (stats.value?.messages?.points ?? []).map((point) => ({
    date: point.date,
    points: Number(point.count || 0),
    tokens: 0,
    requests: 0,
  })),
)


function platformText(platform: string): string {
  if (!platform || platform === 'unknown') return '未知平台'
  return platformLabel(platform)
}

onMounted(reload)

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([bots.fetchBots(), loadWallet(), loadStats()])
  } finally {
    loading.value = false
  }
}

async function loadWallet(): Promise<void> {
  try {
    wallet.value = await getWallet()
  } catch {
    wallet.value = null
  }
}

async function load(): Promise<void> {
  await loadStats()
}

async function loadStats(): Promise<void> {
  try {
    stats.value = await getMeStats(Number(range.value))
  } catch (err) {
    error.value = errorMessage(err, '加载用量统计失败')
    stats.value = null
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
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.page-title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
}

.page-sub {
  margin: 4px 0 0;
  color: var(--console-text-muted);
  font-size: 12.5px;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.stats-row {
  margin-bottom: 4px;
}

.stat-card {
  padding: 14px 16px;
  height: 100%;
}

.stat-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--console-text-muted);
  font-size: 12px;
}

.stat-number {
  margin-top: 8px;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.15;
}

.stat-unit {
  margin-left: 3px;
  font-size: 13px;
  font-weight: 500;
  color: var(--console-text-muted);
}

.stat-hint {
  margin-top: 3px;
  font-size: 11.5px;
}

.main-row {
  margin-top: 4px;
}

.chart-card,
.rank-card,
.usage-card {
  padding: 18px;
  height: 100%;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
}

.card-sub {
  margin: 3px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.range-toggle {
  border: 1px solid var(--console-border);
  border-radius: 8px;
}

.total-points {
  font-size: 12px;
  color: var(--console-text-muted);
}

.total-points strong {
  margin-left: 4px;
  font-size: 20px;
  color: var(--console-text);
}

.chart-body {
  min-height: 230px;
}

.rank-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

.rank-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--console-border);
}

.rank-row:last-child {
  border-bottom: none;
}

.rank-index {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: var(--console-primary-soft);
  color: var(--console-primary);
  font-size: 11px;
  font-weight: 700;
}

.rank-main {
  flex: 1;
  min-width: 0;
}

.rank-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rank-sub {
  margin-top: 2px;
  font-size: 11px;
}

.rank-points {
  font-size: 13px;
  white-space: nowrap;
}

.section-title {
  margin: 22px 0 10px;
  font-size: 18px;
  font-weight: 700;
}

.bar-chart {
  position: relative;
  height: 190px;
  padding-top: 10px;
}

.bar-grid {
  position: absolute;
  inset: 10px 0 22px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.bar-grid-line {
  height: 1px;
  background: var(--console-border);
  opacity: 0.65;
}

.bar-columns {
  position: absolute;
  inset: 10px 0 22px;
  display: flex;
  align-items: flex-end;
  gap: 2px;
}

.bar-column {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  min-width: 2px;
}

.bar-fill {
  width: 100%;
  border-radius: 3px 3px 0 0;
  background: linear-gradient(180deg, var(--console-primary), rgba(60, 150, 202, 0.55));
  transition: height 0.3s ease;
}

.bar-column:hover .bar-fill {
  filter: brightness(1.08);
}

.bar-labels {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  justify-content: space-between;
  color: var(--console-text-muted);
  font-size: 10px;
}

.usage-numbers {
  margin-top: 8px;
}

.usage-big {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.usage-big strong {
  font-size: 40px;
  line-height: 1;
  font-weight: 700;
}

.usage-big span {
  font-size: 13px;
  color: var(--console-text-muted);
}

.usage-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 8px;
  color: var(--console-text-muted);
  font-size: 12px;
}

.usage-meta strong {
  color: var(--console-text);
}

.mini-section {
  margin-top: 12px;
}

.mini-title {
  font-size: 11.5px;
  margin-bottom: 6px;
}

.mini-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mini-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
}

.mini-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-row strong {
  font-weight: 600;
  white-space: nowrap;
}

.bot-rank-name {
  color: var(--console-text);
}

.empty-card {
  padding: 26px;
}

.empty-hint {
  margin: 10px 0;
  font-size: 12px;
}

.small-note {
  font-size: 11.5px;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 599px) {
  .page-title {
    font-size: 22px;
  }

  .stat-number {
    font-size: 22px;
  }

  .chart-card,
  .rank-card,
  .usage-card {
    padding: 14px;
  }

  .total-points strong {
    font-size: 18px;
  }
}
</style>
