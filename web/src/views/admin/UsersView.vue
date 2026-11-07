<template>
  <div>
    <PageHeader title="用户管理" description="查看用户状态、配额与加密状态；封禁会立即撤销会话并停用其全部 Bot。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="admin.usersLoading" @click="reload">
          刷新
        </v-btn>
      </template>
    </PageHeader>

    <div class="page-grid page-grid--stats mb-4">
      <StatCard
        label="用户数"
        :value="String(overview?.users ?? '—')"
        :hint="`Bot ${overview?.bots ?? '—'} 个 · 在线 ${overview?.ready_bots ?? '—'} 个`"
        icon="mdi-account-group-outline"
        :loading="admin.overviewLoading"
      />
      <StatCard
        label="平台点数余额合计"
        :value="formatNumber(overview?.balance_total)"
        hint="仅平台内预付费点数账本，不是上游模型账户余额"
        icon="mdi-wallet-outline"
        :loading="admin.overviewLoading"
      />
      <StatCard
        label="累计充值点数"
        :value="formatNumber(overview?.granted_points)"
        :hint="`已确认订单 ${overview?.paid_orders ?? 0} 笔 · ¥${(overview?.paid_orders_amount_cny ?? 0).toFixed(2)}`"
        icon="mdi-cash-plus"
        color="success"
        :loading="admin.overviewLoading"
      />
      <StatCard
        label="累计扣减 / 消耗"
        :value="formatNumber(overview?.deducted_points)"
        hint="账本口径（手动扣减 + 后续计量消费）"
        icon="mdi-cash-minus"
        color="warning"
        :loading="admin.overviewLoading"
      />
      <StatCard
        label="已用 Token"
        :value="overview?.tokens_metered ? formatNumber(overview.tokens_used) : '—'"
        :hint="overview?.tokens_metered ? '来自后端调用统计' : '尚未接入用量计量（M4）'"
        icon="mdi-chart-timeline-variant"
        color="info"
        :loading="admin.overviewLoading"
      />
    </div>

    <v-card class="filter-card mb-4">
      <form class="filter-row" @submit.prevent="applyFilters">
        <v-text-field
          v-model.trim="search"
          label="搜索邮箱或 ID"
          prepend-inner-icon="mdi-magnify"
          hide-details
          density="compact"
          class="filter-search"
        />
        <v-select
          v-model="statusFilter"
          :items="statusOptions"
          label="状态"
          hide-details
          density="compact"
          class="filter-status"
          @update:model-value="applyFilters"
        />
        <v-btn type="submit" color="primary" variant="tonal">搜索</v-btn>
        <v-btn variant="text" @click="resetFilters">重置</v-btn>
      </form>
    </v-card>

    <v-alert v-if="admin.usersError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ admin.usersError.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="admin.usersLoading && !admin.users.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!admin.usersError && admin.users.length === 0"
      icon="mdi-account-group-outline"
      title="没有符合条件的用户"
      description="调整搜索条件，或等待新用户注册。"
    />

    <v-card v-else-if="admin.users.length" class="table-card">
      <div class="table-scroll">
        <v-table hover class="users-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>状态</th>
              <th class="nowrap">Bot / 配额</th>
              <th class="nowrap">余额 / 充值 / 扣减</th>
              <th class="nowrap">已用 Token</th>
              <th class="nowrap">加密</th>
              <th class="nowrap">创建时间</th>
              <th class="text-right nowrap">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="user in admin.users"
              :key="user.id"
              class="clickable-row"
              data-testid="admin-user-row"
              @click="openDetail(user)"
            >
              <td class="user-cell">
                <div class="user-name-row">
                  <span class="user-name" :title="user.display_name || user.email">
                    {{ user.display_name || user.email.split('@')[0] }}
                  </span>
                  <v-chip
                    v-if="user.role === 'admin'"
                    size="x-small"
                    variant="tonal"
                    color="primary"
                    class="role-chip"
                  >
                    管理员
                  </v-chip>
                </div>
                <div class="user-email" :title="user.email">{{ user.email }}</div>
                <div class="text-mono text-muted user-id">{{ user.id }}</div>
              </td>
              <td class="status-cell">
                <StatusChip :status="user.status" kind="user" />
                <v-chip
                  v-if="user.pending_appeal"
                  size="x-small"
                  variant="tonal"
                  color="warning"
                  class="appeal-chip"
                >
                  有申诉
                </v-chip>
                <div
                  v-if="user.status_reason"
                  class="status-reason text-muted"
                  :title="user.status_reason"
                >
                  {{ user.status_reason }}
                </div>
              </td>
              <td class="nowrap quota-cell">
                {{ user.bot_count ?? '—' }} / {{ user.quota?.max_bots ?? '—' }}
                <span class="text-muted quota-token">Token {{ formatNumber(user.quota?.monthly_tokens) }}</span>
              </td>
              <td class="nowrap points-cell">
                <div>{{ formatNumber(user.balance) }} 点</div>
                <div class="text-muted points-sub">
                  +{{ formatNumber(user.granted_points) }} / -{{ formatNumber(user.deducted_points) }}
                </div>
              </td>
              <td class="nowrap tokens-cell">
                {{ user.used_tokens ? formatNumber(user.used_tokens) : '—' }}
              </td>
              <td>
                <StatusChip :status="user.encryption?.state || 'encrypted'" kind="encryption" />
              </td>
              <td class="nowrap">{{ formatDateTime(user.created_at) }}</td>
              <td class="text-right nowrap">
                <v-btn size="small" variant="text" @click.stop="openDetail(user)">详情</v-btn>
                <v-btn size="small" variant="text" @click.stop="showQuota(user)">配额</v-btn>
                <v-btn
                  v-if="user.status === 'active'"
                  size="small"
                  variant="text"
                  color="error"
                  @click.stop="askToggle(user, 'disabled')"
                >
                  封禁
                </v-btn>
                <v-btn
                  v-else
                  size="small"
                  variant="text"
                  color="success"
                  @click.stop="askToggle(user, 'active')"
                >
                  启用
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>

      <div v-if="admin.usersTotal > admin.usersPageSize" class="pager">
        <v-pagination
          :model-value="currentPage"
          :length="pageCount"
          :total-visible="5"
          density="comfortable"
          @update:model-value="onPage"
        />
      </div>
    </v-card>

    <v-dialog v-model="quotaOpen" max-width="480">
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">配额详情</v-card-title>
        <v-card-text>
          <div class="quota-user">
            <div class="quota-user__name" :title="quotaUser?.display_name || quotaUser?.email">
              {{ quotaUser?.display_name || quotaUser?.email }}
            </div>
            <div class="quota-user__email text-muted" :title="quotaUser?.email">
              {{ quotaUser?.email }}
            </div>
          </div>
          <v-alert v-if="quotaError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ quotaError }}
          </v-alert>
          <div class="quota-form mt-4">
            <v-text-field
              v-model.number="quotaForm.max_bots"
              label="Bot 上限"
              type="number"
              min="0"
              variant="outlined"
              density="compact"
              hide-details
            />
            <v-text-field
              v-model.number="quotaForm.max_memories"
              label="记忆条数上限"
              type="number"
              min="0"
              variant="outlined"
              density="compact"
              hide-details
            />
            <v-text-field
              v-model.number="quotaForm.monthly_tokens"
              label="每月 Token"
              type="number"
              min="0"
              variant="outlined"
              density="compact"
              hide-details
            />
          </div>
          <div class="quota-used mt-4">
            <span>当前 Bot 数 <strong>{{ quotaUser?.bot_count ?? '—' }}</strong></span>
            <span>已用 Token <strong>{{ formatNumber(quotaUser?.quota?.used_tokens) }}</strong></span>
            <span>余额 <strong>{{ formatNumber(quotaUser?.balance) }}</strong> 点</span>
          </div>
          <p class="text-muted quota-note">
            修改后立即生效；已有 Bot/记忆不会被删除。Token 为每月用量上限，仅累计不强制拦截。
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="quotaSaving" @click="quotaOpen = false">取消</v-btn>
          <v-btn color="primary" variant="tonal" :loading="quotaSaving" @click="saveQuota">
            保存配额
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <AdminUserDrawer
      v-model="detailOpen"
      :user="detailUser"
      @updated="onDetailUpdated"
    />

    <ReasonDialog
      v-model="banOpen"
      :title="`封禁「${banTarget?.display_name || banTarget?.email || ''}」？`"
      message="封禁会立即撤销该用户的全部会话并停用其全部 Bot，必须填写原因（会展示给用户并写入审计）。"
      label="封禁原因"
      confirm-text="确认封禁"
      danger
      :loading="banning"
      @confirm="confirmBan"
      @cancel="banOpen = false"
    />

    <ConfirmDialog
      v-model="toggleOpen"
      :title="toggleTarget?.status === 'active' ? '封禁该用户？' : '解除封禁？'"
      :message="
        toggleTarget?.status === 'active'
          ? '封禁会立即撤销该用户的全部会话，并停用其全部 Bot；该操作会写入审计日志。'
          : '解禁后该用户可以重新登录；其 Bot 不会自动启用。'
      "
      :confirm-text="toggleTarget?.status === 'active' ? '封禁用户' : '解除封禁'"
      :danger="toggleTarget?.status === 'active'"
      :loading="toggling"
      @confirm="confirmToggle"
      @cancel="toggleOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ReasonDialog from '@/components/ReasonDialog.vue'
import AdminUserDrawer from '@/components/AdminUserDrawer.vue'
import { useAdminStore } from '@/stores/admin'
import { useUiStore } from '@/stores/ui'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatNumber } from '@/utils/format'
import type { AdminUser, Quota } from '@/types'

const admin = useAdminStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const overview = computed(() => admin.overview)
const search = ref('')
const statusFilter = ref('')
const currentPage = ref(1)

const statusOptions = [
  { title: '全部状态', value: '' },
  { title: '正常', value: 'active' },
  { title: '已封禁', value: 'disabled' },
]

const quotaOpen = ref(false)
const quotaUser = ref<AdminUser | null>(null)
const quotaSaving = ref(false)
const quotaError = ref('')
const quotaForm = reactive<Quota>({ max_bots: 0, max_memories: 0, monthly_tokens: 0 })

const toggleOpen = ref(false)
const toggleTarget = ref<AdminUser | null>(null)
const toggling = ref(false)

const detailOpen = ref(false)
const detailUser = ref<AdminUser | null>(null)

const banOpen = ref(false)
const banTarget = ref<AdminUser | null>(null)
const banning = ref(false)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(admin.usersTotal / Math.max(1, admin.usersPageSize))),
)

watch(
  () => route.query,
  () => {
    syncFromQuery()
    void load()
  },
  { immediate: true },
)

function stringQuery(value: unknown): string {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' ? raw : ''
}

function syncFromQuery(): void {
  search.value = stringQuery(route.query.q)
  statusFilter.value = stringQuery(route.query.status)
  const parsed = Number(stringQuery(route.query.page))
  currentPage.value = Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  if (!admin.overview) void admin.loadOverview()
  try {
    await admin.loadUsers({
      page: currentPage.value,
      page_size: 20,
      q: search.value || undefined,
      status: statusFilter.value || undefined,
    })
  } catch {
    /* store 已记录 */
  }
}

async function applyFilters(): Promise<void> {
  const query: Record<string, string> = {}
  if (search.value) query.q = search.value
  if (statusFilter.value) query.status = statusFilter.value
  if (currentPage.value > 1) query.page = String(currentPage.value)
  await router.replace({ query })
}

async function resetFilters(): Promise<void> {
  search.value = ''
  statusFilter.value = ''
  currentPage.value = 1
  await router.replace({ query: {} })
}

async function reload(): Promise<void> {
  await load()
}

async function onPage(page: number): Promise<void> {
  currentPage.value = page
  await router.replace({ query: { ...route.query, page: String(page) } })
}

function openDetail(user: AdminUser): void {
  detailUser.value = user
  detailOpen.value = true
}

async function onDetailUpdated(): Promise<void> {
  await load()
}

function showQuota(user: AdminUser): void {
  quotaUser.value = user
  quotaForm.max_bots = Number(user.quota?.max_bots ?? 0)
  quotaForm.max_memories = Number(user.quota?.max_memories ?? 0)
  quotaForm.monthly_tokens = Number(user.quota?.monthly_tokens ?? 0)
  quotaError.value = ''
  quotaOpen.value = true
}

async function saveQuota(): Promise<void> {
  if (!quotaUser.value) return
  quotaError.value = ''
  const values: Array<[keyof Quota, string]> = [
    ['max_bots', 'Bot 上限'],
    ['max_memories', '记忆条数上限'],
    ['monthly_tokens', '每月 Token'],
  ]
  for (const [key, label] of values) {
    const value = Number(quotaForm[key])
    if (!Number.isInteger(value) || value < 0) {
      quotaError.value = `${label}必须是非负整数`
      return
    }
  }
  quotaSaving.value = true
  try {
    const updated = await admin.updateUserQuota(quotaUser.value.id, {
      max_bots: Number(quotaForm.max_bots),
      max_memories: Number(quotaForm.max_memories),
      monthly_tokens: Number(quotaForm.monthly_tokens),
    })
    quotaUser.value = updated
    quotaOpen.value = false
    ui.notify('配额已更新', 'success')
    await load()
  } catch (error) {
    quotaError.value = errorMessage(error, '保存配额失败')
  } finally {
    quotaSaving.value = false
  }
}

function askToggle(user: AdminUser, target: 'active' | 'disabled'): void {
  if (target === 'disabled') {
    banTarget.value = user
    banOpen.value = true
    return
  }
  toggleTarget.value = { ...user, status: 'disabled' }
  toggleOpen.value = true
}

async function confirmBan(reason: string): Promise<void> {
  if (!banTarget.value) return
  banning.value = true
  try {
    await admin.setUserStatus(banTarget.value.id, 'disabled', reason)
    banOpen.value = false
    ui.notify('用户已封禁', 'success')
    await load()
  } catch (error) {
    ui.notifyError(errorMessage(error, '封禁用户失败'))
  } finally {
    banning.value = false
  }
}

async function confirmToggle(): Promise<void> {
  if (!toggleTarget.value) return
  const nextStatus = toggleTarget.value.status === 'active' ? 'disabled' : 'active'
  toggling.value = true
  try {
    await admin.setUserStatus(toggleTarget.value.id, nextStatus)
    toggleOpen.value = false
    ui.notify(nextStatus === 'disabled' ? '用户已封禁' : '用户已解禁', 'success')
  } catch (error) {
    toggleOpen.value = false
    ui.notifyError(errorMessage(error, '更新用户状态失败'))
  } finally {
    toggling.value = false
  }
}
</script>

<style scoped>
.filter-card {
  padding: 14px 16px;
}

.filter-row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.filter-search {
  flex: 1 1 220px;
  min-width: 180px;
}

.filter-status {
  flex: 0 1 160px;
}

.table-card {
  padding: 4px 0;
}

.table-scroll {
  overflow-x: auto;
}

.users-table {
  min-width: 1080px;
}

.clickable-row {
  cursor: pointer;
}

.status-cell {
  min-width: 150px;
}

.appeal-chip {
  margin-top: 4px;
}

.status-reason {
  margin-top: 4px;
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.7rem;
}

.clickable-row:hover {
  background: rgba(60, 150, 202, 0.06);
}

.user-cell {
  min-width: 210px;
  max-width: 280px;
}

.user-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.user-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-email {
  font-size: 0.76rem;
  color: var(--console-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 1px;
}

.user-id {
  font-size: 0.72rem;
  margin-top: 2px;
}

.points-cell {
  font-size: 0.85rem;
  line-height: 1.35;
}

.points-sub {
  font-size: 0.72rem;
  white-space: nowrap;
}

.quota-token {
  display: block;
  font-size: 0.72rem;
}

.role-chip {
  height: 18px;
  font-size: 10px;
}

.users-table :deep(th) {
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
  color: var(--console-text-muted);
}

.tokens-cell {
  font-size: 0.85rem;
}

.quota-cell {
  color: var(--console-text-muted);
  font-size: 0.8rem;
}

.nowrap {
  white-space: nowrap;
}

.pager {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dialog-card {
  padding: 8px;
}

.dialog-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

.quota-user {
  margin-bottom: 10px;
  min-width: 0;
}

.quota-user__name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quota-user__email {
  font-size: 0.78rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quota-list {
  margin: 0;
}

.quota-list > div {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px dashed #eef1f4;
  font-size: 0.86rem;
}

.quota-list dt {
  color: var(--console-text-muted);
}

.quota-list dd {
  margin: 0;
}

.quota-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.quota-used {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--console-surface-variant);
  color: var(--console-text-muted);
  font-size: 12.5px;
}

.quota-used strong {
  color: var(--console-text);
  font-weight: 600;
}

.quota-note {
  margin: 12px 0 0;
  font-size: 0.76rem;
  line-height: 1.6;
}

@media (max-width: 599px) {
  .quota-form {
    grid-template-columns: 1fr;
  }
}
</style>
