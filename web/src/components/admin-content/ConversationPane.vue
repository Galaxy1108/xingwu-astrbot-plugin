<template>
  <div class="tab-panel conversations-panel">
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
      v-else-if="cancelled && !conversations.length"
      icon="mdi-shield-lock-outline"
      title="未查看加密内容"
      description="你已取消查看。加密内容不会被解密或显示。"
    >
      <template #actions>
        <v-btn color="primary" variant="tonal" @click="loadConversations(false)">重新查看</v-btn>
      </template>
    </EmptyState>

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
</template>

<script setup lang="ts">
import { computed } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useAdminContentContext } from '@/composables/useAdminContent'
import { formatDateTime } from '@/utils/format'
import type { AdminConversation, ConversationMessage } from '@/types'

/* 对话 tab：会话列表 + 消息视图。共享状态见 useAdminContent。 */
const {
  isNarrow,
  activeConversationId,
  conversations,
  conversationsLoading,
  conversationsError,
  cancelled,
  loadConversations,
  selectConversation,
} = useAdminContentContext()

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
</script>

<style scoped src="./admin-content-shared.css" />

<style scoped>
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
  background: var(--console-surface-variant);
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

@media (max-width: 959px) {
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
