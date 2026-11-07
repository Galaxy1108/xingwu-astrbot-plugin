<template>
  <div>
    <PageHeader title="我的 Bot" description="查看状态、启停与绑定信息；扫码成功后才创建 Bot。">
      <template #actions>
        <v-btn
          variant="tonal"
          color="primary"
          prepend-icon="mdi-robot-outline"
          to="/connect"
          data-testid="open-add-bot"
        >
          添加机器人
        </v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="bots.error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ bots.error.message }}</span>
        <v-btn size="small" variant="text" color="error" :loading="bots.loading" @click="reload">
          重试
        </v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="bots.loading && bots.items.length === 0" variant="card" :rows="3" />

    <EmptyState
      v-else-if="!bots.error && bots.items.length === 0"
      icon="mdi-robot-outline"
      title="还没有 Bot"
      description="添加一个微信或 QQ 机器人，按向导完成创建与扫码绑定。"
    >
      <template #actions>
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-robot-outline" to="/connect">
          添加机器人
        </v-btn>
      </template>
    </EmptyState>

    <template v-else-if="bots.items.length > 0">
      <div v-if="isNarrow" class="bot-cards">
        <v-card v-for="bot in bots.items" :key="bot.id" class="bot-card">
          <div class="bot-card__head">
            <div class="bot-card__title">
              <v-avatar color="primary" variant="tonal" size="36" rounded="lg">
                <v-icon size="18">mdi-robot-outline</v-icon>
              </v-avatar>
              <div class="bot-card__name-wrap">
                <router-link :to="`/bots/${bot.id}`" class="bot-name">{{ bot.name }}</router-link>
                <span class="text-muted bot-meta">
                  {{ platformShortLabel(bot.platform) }} · {{ bot.template_name || '自定义' }}
                </span>
              </div>
            </div>
            <StatusChip :status="bot.status" />
          </div>
          <div class="bot-card__meta">
            <span class="text-muted">创建于 {{ formatRelative(bot.created_at) }}</span>
            <span class="text-muted">
              {{ bot.last_active_at ? `最近活跃 ${formatRelative(bot.last_active_at)}` : '尚未活跃' }}
            </span>
          </div>
          <div class="bot-card__actions">
            <v-btn variant="outlined" size="small" :to="`/bots/${bot.id}`">查看详情</v-btn>
            <v-btn variant="text" size="small" :to="`/bots/${bot.id}/conversations`">
              对话历史
            </v-btn>
          </div>
        </v-card>
      </div>

      <v-card v-else class="bot-table-card">
        <div class="table-scroll">
          <v-table hover class="bots-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>状态</th>
                <th>平台</th>
                <th>模板</th>
                <th>绑定</th>
                <th>创建时间</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="bot in bots.items" :key="bot.id">
                <td>
                  <router-link :to="`/bots/${bot.id}`" class="bot-name">{{ bot.name }}</router-link>
                  <div class="text-muted bot-id text-mono">{{ bot.id }}</div>
                </td>
                <td><StatusChip :status="bot.status" /></td>
                <td>{{ platformShortLabel(bot.platform) }}</td>
                <td>{{ bot.template_name || '—' }}</td>
                <td>
                  <v-icon v-if="bot.bound" color="success" size="18" title="已绑定">mdi-link-variant</v-icon>
                  <span v-else class="text-muted">—</span>
                </td>
                <td class="nowrap">{{ formatDateTime(bot.created_at) }}</td>
                <td class="text-right nowrap">
                  <v-btn size="small" variant="text" :to="`/bots/${bot.id}`">详情</v-btn>
                  <v-btn size="small" variant="text" :to="`/bots/${bot.id}/conversations`">
                    对话
                  </v-btn>
                </td>
              </tr>
            </tbody>
          </v-table>
        </div>
      </v-card>
    </template>

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDisplay } from 'vuetify'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useBotsStore } from '@/stores/bots'
import { formatDateTime, formatRelative, platformShortLabel } from '@/utils/format'

const bots = useBotsStore()
const { smAndDown } = useDisplay()

const isNarrow = computed(() => smAndDown.value)

onMounted(() => {
  void reload()
})

async function reload(): Promise<void> {
  try {
    await bots.fetchBots(true)
  } catch {
    /* store 已记录错误 */
  }
}
</script>

<style scoped>
.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.bot-cards {
  display: grid;
  gap: 12px;
}

.bot-card {
  padding: 16px;
}

.bot-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.bot-card__title {
  display: flex;
  gap: 10px;
  min-width: 0;
}

.bot-card__name-wrap {
  min-width: 0;
}

.bot-name {
  font-weight: 600;
  color: var(--console-text);
}

.bot-name:hover {
  color: var(--console-primary);
}

.bot-meta {
  display: block;
  font-size: 0.78rem;
  margin-top: 2px;
}

.bot-id {
  font-size: 0.72rem;
  margin-top: 2px;
}

.bot-card__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.78rem;
  margin: 12px 0;
}

.bot-card__actions {
  display: flex;
  gap: 8px;
}

.bot-table-card {
  padding: 4px 0;
}

.bots-table {
  min-width: 900px;
}

.bots-table :deep(th) {
  white-space: nowrap;
}

.table-scroll {
  overflow-x: auto;
}

.nowrap {
  white-space: nowrap;
}
</style>
