<template>
  <div>
    <PageHeader title="审计日志" description="全部管理操作与内容访问的留痕；筛选条件与分页保留在 URL。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="admin.auditLoading" @click="reload">
          刷新
        </v-btn>
      </template>
    </PageHeader>

    <v-card class="filter-card mb-4">
      <form class="filter-row" @submit.prevent="applyFilters">
        <v-text-field
          v-model.trim="actionFilter"
          label="动作（action）"
          prepend-inner-icon="mdi-tag-outline"
          hide-details
          density="compact"
          class="filter-field"
        />
        <v-text-field
          v-model.trim="actorFilter"
          label="操作者 ID"
          hide-details
          density="compact"
          class="filter-field"
        />
        <v-text-field
          v-model.trim="targetFilter"
          label="对象 ID"
          hide-details
          density="compact"
          class="filter-field"
        />
        <v-btn type="submit" color="primary" variant="tonal">筛选</v-btn>
        <v-btn variant="text" @click="resetFilters">重置</v-btn>
      </form>
    </v-card>

    <v-alert v-if="admin.auditError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ admin.auditError.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="admin.auditLoading && !admin.audit.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!admin.auditError && admin.audit.length === 0"
      icon="mdi-clipboard-text-clock-outline"
      title="暂无审计记录"
      description="管理操作（模板变更、用户禁用、Bot 禁用、内容访问等）会记录在这里。"
    />

    <v-card v-else-if="admin.audit.length" class="table-card">
      <div class="table-scroll">
        <v-table hover class="audit-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>操作者</th>
              <th>动作</th>
              <th>对象</th>
              <th>IP</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in admin.audit" :key="String(log.id)">
              <td class="nowrap">{{ formatDateTime(log.created_at) }}</td>
              <td>
                <div class="text-mono actor">{{ log.actor_id || '—' }}</div>
                <div class="text-muted actor-role">{{ log.actor_role || '—' }}</div>
              </td>
              <td class="nowrap action">{{ log.action || '—' }}</td>
              <td class="nowrap">
                {{ log.target_type || '—' }}
                <span v-if="log.target_id" class="text-mono text-muted"> · {{ shortId(log.target_id) }}</span>
              </td>
              <td class="text-mono">{{ log.ip || '—' }}</td>
              <td class="detail-cell" :title="detailText(log.detail)">{{ detailText(log.detail) }}</td>
            </tr>
          </tbody>
        </v-table>
      </div>

      <div v-if="admin.auditTotal > admin.auditPageSize" class="pager">
        <v-pagination
          :model-value="currentPage"
          :length="pageCount"
          :total-visible="5"
          density="comfortable"
          @update:model-value="onPage"
        />
      </div>
    </v-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useAdminStore } from '@/stores/admin'
import { formatDateTime, shortId, truncate } from '@/utils/format'

const admin = useAdminStore()
const route = useRoute()
const router = useRouter()

const actionFilter = ref('')
const actorFilter = ref('')
const targetFilter = ref('')
const currentPage = ref(1)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(admin.auditTotal / Math.max(1, admin.auditPageSize))),
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
  actionFilter.value = stringQuery(route.query.action)
  actorFilter.value = stringQuery(route.query.actor_id)
  targetFilter.value = stringQuery(route.query.target_id)
  const parsed = Number(stringQuery(route.query.page))
  currentPage.value = Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  try {
    await admin.loadAudit({
      page: currentPage.value,
      page_size: 20,
      action: actionFilter.value || undefined,
      actor_id: actorFilter.value || undefined,
      target_id: targetFilter.value || undefined,
    })
  } catch {
    /* store 已记录 */
  }
}

async function applyFilters(): Promise<void> {
  const query: Record<string, string> = {}
  if (actionFilter.value) query.action = actionFilter.value
  if (actorFilter.value) query.actor_id = actorFilter.value
  if (targetFilter.value) query.target_id = targetFilter.value
  await router.replace({ query })
}

async function resetFilters(): Promise<void> {
  actionFilter.value = ''
  actorFilter.value = ''
  targetFilter.value = ''
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

function detailText(detail: unknown): string {
  if (detail === null || detail === undefined || detail === '') return '—'
  if (typeof detail === 'string') return truncate(detail, 100)
  try {
    return truncate(JSON.stringify(detail), 100)
  } catch {
    return '—'
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

.filter-field {
  flex: 1 1 160px;
  min-width: 150px;
}

.table-card {
  padding: 4px 0;
}

.audit-table {
  min-width: 1000px;
}

.audit-table :deep(th) {
  white-space: nowrap;
}

.table-scroll {
  overflow-x: auto;
}

.nowrap {
  white-space: nowrap;
}

.actor {
  font-size: 0.78rem;
}

.actor-role {
  font-size: 0.72rem;
}

.action {
  font-weight: 500;
}

.detail-cell {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--console-text-muted);
  font-size: 0.78rem;
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
</style>
