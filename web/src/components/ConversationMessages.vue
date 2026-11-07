<template>
  <div class="chat-transcript">
    <div
      v-for="(message, index) in messages"
      :key="index"
      class="chat-row"
      :class="`chat-row--${roleMeta(message.role).key}`"
      data-testid="conversation-message"
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
    <div v-if="messages.length === 0" class="transcript-empty text-muted">
      该会话还没有消息。
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ConversationMessage } from '@/types'

withDefaults(defineProps<{ messages: ConversationMessage[] }>(), { messages: () => [] })

const roleMetaMap: Record<string, { key: string; label: string; icon: string }> = {
  user: { key: 'user', label: '用户', icon: 'mdi-account-outline' },
  assistant: { key: 'assistant', label: '助手', icon: 'mdi-robot-happy-outline' },
  system: { key: 'system', label: '系统', icon: 'mdi-cog-outline' },
  tool: { key: 'tool', label: '工具', icon: 'mdi-wrench-outline' },
}

function roleMeta(role: string): { key: string; label: string; icon: string } {
  return (
    roleMetaMap[role] ?? {
      key: 'other',
      label: role || '未知',
      icon: 'mdi-help-circle-outline',
    }
  )
}
</script>

<style scoped>
.chat-transcript {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chat-row {
  display: flex;
  gap: 10px;
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

.transcript-empty {
  padding: 20px;
  text-align: center;
  font-size: 13px;
}
</style>
