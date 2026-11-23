<template>
  <v-navigation-drawer
    v-if="open"
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

      <v-alert
        v-if="encryptedNotice"
        type="warning"
        variant="tonal"
        density="compact"
        icon="mdi-lock-open-alert"
        class="encrypted-alert"
        data-testid="admin-content-encrypted-notice"
      >
        该用户已开启加密，本次查看已记录
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
        <v-tab value="notes" data-testid="admin-content-tab-notes">
          <v-icon start size="18">mdi-note-text-outline</v-icon>
          笔记
        </v-tab>
      </v-tabs>

      <v-divider />

      <div class="drawer-body">
        <ConversationPane v-if="activeTab === 'conversations'" />
        <MemoryPane v-else-if="activeTab === 'memories'" />
        <NotesPane v-else />
      </div>
    </div>

    <ConfirmDialog
      v-model="confirmationOpen"
      title="查看加密内容？"
      :message="confirmationMessage"
      confirm-text="确认查看并记录"
      danger
      @confirm="confirmContentAccess"
      @cancel="cancelContentAccess"
    />
  </v-navigation-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useDisplay } from 'vuetify'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ConversationPane from '@/components/admin-content/ConversationPane.vue'
import MemoryPane from '@/components/admin-content/MemoryPane.vue'
import NotesPane from '@/components/admin-content/NotesPane.vue'
import { provideAdminContent, useAdminContent } from '@/composables/useAdminContent'
import type { AdminContentTarget } from '@/types'

/*
 * 内容查看抽屉（壳）：负责 v-navigation-drawer、头部、访问提示、tabs 与
 * 加密内容确认对话框；各标签页由子组件渲染，共享状态经 useAdminContent 下发。
 * 抽屉关闭（v-if="open" 为假）时整棵子树卸载，不残留任何状态或弹层。
 */
const props = defineProps<{
  modelValue: boolean
  bot: AdminContentTarget | null
}>()

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const { smAndDown } = useDisplay()

const isNarrow = computed(() => smAndDown.value)
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const botId = computed(() => props.bot?.id ?? '')

const ctx = useAdminContent({
  visible: computed(() => props.modelValue),
  botId,
  isNarrow,
})
provideAdminContent(ctx)

const {
  activeTab,
  confirmationOpen,
  confirmationMessage,
  encryptedNotice,
  confirmContentAccess,
  cancelContentAccess,
} = ctx

function close(): void {
  open.value = false
}
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

.access-alert,
.encrypted-alert {
  flex: 0 0 auto;
  margin: 2px 20px 8px;
  font-size: 12px;
}

.content-tabs {
  flex: 0 0 auto;
  padding: 0 12px;
  border-bottom: 1px solid var(--console-border);
}

.content-tabs :deep(.v-tab) {
  height: 40px !important;
  min-height: 40px !important;
  padding-inline: 14px !important;
  font-size: 13.5px !important;
  text-transform: none;
  border-radius: 8px 8px 0 0;
}

.content-tabs :deep(.v-tab--selected) {
  background: rgba(60, 150, 202, 0.12);
  color: rgb(var(--v-theme-primary));
}

.content-tabs :deep(.v-tab__slider) {
  height: 2px;
}

.drawer-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

@media (max-width: 959px) {
  .drawer-head {
    padding-left: 14px;
    padding-right: 14px;
  }

  .access-alert {
    margin-left: 14px;
    margin-right: 14px;
  }
}
</style>
