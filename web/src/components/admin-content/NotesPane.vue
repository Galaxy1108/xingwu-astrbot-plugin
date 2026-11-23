<template>
  <div class="tab-panel notes-panel">
    <div class="memory-toolbar">
      <form class="memory-filters" @submit.prevent="applyNoteFilters">
        <v-text-field
          v-model.trim="noteFilters.q"
          label="搜索标题 / 正文"
          prepend-inner-icon="mdi-magnify"
          density="compact"
          hide-details
          class="filter-q"
          data-testid="admin-note-search"
        />
        <v-text-field
          v-model.trim="noteFilters.tag"
          label="标签"
          density="compact"
          hide-details
          class="filter-kind"
        />
        <v-btn type="submit" color="primary" variant="tonal" :loading="notesLoading">
          筛选
        </v-btn>
        <v-btn variant="text" @click="resetNoteFilters">重置</v-btn>
      </form>
    </div>

    <v-alert v-if="notesError" type="error" variant="tonal" class="mb-3">
      <div class="alert-row">
        <span>{{ notesError }}</span>
        <v-btn size="small" variant="text" color="error" @click="loadNotes(notesPage)">
          重试
        </v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="notesLoading && !notes.length" variant="table" :rows="6" />

    <EmptyState
      v-else-if="!notesError && notes.length === 0"
      icon="mdi-note-text-outline"
      :title="hasNoteFilters ? '没有符合条件的笔记' : '暂无笔记'"
      :description="
        hasNoteFilters
          ? '试试调整搜索关键词或标签。'
          : '该 Bot 还没有创建笔记；笔记与记忆分开保存长文本资料。'
      "
    />

    <template v-else-if="notes.length">
      <div class="memory-list">
        <article
          v-for="note in notes"
          :key="note.short_id"
          class="memory-row"
          data-testid="admin-note-row"
        >
          <div class="memory-main">
            <div class="memory-meta">
              <v-chip size="x-small" variant="tonal" color="primary">笔记</v-chip>
              <span class="text-mono text-muted note-short">{{ note.short_id }}</span>
              <span class="text-muted memory-importance">{{ note.content_length }} 字</span>
            </div>
            <p class="memory-content">{{ note.title || '未命名笔记' }}</p>
            <p class="memory-reason text-muted">{{ truncate(note.preview, 140) }}</p>
            <div class="memory-sub text-muted">
              更新 {{ formatDateTime(note.updated_at) }}
              <template v-if="note.tags?.length"> · {{ note.tags.join(' / ') }}</template>
            </div>
          </div>
          <div class="memory-actions">
            <v-btn
              icon
              size="small"
              variant="text"
              title="查看"
              aria-label="查看笔记"
              data-testid="admin-note-open"
              @click="openNoteViewer(note)"
            >
              <v-icon size="18">mdi-eye-outline</v-icon>
            </v-btn>
            <v-btn
              icon
              size="small"
              variant="text"
              color="error"
              title="删除"
              aria-label="删除笔记"
              data-testid="admin-note-delete"
              @click="askDeleteNote(note)"
            >
              <v-icon size="18">mdi-delete-outline</v-icon>
            </v-btn>
          </div>
        </article>
      </div>

      <div class="memory-footer">
        <span class="text-muted">共 {{ notesTotal }} 篇 · 第 {{ notesPage }} / {{ notePageCount }} 页</span>
        <v-pagination
          v-if="notesTotal > notesPageSize"
          :model-value="notesPage"
          :length="notePageCount"
          :total-visible="5"
          density="compact"
          @update:model-value="loadNotes"
        />
      </div>
    </template>
  </div>

  <v-dialog v-model="noteViewerOpen" max-width="720" scrollable>
    <v-card class="note-viewer-card">
      <v-card-title class="note-viewer-title">
        <span>{{ noteRead?.title || selectedNote?.title || '查看笔记' }}</span>
        <v-btn icon variant="text" aria-label="关闭笔记" @click="noteViewerOpen = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-card-title>
      <v-card-text>
        <div class="text-muted note-viewer-meta">
          <span class="text-mono">{{ selectedNote?.short_id }}</span>
          <span v-if="noteRead"> · {{ noteRead.total_length }} 字</span>
        </div>
        <v-alert v-if="noteReadError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ noteReadError }}
        </v-alert>
        <pre class="note-viewer-body">{{ noteReadContent || '（空笔记）' }}</pre>
        <div v-if="noteRead?.has_more" class="note-viewer-more">
          <v-btn variant="tonal" color="primary" :loading="noteReadMore" @click="loadMoreNote">
            加载更多
          </v-btn>
          <span class="text-muted">已显示 {{ noteReadContent.length }} / {{ noteRead.total_length }} 字</span>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-btn
          variant="text"
          color="error"
          :disabled="!selectedNote"
          @click="selectedNote && askDeleteNote(selectedNote)"
        >
          删除笔记
        </v-btn>
        <v-spacer />
        <v-btn variant="text" @click="noteViewerOpen = false">关闭</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <ConfirmDialog
    v-model="noteDeleteOpen"
    title="删除这篇笔记？"
    :message="`删除后不可恢复。\n\n${noteDeleteTarget?.title || ''}`"
    confirm-text="删除笔记"
    danger
    :loading="noteDeleting"
    @confirm="confirmDeleteNote"
    @cancel="noteDeleteOpen = false"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useAdminContentContext } from '@/composables/useAdminContent'
import { formatDateTime, truncate } from '@/utils/format'

/* 笔记 tab：列表、搜索、查看弹窗与删除确认。共享状态见 useAdminContent。 */
const {
  noteFilters,
  notes,
  notesTotal,
  notesPage,
  notesPageSize,
  notesLoading,
  notesError,
  loadNotes,
  applyNoteFilters,
  resetNoteFilters,
  openNoteViewer,
  askDeleteNote,
  noteViewerOpen,
  selectedNote,
  noteRead,
  noteReadContent,
  noteReadError,
  noteReadMore,
  loadMoreNote,
  noteDeleteOpen,
  noteDeleteTarget,
  noteDeleting,
  confirmDeleteNote,
} = useAdminContentContext()

const hasNoteFilters = computed(() => Boolean(noteFilters.q || noteFilters.tag))
const notePageCount = computed(() =>
  Math.max(1, Math.ceil(notesTotal.value / Math.max(1, notesPageSize.value))),
)
</script>

<style scoped src="./admin-content-shared.css" />

<style scoped>
.note-short {
  font-size: 0.7rem;
}

.note-viewer-card {
  padding: 8px;
}

.note-viewer-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 18px;
  font-weight: 650;
  padding: 12px 20px 0;
}

.note-viewer-meta {
  font-size: 12px;
  margin-bottom: 10px;
  overflow-wrap: anywhere;
}

.note-viewer-body {
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

.note-viewer-more {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
  font-size: 12px;
}
</style>
