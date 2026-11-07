<template>
  <div>
    <PageHeader title="我的 Bot" description="查看状态、启停与扫码接入；删除等危险操作在详情页。">
      <template #actions>
        <v-btn variant="tonal" color="primary" prepend-icon="mdi-qrcode-scan" to="/connect">扫码接入</v-btn>
        <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate" variant="tonal">新建 Bot</v-btn>
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
      description="扫码接入一个微信或 QQ 机器人，或先创建 Bot 稍后再扫码。"
      :actions="[
        { label: '扫码接入', to: '/connect' },
        { label: '新建 Bot', variant: 'tonal', onClick: openCreate },
      ]"
    />

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
                <span class="text-muted bot-meta">{{ platformShortLabel(bot.platform) }} · {{ bot.template_name || '自定义' }}</span>
              </div>
            </div>
            <StatusChip :status="bot.status" />
          </div>
          <div class="bot-card__meta">
            <span class="text-muted">创建于 {{ formatRelative(bot.created_at) }}</span>
            <span class="text-muted">{{ bot.last_active_at ? `最近活跃 ${formatRelative(bot.last_active_at)}` : '尚未活跃' }}</span>
          </div>
          <div class="bot-card__actions">
            <v-btn variant="outlined" size="small" :to="`/bots/${bot.id}`">查看详情</v-btn>
            <v-btn
              v-if="bot.status === 'pending_qr'"
              color="primary"
              variant="tonal"
              size="small"
              :to="`/bots/${bot.id}?qr=1`"
            >
              继续扫码
            </v-btn>
          </div>
        </v-card>
      </div>

      <v-card v-else class="bot-table-card">
        <div class="table-scroll">
          <v-table hover>
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
                  <span v-else class="text-muted">未绑定</span>
                </td>
                <td class="nowrap">{{ formatDateTime(bot.created_at) }}</td>
                <td class="text-right">
                  <v-btn size="small" variant="text" :to="`/bots/${bot.id}`">详情</v-btn>
                  <v-btn
                    v-if="bot.status === 'pending_qr'"
                    size="small"
                    variant="text"
                    color="primary"
                    :to="`/bots/${bot.id}?qr=1`"
                  >
                    继续扫码
                  </v-btn>
                </td>
              </tr>
            </tbody>
          </v-table>
        </div>
      </v-card>
    </template>

    <v-dialog v-model="createOpen" max-width="540" persistent>
      <v-card class="create-dialog">
        <v-card-title class="create-title">新建 Bot</v-card-title>
        <v-card-text>
          <v-alert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ createError }}
          </v-alert>
          <v-alert
            v-if="templatesError"
            type="warning"
            variant="tonal"
            density="compact"
            class="mb-3"
          >
            <div class="alert-row">
              <span>{{ templatesError }}</span>
              <v-btn size="small" variant="text" @click="loadTemplates">重试</v-btn>
            </div>
          </v-alert>
          <v-text-field
            v-model.trim="createName"
            label="Bot 名称"
            counter="32"
            maxlength="32"
            :error-messages="createNameError"
            hint="仅作为展示名，之后可修改"
            persistent-hint
            autofocus
          />
          <v-select
            v-model="createPlatform"
            label="平台"
            :items="platformOptions"
            item-title="title"
            item-value="value"
            class="mt-4"
          />
          <v-select
            v-model="createTemplateId"
            label="模板"
            :items="templates"
            item-title="name"
            item-value="id"
            :loading="templatesLoading"
            no-data-text="暂无可用模板"
            :error-messages="createTemplateError"
            class="mt-4"
          >
            <template #append-item>
              <div v-if="selectedTemplate?.description" class="template-hint text-muted">
                {{ selectedTemplate.description }}
              </div>
            </template>
          </v-select>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="creating" @click="createOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="creating" @click="submitCreate" variant="tonal">创建</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import PageHeader from '@/components/PageHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useBotsStore } from '@/stores/bots'
import { useUiStore } from '@/stores/ui'
import { listTemplates } from '@/api/wallet'
import { toApiError } from '@/api/client'
import type { Platform, Template } from '@/types'
import { errorMessage, fieldError } from '@/utils/errors'
import { formatDateTime, formatRelative, platformShortLabel } from '@/utils/format'

const bots = useBotsStore()
const ui = useUiStore()
const router = useRouter()
const { smAndDown } = useDisplay()

const isNarrow = computed(() => smAndDown.value)

const platformOptions: Array<{ title: string; value: Platform }> = [
  { title: '微信（个人号 · 官方接口）', value: 'weixin_oc' },
  { title: 'QQ 官方机器人', value: 'qq_official' },
]

const templates = ref<Template[]>([])
const templatesLoading = ref(false)
const templatesError = ref('')

const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const createName = ref('')
const createNameError = ref('')
const createPlatform = ref<Platform>('weixin_oc')
const createTemplateId = ref('')
const createTemplateError = ref('')

const selectedTemplate = computed(() =>
  templates.value.find((template) => template.id === createTemplateId.value),
)

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

async function loadTemplates(): Promise<void> {
  templatesLoading.value = true
  templatesError.value = ''
  try {
    const result = await listTemplates()
    templates.value = result.items ?? []
    if (!createTemplateId.value && templates.value.length > 0) {
      createTemplateId.value = templates.value[0].id
    }
  } catch (error) {
    templatesError.value = errorMessage(error, '加载模板失败')
  } finally {
    templatesLoading.value = false
  }
}

function openCreate(): void {
  createOpen.value = true
  createError.value = ''
  createNameError.value = ''
  createTemplateError.value = ''
  if (templates.value.length === 0) void loadTemplates()
}

async function submitCreate(): Promise<void> {
  createError.value = ''
  createNameError.value = ''
  createTemplateError.value = ''
  const name = createName.value.trim()
  if (!name) {
    createNameError.value = '请输入 Bot 名称'
    return
  }
  if (name.length > 32) {
    createNameError.value = '名称最多 32 个字符'
    return
  }
  if (!createTemplateId.value) {
    createTemplateError.value = '请选择模板'
    return
  }

  creating.value = true
  try {
    const bot = await bots.createBot({
      name,
      template_id: createTemplateId.value,
      platform: createPlatform.value,
    })
    createOpen.value = false
    ui.notify(`已创建「${bot.name}」，请继续扫码接入`, 'success')
    await router.push(`/bots/${bot.id}?qr=1`)
  } catch (error) {
    const apiError = toApiError(error)
    if (fieldError(apiError, 'name')) createNameError.value = apiError.message
    if (fieldError(apiError, 'template_id')) createTemplateError.value = apiError.message
    createError.value = apiError.message
  } finally {
    creating.value = false
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

.table-scroll {
  overflow-x: auto;
}

.nowrap {
  white-space: nowrap;
}

.create-dialog {
  padding: 8px;
}

.create-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

.template-hint {
  font-size: 0.78rem;
  padding: 4px 16px 8px;
  line-height: 1.5;
}
</style>
