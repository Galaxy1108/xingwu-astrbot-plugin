<template>
  <div>
    <PageHeader title="用户管理" description="查看用户状态、配额与加密状态；禁用会立即撤销会话并停用其全部 Bot。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="admin.usersLoading" @click="reload">
          刷新
        </v-btn>
      </template>
    </PageHeader>

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
        <v-table hover>
          <thead>
            <tr>
              <th>邮箱</th>
              <th>角色</th>
              <th>状态</th>
              <th>Bot 数</th>
              <th>配额</th>
              <th>加密</th>
              <th>创建时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in admin.users" :key="user.id">
              <td>
                <div class="user-email">{{ user.email }}</div>
                <div class="text-mono text-muted user-id">{{ user.id }}</div>
              </td>
              <td>{{ user.role === 'admin' ? '管理员' : '用户' }}</td>
              <td><StatusChip :status="user.status" kind="user" /></td>
              <td>{{ user.bot_count ?? '—' }}</td>
              <td class="nowrap quota-cell">
                Bot {{ user.quota?.max_bots ?? '—' }} · Token {{ formatNumber(user.quota?.monthly_tokens) }}
              </td>
              <td>
                <StatusChip :status="user.encryption?.state || 'encrypted'" kind="encryption" />
              </td>
              <td class="nowrap">{{ formatDateTime(user.created_at) }}</td>
              <td class="text-right nowrap">
                <v-btn size="small" variant="text" @click="showQuota(user)">配额</v-btn>
                <v-btn
                  v-if="user.status === 'active'"
                  size="small"
                  variant="text"
                  color="error"
                  @click="askToggle(user, 'disabled')"
                >
                  禁用
                </v-btn>
                <v-btn
                  v-else
                  size="small"
                  variant="text"
                  color="success"
                  @click="askToggle(user, 'active')"
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
        <v-card-title class="dialog-title">配额 · {{ quotaUser?.email }}</v-card-title>
        <v-card-text>
          <dl class="quota-list">
            <div><dt>Bot 上限</dt><dd>{{ quotaUser?.quota?.max_bots ?? '—' }}</dd></div>
            <div><dt>记忆条数上限</dt><dd>{{ formatNumber(quotaUser?.quota?.max_memories) }}</dd></div>
            <div><dt>每月 Token</dt><dd>{{ formatNumber(quotaUser?.quota?.monthly_tokens) }}</dd></div>
            <div><dt>当前 Bot 数</dt><dd>{{ quotaUser?.bot_count ?? '—' }}</dd></div>
            <div><dt>余额</dt><dd>{{ formatNumber(quotaUser?.balance) }}</dd></div>
          </dl>
          <p class="text-muted quota-note">
            M1 仅查看；配额修改接口已预留（PATCH /api/admin/users/{id}），后续版本开放编辑。
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="quotaOpen = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="toggleOpen"
      :title="toggleTarget?.status === 'active' ? '禁用该用户？' : '启用该用户？'"
      :message="
        toggleTarget?.status === 'active'
          ? '禁用会立即撤销该用户的全部会话，并停用其全部 Bot；该操作会写入审计日志。'
          : '启用后该用户可以重新登录；其 Bot 不会自动启用。'
      "
      :confirm-text="toggleTarget?.status === 'active' ? '禁用用户' : '启用用户'"
      :danger="toggleTarget?.status === 'active'"
      :loading="toggling"
      @confirm="confirmToggle"
      @cancel="toggleOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useAdminStore } from '@/stores/admin'
import { useUiStore } from '@/stores/ui'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatNumber } from '@/utils/format'
import type { AdminUser } from '@/types'

const admin = useAdminStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const search = ref('')
const statusFilter = ref('')
const currentPage = ref(1)

const statusOptions = [
  { title: '全部状态', value: '' },
  { title: '正常', value: 'active' },
  { title: '已禁用', value: 'disabled' },
]

const quotaOpen = ref(false)
const quotaUser = ref<AdminUser | null>(null)

const toggleOpen = ref(false)
const toggleTarget = ref<AdminUser | null>(null)
const toggling = ref(false)

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

function showQuota(user: AdminUser): void {
  quotaUser.value = user
  quotaOpen.value = true
}

function askToggle(user: AdminUser, target: 'active' | 'disabled'): void {
  toggleTarget.value = target === 'disabled' ? user : { ...user, status: 'disabled' }
  toggleOpen.value = true
}

async function confirmToggle(): Promise<void> {
  if (!toggleTarget.value) return
  const nextStatus = toggleTarget.value.status === 'active' ? 'disabled' : 'active'
  toggling.value = true
  try {
    await admin.setUserStatus(toggleTarget.value.id, nextStatus)
    toggleOpen.value = false
    ui.notify(nextStatus === 'disabled' ? '用户已禁用' : '用户已启用', 'success')
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

.user-email {
  font-weight: 600;
}

.user-id {
  font-size: 0.72rem;
  margin-top: 2px;
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
  overflow-wrap: anywhere;
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

.quota-note {
  margin: 12px 0 0;
  font-size: 0.76rem;
  line-height: 1.6;
}
</style>
