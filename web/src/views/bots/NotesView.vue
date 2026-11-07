<template>
  <div>
    <PageHeader
      :title="pageTitle"
      description="笔记与记忆分开管理：用于保存长文本资料，可按正文分页查看。"
      :back-to="`/bots/${botId}`"
    >

    </PageHeader>

    <BotTabs :bot-id="botId" active="notes" />

    <div class="content-toolbar">
      <span class="text-muted toolbar-hint">长文本资料与记忆分开管理</span>
      <v-spacer />
      <v-btn size="small" variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">
        刷新
      </v-btn>
      <v-btn
        size="small"
        color="primary"
        variant="tonal"
        prepend-icon="mdi-plus"
        data-testid="note-create"
        @click="openCreate"
      >
        新建笔记
      </v-btn>
    </div>

    <v-card class="filter-card mb-4">
      <form class="filter-row" @submit.prevent="applyFilters">
        <v-text-field
          v-model.trim="filters.q"
          label="搜索标题 / 正文"
          prepend-inner-icon="mdi-magnify"
          density="compact"
          hide-details
          class="filter-q"
        />
        <v-text-field
          v-model.trim="filters.tag"
          label="标签（单值）"
          density="compact"
          hide-details
          class="filter-tag"
        />
        <v-btn type="submit" color="primary" variant="tonal">筛选</v-btn>
        <v-btn variant="text" @click="resetFilters">重置</v-btn>
      </form>
    </v-card>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !notes.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!error && notes.length === 0"
      icon="mdi-note-text-outline"
      :title="hasFilters ? '没有符合条件的笔记' : '还没有笔记'"
      :description="
        hasFilters
          ? '试试调整搜索关键词或标签。'
          : '笔记用于保存长文本资料；点击右上角「新建笔记」开始。'
      "
      :actions="
        hasFilters
          ? [{ label: '清空筛选', onClick: resetFilters }]
          : [{ label: '新建笔记', onClick: openCreate }]
      "
    />

    <v-card v-else-if="notes.length" class="table-card">
      <div class="table-head">
        <span class="text-muted">共 {{ total }} 篇 · 当前第 {{ page }} 页</span>
      </div>
      <div class="table-scroll">
        <v-table hover class="notes-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>预览</th>
              <th>标签</th>
              <th>更新时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="note in notes" :key="note.short_id" data-testid="note-row">
              <td class="title-cell">
                <button type="button" class="title-link" @click="openNote(note)">
                  {{ note.title || '未命名笔记' }}
                </button>
                <div class="text-mono text-muted note-id">{{ note.short_id }}</div>
              </td>
              <td class="preview-cell" :title="note.preview">{{ note.preview || '—' }}</td>
              <td class="tags-cell">
                <template v-if="note.tags?.length">
                  <v-chip v-for="tag in note.tags" :key="tag" size="x-small" variant="outlined" class="tag-chip">
                    {{ tag }}
                  </v-chip>
                </template>
                <span v-else class="text-muted">—</span>
              </td>
              <td class="nowrap">{{ formatDateTime(note.updated_at) }}</td>
              <td class="text-right nowrap">
                <v-btn size="small" variant="text" @click="openNote(note)">查看</v-btn>
                <v-btn size="small" variant="text" color="error" @click="askDelete(note)">删除</v-btn>
              </td>
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
    </v-card>

    <v-dialog v-model="createOpen" max-width="640" persistent>
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">新建笔记</v-card-title>
        <v-card-text>
          <v-alert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ createError }}
          </v-alert>
          <v-text-field v-model.trim="form.title" label="标题" counter="200" maxlength="200" class="mb-2" />
          <v-textarea v-model="form.content" label="正文" rows="8" auto-grow class="mb-2" />
          <v-text-field v-model.trim="form.tags" label="标签（逗号分隔）" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="saving" @click="createOpen = false">取消</v-btn>
          <v-btn color="primary" variant="tonal" :loading="saving" data-testid="note-save" @click="submitCreate">
            保存
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="viewerOpen" max-width="760" scrollable>
      <v-card class="dialog-card">
        <v-card-title class="dialog-title viewer-title">
          <span>{{ viewerTitle }}</span>
          <v-btn icon variant="text" aria-label="关闭笔记" @click="viewerOpen = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </v-card-title>
        <v-card-text>
          <div class="viewer-meta text-muted">
            <span class="text-mono">{{ viewerShortId }}</span>
            <span v-if="viewerTags.length">· {{ viewerTags.join(' / ') }}</span>
            <span v-if="readPage">· {{ readPage.total_length }} 字</span>
          </div>
          <v-alert v-if="readError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ readError }}
          </v-alert>
          <pre class="note-body">{{ readContent || '（空笔记）' }}</pre>
          <div v-if="readPage?.has_more" class="viewer-more">
            <v-btn
              variant="tonal"
              color="primary"
              :loading="readingMore"
              data-testid="note-load-more"
              @click="loadMore"
            >
              加载更多
            </v-btn>
            <span class="text-muted">已显示 {{ readContent.length }} / {{ readPage.total_length }} 字</span>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-btn
            variant="text"
            color="error"
            :disabled="!currentNote"
            @click="askDelete(currentNote!)"
          >
            删除笔记
          </v-btn>
          <v-spacer />
          <v-btn variant="text" @click="viewerOpen = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="deleteOpen"
      title="删除这篇笔记？"
      :message="`删除后不可恢复。\n\n${deleteTarget?.title || ''}`"
      confirm-text="删除笔记"
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
import PageHeader from '@/components/PageHeader.vue'
import BotTabs from '@/components/BotTabs.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useBotsStore } from '@/stores/bots'
import { useUiStore } from '@/stores/ui'
import { createNote, deleteNote, listNotes, readNote } from '@/api/notes'
import { toApiError } from '@/api/client'
import type { NoteReadPage, NoteSummary } from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const bots = useBotsStore()
const ui = useUiStore()

const botId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const bot = computed(() => (bots.current?.id === botId.value ? bots.current : null))
const pageTitle = computed(() => (bot.value ? `${bot.value.name} · 笔记` : '笔记'))

const notes = ref<NoteSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')
const filters = reactive({ q: '', tag: '' })
const hasFilters = computed(() => Boolean(filters.q || filters.tag))

const createOpen = ref(false)
const saving = ref(false)
const createError = ref('')
const form = reactive({ title: '', content: '', tags: '' })

const viewerOpen = ref(false)
const currentNote = ref<NoteSummary | null>(null)
const readPage = ref<NoteReadPage | null>(null)
const readContent = ref('')
const readingMore = ref(false)
const readError = ref('')

const deleteOpen = ref(false)
const deleteTarget = ref<NoteSummary | null>(null)
const deleting = ref(false)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))
const viewerTitle = computed(() => currentNote.value?.title || readPage.value?.title || '查看笔记')
const viewerShortId = computed(() => currentNote.value?.short_id || readPage.value?.short_id || '')
const viewerTags = computed(() => currentNote.value?.tags ?? [])

watch(
  () => route.query,
  () => {
    syncFromQuery()
    void load()
  },
  { immediate: true },
)

onMounted(() => {
  if (botId.value) void bots.loadBot(botId.value).catch(() => undefined)
})

function stringQuery(value: unknown): string {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' ? raw : ''
}

function syncFromQuery(): void {
  filters.q = stringQuery(route.query.q)
  filters.tag = stringQuery(route.query.tag)
  const parsed = Number(stringQuery(route.query.page))
  page.value = Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  if (!botId.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await listNotes(botId.value, {
      page: page.value,
      page_size: pageSize.value,
      q: filters.q || undefined,
      tag: filters.tag || undefined,
    })
    notes.value = result.items ?? []
    total.value = result.total ?? 0
    page.value = result.page ?? page.value
    pageSize.value = result.page_size ?? pageSize.value
  } catch (err) {
    const apiError = toApiError(err)
    error.value =
      apiError.status === 404
        ? '笔记接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载笔记失败')
  } finally {
    loading.value = false
  }
}

async function applyFilters(): Promise<void> {
  const query: Record<string, string> = {}
  if (filters.q) query.q = filters.q
  if (filters.tag) query.tag = filters.tag
  await router.replace({ query })
}

async function resetFilters(): Promise<void> {
  filters.q = ''
  filters.tag = ''
  await router.replace({ query: {} })
}

async function onPage(next: number): Promise<void> {
  await router.replace({ query: { ...route.query, page: String(next) } })
}

function openCreate(): void {
  form.title = ''
  form.content = ''
  form.tags = ''
  createError.value = ''
  createOpen.value = true
}

async function submitCreate(): Promise<void> {
  if (!botId.value) return
  createError.value = ''
  if (!form.title.trim() && !form.content.trim()) {
    createError.value = '请填写标题或正文'
    return
  }
  saving.value = true
  try {
    await createNote(botId.value, {
      title: form.title.trim(),
      content: form.content,
      tags: form.tags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    })
    createOpen.value = false
    ui.notify('笔记已创建', 'success')
    await load()
  } catch (err) {
    createError.value = errorMessage(err, '创建笔记失败')
  } finally {
    saving.value = false
  }
}

async function openNote(note: NoteSummary): Promise<void> {
  currentNote.value = note
  readPage.value = null
  readContent.value = ''
  readError.value = ''
  viewerOpen.value = true
  await loadRead(note.short_id, 0, true)
}

async function loadRead(shortId: string, offset: number, replace = false): Promise<void> {
  if (!botId.value) return
  readingMore.value = !replace
  readError.value = ''
  try {
    const result = await readNote(botId.value, shortId, offset, 4000)
    readPage.value = result
    readContent.value = replace ? result.content : readContent.value + result.content
  } catch (err) {
    readError.value = errorMessage(err, '加载正文失败')
  } finally {
    readingMore.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!readPage.value?.next_offset) return
  await loadRead(readPage.value.short_id, readPage.value.next_offset)
}

function askDelete(note: NoteSummary): void {
  deleteTarget.value = note
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!botId.value || !deleteTarget.value) return
  deleting.value = true
  try {
    await deleteNote(botId.value, deleteTarget.value.short_id)
    deleteOpen.value = false
    ui.notify('笔记已删除', 'success')
    if (currentNote.value?.short_id === deleteTarget.value.short_id) {
      viewerOpen.value = false
      currentNote.value = null
    }
    await load()
  } catch (err) {
    deleteOpen.value = false
    ui.notifyError(errorMessage(err, '删除笔记失败'))
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.toolbar-hint {
  font-size: 12px;
}

.filter-card {
  padding: 14px 16px;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-q {
  flex: 1 1 240px;
  min-width: 180px;
}

.filter-tag {
  flex: 0 1 180px;
}

.table-card {
  padding: 4px 0;
}

.table-head {
  padding: 12px 16px 4px;
  font-size: 0.8rem;
}

.table-scroll {
  overflow-x: auto;
}

.notes-table {
  min-width: 860px;
}

.notes-table :deep(th) {
  white-space: nowrap;
}

.title-cell {
  min-width: 180px;
}

.title-link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--console-text);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.title-link:hover {
  color: var(--console-primary);
  text-decoration: underline;
}

.note-id {
  font-size: 0.7rem;
  margin-top: 2px;
}

.preview-cell {
  max-width: 420px;
  color: var(--console-text-muted);
  font-size: 0.82rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tags-cell {
  max-width: 200px;
}

.tag-chip {
  margin: 2px 4px 2px 0;
}

.nowrap {
  white-space: nowrap;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pager {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}

.dialog-card {
  padding: 8px;
}

.dialog-title {
  font-size: 18px;
  font-weight: 650;
  padding: 12px 20px 0;
}

.viewer-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.viewer-meta {
  font-size: 12px;
  margin-bottom: 10px;
  overflow-wrap: anywhere;
}

.note-body {
  margin: 0;
  padding: 12px;
  background: var(--console-surface-variant);
  border: 1px solid var(--console-border);
  border-radius: 8px;
  color: var(--console-text);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 52vh;
  overflow-y: auto;
}

.viewer-more {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
  font-size: 12px;
}
</style>
