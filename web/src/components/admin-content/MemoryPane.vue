<template>
  <div class="tab-panel memories-panel">
    <div class="memory-toolbar">
      <form class="memory-filters" @submit.prevent="applyMemoryFilters">
        <v-text-field
          v-model.trim="memoryFilters.q"
          label="关键字"
          prepend-inner-icon="mdi-magnify"
          density="compact"
          hide-details
          class="filter-q"
          data-testid="admin-memory-search"
        />
        <v-select
          v-model="memoryFilters.kind"
          :items="kindFilterOptions"
          label="类型"
          density="compact"
          hide-details
          class="filter-kind"
          @update:model-value="applyMemoryFilters"
        />
        <v-btn type="submit" color="primary" variant="tonal" :loading="memoryLoading">
          筛选
        </v-btn>
        <v-btn variant="text" @click="resetMemoryFilters">重置</v-btn>
      </form>
      <v-btn
        variant="tonal"
        prepend-icon="mdi-upload"
        data-testid="admin-memory-import"
        @click="openImport"
      >
        导入快照
      </v-btn>
      <v-btn
        variant="tonal"
        prepend-icon="mdi-download"
        :loading="exporting"
        data-testid="admin-memory-export"
        @click="exportConfirmOpen = true"
      >
        导出
      </v-btn>
    </div>

    <v-alert v-if="memoryError" type="error" variant="tonal" class="mb-3">
      <div class="alert-row">
        <span>{{ memoryError }}</span>
        <v-btn size="small" variant="text" color="error" @click="loadMemories(memoryPage)">
          重试
        </v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton
      v-if="memoryLoading && !memories.length"
      variant="table"
      :rows="6"
    />

    <EmptyState
      v-else-if="cancelled && !memories.length"
      icon="mdi-shield-lock-outline"
      title="未查看加密内容"
      description="你已取消查看。加密记忆不会被解密或显示。"
    >
      <template #actions>
        <v-btn color="primary" variant="tonal" @click="loadMemories(1, false)">重新查看</v-btn>
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="!memoryError && memories.length === 0"
      icon="mdi-brain"
      :title="hasMemoryFilters ? '没有符合条件的记忆' : '暂无记忆'"
      :description="
        hasMemoryFilters
          ? '试试调整关键字或类型。'
          : '当 Bot 通过 LLM 工具记录事实、偏好或事件后，会出现在这里。'
      "
    />

    <template v-else-if="memories.length">
      <div class="memory-list">
        <article
          v-for="memory in memories"
          :key="memory.id"
          class="memory-row"
          data-testid="admin-memory-row"
        >
          <div class="memory-main">
            <div class="memory-meta">
              <v-chip
                size="x-small"
                variant="tonal"
                :color="kindColor(memory.kind)"
                :prepend-icon="kindIcon(memory.kind)"
              >
                {{ memory.kind_label || kindLabel(memory.kind) }}
              </v-chip>
              <v-icon v-if="memory.pinned" size="15" color="warning" title="已置顶">
                mdi-pin
              </v-icon>
              <v-chip
                v-if="memory.importance >= 6"
                size="x-small"
                variant="tonal"
                :color="importanceColor(memory.importance)"
                :title="importanceText(memory.importance)"
              >
                总是注入
              </v-chip>
              <span v-else class="text-muted memory-importance">★ {{ memory.importance }}/6</span>
              <v-chip
                v-if="isAutoExtracted(memory)"
                size="x-small"
                variant="tonal"
                color="info"
              >
                自动提取
              </v-chip>
            </div>
            <p class="memory-content">{{ memory.content }}</p>
            <p v-if="memory.reasoning" class="memory-reason text-muted">
              {{ truncate(memory.reasoning, 140) }}
            </p>
            <div v-if="memory.tags?.length" class="memory-tags">
              <v-chip v-for="tag in memory.tags" :key="tag" size="x-small" variant="outlined">
                {{ tag }}
              </v-chip>
            </div>
            <div class="memory-sub text-muted">
              更新 {{ formatDateTime(memory.updated_at) }} · 召回 {{ memory.recall_count }} 次
            </div>
          </div>
          <div class="memory-actions">
            <v-btn
              icon
              size="small"
              variant="text"
              title="编辑"
              aria-label="编辑记忆"
              data-testid="admin-memory-edit"
              @click="openEditor(memory)"
            >
              <v-icon size="18">mdi-pencil-outline</v-icon>
            </v-btn>
            <v-btn
              icon
              size="small"
              variant="text"
              color="error"
              title="删除"
              aria-label="删除记忆"
              data-testid="admin-memory-delete"
              @click="askDelete(memory)"
            >
              <v-icon size="18">mdi-delete-outline</v-icon>
            </v-btn>
          </div>
        </article>
      </div>

      <div class="memory-footer">
        <span class="text-muted">
          共 {{ memoryTotal }} 条 · 第 {{ memoryPage }} / {{ memoryPageCount }} 页
        </span>
        <v-pagination
          v-if="memoryTotal > memoryPageSize"
          :model-value="memoryPage"
          :length="memoryPageCount"
          :total-visible="5"
          density="compact"
          @update:model-value="loadMemories"
        />
      </div>
    </template>
  </div>

  <!-- 记忆编辑 drawer -->
  <v-navigation-drawer
    v-if="editorOpen"
    v-model="editorOpen"
    location="right"
    temporary
    :width="isNarrow ? '100%' : 460"
    :z-index="2600"
    class="memory-editor-drawer"
    data-testid="admin-memory-editor"
  >
    <div class="editor-shell">
      <div class="editor-head">
        <h3 class="editor-title">
          编辑记忆 <span class="text-muted text-mono">#{{ editingId ?? '' }}</span>
        </h3>
        <v-btn icon variant="text" aria-label="关闭编辑" @click="editorOpen = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>
      <div class="editor-body">
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
        <v-select v-model="editor.kind" :items="kindEditOptions" label="类型" class="mb-2" />
        <v-select v-model="editor.importance" :items="importanceOptions" label="重要度" class="mb-2" />
        <v-switch v-model="editor.pinned" label="置顶（列表优先展示）" color="primary" />
        <v-text-field v-model="editor.tags" label="标签（逗号分隔，保存时全量替换）" class="mb-2" />
        <v-textarea v-model="editor.reasoning" label="推理 / 来源说明" rows="3" auto-grow class="mb-2" />
        <v-textarea
          v-model="editor.metadataText"
          label="metadata（JSON 对象，全量替换）"
          rows="4"
          auto-grow
          :error-messages="metadataError"
        />
        <p class="editor-hint text-muted">
          保存为 PATCH 部分更新；tags 与 metadata 以本次提交内容全量替换。操作会写入访问审计。
        </p>
      </div>
      <div class="editor-actions">
        <v-btn variant="text" :disabled="saving" @click="editorOpen = false">取消</v-btn>
        <v-btn color="primary" :loading="saving" data-testid="admin-memory-save" @click="saveEditor" variant="tonal">
          保存
        </v-btn>
      </div>
    </div>
  </v-navigation-drawer>

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

  <ConfirmDialog
    v-model="exportConfirmOpen"
    title="导出该 Bot 的全部记忆？"
    message="导出会生成包含全部记忆的 JSON 文件（含笔记），并写入审计日志。单条查看请直接在列表中操作；请确认已获得数据授权。"
    confirm-text="确认导出"
    :loading="exporting"
    @confirm="confirmExport"
    @cancel="exportConfirmOpen = false"
  />

<MemoryImportDialog />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import MemoryImportDialog from '@/components/admin-content/MemoryImportDialog.vue'
import { useAdminContentContext } from '@/composables/useAdminContent'
import { useMemoryKindMeta } from '@/composables/useMemoryKindMeta'
import { importanceColor, importanceText, isAutoExtracted, memoryImportanceOptions } from '@/utils/memoryMeta'
import { formatDateTime, truncate } from '@/utils/format'

/* 记忆 tab：列表、筛选、编辑抽屉、删除与导出确认。共享状态见 useAdminContent。 */
const { kindColor, kindIcon, kindLabel } = useMemoryKindMeta()

const {
  isNarrow,
  cancelled,
  memories,
  memoryTotal,
  memoryPage,
  memoryPageSize,
  memoryLoading,
  memoryError,
  memoryFilters,
  loadMemories,
  applyMemoryFilters,
  resetMemoryFilters,
  openImport,
  exporting,
  exportConfirmOpen,
  confirmExport,
  editorOpen,
  editingId,
  editorError,
  metadataError,
  saving,
  editor,
  openEditor,
  saveEditor,
  deleteOpen,
  deleteTarget,
  deleting,
  askDelete,
  confirmDelete,
} = useAdminContentContext()

const kindFilterOptions = [
  { title: '全部类型', value: '' },
  { title: '事实', value: 'fact' },
  { title: '偏好', value: 'preference' },
  { title: '事件', value: 'event' },
  { title: '笔记', value: 'note' },
]
const kindEditOptions = kindFilterOptions.slice(1)
const importanceOptions = memoryImportanceOptions

const hasMemoryFilters = computed(() => Boolean(memoryFilters.q || memoryFilters.kind))
const memoryPageCount = computed(() =>
  Math.max(1, Math.ceil(memoryTotal.value / Math.max(1, memoryPageSize.value))),
)
</script>

<style scoped src="./admin-content-shared.css" />

<style scoped>
/* editor */
.memory-editor-drawer {
  border-left: 1px solid var(--console-border);
}

.editor-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 6px;
}

.editor-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}

.editor-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 8px 16px;
}

.editor-hint {
  font-size: 0.74rem;
  line-height: 1.55;
}

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--console-border);
}
</style>
