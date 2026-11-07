<template>
  <div class="bot-tabs" role="tablist" aria-label="Bot 导航">
    <button
      v-for="item in tabs"
      :key="item.key"
      type="button"
      class="bot-tab"
      :class="{ 'bot-tab--active': item.key === active }"
      role="tab"
      :aria-selected="item.key === active"
      :data-testid="item.testid"
      @click="go(item)"
    >
      <v-icon size="16">{{ item.icon }}</v-icon>
      {{ item.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

type BotTabKey = 'overview' | 'conversations' | 'memory' | 'notes' | 'settings'

const props = defineProps<{
  botId: string
  active: BotTabKey
}>()

const router = useRouter()

const tabs: Array<{
  key: BotTabKey
  label: string
  icon: string
  to: string
  testid: string
}> = [
  { key: 'overview', label: '概览', icon: 'mdi-view-dashboard-outline', to: '', testid: 'bot-tab-overview' },
  {
    key: 'conversations',
    label: '对话历史',
    icon: 'mdi-chat-processing-outline',
    to: 'conversations',
    testid: 'bot-tab-conversations',
  },
  { key: 'memory', label: '记忆', icon: 'mdi-brain', to: 'memory', testid: 'bot-tab-memory' },
  { key: 'notes', label: '笔记', icon: 'mdi-note-text-outline', to: 'notes', testid: 'bot-tab-notes' },
  { key: 'settings', label: '设置', icon: 'mdi-cog-outline', to: '?tab=settings', testid: 'bot-settings' },
]

function go(item: (typeof tabs)[number]): void {
  if (item.key === props.active) return
  const base = `/bots/${encodeURIComponent(props.botId)}`
  if (item.key === 'settings') {
    void router.push({ path: base, query: { tab: 'settings' } })
    return
  }
  void router.push(item.to ? `${base}/${item.to}` : base)
}
</script>

<style scoped>
.bot-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 40px;
  margin: -8px 0 20px;
  border-bottom: 1px solid var(--console-border);
  overflow-x: auto;
  scrollbar-width: none;
}

.bot-tabs::-webkit-scrollbar {
  display: none;
}

.bot-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 14px;
  border: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--console-text-muted);
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.bot-tab:hover {
  color: var(--console-text);
  background: rgba(60, 150, 202, 0.06);
}

.bot-tab:focus-visible {
  outline: 2px solid var(--console-primary);
  outline-offset: -2px;
}

.bot-tab--active {
  color: rgb(var(--v-theme-primary));
  background: rgba(60, 150, 202, 0.12);
  box-shadow: inset 0 -2px 0 rgb(var(--v-theme-primary));
}

@media (max-width: 599px) {
  .bot-tab {
    padding: 0 11px;
    font-size: 13px;
  }
}

@media (max-width: 420px) {
  .bot-tab {
    padding: 0 9px;
    gap: 0;
  }

  .bot-tab :deep(.v-icon) {
    display: none;
  }
}
</style>
