<template>
  <v-navigation-drawer
    v-model="open"
    location="right"
    temporary
    :width="isNarrow ? '100%' : 780"
    class="admin-content-drawer"
    data-testid="admin-content-drawer"
  >
    <div class="drawer-shell">
      <header class="drawer-head">
        <div class="head-text">
          <h2 class="drawer-title">
            内容查看
            <span v-if="bot" class="bot-name">· {{ bot.name }}</span>
          </h2>
          <p class="drawer-sub text-muted">
            对话与记忆 · 单条查看 · 本次访问已记录
          </p>
        </div>
        <v-btn icon variant="text" aria-label="关闭内容查看" @click="close">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </header>

      <v-alert
        type="info"
        variant="tonal"
        density="compact"
        icon="mdi-shield-eye-outline"
        class="access-alert"
        data-testid="admin-content-access-notice"
      >
        本次访问会记录在案：操作人、Bot、时间与 IP 将写入访问审计。
      </v-alert>

      <v-tabs v-model="activeTab" density="compact" class="content-tabs" color="primary">
        <v-tab value="conversations" data-testid="admin-content-tab-conversations">
          <v-icon start size="18">mdi-chat-processing-outline</v-icon>
          对话
        </v-tab>
        <v-tab value="memories" data-testid="admin-content-tab-memories">
          <v-icon start size="18">mdi-brain</v-icon>
          记忆
        </v-tab>
      </v-tabs>

      <v-divider />

      <div class="drawer-body">
        <!-- 对话 -->
        <div v-if="activeTab === 'conversations'" class="tab-panel conversations-panel">
          <v-alert v-if="conversationsError" type="error" variant="tonal" class="mb-3">
            <div class="alert-row">
              <span>{{ conversationsError }}</span>
              <v-btn size="small" variant="text" color="error" @click="loadConversations">
                重试
              </v-btn>
            </div>
          </v-alert>

          <LoadingSkeleton
            v-if="conversationsLoading && !conversations.length"
            variant="table"
            :rows="6"
          />

          <EmptyState
            v-else-if="!conversationsError && conversations.length === 0"
            icon="mdi-chat-outline"
            title="暂无对话"
            description="该 Bot 还没有产生对话记录，或对话数据尚未同步。"
          />

          <div v-else-if="conversations.length" class="conversation-split">
            <aside class="conv-list-pane" :class="{ 'is-hidden': isNarrow && selectedConversation }">
              <div class="pane-title text-muted">
                共 {{ conversations.length }} 个会话
                <v-chip v-if="encryptedCount" size="x-small" variant="tonal" color="primary">
                  加密 {{ encryptedCount }}
                </v-chip>
              </div>
              <v-list density="compact" nav class="conv-list">
                <v-list-item
                  v-for="conversation in conversations"
                  :key="conversation.id"
                  :active="conversation.id === activeConversationId"
                  class="conv-item"
                  data-testid="admin-conversation-item"
                  @click="selectConversation(conversation)"
                >
                  <template #prepend>
                    <v-icon
                      size="18"
                      :color="conversation.decrypt_error ? 'error' : undefined"
                    >
                      {{ conversation.decrypt_error ? 'mdi-lock-alert' : 'mdi-message-text-outline' }}
                    </v-icon>
                  </template>
                  <v-list-item-title class="conv-title">
                    {{ conversationTitle(conversation) }}
                  </v-list-item-title>
                  <v-list-item-subtitle class="conv-sub">
                    {{ formatDateTime(conversation.created_at) }}
                    · {{ conversation.history?.length ?? 0 }} 条
                    <v-icon v-if="conversation.encrypted" size="12">mdi-lock</v-icon>
                  </v-list-item-subtitle>
                </v-list-item>
              </v-list>
            </aside>

            <section class="message-pane">
              <template v-if="selectedConversation">
                <div class="message-head">
                  <v-btn
                    v-if="isNarrow"
                    icon
                    size="small"
                    variant="text"
                    aria-label="返回会话列表"
                    @click="activeConversationId = ''"
                  >
                    <v-icon>mdi-arrow-left</v-icon>
                  </v-btn>
                  <div class="message-head__text">
                    <div class="message-title">{{ conversationTitle(selectedConversation) }}</div>
                    <div class="message-meta text-muted">
                      {{ formatDateTime(selectedConversation.created_at) }}
                      · {{ selectedConversation.history?.length ?? 0 }} 条消息
                      <template v-if="selectedConversation.token_usage">
                        · {{ selectedConversation.token_usage }} tokens
                      </template>
                    </div>
                  </div>
                </div>

                <v-alert
                  v-if="selectedConversation.decrypt_error"
                  type="error"
                  variant="tonal"
                  density="compact"
                  class="mb-3 decrypt-alert"
                  data-testid="admin-conversation-decrypt-error"
                >
                  该会话无法解密（密钥缺失或数据损坏），以下内容不可读。请让用户确认加密状态或联系运维。
                </v-alert>

                <div class="message-scroll">
                  <div
                    v-for="(message, index) in normalizedHistory"
                    :key="`${selectedConversation.id}-${index}`"
                    class="chat-row"
                    :class="`chat-row--${roleMeta(message.role).key}`"
                    data-testid="admin-conversation-message"
                  >
                    <div class="chat-avatar">
                      <v-icon size="16">{{ roleMeta(message.role).icon }}</v-icon>
                    </div>
                    <div class="chat-main">
                      <div class="chat-meta">
                        <span>{{ roleMeta(message.role).label }}</span>
                        <span class="text-muted">#{{ index + 1 }}</span>
                      </div>
                      <div class="chat-bubble">{{ message.content }}</div>
                    </div>
                  </div>
                  <EmptyState
                    v-if="normalizedHistory.length === 0"
                    icon="mdi-message-off-outline"
                    title="该会话没有消息"
                    description="历史内容为空，或已被清理。"
                  />
                </div>
              </template>

              <div v-else class="message-placeholder">
                <v-icon size="40" color="primary">mdi-message-text-outline</v-icon>
                <p class="text-muted">从左侧选择一个会话查看消息。</p>
              </div>
            </section>
          </div>
        </div>

        <!-- 记忆 -->
        <div v-else class="tab-panel memories-panel">
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
                    <span class="text-muted memory-importance">★ {{ memory.importance }}/5</span>
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
      </div>
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
          <v-btn color="primary" :loading="saving" data-testid="admin-memory-save" @click="saveEditor">
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
      message="导出会生成包含全部记忆的 JSON 文件，并写入审计日志。单条查看请直接在列表中操作；请确认已获得数据授权。"
      confirm-text="确认导出"
      :loading="exporting"
      @confirm="confirmExport"
      @cancel="exportConfirmOpen = false"
    />
  </v-navigation-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useUiStore } from '@/stores/ui'
import { useMemoryKindMeta } from '@/composables/useMemoryKindMeta'
import { downloadJson } from '@/utils/download'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, truncate } from '@/utils/format'
import {
  deleteAdminBotMemory,
  exportAdminBotMemories,
  listAdminBotConversations,
  listAdminBotMemories,
  patchAdminBotMemory,
} from '@/api/admin'
import type {
  AdminContentTarget,
  AdminConversation,
  ConversationMessage,
  MemoryItem,
  MemoryKind,
  MemoryPatch,
} from '@/types'

const props = defineProps<{
  modelValue: boolean
  bot: AdminContentTarget | null
}>()

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const ui = useUiStore()
const { smAndDown } = useDisplay()
const { kindColor, kindIcon, kindLabel } = useMemoryKindMeta()

const isNarrow = computed(() => smAndDown.value)
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const botId = computed(() => props.bot?.id ?? '')

/* ------------------------------------------------------------ tabs */
const activeTab = ref<'conversations' | 'memories'>('conversations')

/* ------------------------------------------------------ conversations */
const conversations = ref<AdminConversation[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref('')
const activeConversationId = ref('')

const selectedConversation = computed(
  () => conversations.value.find((item) => item.id === activeConversationId.value) ?? null,
)
const encryptedCount = computed(() => conversations.value.filter((item) => item.encrypted).length)

const normalizedHistory = computed<ConversationMessage[]>(() => {
  const history = selectedConversation.value?.history
  return Array.isArray(history) ? history : []
})

const roleMetaMap: Record<string, { key: string; label: string; color: string; icon: string }> = {
  user: { key: 'user', label: '用户', color: 'primary', icon: 'mdi-account-outline' },
  assistant: { key: 'assistant', label: '助手', color: 'success', icon: 'mdi-robot-happy-outline' },
  system: { key: 'system', label: '系统', color: 'warning', icon: 'mdi-cog-outline' },
  tool: { key: 'tool', label: '工具', color: 'info', icon: 'mdi-wrench-outline' },
}

function roleMeta(role: string): { key: string; label: string; color: string; icon: string } {
  return (
    roleMetaMap[role] ?? {
      key: 'other',
      label: role || '未知',
      color: 'default',
      icon: 'mdi-help-circle-outline',
    }
  )
}

function conversationTitle(conversation: AdminConversation): string {
  if (conversation.title) return conversation.title
  const platform = conversation.platform_id ? `${conversation.platform_id} · ` : ''
  return `${platform}会话 ${conversation.id.slice(0, 8)}`
}

async function loadConversations(): Promise<void> {
  if (!botId.value) return
  conversationsLoading.value = true
  conversationsError.value = ''
  try {
    const result = await listAdminBotConversations(botId.value)
    conversations.value = result.items ?? []
    if (
      activeConversationId.value &&
      !conversations.value.some((item) => item.id === activeConversationId.value)
    ) {
      activeConversationId.value = ''
    }
    if (!activeConversationId.value && !isNarrow.value && conversations.value.length) {
      activeConversationId.value = conversations.value[0].id
    }
  } catch (error) {
    conversationsError.value = errorMessage(error, '加载对话失败')
  } finally {
    conversationsLoading.value = false
  }
}

function selectConversation(conversation: AdminConversation): void {
  activeConversationId.value = conversation.id
}

/* ----------------------------------------------------------- memories */
const memories = ref<MemoryItem[]>([])
const memoryTotal = ref(0)
const memoryPage = ref(1)
const memoryPageSize = ref(10)
const memoryLoading = ref(false)
const memoryError = ref('')
const memoryLoaded = ref(false)
const memoryFilters = reactive({ q: '', kind: '' })

const kindFilterOptions = [
  { title: '全部类型', value: '' },
  { title: '事实', value: 'fact' },
  { title: '偏好', value: 'preference' },
  { title: '事件', value: 'event' },
  { title: '笔记', value: 'note' },
]
const kindEditOptions = kindFilterOptions.slice(1)
const importanceOptions = [1, 2, 3, 4, 5].map((value) => ({
  title: `${value} · ${['很低', '较低', '一般', '较高', '很高'][value - 1]}`,
  value,
}))

const hasMemoryFilters = computed(() => Boolean(memoryFilters.q || memoryFilters.kind))
const memoryPageCount = computed(() =>
  Math.max(1, Math.ceil(memoryTotal.value / Math.max(1, memoryPageSize.value))),
)

async function loadMemories(page = 1): Promise<void> {
  if (!botId.value) return
  memoryLoading.value = true
  memoryError.value = ''
  try {
    const result = await listAdminBotMemories(botId.value, {
      page,
      page_size: memoryPageSize.value,
      q: memoryFilters.q || undefined,
      kind: memoryFilters.kind || undefined,
    })
    memories.value = result.items ?? []
    memoryTotal.value = result.total ?? 0
    memoryPage.value = result.page ?? page
    memoryPageSize.value = result.page_size ?? memoryPageSize.value
    memoryLoaded.value = true
  } catch (error) {
    memoryError.value = errorMessage(error, '加载记忆失败')
  } finally {
    memoryLoading.value = false
  }
}

function applyMemoryFilters(): void {
  void loadMemories(1)
}

function resetMemoryFilters(): void {
  memoryFilters.q = ''
  memoryFilters.kind = ''
  void loadMemories(1)
}

/* ------------------------------------------------------------- editor */
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

function openEditor(memory: MemoryItem): void {
  editingId.value = memory.id
  editor.content = memory.content
  editor.kind = memory.kind
  editor.reasoning = memory.reasoning || ''
  editor.importance = memory.importance || 3
  editor.pinned = Boolean(memory.pinned)
  editor.tags = (memory.tags || []).join(', ')
  editor.metadataText = JSON.stringify(memory.metadata ?? {}, null, 2)
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
    await patchAdminBotMemory(botId.value, editingId.value, payload)
    editorOpen.value = false
    ui.notify('记忆已保存', 'success')
    await loadMemories(memoryPage.value)
  } catch (error) {
    editorError.value = errorMessage(error, '保存记忆失败')
  } finally {
    saving.value = false
  }
}

/* ------------------------------------------------------------- delete */
const deleteOpen = ref(false)
const deleteTarget = ref<MemoryItem | null>(null)
const deleting = ref(false)

function askDelete(memory: MemoryItem): void {
  deleteTarget.value = memory
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!botId.value || !deleteTarget.value) return
  deleting.value = true
  try {
    await deleteAdminBotMemory(botId.value, deleteTarget.value.id)
    deleteOpen.value = false
    ui.notify('记忆已删除', 'success')
    const targetPage =
      memories.value.length === 1 && memoryPage.value > 1 ? memoryPage.value - 1 : memoryPage.value
    await loadMemories(targetPage)
  } catch (error) {
    deleteOpen.value = false
    ui.notifyError(errorMessage(error, '删除记忆失败'))
  } finally {
    deleting.value = false
  }
}

/* ------------------------------------------------------------- export */
const exportConfirmOpen = ref(false)
const exporting = ref(false)

async function confirmExport(): Promise<void> {
  if (!botId.value) return
  exporting.value = true
  try {
    const result = await exportAdminBotMemories(botId.value)
    downloadJson(`memories-${botId.value}-admin.json`, result)
    exportConfirmOpen.value = false
    ui.notify(`已导出 ${result.count} 条记忆（已记录审计）`, 'success')
    await loadMemories(memoryPage.value)
  } catch (error) {
    exportConfirmOpen.value = false
    ui.notifyError(errorMessage(error, '导出记忆失败'))
  } finally {
    exporting.value = false
  }
}

/* -------------------------------------------------------------- shell */
function close(): void {
  open.value = false
}

function resetState(): void {
  activeTab.value = 'conversations'
  conversations.value = []
  conversationsError.value = ''
  activeConversationId.value = ''
  memories.value = []
  memoryTotal.value = 0
  memoryPage.value = 1
  memoryLoaded.value = false
  memoryError.value = ''
  memoryFilters.q = ''
  memoryFilters.kind = ''
  editorOpen.value = false
  editingId.value = null
  deleteOpen.value = false
  exportConfirmOpen.value = false
}

async function initialize(): Promise<void> {
  if (!botId.value) return
  resetState()
  await loadConversations()
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) void initialize()
  },
  { immediate: true },
)

watch(
  () => props.bot?.id,
  () => {
    if (props.modelValue) void initialize()
  },
)

watch(activeTab, (tab) => {
  if (tab === 'memories' && !memoryLoaded.value) void loadMemories(1)
})
</script>

<style scoped>
.drawer-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.drawer-head {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px 8px;
}

.drawer-title {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  line-height: 1.4;
}

.bot-name {
  color: var(--console-primary);
}

.drawer-sub {
  margin: 3px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

.access-alert {
  flex: 0 0 auto;
  margin: 2px 20px 8px;
  font-size: 12px;
}

.content-tabs {
  flex: 0 0 auto;
  padding: 0 12px;
  border-bottom: 1px solid var(--console-border);
}

.drawer-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tab-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 14px 20px 16px;
  overflow: hidden;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

/* conversations */
.conversation-split {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: 14px;
}

.conv-list-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--console-border);
  padding-right: 8px;
}

.pane-title {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 6px 8px;
  font-size: 0.76rem;
}

.conv-list {
  flex: 1 1 auto;
  overflow-y: auto;
  background: transparent;
}

.conv-item {
  border-radius: 8px;
  margin-bottom: 2px;
}

.conv-title {
  font-size: 0.84rem;
  font-weight: 550;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-sub {
  font-size: 0.7rem !important;
  opacity: 0.85;
}

.message-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.message-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 0 10px;
}

.message-head__text {
  min-width: 0;
}

.message-title {
  font-size: 0.9rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-meta {
  font-size: 0.72rem;
}

.decrypt-alert {
  font-size: 0.8rem;
}

.message-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.chat-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: flex-start;
}

.chat-row--user {
  flex-direction: row-reverse;
}

.chat-avatar {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(60, 150, 202, 0.12);
  color: var(--console-primary);
}

.chat-row--user .chat-avatar {
  background: rgba(60, 150, 202, 0.2);
}

.chat-main {
  min-width: 0;
  max-width: 82%;
}

.chat-row--user .chat-main {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.chat-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 11px;
  color: var(--console-text-muted);
}

.chat-bubble {
  border-radius: 12px;
  padding: 10px 14px;
  background: #f4f6f8;
  color: var(--console-text);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.chat-row--user .chat-bubble {
  background: rgba(60, 150, 202, 0.14);
  border-radius: 14px;
}

.message-placeholder {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 0.85rem;
}

/* memories */
.memory-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.memory-filters {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.filter-q {
  flex: 1 1 200px;
  min-width: 160px;
  max-width: 320px;
}

.filter-kind {
  flex: 0 1 130px;
  min-width: 110px;
}

.memory-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.memory-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 10px;
  border-bottom: 1px solid var(--console-border);
}

.memory-row:last-child {
  border-bottom: none;
}

.memory-main {
  flex: 1 1 auto;
  min-width: 0;
}

.memory-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.memory-importance {
  font-size: 0.74rem;
  font-variant-numeric: tabular-nums;
}

.memory-content {
  margin: 0;
  font-size: 0.86rem;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.memory-reason {
  margin: 4px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
}

.memory-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.memory-sub {
  margin-top: 6px;
  font-size: 0.72rem;
}

.memory-actions {
  display: flex;
  flex-shrink: 0;
}

.memory-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 8px;
  font-size: 0.76rem;
}

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

@media (max-width: 959px) {
  .drawer-head,
  .tab-panel {
    padding-left: 14px;
    padding-right: 14px;
  }

  .access-alert {
    margin-left: 14px;
    margin-right: 14px;
  }

  .conversation-split {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .conv-list-pane {
    border-right: none;
    padding-right: 0;
  }

  .conv-list-pane.is-hidden {
    display: none;
  }

  .message-pane {
    height: 100%;
  }
}
</style>
