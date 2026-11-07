<template>
  <div>
    <PageHeader title="Bot 管理" description="查看全部租户的 Bot 元数据，可停用异常实例。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="admin.botsLoading" @click="load">
          刷新
        </v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="admin.botsError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ admin.botsError.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="admin.botsLoading && !admin.bots.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!admin.botsError && admin.bots.length === 0"
      icon="mdi-robot-outline"
      title="暂无 Bot"
      description="用户创建 Bot 后会显示在这里。"
    />

    <v-card v-else-if="admin.bots.length" class="table-card">
      <div class="table-scroll">
        <v-table hover class="bots-table">
          <thead>
            <tr>
              <th>Bot</th>
              <th>归属用户</th>
              <th>平台</th>
              <th>状态</th>
              <th class="nowrap">创建时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="bot in admin.bots" :key="bot.id">
              <td>
                <div class="bot-name">{{ bot.name }}</div>
                <div class="text-mono text-muted bot-id">{{ bot.id }}</div>
              </td>
              <td>{{ bot.owner_email || '—' }}</td>
              <td>{{ platformShortLabel(bot.platform) }}</td>
              <td>
                <StatusChip :status="bot.status" />
                <v-chip
                  v-if="bot.admin_disabled"
                  size="x-small"
                  color="error"
                  variant="tonal"
                  class="admin-disabled-chip"
                  :title="bot.admin_disabled_reason || ''"
                >
                  管理员停用
                </v-chip>
                <div class="bot-flags text-muted">
                  <span :class="{ 'flag-on': bot.enabled }">
                    <v-icon size="13">{{ bot.enabled ? 'mdi-check-circle' : 'mdi-minus-circle-outline' }}</v-icon>
                    {{ bot.enabled ? '已启用' : '已停用' }}
                  </span>
                  <span class="flag-sep">·</span>
                  <span :class="{ 'flag-on': bot.bound }">
                    <v-icon size="13">{{ bot.bound ? 'mdi-link-variant' : 'mdi-link-off' }}</v-icon>
                    {{ bot.bound ? '已绑定' : '未绑定' }}
                  </span>
                </div>
              </td>
              <td class="nowrap">{{ formatDateTime(bot.created_at) }}</td>
              <td class="text-right nowrap">
                <v-btn
                  size="small"
                  variant="text"
                  color="primary"
                  prepend-icon="mdi-eye-outline"
                  data-testid="admin-bot-content"
                  @click="openContent(bot)"
                >
                  内容
                </v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  color="error"
                  :disabled="!bot.enabled || bot.status === 'deleted' || bot.admin_disabled"
                  @click="askStop(bot)"
                >
                  停用
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
    </v-card>

    <AdminContentDrawer v-model="contentOpen" :bot="contentTarget" />

    <ReasonDialog
      v-model="stopOpen"
      :title="`停用「${stopTarget?.name || ''}」？`"
      :message="`将停用 ${stopTarget?.owner_email || '该用户'} 名下的这个 Bot 平台实例，消息将不再处理。必须填写原因，用户会在 Bot 详情看到并可以申诉。`"
      label="停用原因"
      confirm-text="确认停用"
      danger
      :loading="stopping"
      @confirm="confirmStop"
      @cancel="stopOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ReasonDialog from '@/components/ReasonDialog.vue'
import AdminContentDrawer from '@/components/AdminContentDrawer.vue'
import { useAdminStore } from '@/stores/admin'
import { useUiStore } from '@/stores/ui'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, platformShortLabel } from '@/utils/format'
import type { AdminBot, AdminContentTarget } from '@/types'

const admin = useAdminStore()
const ui = useUiStore()

const contentOpen = ref(false)
const contentTarget = ref<AdminContentTarget | null>(null)
const stopOpen = ref(false)
const stopTarget = ref<AdminBot | null>(null)
const stopping = ref(false)

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  try {
    await admin.loadBots()
  } catch {
    /* store 已记录 */
  }
}

function askStop(bot: AdminBot): void {
  stopTarget.value = bot
  stopOpen.value = true
}

function openContent(bot: AdminBot): void {
  contentTarget.value = { id: bot.id, name: bot.name }
  contentOpen.value = true
}

async function confirmStop(reason: string): Promise<void> {
  if (!stopTarget.value) return
  stopping.value = true
  try {
    await admin.disableBot(stopTarget.value.id, reason)
    stopOpen.value = false
    ui.notify('Bot 已停用', 'success')
    await load()
  } catch (error) {
    ui.notifyError(errorMessage(error, '停用 Bot 失败'))
  } finally {
    stopping.value = false
  }
}
</script>

<style scoped>
.table-card {
  padding: 4px 0;
}

.table-scroll {
  overflow-x: auto;
}

.bots-table {
  min-width: 980px;
}

.bots-table :deep(th) {
  white-space: nowrap;
}

.admin-disabled-chip {
  margin-top: 4px;
}

.bot-flags {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 4px;
  font-size: 0.7rem;
  white-space: nowrap;
}

.bot-flags .v-icon {
  margin-right: 2px;
}

.flag-on {
  color: #2e7d32;
}

.flag-sep {
  opacity: 0.5;
}

.bot-name {
  font-weight: 600;
}

.bot-id {
  font-size: 0.72rem;
  margin-top: 2px;
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
</style>
