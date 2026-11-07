<template>
  <div class="access-log-table">
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">
      <div class="error-row">
        <span>{{ error.message || '加载访问记录失败' }}</span>
        <v-btn size="small" variant="text" color="error" @click="$emit('retry')">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-else-if="loading" variant="table" :rows="4" />

    <EmptyState
      v-else-if="!items.length"
      icon="mdi-file-eye-outline"
      title="暂无访问记录"
      description="管理员查看对话或记忆内容时会在这里留痕。M1 阶段记录为空，后续版本提供明细。"
    />

    <template v-else>
      <div class="table-scroll">
        <v-table class="access-table" hover>
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
            <tr v-for="item in items" :key="String(item.id)">
              <td class="nowrap">{{ formatDateTime(item.created_at) }}</td>
              <td>{{ actorLabel(item) }}</td>
              <td>{{ actionLabel(item) }}</td>
              <td class="nowrap">{{ targetLabel(item) }}</td>
              <td class="text-mono">{{ item.ip || '—' }}</td>
              <td class="detail-cell" :title="detailText(item.detail, item.reason)">{{ detailText(item.detail, item.reason) }}</td>
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
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import EmptyState from './EmptyState.vue'
import LoadingSkeleton from './LoadingSkeleton.vue'
import type { ApiError } from '@/api/client'
import type { AccessLogEntry } from '@/types'
import { formatDateTime, shortId, truncate } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    items: AccessLogEntry[]
    loading?: boolean
    error?: ApiError | null
    page?: number
    pageSize?: number
    total?: number
  }>(),
  { loading: false, error: null, page: 1, pageSize: 20, total: 0 },
)

const emit = defineEmits<{
  retry: []
  'update:page': [page: number]
}>()

const pageCount = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, props.pageSize))))

function actorLabel(item: AccessLogEntry): string {
  return item.actor_name || item.actor_email || item.actor_id || item.admin_id || '—'
}

function actionLabel(item: AccessLogEntry): string {
  if (item.action) return item.action
  const labels: Record<string, string> = {
    conversation: '查看对话',
    memory: '查看记忆',
    memory_export: '导出记忆',
    memory_import: '导入记忆',
  }
  return item.resource ? labels[item.resource] ?? item.resource : '—'
}

function targetLabel(item: AccessLogEntry): string {
  if (item.bot_name) return `Bot · ${item.bot_name}`
  const type = item.target_type || item.resource || ''
  const id = item.target_id || item.resource_id || item.bot_id || ''
  if (!type && !id) return '—'
  return type ? `${type}${id ? ` · ${shortId(id)}` : ''}` : shortId(id)
}

function detailText(detail: unknown, reason?: string): string {
  if (reason === 'confirmed_encrypted') return '加密内容 · 已确认解密查看'
  if (detail === null || detail === undefined || detail === '') return '—'
  if (typeof detail === 'string') return truncate(detail, 80)
  try {
    return truncate(JSON.stringify(detail), 80)
  } catch {
    return '—'
  }
}

function onPage(page: number): void {
  emit('update:page', page)
}
</script>

<style scoped>
.table-scroll {
  overflow-x: auto;
}

.access-table {
  min-width: 640px;
}

.nowrap {
  white-space: nowrap;
}

.detail-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--console-text-muted);
  font-size: 0.8rem;
}

.error-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
