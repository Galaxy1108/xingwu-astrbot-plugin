<template>
  <div>
    <PageHeader
      title="申诉处理"
      description="查看用户/Bot 封禁申诉，通过或拒绝并填写备注；处理结果会同步给用户。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
      </template>
    </PageHeader>

    <v-card class="filter-card mb-4">
      <form class="filter-row" @submit.prevent="load">
        <v-select
          v-model="statusFilter"
          :items="statusOptions"
          label="状态"
          hide-details
          density="compact"
          class="filter-status"
          @update:model-value="load"
        />
        <v-btn type="submit" color="primary" variant="tonal">筛选</v-btn>
        <v-btn variant="text" @click="resetFilter">重置</v-btn>
      </form>
    </v-card>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !appeals.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!error && appeals.length === 0"
      icon="mdi-gavel"
      title="暂无申诉"
      description="用户或 Bot 被封禁后提交的申诉会出现在这里。"
    />

    <v-card v-else-if="appeals.length" class="table-card">
      <div class="table-scroll">
        <v-table hover class="appeals-table">
          <thead>
            <tr>
              <th>对象</th>
              <th>用户</th>
              <th>申诉说明</th>
              <th>提交时间</th>
              <th>状态</th>
              <th>管理员备注</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="appeal in appeals" :key="String(appeal.id)" data-testid="appeal-row">
              <td class="nowrap">
                <v-chip size="small" variant="tonal" :color="appeal.target_type === 'bot' ? 'info' : 'primary'">
                  {{ appeal.target_type === 'bot' ? 'Bot' : '用户' }}
                </v-chip>
                <div class="text-mono text-muted target-id" :title="appeal.target_id || ''">
                  {{ appeal.target_name || appeal.target_id || '—' }}
                </div>
              </td>
              <td class="user-cell">
                <div class="user-email">{{ appeal.user_email || '—' }}</div>
                <div class="text-mono text-muted user-id">{{ appeal.user_id || '' }}</div>
              </td>
              <td class="reason-cell" :title="appeal.reason">{{ appeal.reason }}</td>
              <td class="nowrap">{{ formatDateTime(appeal.created_at) }}</td>
              <td>
                <v-chip :color="statusMeta(appeal.status).color" variant="tonal" size="small">
                  {{ statusMeta(appeal.status).label }}
                </v-chip>
              </td>
              <td class="note-cell" :title="appeal.note || ''">{{ appeal.note || '—' }}</td>
              <td class="text-right nowrap">
                <template v-if="appeal.status === 'pending'">
                  <v-btn size="small" variant="text" color="success" @click="openAction(appeal, 'approve')">
                    通过
                  </v-btn>
                  <v-btn size="small" variant="text" color="error" @click="openAction(appeal, 'reject')">
                    拒绝
                  </v-btn>
                </template>
                <span v-else class="text-muted">—</span>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
    </v-card>

    <ReasonDialog
      v-model="actionOpen"
      :title="action === 'approve' ? '通过该申诉？' : '拒绝该申诉？'"
      :message="
        action === 'approve'
          ? '通过后系统会按后端策略恢复对象状态；请确认已核实情况。'
          : '拒绝会保留当前状态；请填写说明，用户可在申诉历史中看到备注。'
      "
      label="管理员备注（可选）"
      placeholder="填写处理说明（可选）"
      :required="false"
      :danger="action === 'reject'"
      :confirm-text="action === 'approve' ? '通过申诉' : '拒绝申诉'"
      :loading="acting"
      @confirm="submitAction"
      @cancel="actionOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ReasonDialog from '@/components/ReasonDialog.vue'
import { useUiStore } from '@/stores/ui'
import { approveAppeal, listAdminAppeals, rejectAppeal } from '@/api/appeals'
import { toApiError } from '@/api/client'
import type { Appeal } from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'

const ui = useUiStore()

const appeals = ref<Appeal[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('pending')

const actionOpen = ref(false)
const action = ref<'approve' | 'reject'>('approve')
const actionTarget = ref<Appeal | null>(null)
const acting = ref(false)

const statusOptions = [
  { title: '待处理', value: 'pending' },
  { title: '已通过', value: 'approved' },
  { title: '已拒绝', value: 'rejected' },
  { title: '全部', value: '' },
]

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listAdminAppeals(statusFilter.value || undefined)
    appeals.value = result.items ?? []
  } catch (err) {
    const apiError = toApiError(err)
    error.value =
      apiError.status === 404 || apiError.status === 405
        ? '申诉接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载申诉失败')
  } finally {
    loading.value = false
  }
}

function resetFilter(): void {
  statusFilter.value = ''
  void load()
}

function statusMeta(status: string): { label: string; color: string } {
  if (status === 'approved') return { label: '已通过', color: 'success' }
  if (status === 'rejected') return { label: '已拒绝', color: 'error' }
  return { label: '待处理', color: 'warning' }
}

function openAction(appeal: Appeal, next: 'approve' | 'reject'): void {
  actionTarget.value = appeal
  action.value = next
  actionOpen.value = true
}

async function submitAction(note: string): Promise<void> {
  if (!actionTarget.value) return
  acting.value = true
  try {
    if (action.value === 'approve') {
      await approveAppeal(actionTarget.value.id, note)
      ui.notify('申诉已通过', 'success')
    } else {
      await rejectAppeal(actionTarget.value.id, note)
      ui.notify('申诉已拒绝', 'success')
    }
    actionOpen.value = false
    await load()
  } catch (err) {
    const apiError = toApiError(err)
    ui.notifyError(
      apiError.status === 404 || apiError.status === 405
        ? '申诉处理接口尚未就绪，请稍后重试。'
        : errorMessage(apiError, '处理申诉失败'),
    )
  } finally {
    acting.value = false
  }
}
</script>

<style scoped>
.filter-card {
  padding: 14px 16px;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-status {
  flex: 0 1 180px;
}

.table-card {
  padding: 4px 0;
}

.table-scroll {
  overflow-x: auto;
}

.appeals-table {
  min-width: 1000px;
}

.appeals-table :deep(th) {
  white-space: nowrap;
}

.nowrap {
  white-space: nowrap;
}

.target-id {
  margin-top: 2px;
  font-size: 0.72rem;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-cell {
  min-width: 180px;
}

.user-email {
  font-weight: 600;
}

.user-id {
  font-size: 0.7rem;
  margin-top: 2px;
}

.reason-cell {
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--console-text-muted);
  font-size: 0.83rem;
}

.note-cell {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--console-text-muted);
  font-size: 0.8rem;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
