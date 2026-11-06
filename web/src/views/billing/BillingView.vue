<template>
  <div>
    <PageHeader title="额度" description="余额与流水；M1 阶段为只读展示。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
      </template>
    </PageHeader>

    <div class="page-grid page-grid--stats mb-6">
      <StatCard
        label="可用额度"
        :value="walletText"
        :hint="wallet?.currency === 'points' ? '积分余额' : wallet?.currency || '以服务端为准'"
        icon="mdi-wallet-outline"
        :loading="loading"
      />
      <StatCard
        label="本月 Token 上限"
        :value="tokenLimitText"
        hint="来自账号配额"
        icon="mdi-chart-line"
        color="info"
        :loading="false"
      />
    </div>

    <v-card class="ledger-card">
      <div class="ledger-head">
        <h2 class="section-title">流水记录</h2>
        <span class="text-muted ledger-count">共 {{ total }} 条</span>
      </div>

      <v-alert v-if="error" type="error" variant="tonal" class="mb-3">
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
        description="充值或消费后会在这里展示明细。M1 阶段额度系统尚未接入，因此列表为空。"
      />

      <template v-else>
        <div class="table-scroll">
          <v-table hover>
            <thead>
              <tr>
                <th>时间</th>
                <th>变动</th>
                <th>余额</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in items" :key="String(entry.id)">
                <td class="nowrap">{{ formatDateTime(entry.created_at) }}</td>
                <td :class="entry.amount >= 0 ? 'amount-plus' : 'amount-minus'">
                  {{ entry.amount >= 0 ? '+' : '' }}{{ formatNumber(entry.amount) }}
                </td>
                <td>{{ entry.balance_after !== undefined ? formatNumber(entry.balance_after) : '—' }}</td>
                <td>{{ entry.reason || '—' }}</td>
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
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { getWallet, getWalletLedger } from '@/api/wallet'
import { toApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { LedgerEntry, Wallet } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const wallet = ref<Wallet | null>(null)
const items = ref<LedgerEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')

const walletText = computed(() => {
  if (!wallet.value) return '—'
  const unit = wallet.value.currency === 'points' ? '积分' : wallet.value.currency
  return `${formatNumber(wallet.value.balance)} ${unit}`
})

const tokenLimitText = computed(() =>
  auth.limits ? formatNumber(auth.limits.monthly_tokens) : '—',
)

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
  } catch (err) {
    error.value = toApiError(err).message
  } finally {
    loading.value = false
  }
}

async function onPage(next: number): Promise<void> {
  page.value = next
  await router.replace({ query: { ...route.query, page: String(next) } })
  await load()
}
</script>

<style scoped>
.ledger-card {
  padding: 20px;
}

.ledger-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.ledger-count {
  font-size: 0.78rem;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.table-scroll {
  overflow-x: auto;
}

.nowrap {
  white-space: nowrap;
}

.amount-plus {
  color: #2e7d32;
  font-weight: 600;
}

.amount-minus {
  color: #c62828;
  font-weight: 600;
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
