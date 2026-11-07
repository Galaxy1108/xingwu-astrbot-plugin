<template>
  <div>
    <PageHeader
      :title="pageTitle"
      description="查看该 Bot 的对话历史；分享链接为只读，可随时撤销。"
      :back-to="`/bots/${botId}`"
    >

    </PageHeader>

    <BotTabs :bot-id="botId" active="conversations" />

    <div class="content-toolbar">
      <span class="text-muted toolbar-hint">只读对话历史与分享链接</span>
      <v-spacer />
      <v-btn size="small" variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">
        刷新
      </v-btn>
    </div>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !items.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!error && items.length === 0"
      icon="mdi-chat-processing-outline"
      title="暂无对话历史"
      description="Bot 产生对话后会显示在这里；分享功能可用于把只读对话发给他人。"
    />

    <v-card v-else-if="items.length" class="table-card">
      <div class="table-head">
        <span class="text-muted">共 {{ total }} 个会话 · 当前第 {{ page }} 页</span>
      </div>
      <div class="table-scroll">
        <v-table hover class="conversations-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>消息数</th>
              <th>创建时间</th>
              <th>分享</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id" data-testid="conversation-row">
              <td class="title-cell">
                <button type="button" class="title-link" @click="openConversation(item)">
                  {{ item.title || '未命名会话' }}
                </button>
                <div class="text-mono text-muted conv-id">{{ item.id }}</div>
              </td>
              <td class="nowrap">{{ messageCount(item) }} 条</td>
              <td class="nowrap">{{ formatDateTime(item.created_at) }}</td>
              <td>
                <v-chip v-if="shareOf(item)" size="small" variant="tonal" color="success">已分享</v-chip>
                <span v-else class="text-muted">—</span>
              </td>
              <td class="text-right nowrap">
                <v-btn size="small" variant="text" @click="openConversation(item)">查看</v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
      <div v-if="total > pageSize" class="pager">
        <v-pagination
          :model-value="page"
          :length="pageCount"
          :total-visible="5"
          density="comfortable"
          @update:model-value="onPage"
        />
      </div>
    </v-card>

    <v-dialog v-model="detailOpen" max-width="860" scrollable>
      <v-card class="detail-card">
        <v-card-title class="detail-title">
          <span>{{ selected?.title || '对话详情' }}</span>
          <v-btn icon variant="text" aria-label="关闭对话详情" @click="detailOpen = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </v-card-title>
        <v-divider />
        <v-card-text class="detail-body">
          <v-alert v-if="detailError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ detailError }}
          </v-alert>
          <LoadingSkeleton v-if="detailLoading" variant="list" :rows="4" />
          <template v-else-if="messages.length">
            <ConversationMessages :messages="messages" />
          </template>
          <EmptyState
            v-else-if="!detailError"
            icon="mdi-message-off-outline"
            title="该会话没有消息"
            description="历史内容为空，或已被清理。"
          />

          <v-divider class="my-5" />
          <div class="share-section">
            <div class="share-head">
              <div>
                <div class="share-title">分享只读链接</div>
                <div class="share-desc text-muted">
                  分享链接可被任何人查看且不需要登录；可随时撤销。
                </div>
              </div>
              <v-chip v-if="currentShare" size="small" variant="tonal" color="success">
                已分享
              </v-chip>
            </div>
            <v-alert v-if="shareError" type="error" variant="tonal" density="compact" class="mt-3">
              {{ shareError }}
            </v-alert>
            <div class="share-actions">
              <v-select
                v-model="expiresHours"
                :items="expireOptions"
                label="有效期"
                density="compact"
                hide-details
                class="share-expire"
                :disabled="Boolean(currentShare)"
              />
              <v-btn
                v-if="!currentShare"
                color="primary"
                variant="tonal"
                :loading="sharing"
                data-testid="conversation-share"
                @click="share"
              >
                创建分享链接
              </v-btn>
              <v-btn
                v-else
                color="primary"
                variant="tonal"
                data-testid="conversation-share-manage"
                @click="shareOpen = true"
              >
                管理分享链接
              </v-btn>
            </div>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="detailOpen = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="shareOpen" max-width="560">
      <v-card class="share-dialog">
        <v-card-title class="share-dialog-title">分享链接</v-card-title>
        <v-card-text>
          <v-alert v-if="shareError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ shareError }}
          </v-alert>
          <v-text-field
            :model-value="currentShare?.url || ''"
            label="只读链接"
            readonly
            density="compact"
            data-testid="conversation-share-url"
          >
            <template #append-inner>
              <v-btn icon size="small" variant="text" aria-label="复制分享链接" @click="copyShare">
                <v-icon size="18">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
              </v-btn>
            </template>
          </v-text-field>
          <p class="share-meta text-muted">
            {{ currentShare?.expires_at ? `过期时间：${formatDateTime(currentShare.expires_at)}` : '永久有效' }}
          </p>
        </v-card-text>
        <v-card-actions>
          <v-btn
            variant="text"
            color="error"
            :loading="revoking"
            data-testid="conversation-share-revoke"
            @click="revoke"
          >
            撤销分享
          </v-btn>
          <v-spacer />
          <v-btn color="primary" variant="tonal" @click="shareOpen = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import BotTabs from '@/components/BotTabs.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConversationMessages from '@/components/ConversationMessages.vue'
import { useBotsStore } from '@/stores/bots'
import { useUiStore } from '@/stores/ui'
import { useClipboard } from '@/composables/useClipboard'
import {
  getConversation,
  listConversations,
  revokeConversationShare,
  shareConversation,
} from '@/api/conversations'
import { toApiError } from '@/api/client'
import type { ConversationMessage, ConversationShare, ConversationSummary } from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const bots = useBotsStore()
const ui = useUiStore()
const { copied, copy } = useClipboard()

const botId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const bot = computed(() => (bots.current?.id === botId.value ? bots.current : null))
const pageTitle = computed(() => (bot.value ? `${bot.value.name} · 对话历史` : '对话历史'))

const items = ref<ConversationSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')

const detailOpen = ref(false)
const selected = ref<ConversationSummary | null>(null)
const messages = ref<ConversationMessage[]>([])
const detailLoading = ref(false)
const detailError = ref('')

const shareOpen = ref(false)
const currentShare = ref<ConversationShare | null>(null)
const shares = ref<Record<string, ConversationShare>>({})
const expiresHours = ref(0)
const sharing = ref(false)
const revoking = ref(false)
const shareError = ref('')

const expireOptions = [
  { title: '永久有效', value: 0 },
  { title: '24 小时', value: 24 },
  { title: '7 天', value: 168 },
]

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))
const selectedId = computed(() => selected.value?.id || '')

onMounted(() => {
  page.value = readPage()
  void bots.loadBot(botId.value).catch(() => undefined)
  void load()
})

function readPage(): number {
  const raw = route.query.page
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  if (!botId.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await listConversations(botId.value, page.value, pageSize.value)
    items.value = result.items ?? []
    total.value = result.total ?? 0
    page.value = result.page ?? page.value
    pageSize.value = result.page_size ?? pageSize.value
    for (const item of items.value) {
      if (item.share) shares.value[item.id] = item.share
    }
  } catch (err) {
    const apiError = toApiError(err)
    error.value =
      apiError.status === 404 || apiError.status === 405
        ? '对话历史接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载对话历史失败')
  } finally {
    loading.value = false
  }
}

async function onPage(next: number): Promise<void> {
  page.value = next
  await router.replace({ query: { ...route.query, page: String(next) } })
  await load()
}

function messageCount(item: ConversationSummary): number {
  if (typeof item.message_count === 'number') return item.message_count
  return Array.isArray(item.history) ? item.history.length : 0
}

function shareOf(item: ConversationSummary): ConversationShare | null {
  return shares.value[item.id] ?? item.share ?? null
}

async function openConversation(item: ConversationSummary): Promise<void> {
  selected.value = item
  messages.value = Array.isArray(item.history) ? item.history : []
  detailError.value = ''
  detailOpen.value = true
  currentShare.value = shareOf(item)
  shareError.value = ''
  detailLoading.value = !messages.value.length
  if (messages.value.length) return
  try {
    const result = await getConversation(botId.value, item.id)
    selected.value = { ...item, ...result.conversation }
    messages.value = result.conversation.history ?? []
    if (result.conversation.share) {
      shares.value[item.id] = result.conversation.share
      currentShare.value = result.conversation.share
    }
  } catch (err) {
    const apiError = toApiError(err)
    detailError.value =
      apiError.status === 404 || apiError.status === 405
        ? '对话详情接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载对话详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function share(): Promise<void> {
  if (!selected.value) return
  shareError.value = ''
  sharing.value = true
  try {
    const result = await shareConversation(
      botId.value,
      selected.value.id,
      expiresHours.value || undefined,
    )
    currentShare.value = result.share
    shares.value[selected.value.id] = result.share
    shareOpen.value = true
    ui.notify('分享链接已创建', 'success')
  } catch (err) {
    const apiError = toApiError(err)
    shareError.value =
      apiError.status === 404 || apiError.status === 405
        ? '分享接口尚未就绪，请稍后重试。'
        : errorMessage(apiError, '创建分享链接失败')
  } finally {
    sharing.value = false
  }
}

async function revoke(): Promise<void> {
  if (!selected.value) return
  revoking.value = true
  shareError.value = ''
  try {
    await revokeConversationShare(botId.value, selected.value.id)
    currentShare.value = null
    delete shares.value[selected.value.id]
    shareOpen.value = false
    ui.notify('分享链接已撤销', 'success')
  } catch (err) {
    shareError.value = errorMessage(err, '撤销分享失败')
  } finally {
    revoking.value = false
  }
}

async function copyShare(): Promise<void> {
  if (!currentShare.value?.url) return
  await copy(currentShare.value.url)
  ui.notify('分享链接已复制', 'success')
}
</script>

<style scoped>
.toolbar-hint {
  font-size: 12px;
}

.table-card {
  padding: 4px 0;
}

.table-head {
  padding: 12px 16px 4px;
  font-size: 0.8rem;
}

.table-scroll {
  overflow-x: auto;
}

.conversations-table {
  min-width: 820px;
}

.conversations-table :deep(th) {
  white-space: nowrap;
}

.title-cell {
  min-width: 220px;
}

.title-link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--console-text);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.title-link:hover {
  color: var(--console-primary);
  text-decoration: underline;
}

.conv-id {
  margin-top: 2px;
  font-size: 0.7rem;
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

.pager {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}

.detail-card {
  padding: 8px;
}

.detail-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 18px;
  font-weight: 650;
  padding: 12px 20px 10px;
}

.detail-body {
  max-height: 66vh;
}

.share-section {
  padding-top: 2px;
}

.share-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.share-title {
  font-size: 14px;
  font-weight: 650;
}

.share-desc {
  margin-top: 2px;
  font-size: 12px;
}

.share-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.share-expire {
  flex: 0 1 180px;
}

.share-dialog {
  padding: 8px;
}

.share-dialog-title {
  font-size: 18px;
  font-weight: 650;
  padding: 12px 20px 0;
}

.share-meta {
  margin: 6px 0 0;
  font-size: 12px;
}
</style>
