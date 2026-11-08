<template>
  <div>
    <PageHeader
      :title="pageTitle"
      description="记忆由对话自动记录（LLM 工具/命令），本页管理已有记忆，不提供手动新建入口。"
      :back-to="`/bots/${botId}`"
    />

    <BotTabs :bot-id="botId" active="memory" />

    <div class="content-toolbar">
      <span class="text-muted toolbar-hint">记忆由对话自动记录，可导入/导出快照</span>
      <v-spacer />
      <v-btn variant="text" size="small" prepend-icon="mdi-magnify" @click="openSearch">检索预览</v-btn>
      <v-btn
        size="small"
        variant="tonal"
        color="primary"
        prepend-icon="mdi-upload"
        data-testid="memory-import"
        @click="openImport"
      >
        导入 JSON 快照
      </v-btn>
      <v-btn
        size="small"
        variant="tonal"
        color="primary"
        prepend-icon="mdi-download"
        data-testid="memory-export"
        @click="onExport"
      >
        导出 JSON
      </v-btn>
      <v-btn size="small" variant="text" prepend-icon="mdi-refresh" :loading="bucket.loading" @click="reload">
        刷新
      </v-btn>
    </div>

    <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-brain">
      记忆由对话自动记录；可导入/导出 JSON 快照（含记忆与笔记，导入按内容去重）。
      重要度为 6 的记忆会在每条对话中<strong>始终注入</strong>；自动提取的记忆带「自动提取」标签。
    </v-alert>

    <v-card class="filter-card mb-4">
      <form class="filter-row" @submit.prevent="applyFilters">
        <v-text-field
          v-model.trim="filters.q"
          label="关键字"
          prepend-inner-icon="mdi-magnify"
          hide-details
          density="compact"
          class="filter-search"
        />
        <v-select
          v-model="filters.kind"
          :items="kindFilterOptions"
          label="类型"
          hide-details
          density="compact"
          class="filter-select"
          @update:model-value="applyFilters"
        />
        <v-text-field
          v-model.trim="filters.tag"
          label="标签（单值）"
          hide-details
          density="compact"
          class="filter-select"
        />
        <v-select
          v-model="filters.importance"
          :items="importanceFilterOptions"
          label="重要度"
          hide-details
          density="compact"
          class="filter-select"
          @update:model-value="applyFilters"
        />
        <v-btn type="submit" color="primary" variant="tonal">筛选</v-btn>
        <v-btn variant="text" @click="resetFilters">重置</v-btn>
      </form>
    </v-card>

    <v-alert v-if="bucket.error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ bucket.error.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-else-if="bucket.loading && !bucket.loaded" variant="table" :rows="5" />

    <EmptyState
      v-else-if="bucket.items.length === 0"
      icon="mdi-brain"
      :title="hasFilters ? '没有符合条件的记忆' : '还没有记忆'"
      :description="
        hasFilters
          ? '尝试调整关键字、类型或标签；也可以清空筛选查看全部记忆。'
          : '当 Bot 在对话中通过 LLM 工具记录事实、偏好或事件后，会出现在这里。'
      "
      :actions="
        hasFilters
          ? [{ label: '清空筛选', onClick: resetFilters }]
          : [{ label: '检索预览', variant: 'tonal', onClick: openSearch }]
      "
    />

    <template v-else>
      <v-card v-if="!isNarrow" class="table-card">
        <div class="table-head">
          <div class="table-head__count text-muted">
            共 {{ bucket.total }} 条<template v-if="filters.tag"> · 标签：{{ filters.tag }}</template>
            · 当前第 {{ bucket.page }} 页
          </div>
          <div class="text-muted table-head__hint">置顶记忆排在前面</div>
        </div>
        <div class="table-scroll">
          <v-table hover>
            <thead>
              <tr>
                <th>内容</th>
                <th>类型</th>
                <th>重要度</th>
                <th>标签</th>
                <th>召回</th>
                <th>更新时间</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="memory in bucket.items" :key="memory.id" data-testid="memory-row">
                <td class="content-cell">
                  <div class="content-line">
                    <v-icon
                      v-if="memory.pinned"
                      color="warning"
                      size="16"
                      title="已置顶"
                      aria-label="已置顶"
                    >
                      mdi-pin
                    </v-icon>
                    <span class="content-text">{{ truncate(memory.content, 120) }}</span>
                    <v-chip
                      v-if="isAutoExtracted(memory)"
                      size="x-small"
                      variant="tonal"
                      color="info"
                    >
                      自动提取
                    </v-chip>
                  </div>
                  <div v-if="memory.reasoning" class="content-reason text-muted">
                    {{ truncate(memory.reasoning, 100) }}
                  </div>
                </td>
                <td>
                  <v-chip
                    :color="kindColor(memory.kind)"
                    :prepend-icon="kindIcon(memory.kind)"
                    variant="tonal"
                    size="small"
                  >
                    {{ memory.kind_label || kindLabel(memory.kind) }}
                  </v-chip>
                </td>
                <td class="nowrap">
                  <v-chip
                    v-if="memory.importance >= 6"
                    size="x-small"
                    variant="tonal"
                    color="error"
                    :title="importanceText(memory.importance)"
                  >
                    总是注入
                  </v-chip>
                  <span v-else class="importance" :title="`重要度 ${memory.importance}/6`">
                    ★ {{ memory.importance }}/6
                  </span>
                </td>
                <td class="tags-cell">
                  <template v-if="memory.tags.length">
                    <v-chip
                      v-for="tag in memory.tags"
                      :key="tag"
                      size="x-small"
                      variant="outlined"
                      class="tag-chip"
                    >
                      {{ tag }}
                    </v-chip>
                  </template>
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="nowrap recall-cell">
                  {{ memory.recall_count }} 次
                  <div v-if="memory.last_recalled_at" class="text-muted recall-time">
                    {{ formatRelative(memory.last_recalled_at) }}
                  </div>
                </td>
                <td class="nowrap">{{ formatDateTime(memory.updated_at) }}</td>
                <td class="text-right nowrap">
                  <v-btn
                    icon
                    size="small"
                    variant="text"
                    :title="memory.pinned ? '取消置顶' : '置顶'"
                    :aria-label="memory.pinned ? '取消置顶' : '置顶'"
                    data-testid="memory-pin"
                    @click="togglePin(memory)"
                  >
                    <v-icon size="18">{{ memory.pinned ? 'mdi-pin-off' : 'mdi-pin-outline' }}</v-icon>
                  </v-btn>
                  <v-btn
                    icon
                    size="small"
                    variant="text"
                    title="编辑"
                    aria-label="编辑"
                    data-testid="memory-edit"
                    @click="openEdit(memory)"
                  >
                    <v-icon size="18">mdi-pencil-outline</v-icon>
                  </v-btn>
                  <v-btn
                    icon
                    size="small"
                    variant="text"
                    color="error"
                    title="删除"
                    aria-label="删除"
                    data-testid="memory-delete"
                    @click="askDelete(memory)"
                  >
                    <v-icon size="18">mdi-delete-outline</v-icon>
                  </v-btn>
                </td>
              </tr>
            </tbody>
          </v-table>
        </div>
      </v-card>

      <div v-else class="memory-cards">
        <v-card
          v-for="memory in bucket.items"
          :key="memory.id"
          class="memory-card"
          data-testid="memory-card"
        >
          <div class="memory-card__head">
            <v-chip
              :color="kindColor(memory.kind)"
              :prepend-icon="kindIcon(memory.kind)"
              variant="tonal"
              size="small"
            >
              {{ memory.kind_label || kindLabel(memory.kind) }}
            </v-chip>
            <v-chip
              v-if="isAutoExtracted(memory)"
              size="x-small"
              variant="tonal"
              color="info"
            >
              自动提取
            </v-chip>
            <v-icon v-if="memory.pinned" color="warning" size="18" title="已置顶">mdi-pin</v-icon>
            <v-spacer />
            <span v-if="memory.importance >= 6" class="importance importance--inject">总是注入</span>
            <span v-else class="importance">★ {{ memory.importance }}/6</span>
          </div>
          <p class="memory-card__content">{{ memory.content }}</p>
          <p v-if="memory.reasoning" class="memory-card__reason text-muted">
            {{ memory.reasoning }}
          </p>
          <div v-if="memory.tags.length" class="memory-card__tags">
            <v-chip v-for="tag in memory.tags" :key="tag" size="x-small" variant="outlined">
              {{ tag }}
            </v-chip>
          </div>
          <div class="memory-card__meta text-muted">
            <span>召回 {{ memory.recall_count }} 次</span>
            <span>更新 {{ formatRelative(memory.updated_at) }}</span>
          </div>
          <div class="memory-card__actions">
            <v-btn size="small" variant="outlined" @click="openEdit(memory)">编辑</v-btn>
            <v-btn size="small" variant="text" @click="togglePin(memory)">
              {{ memory.pinned ? '取消置顶' : '置顶' }}
            </v-btn>
            <v-spacer />
            <v-btn size="small" variant="text" color="error" @click="askDelete(memory)">删除</v-btn>
          </div>
        </v-card>
      </div>

      <div v-if="bucket.total > bucket.pageSize" class="pager">
        <v-pagination
          :model-value="bucket.page"
          :length="pageCount"
          :total-visible="5"
          density="comfortable"
          @update:model-value="onPage"
        />
      </div>
    </template>

    <v-navigation-drawer
      v-if="editorOpen"
      v-model="editorOpen"
      location="right"
      temporary
      :width="isNarrow ? 360 : 480"
      class="memory-drawer"
    >
      <div class="drawer-inner">
        <div class="drawer-head">
          <h2 class="drawer-title">
            编辑记忆 <span class="text-muted text-mono">#{{ editingId }}</span>
          </h2>
          <v-btn icon variant="text" aria-label="关闭" @click="editorOpen = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>

        <div class="drawer-body">
          <v-alert v-if="editorError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ editorError }}
          </v-alert>
          <v-textarea
            v-model="editor.content"
            label="内容"
            rows="5"
            auto-grow
            counter="4000"
            maxlength="4000"
            class="mb-2"
          />
          <v-select
            v-model="editor.kind"
            :items="kindEditOptions"
            label="类型"
            class="mb-2"
          />
          <v-select
            v-model="editor.importance"
            :items="memoryImportanceOptions"
            label="重要度"
            class="mb-2"
          />
          <v-switch v-model="editor.pinned" label="置顶（列表优先展示）" color="primary" />
          <v-text-field
            v-model="editor.tags"
            label="标签（逗号分隔，保存时全量替换）"
            class="mb-2"
          />
          <v-textarea
            v-model="editor.reasoning"
            label="推理 / 来源说明"
            rows="3"
            auto-grow
            class="mb-2"
          />
          <v-textarea
            v-model="editor.metadataText"
            label="metadata（JSON 对象，全量替换）"
            rows="4"
            auto-grow
            :error-messages="metadataError"
          />
          <p class="drawer-hint text-muted">
            保存为 PATCH 部分更新；tags 与 metadata 会以本次提交的内容全量替换。
          </p>
        </div>

        <div class="drawer-actions">
          <v-btn variant="text" :disabled="saving" @click="editorOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="saving" data-testid="memory-save" @click="saveEditor" variant="tonal">
            保存
          </v-btn>
        </div>
      </div>
    </v-navigation-drawer>

    <v-dialog v-model="searchOpen" max-width="720" scrollable>
      <v-card class="search-dialog">
        <v-card-title class="search-title">检索预览（服务端 FTS）</v-card-title>
        <v-card-text>
          <div class="search-row">
            <v-text-field
              v-model.trim="searchQuery"
              label="关键词"
              hide-details
              density="compact"
              class="search-input"
              @keyup.enter="runSearch"
            />
            <v-select
              v-model="searchKind"
              :items="kindFilterOptions"
              label="类型"
              hide-details
              density="compact"
              class="search-kind"
            />
            <v-select
              v-model="searchLimit"
              :items="[5, 10, 20, 50]"
              label="条数"
              hide-details
              density="compact"
              class="search-limit"
            />
            <v-btn color="primary" :loading="searchLoading" @click="runSearch" variant="tonal">检索</v-btn>
          </div>

          <v-alert v-if="searchError" type="error" variant="tonal" density="compact" class="mt-3">
            {{ searchError }}
          </v-alert>

          <p v-if="searchDone && !searchError" class="search-summary text-muted">
            命中 {{ searchTotal }} 条，显示 {{ searchResults.length }} 条
          </p>

          <v-list v-if="searchResults.length" density="comfortable" class="search-list">
            <v-list-item
              v-for="memory in searchResults"
              :key="memory.id"
              :title="truncate(memory.content, 80)"
              :subtitle="`${memory.kind_label || kindLabel(memory.kind)} · 重要度 ${memory.importance}/6 · 召回 ${memory.recall_count} 次`"
            >
              <template #prepend>
                <v-chip
                  :color="kindColor(memory.kind)"
                  variant="tonal"
                  size="small"
                  class="mr-2"
                >
                  {{ memory.kind_label || kindLabel(memory.kind) }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
          <EmptyState
            v-else-if="searchDone && !searchError"
            icon="mdi-magnify-close"
            title="没有命中"
            description="换一个关键词，或调整类型筛选。"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="searchOpen = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="importOpen" max-width="560" persistent>
      <v-card class="import-card">
        <v-card-title class="dialog-title">导入 JSON 快照</v-card-title>
        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-3">
            快照由本页导出生成，包含记忆与笔记；导入按内容去重，可重复执行。
          </v-alert>
          <v-alert v-if="importError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ importError }}
          </v-alert>
          <v-file-input
            v-model="importFile"
            label="选择 JSON 快照"
            accept=".json,application/json"
            prepend-icon="mdi-paperclip"
            density="compact"
            show-size
            class="mb-2"
            @update:model-value="onImportFileChange"
          />
          <v-checkbox
            v-model="importDryRun"
            label="仅预检（dry-run，不写入）"
            density="compact"
            hide-details
          />
          <v-alert
            v-if="importReport"
            :type="importReport.dry_run ? 'info' : 'success'"
            variant="tonal"
            density="compact"
            class="mt-3"
            data-testid="memory-import-report"
          >
            <div>
              记忆：导入 {{ importReport.memories.imported }} · 跳过 {{ importReport.memories.skipped }} ·
              失败 {{ importReport.memories.failed }}
            </div>
            <div>
              笔记：导入 {{ importReport.notes.imported }} · 跳过 {{ importReport.notes.skipped }} ·
              失败 {{ importReport.notes.failed }}
            </div>
            <div v-if="importReport.dry_run" class="mt-1">当前为预检结果，未写入任何数据。</div>
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="importing" @click="importOpen = false">关闭</v-btn>
          <v-btn
            color="primary"
            variant="tonal"
            :loading="importing"
            data-testid="memory-import-submit"
            @click="submitImport"
          >
            开始导入
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="deleteOpen"
      title="删除这条记忆？"
      :message="`删除后该记忆不再参与检索与回复，操作不可恢复。\n\n${truncate(deleteTarget?.content || '', 120)}`"
      confirm-text="删除记忆"
      danger
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="deleteOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import PageHeader from '@/components/PageHeader.vue'
import BotTabs from '@/components/BotTabs.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useBotsStore } from '@/stores/bots'
import { useMemoryStore } from '@/stores/memory'
import { importMemories } from '@/api/memory'
import { useUiStore } from '@/stores/ui'
import { useMemoryKindMeta } from '@/composables/useMemoryKindMeta'
import { importanceColor, importanceText, isAutoExtracted, memoryImportanceOptions } from '@/utils/memoryMeta'
import { downloadJson } from '@/utils/download'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatRelative, truncate } from '@/utils/format'
import type { MemoryImportReport, MemoryItem, MemoryKind, MemoryPatch } from '@/types'

const route = useRoute()
const router = useRouter()
const bots = useBotsStore()
const memory = useMemoryStore()
const ui = useUiStore()
const { smAndDown } = useDisplay()
const { kindColor, kindIcon, kindLabel } = useMemoryKindMeta()

const botId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const isNarrow = computed(() => smAndDown.value)

const pageSize = 20

const bucket = computed(() => memory.bucket(botId.value))
const bot = computed(() => (bots.current?.id === botId.value ? bots.current : null))
const pageTitle = computed(() => (bot.value ? `${bot.value.name} · 记忆` : '记忆'))
const pageCount = computed(() => Math.max(1, Math.ceil(bucket.value.total / Math.max(1, bucket.value.pageSize))))

const filters = reactive({ kind: '', tag: '', q: '', importance: '' })
const hasFilters = computed(() =>
  Boolean(filters.kind || filters.tag || filters.q || filters.importance),
)

const kindFilterOptions = [
  { title: '全部类型', value: '' },
  { title: '事实', value: 'fact' },
  { title: '偏好', value: 'preference' },
  { title: '事件', value: 'event' },
  { title: '笔记', value: 'note' },
]
const kindEditOptions = kindFilterOptions.slice(1)
const importanceFilterOptions = [
  { title: '全部重要度', value: '' },
  ...memoryImportanceOptions.map((option) => ({ title: option.title, value: String(option.value) })),
]

const exporting = ref(false)
const importOpen = ref(false)
const importFile = ref<File | File[] | null>(null)
const importDryRun = ref(false)
const importing = ref(false)
const importError = ref('')
const importReport = ref<MemoryImportReport | null>(null)
let pendingSnapshot: Record<string, unknown> | null = null

const editorOpen = ref(false)
const editingId = ref<number | null>(null)
const editorError = ref('')
const metadataError = ref('')
const saving = ref(false)
const editor = reactive({
  content: '',
  kind: 'fact' as MemoryKind,
  reasoning: '',
  importance: 3,
  pinned: false,
  tags: '',
  metadataText: '{}',
})

const deleteOpen = ref(false)
const deleteTarget = ref<MemoryItem | null>(null)
const deleting = ref(false)

const searchOpen = ref(false)
const searchQuery = ref('')
const searchKind = ref('')
const searchLimit = ref(10)
const searchLoading = ref(false)
const searchError = ref('')
const searchDone = ref(false)
const searchResults = ref<MemoryItem[]>([])
const searchTotal = ref(0)

watch(
  () => route.query,
  () => {
    syncFromQuery()
    void load()
  },
  { immediate: true },
)

onMounted(() => {
  void loadBotInfo()
})

function stringQuery(value: unknown): string {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' ? raw : ''
}

function readPage(): number {
  const parsed = Number(stringQuery(route.query.page))
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

function syncFromQuery(): void {
  filters.kind = stringQuery(route.query.kind)
  filters.tag = stringQuery(route.query.tag)
  filters.q = stringQuery(route.query.q)
  filters.importance = stringQuery(route.query.importance)
}

async function loadBotInfo(): Promise<void> {
  if (!botId.value) return
  try {
    await bots.loadBot(botId.value)
  } catch {
    /* 页头降级为通用标题；错误由 store 记录 */
  }
}

async function load(): Promise<void> {
  if (!botId.value) return
  try {
    await memory.fetchList(botId.value, {
      page: readPage(),
      page_size: pageSize,
      kind: filters.kind || undefined,
      tag: filters.tag || undefined,
      q: filters.q || undefined,
      importance: filters.importance || undefined,
    })
  } catch {
    /* 错误已写入 bucket，页面展示重试 */
  }
}

async function reload(): Promise<void> {
  await load()
}

async function applyFilters(): Promise<void> {
  const query: Record<string, string> = {}
  if (filters.q) query.q = filters.q
  if (filters.kind) query.kind = filters.kind
  if (filters.tag) query.tag = filters.tag
  if (filters.importance) query.importance = filters.importance
  await router.replace({ query })
}

async function resetFilters(): Promise<void> {
  filters.q = ''
  filters.kind = ''
  filters.tag = ''
  filters.importance = ''
  await router.replace({ query: {} })
}

async function onPage(page: number): Promise<void> {
  await router.replace({ query: { ...route.query, page: String(page) } })
}

function openEdit(item: MemoryItem): void {
  editingId.value = item.id
  editor.content = item.content
  editor.kind = item.kind
  editor.reasoning = item.reasoning || ''
  editor.importance = item.importance || 3
  editor.pinned = Boolean(item.pinned)
  editor.tags = (item.tags || []).join(', ')
  editor.metadataText = JSON.stringify(item.metadata ?? {}, null, 2)
  editorError.value = ''
  metadataError.value = ''
  editorOpen.value = true
}

async function saveEditor(): Promise<void> {
  if (!botId.value || editingId.value === null) return
  editorError.value = ''
  metadataError.value = ''
  const content = editor.content.trim()
  if (!content) {
    editorError.value = '记忆内容不能为空'
    return
  }
  if (content.length > 4000) {
    editorError.value = '记忆内容最多 4000 个字符'
    return
  }

  let metadata: Record<string, unknown> = {}
  if (editor.metadataText.trim()) {
    try {
      const parsed = JSON.parse(editor.metadataText) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        metadataError.value = 'metadata 必须是 JSON 对象'
        return
      }
      metadata = parsed as Record<string, unknown>
    } catch {
      metadataError.value = 'metadata 不是合法的 JSON'
      return
    }
  }

  const payload: MemoryPatch = {
    content,
    kind: editor.kind,
    reasoning: editor.reasoning.trim(),
    importance: editor.importance,
    pinned: editor.pinned,
    tags: editor.tags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean),
    metadata,
  }

  saving.value = true
  try {
    await memory.updateMemory(botId.value, editingId.value, payload)
    editorOpen.value = false
    ui.notify('记忆已保存', 'success')
    await load()
  } catch (error) {
    editorError.value = errorMessage(error, '保存记忆失败')
  } finally {
    saving.value = false
  }
}

async function togglePin(item: MemoryItem): Promise<void> {
  if (!botId.value) return
  try {
    await memory.updateMemory(botId.value, item.id, { pinned: !item.pinned })
    ui.notify(item.pinned ? '已取消置顶' : '已置顶', 'success')
  } catch (error) {
    ui.notifyError(errorMessage(error, '更新置顶状态失败'))
  }
}

function askDelete(item: MemoryItem): void {
  deleteTarget.value = item
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!botId.value || !deleteTarget.value) return
  deleting.value = true
  try {
    await memory.deleteMemory(botId.value, deleteTarget.value.id)
    deleteOpen.value = false
    ui.notify('记忆已删除', 'success')
    if (bucket.value.items.length === 0 && bucket.value.page > 1) {
      await router.replace({ query: { ...route.query, page: String(bucket.value.page - 1) } })
    } else {
      await load()
    }
  } catch (error) {
    deleteOpen.value = false
    ui.notifyError(errorMessage(error, '删除记忆失败'))
  } finally {
    deleting.value = false
  }
}

async function onExport(): Promise<void> {
  if (!botId.value) return
  exporting.value = true
  try {
    const result = await memory.exportAll(botId.value)
    downloadJson(`memories-${botId.value}-snapshot.json`, result)
    ui.notify(`已导出 ${result.count} 条记忆（含笔记快照）`, 'success')
  } catch (error) {
    ui.notifyError(errorMessage(error, '导出记忆失败'))
  } finally {
    exporting.value = false
  }
}

function openImport(): void {
  importFile.value = null
  importDryRun.value = false
  importError.value = ''
  importReport.value = null
  pendingSnapshot = null
  importOpen.value = true
}

function onImportFileChange(): void {
  pendingSnapshot = null
  importReport.value = null
  importError.value = ''
}

function pickedFile(): File | null {
  const value = importFile.value
  if (Array.isArray(value)) return value[0] ?? null
  return value
}

async function submitImport(): Promise<void> {
  if (!botId.value) return
  importError.value = ''
  if (!pendingSnapshot) {
    const file = pickedFile()
    if (!file) {
      importError.value = '请选择 JSON 快照文件'
      return
    }
    try {
      const parsed = JSON.parse(await file.text()) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        importError.value = '快照必须是 JSON 对象'
        return
      }
      pendingSnapshot = parsed as Record<string, unknown>
    } catch {
      importError.value = '文件不是合法的 JSON'
      return
    }
  }

  importing.value = true
  try {
    const report = await importMemories(botId.value, pendingSnapshot, importDryRun.value)
    importReport.value = report
    ui.notify(
      report.dry_run
        ? `预检完成：记忆 ${report.memories.imported} 条、笔记 ${report.notes.imported} 条（未写入）`
        : `导入完成：记忆 ${report.memories.imported} 条、笔记 ${report.notes.imported} 条`,
      'success',
    )
    if (!report.dry_run) await load()
  } catch (error) {
    importError.value = errorMessage(error, '导入快照失败')
  } finally {
    importing.value = false
  }
}

function openSearch(): void {
  searchQuery.value = filters.q || ''
  searchKind.value = filters.kind || ''
  searchError.value = ''
  searchDone.value = false
  searchResults.value = []
  searchTotal.value = 0
  searchOpen.value = true
}

async function runSearch(): Promise<void> {
  if (!botId.value) return
  searchError.value = ''
  const query = searchQuery.value.trim()
  if (!query) {
    searchError.value = '请输入检索关键词'
    return
  }
  searchLoading.value = true
  try {
    const result = await memory.search(botId.value, {
      q: query,
      kind: searchKind.value || undefined,
      limit: searchLimit.value,
    })
    searchResults.value = result.items ?? []
    searchTotal.value = result.total ?? searchResults.value.length
    searchDone.value = true
  } catch (error) {
    searchError.value = errorMessage(error, '检索失败')
  } finally {
    searchLoading.value = false
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

.filter-select {
  flex: 0 1 160px;
  min-width: 140px;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.table-card {
  padding: 4px 0;
}

.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px 4px;
  font-size: 0.8rem;
}

.table-head__hint {
  font-size: 0.76rem;
}

.table-scroll {
  overflow-x: auto;
}

.content-cell {
  max-width: 460px;
}

.content-line {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.content-text {
  display: inline;
  color: var(--console-text);
  font: inherit;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.content-link {
  display: inline;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--console-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  line-height: 1.5;
}

.content-link:hover {
  color: var(--console-primary);
  text-decoration: underline;
}

.content-link:focus-visible {
  outline: 2px solid var(--console-primary);
  outline-offset: 2px;
  border-radius: 2px;
}

.content-reason {
  margin-top: 4px;
  font-size: 0.76rem;
  line-height: 1.5;
}

.importance--inject {
  color: var(--console-danger);
  font-weight: 700;
}

.importance {
  font-size: 0.8rem;
  white-space: nowrap;
  color: var(--console-text-muted);
  font-variant-numeric: tabular-nums;
}

.tags-cell {
  max-width: 200px;
}

.tag-chip {
  margin: 2px 4px 2px 0;
}

.recall-cell {
  font-size: 0.8rem;
  color: var(--console-text-muted);
}

.recall-time {
  font-size: 0.72rem;
}

.nowrap {
  white-space: nowrap;
}

.memory-cards {
  display: grid;
  gap: 12px;
}

.memory-card {
  padding: 14px;
}

.memory-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.memory-card__content {
  margin: 10px 0 0;
  font-size: 0.88rem;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.memory-card__reason {
  margin: 6px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
}

.memory-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.memory-card__meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
  font-size: 0.74rem;
}

.memory-card__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

.memory-drawer {
  border-left: 1px solid var(--console-border);
  max-width: 100vw;
}

.drawer-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 12px 20px;
  border-bottom: 1px solid var(--console-border);
}

.drawer-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.drawer-hint {
  font-size: 0.74rem;
  line-height: 1.6;
  margin: 8px 0 0;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--console-border);
}

.search-dialog {
  padding: 8px;
}

.import-card {
  padding: 8px;
}

.import-card .dialog-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

.search-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

.search-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.search-input {
  flex: 1 1 200px;
  min-width: 160px;
}

.search-kind {
  flex: 0 1 140px;
}

.search-limit {
  flex: 0 1 110px;
}

.search-summary {
  margin: 12px 0 4px;
  font-size: 0.8rem;
}

.search-list {
  margin: 0 -8px;
}

@media (max-width: 599px) {
  .filter-select {
    flex: 1 1 140px;
  }

  .table-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
}
</style>
