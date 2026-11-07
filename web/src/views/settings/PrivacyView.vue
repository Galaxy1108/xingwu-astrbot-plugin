<template>
  <div>
    <PageHeader
      title="隐私与加密"
      description="关闭加密会立即解密全部历史数据；开启会重新加密。操作在后台执行，可离开页面。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <v-alert v-if="encryption.state === 'paused'" type="warning" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>上一次{{ directionText }}任务已暂停：{{ encryption.status?.job?.error || '部分数据未能转换' }}</span>
        <v-btn size="small" variant="text" color="warning" @click="retry">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !encryption.status" variant="detail" />

    <template v-else>
      <EncryptionSwitch
        :enabled="encryption.enabled"
        :state="encryption.state"
        :done="encryption.status?.done ?? 0"
        :total="encryption.status?.total ?? 0"
        :eta="encryption.status?.eta ?? null"
        :readonly="false"
        :busy="switching"
        @toggle="onToggle"
      />

      <v-card class="access-card mt-4" data-testid="privacy-access-log">
        <div class="access-head">
          <div>
            <h2 class="section-title">访问记录</h2>
            <p class="access-desc text-muted">
              管理员查看你的对话或记忆时会产生记录；仅在你关闭加密后管理员才可查看内容。
            </p>
          </div>
          <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="accessLoading" @click="loadAccessLog">
            刷新
          </v-btn>
        </div>
        <AccessLogTable
          :items="accessItems"
          :loading="accessLoading"
          :error="accessError"
          :page="accessPage"
          :page-size="accessPageSize"
          :total="accessTotal"
          @retry="loadAccessLog"
          @update:page="onAccessPage"
        />
      </v-card>

      <v-card class="privacy-info mt-4">
        <h2 class="section-title">关于加密</h2>
        <ul class="privacy-list">
          <li>对话与记忆使用租户密钥加密后落盘，密钥由平台根密钥信封加密。</li>
          <li>管理员直接查看明文内容属于受审计操作，会写入访问记录。</li>
          <li>关闭加密后数据将以明文存储，管理员可直接查看（访问仍会留痕）。</li>
          <li>关闭需要逐条确认后果，并输入「确认解密」；重新开启会重新加密全部数据。</li>
          <li>已经产生的备份与导出文件不会因重新开启而自动清除。</li>
        </ul>
        <v-btn variant="text" color="primary" prepend-icon="mdi-arrow-left" to="/">返回总览</v-btn>
      </v-card>
    </template>

    <ConfirmDialog
      v-model="confirmOpen"
      :title="pendingEnabled ? '重新开启加密？' : '关闭加密并解密全部数据？'"
      :message="confirmMessage"
      :confirm-text="pendingEnabled ? '开始加密' : '确认解密'"
      :danger="!pendingEnabled"
      :type-to-confirm="pendingEnabled ? '' : '确认解密'"
      :loading="switching"
      @confirm="onConfirm"
      @cancel="confirmOpen = false"
    >
      <div v-if="!pendingEnabled" class="confirm-list">
        <p>关闭后：</p>
        <ol>
          <li>所有 Bot 的对话记录与记忆将以<strong>明文</strong>保存在服务器上。</li>
          <li>管理员和运维人员可以直接查看这些内容（查看行为仍会被记录）。</li>
          <li>如果数据库、备份或磁盘被泄露，内容可以被直接读取。</li>
          <li>关闭期间产生的新数据同样是明文。</li>
          <li>重新开启会重新加密历史数据，但已经产生的备份和导出文件不会自动清除。</li>
        </ol>
      </div>
      <div v-else class="confirm-list">
        <p>开启后将对该账号全部 Bot 执行：</p>
        <ol>
          <li>对话重新加密（逐条回填）。</li>
          <li>记忆库从普通 SQLite 转为 SQLCipher 加密库。</li>
          <li>平台凭据重新加密保存。</li>
        </ol>
      </div>
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import EncryptionSwitch from '@/components/EncryptionSwitch.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import AccessLogTable from '@/components/AccessLogTable.vue'
import { useEncryptionStore } from '@/stores/encryption'
import { useUiStore } from '@/stores/ui'
import { listAccessLog } from '@/api/privacy'
import type { ApiError } from '@/api/client'
import { errorMessage } from '@/utils/errors'
import type { AccessLogEntry } from '@/types'

const encryption = useEncryptionStore()
const ui = useUiStore()

const loading = ref(false)
const switching = ref(false)
const error = ref('')
const confirmOpen = ref(false)
const pendingEnabled = ref(true)

const accessItems = ref<AccessLogEntry[]>([])
const accessTotal = ref(0)
const accessPage = ref(1)
const accessPageSize = ref(20)
const accessLoading = ref(false)
const accessError = ref<ApiError | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

const directionText = computed(() => (encryption.enabled ? '解密' : '加密'))
const confirmMessage = computed(() =>
  pendingEnabled.value
    ? '将在后台重新加密全部对话、记忆库与凭据，期间服务可用。'
    : '该操作会逐条解密你的对话与记忆，并可能影响正在进行中的会话。',
)

onMounted(() => {
  void Promise.allSettled([load(), loadAccessLog()])
})

onBeforeUnmount(() => {
  stopPolling()
})

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const status = await encryption.fetchStatus()
      if (status.state !== 'decrypting' && status.state !== 'encrypting') {
        stopPolling()
        switching.value = false
        if (status.state === 'plaintext') ui.notify('已关闭加密，全部数据已解密', 'info', 5000)
        else if (status.state === 'encrypted') ui.notify('已重新开启加密', 'success')
        else if (status.state === 'paused') ui.notifyError('任务暂停，请重试或联系管理员')
      }
    } catch {
      stopPolling()
      switching.value = false
    }
  }, 1500)
}

async function loadAccessLog(): Promise<void> {
  accessLoading.value = true
  accessError.value = null
  try {
    const result = await listAccessLog(accessPage.value, accessPageSize.value)
    accessItems.value = result.items ?? []
    accessTotal.value = result.total ?? 0
    accessPage.value = result.page ?? accessPage.value
    accessPageSize.value = result.page_size ?? accessPageSize.value
  } catch (err) {
    accessError.value = err as ApiError
  } finally {
    accessLoading.value = false
  }
}

async function onAccessPage(page: number): Promise<void> {
  accessPage.value = page
  await loadAccessLog()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const status = await encryption.fetchStatus()
    if (status.state === 'decrypting' || status.state === 'encrypting') {
      switching.value = true
      startPolling()
    }
  } catch (err) {
    error.value = errorMessage(err, '加载加密状态失败')
  } finally {
    loading.value = false
  }
}

function onToggle(enabled: boolean): void {
  pendingEnabled.value = enabled
  confirmOpen.value = true
}

async function onConfirm(): Promise<void> {
  confirmOpen.value = false
  switching.value = true
  error.value = ''
  try {
    await encryption.toggle(pendingEnabled.value, pendingEnabled.value ? undefined : '确认解密')
    ui.notify(pendingEnabled.value ? '已开始加密' : '已开始解密', 'info')
    startPolling()
  } catch (err) {
    switching.value = false
    error.value = errorMessage(err, '提交加密任务失败')
  }
}

async function retry(): Promise<void> {
  pendingEnabled.value = !encryption.enabled
  await onConfirm()
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

.access-card {
  padding: 20px;
}

.access-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.access-desc {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.6;
  max-width: 680px;
}

.privacy-info {
  padding: 20px;
}

.privacy-list {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--console-text-muted);
  font-size: 0.85rem;
  line-height: 1.8;
}

.confirm-list {
  color: var(--console-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}

.confirm-list p {
  margin: 0 0 6px;
}

.confirm-list ol {
  margin: 0 0 10px;
  padding-left: 20px;
}
</style>
