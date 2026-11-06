<template>
  <div>
    <PageHeader
      :title="greeting"
      description="这里汇总你的 Bot、额度与最近动态。"
    >
      <template #actions>
        <v-btn variant="tonal" prepend-icon="mdi-qrcode-scan" to="/connect">扫码接入</v-btn>
        <v-btn color="primary" prepend-icon="mdi-plus" to="/bots">我的 Bot</v-btn>
      </template>
    </PageHeader>

    <div class="page-grid page-grid--stats mb-6">
      <StatCard
        label="Bot 数量"
        :value="botCountText"
        :hint="limits ? `配额上限 ${limits.max_bots} 个` : '配额以服务端为准'"
        icon="mdi-robot-outline"
        :loading="bots.loading"
      />
      <StatCard
        label="可用额度"
        :value="walletText"
        hint="本期为只读展示"
        icon="mdi-wallet-outline"
        :loading="walletLoading"
      />
      <StatCard
        label="加密状态"
        :value="encryptionText"
        :hint="privacyHint"
        icon="mdi-shield-lock-outline"
        :color="encryptionEnabled ? 'success' : 'error'"
        :loading="encryptionLoading"
      />
      <StatCard
        label="运行中 Bot"
        :value="bots.readyBots.length"
        hint="状态以平台实例为准"
        icon="mdi-play-circle-outline"
        color="success"
        :loading="bots.loading"
      />
    </div>

    <v-alert v-if="bots.error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ bots.error.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>

    <EmptyState
      v-if="!bots.loading && !bots.error && bots.items.length === 0"
      icon="mdi-robot-outline"
      title="还没有 Bot"
      description="扫码接入一个微信或 QQ 机器人，几分钟内即可上线。也可以先到「我的 Bot」创建并稍后扫码。"
      :actions="[
        { label: '扫码接入', to: '/connect' },
        { label: '我的 Bot', to: '/bots', variant: 'tonal' },
      ]"
      class="mb-6"
    />

    <v-row v-else class="dashboard-row">
      <v-col cols="12" md="7">
        <v-card class="panel">
          <div class="panel-head">
            <h2 class="section-title">最近活动</h2>
            <v-btn size="small" variant="text" to="/access-log">访问记录</v-btn>
          </div>
          <LoadingSkeleton v-if="bots.loading" variant="list" :rows="3" />
          <div v-else-if="recentBots.length === 0" class="panel-empty text-muted">
            暂无活动，创建 Bot 后会在这里显示。
          </div>
          <v-list v-else density="comfortable" class="activity-list">
            <v-list-item
              v-for="bot in recentBots"
              :key="bot.id"
              :to="`/bots/${bot.id}`"
              :title="bot.name"
              :subtitle="`${platformShortLabel(bot.platform)} · ${bot.last_active_at ? formatRelative(bot.last_active_at) + '活跃' : '尚未活跃'}`"
            >
              <template #prepend>
                <v-avatar color="primary" variant="tonal" size="34" rounded="lg">
                  <v-icon size="18">mdi-robot-outline</v-icon>
                </v-avatar>
              </template>
              <template #append>
                <StatusChip :status="bot.status" />
              </template>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>

      <v-col cols="12" md="5">
        <v-card class="panel">
          <h2 class="section-title">快捷入口</h2>
          <div class="quick-links">
            <v-btn block variant="tonal" color="primary" prepend-icon="mdi-qrcode-scan" to="/connect">
              扫码接入新 Bot
            </v-btn>
            <v-btn block variant="tonal" prepend-icon="mdi-shield-lock-outline" to="/settings/privacy">
              查看加密状态
            </v-btn>
            <v-btn block variant="tonal" prepend-icon="mdi-wallet-outline" to="/billing">
              查看额度
            </v-btn>
            <v-btn
              v-if="auth.isAdmin"
              block
              variant="tonal"
              color="secondary"
              prepend-icon="mdi-shield-account-outline"
              to="/admin"
            >
              进入管理后台
            </v-btn>
          </div>

          <v-divider class="my-4" />
          <h2 class="section-title">账号</h2>
          <div class="account-line">
            <span class="text-muted">邮箱</span>
            <span class="account-value">{{ auth.user?.email }}</span>
          </div>
          <div class="account-line">
            <span class="text-muted">角色</span>
            <span class="account-value">{{ auth.isAdmin ? '管理员' : '普通用户' }}</span>
          </div>
          <div class="account-line">
            <span class="text-muted">版本</span>
            <span class="account-value">{{ auth.version || '—' }}</span>
          </div>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import StatusChip from '@/components/StatusChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useAuthStore } from '@/stores/auth'
import { useBotsStore } from '@/stores/bots'
import { useEncryptionStore } from '@/stores/encryption'
import { getWallet } from '@/api/wallet'
import { toApiError } from '@/api/client'
import type { Wallet } from '@/types'
import { formatNumber, formatRelative, platformShortLabel } from '@/utils/format'

const auth = useAuthStore()
const bots = useBotsStore()
const encryption = useEncryptionStore()

const wallet = ref<Wallet | null>(null)
const walletLoading = ref(false)
const walletError = ref('')
const encryptionLoading = ref(false)
const encryptionEnabled = computed(() => encryption.enabled)
const encryptionError = ref('')

const limits = computed(() => auth.limits)
const greeting = computed(() => (auth.user?.email ? `欢迎回来，${auth.user.email}` : '总览'))

const botCountText = computed(() => {
  const used = bots.total
  return limits.value ? `${used} / ${limits.value.max_bots}` : String(used)
})

const walletText = computed(() => {
  if (walletLoading.value) return '…'
  if (!wallet.value) return '—'
  return `${formatNumber(wallet.value.balance)} ${wallet.value.currency === 'points' ? '积分' : wallet.value.currency}`
})

const encryptionText = computed(() => {
  if (encryptionLoading.value) return '…'
  if (encryption.error) return '加载失败'
  return encryptionEnabled.value ? '已开启' : '明文存储'
})

const privacyHint = computed(() => {
  if (encryption.error) return '可到隐私页重试'
  return encryptionEnabled.value ? '对话与记忆均加密存储' : '当前为明文存储'
})

const recentBots = computed(() =>
  [...bots.items]
    .sort((a, b) => (b.last_active_at || b.updated_at) - (a.last_active_at || a.updated_at))
    .slice(0, 5),
)

onMounted(() => {
  void Promise.allSettled([reloadBots(), loadWallet(), loadEncryption()])
})

async function reloadBots(): Promise<void> {
  try {
    await bots.fetchBots(true)
  } catch {
    /* 错误已在 store 中记录 */
  }
}

async function loadWallet(): Promise<void> {
  walletLoading.value = true
  walletError.value = ''
  try {
    wallet.value = await getWallet()
  } catch (error) {
    walletError.value = toApiError(error).message
  } finally {
    walletLoading.value = false
  }
}

async function loadEncryption(): Promise<void> {
  encryptionLoading.value = true
  encryptionError.value = ''
  try {
    await encryption.fetchStatus()
  } catch (error) {
    encryptionError.value = toApiError(error).message
  } finally {
    encryptionLoading.value = false
  }
}

async function reload(): Promise<void> {
  await Promise.allSettled([reloadBots(), loadWallet(), loadEncryption()])
}
</script>

<style scoped>
.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dashboard-row {
  margin-top: -12px;
}

.panel {
  padding: 20px;
  height: 100%;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-empty {
  padding: 16px 0;
  font-size: 0.85rem;
}

.activity-list {
  margin: 0 -8px;
}

.quick-links {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.account-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  font-size: 0.83rem;
}

.account-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wallet-error {
  font-size: 0.78rem;
  color: #c62828;
  margin-top: 4px;
}
</style>
