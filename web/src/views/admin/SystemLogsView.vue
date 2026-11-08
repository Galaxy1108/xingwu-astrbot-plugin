<template>
  <div>
    <PageHeader title="系统日志" description="用户操作触发的服务端错误与后端运行日志；错误记录会自动脱敏。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
      </template>
    </PageHeader>

    <v-tabs v-model="tab" color="primary" density="comfortable" class="mb-4">
      <v-tab value="errors">错误记录</v-tab>
      <v-tab value="logs">运行日志</v-tab>
    </v-tabs>

    <template v-if="tab === 'errors'">
      <v-card class="filter-card mb-4">
        <div class="log-filters">
          <v-select
            v-model="level"
            :items="levelOptions"
            item-title="title"
            item-value="value"
            label="级别"
            density="compact"
            hide-details
            class="level-select"
            @update:model-value="reloadErrors"
          />
          <v-text-field
            v-model.trim="q"
            label="搜索路径 / 错误码 / 信息"
            density="compact"
            hide-details
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="reloadErrors"
          />
          <v-btn variant="tonal" color="primary" @click="reloadErrors">筛选</v-btn>
        </div>
      </v-card>

      <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
      <LoadingSkeleton v-if="loading && !items.length" variant="table" :rows="5" />
      <EmptyState
        v-else-if="!items.length"
        icon="mdi-shield-check-outline"
        title="暂无错误记录"
        description="用户操作触发的服务端错误会出现在这里。"
      />
      <v-card v-else class="table-card">
        <div class="table-scroll">
          <v-table hover density="comfortable">
            <thead>
              <tr>
                <th>时间</th>
                <th>级别</th>
                <th>状态</th>
                <th>路径</th>
                <th>错误码</th>
                <th>信息</th>
                <th class="text-right">详情</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="item in items" :key="item.id">
                <tr>
                  <td class="nowrap text-caption muted">{{ formatDateTime(item.created_at) }}</td>
                  <td><v-chip size="x-small" variant="tonal" :color="levelColor(item.level)">{{ item.level }}</v-chip></td>
                  <td>{{ item.status }}</td>
                  <td class="text-mono path-cell">{{ item.method }} {{ item.path }}</td>
                  <td class="text-mono">{{ item.code || '—' }}</td>
                  <td class="message-cell" :title="item.message">{{ item.message }}</td>
                  <td class="text-right">
                    <v-btn size="small" variant="text" @click="toggle(item.id)">
                      {{ expanded === item.id ? '收起' : '查看' }}
                    </v-btn>
                  </td>
                </tr>
                <tr v-if="expanded === item.id">
                  <td colspan="7" class="detail-cell">
                    <pre>{{ item.detail || '无堆栈详情' }}</pre>
                  </td>
                </tr>
              </template>
            </tbody>
          </v-table>
        </div>
        <div v-if="total > pageSize" class="pager">
          <v-pagination v-model="page" :length="pageCount" density="comfortable" @update:model-value="load" />
        </div>
      </v-card>
    </template>

    <template v-else>
      <v-card class="pa-4">
        <div class="log-filters mb-3">
          <v-select v-model="logLevel" :items="logLevels" label="级别" density="compact" hide-details class="level-select" @update:model-value="loadBackendLogs" />
          <v-btn variant="tonal" color="primary" prepend-icon="mdi-refresh" :loading="logsLoading" @click="loadBackendLogs">刷新</v-btn>
          <v-spacer />
          <span class="text-caption muted">最近 {{ logs.length }} 行 · 来自进程日志缓冲</span>
        </div>
        <v-alert v-if="!logsAvailable" type="info" variant="tonal" density="compact">
          日志缓冲尚未初始化（仅 AstrBot 进程内运行时可用）。
        </v-alert>
        <div v-else class="log-view">
          <div v-for="(line, index) in logs" :key="index" class="log-line" :class="`log-line--${line.level.toLowerCase()}`">
            <span class="log-time">{{ formatDateTime(line.time) }}</span>
            <span class="log-level">{{ line.level }}</span>
            <span class="log-source">{{ line.logger }}</span>
            <span class="log-message">{{ line.message }}</span>
          </div>
        </div>
      </v-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import { listBackendLogs, listErrorLogs, type BackendLogLine } from '@/api/admin'
import type { AdminErrorLog } from '@/types'
import { formatDateTime } from '@/utils/format'

const tab = ref<'errors' | 'logs'>('errors')
const loading = ref(false)
const error = ref('')
const items = ref<AdminErrorLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const level = ref('error')
const q = ref('')
const expanded = ref<number | null>(null)
const levelOptions = [
  { title: '错误', value: 'error' },
  { title: '警告', value: 'warning' },
  { title: '全部', value: '' },
]
const logs = ref<BackendLogLine[]>([])
const logsLoading = ref(false)
const logsAvailable = ref(true)
const logLevel = ref('')
const logLevels = [
  { title: '全部', value: '' },
  { title: 'ERROR', value: 'ERROR' },
  { title: 'WARNING', value: 'WARNING' },
  { title: 'INFO', value: 'INFO' },
]
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listErrorLogs(page.value, pageSize.value, {
      level: level.value || undefined,
      q: q.value || undefined,
    })
    items.value = result.items ?? []
    total.value = result.total ?? 0
  } catch (err) {
    error.value = (err as Error).message || '加载错误记录失败'
  } finally {
    loading.value = false
  }
  await loadBackendLogs()
}

function reloadErrors(): void {
  page.value = 1
  void load()
}

function toggle(id: number): void {
  expanded.value = expanded.value === id ? null : id
}

async function loadBackendLogs(): Promise<void> {
  logsLoading.value = true
  try {
    const result = await listBackendLogs(300, logLevel.value)
    logs.value = result.items ?? []
    logsAvailable.value = result.available !== false
  } catch {
    logsAvailable.value = false
    logs.value = []
  } finally {
    logsLoading.value = false
  }
}

function levelColor(value: string): string {
  return value === 'error' ? 'error' : value === 'warning' ? 'warning' : 'default'
}
</script>

<style scoped>
.log-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.level-select {
  max-width: 150px;
}
.path-cell {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.message-cell {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-cell {
  background: var(--console-surface-variant);
}
.detail-cell pre {
  margin: 0;
  max-height: 280px;
  overflow: auto;
  font-size: 11.5px;
  white-space: pre-wrap;
}
.table-scroll {
  overflow-x: auto;
}
.log-view {
  max-height: 620px;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.65;
}
.log-line {
  display: grid;
  grid-template-columns: 132px 58px 180px minmax(0, 1fr);
  gap: 10px;
  padding: 2px 4px;
  border-bottom: 1px solid var(--console-border);
}
.log-line--error {
  color: var(--console-danger);
}
.log-line--warning {
  color: #d69e2e;
}
.log-time {
  color: var(--console-text-muted);
}
.log-source {
  color: var(--console-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
}
.log-message {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
@media (max-width: 959px) {
  .log-line {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}
</style>
