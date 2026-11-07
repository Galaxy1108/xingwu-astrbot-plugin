<template>
  <div>
    <PageHeader title="Bot 管理" description="查看全部租户的 Bot 元数据，可禁用异常实例。">
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
        <v-table hover>
          <thead>
            <tr>
              <th>Bot</th>
              <th>归属用户</th>
              <th>平台</th>
              <th>状态</th>
              <th>启用</th>
              <th>绑定</th>
              <th>创建时间</th>
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
              <td><StatusChip :status="bot.status" /></td>
              <td>
                <v-icon :color="bot.enabled ? 'success' : 'default'" size="18">
                  {{ bot.enabled ? 'mdi-check-circle' : 'mdi-minus-circle-outline' }}
                </v-icon>
              </td>
              <td>{{ bot.bound ? '已绑定' : '未绑定' }}</td>
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
                  :disabled="!bot.enabled || bot.status === 'deleted'"
                  @click="askDisable(bot)"
                >
                  禁用
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
    </v-card>

    <AdminContentDrawer v-model="contentOpen" :bot="contentTarget" />

    <ConfirmDialog
      v-model="disableOpen"
      :title="`禁用「${disableTarget?.name || ''}」？`"
      :message="`将停用 ${disableTarget?.owner_email || '该用户'} 名下的这个 Bot 平台实例，消息将不再处理。该操作会写入审计日志。`"
      confirm-text="禁用 Bot"
      danger
      :loading="disabling"
      @confirm="confirmDisable"
      @cancel="disableOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
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
const disableOpen = ref(false)
const disableTarget = ref<AdminBot | null>(null)
const disabling = ref(false)

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

function askDisable(bot: AdminBot): void {
  disableTarget.value = bot
  disableOpen.value = true
}

function openContent(bot: AdminBot): void {
  contentTarget.value = { id: bot.id, name: bot.name }
  contentOpen.value = true
}

async function confirmDisable(): Promise<void> {
  if (!disableTarget.value) return
  disabling.value = true
  try {
    await admin.disableBot(disableTarget.value.id)
    disableOpen.value = false
    ui.notify('Bot 已禁用', 'success')
  } catch (error) {
    disableOpen.value = false
    ui.notifyError(errorMessage(error, '禁用 Bot 失败'))
  } finally {
    disabling.value = false
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
