<template>
  <div class="banned-page">
    <div class="banned-shell">
      <div class="brand-row">
        <v-icon color="error" size="30">mdi-account-cancel-outline</v-icon>
        <span class="brand-name">星坞 Xingwu</span>
      </div>

      <v-card class="banned-card">
        <div class="banned-head">
          <h1 class="banned-title">账号已被封禁</h1>
          <p class="banned-sub text-muted">
            {{ auth.user?.email || '—' }} · 你仍可查看本页并提交申诉
          </p>
        </div>

        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
          {{ error }}
        </v-alert>

        <div class="status-box">
          <div class="status-row">
            <span class="status-label text-muted">封禁原因</span>
            <span class="status-value">{{ reason || '管理员未填写原因' }}</span>
          </div>
          <div class="status-row">
            <span class="status-label text-muted">封禁时间</span>
            <span class="status-value">{{ changedAt ? formatDateTime(changedAt) : '—' }}</span>
          </div>
        </div>

        <v-alert
          v-if="balance > 0"
          type="warning"
          variant="tonal"
          density="compact"
          class="mt-3"
        >
          账号仍有 <strong>{{ formatNumber(balance) }}</strong> 点余额。封禁不会自动清除点数；
          如对处理有异议，可在申诉中说明。
        </v-alert>

        <v-alert
          v-if="pendingAppeal || submitted"
          type="success"
          variant="tonal"
          class="mt-3"
          data-testid="banned-appeal-submitted"
        >
          申诉已提交，等待管理员处理。处理结果会更新到下方历史记录。
        </v-alert>

        <template v-else>
          <h2 class="section-title mt-5">提交申诉</h2>
          <p class="section-desc text-muted">
            请说明你认为需要复核的情况；申诉会记录在案并通知管理员。
          </p>
          <v-alert v-if="formError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ formError }}
          </v-alert>
          <v-textarea
            v-model.trim="appealReason"
            label="申诉说明"
            rows="4"
            auto-grow
            maxlength="1000"
            counter="1000"
            placeholder="例如：该账号为本人使用，封禁原因可能存在误判……"
            data-testid="banned-appeal-reason"
            class="mt-2"
          />
          <v-btn
            color="primary"
            variant="tonal"
            :loading="submitting"
            :disabled="!appealReason"
            data-testid="banned-appeal-submit"
            @click="submit"
          >
            提交申诉
          </v-btn>
        </template>

        <template v-if="appeals.length">
          <h2 class="section-title mt-6">申诉历史</h2>
          <div class="appeal-list">
            <div v-for="appeal in appeals" :key="String(appeal.id)" class="appeal-item">
              <div class="appeal-main">
                <div class="appeal-reason">{{ appeal.reason }}</div>
                <div class="appeal-meta text-muted">
                  {{ formatDateTime(appeal.created_at) }}
                  <template v-if="appeal.note"> · 管理员备注：{{ appeal.note }}</template>
                </div>
              </div>
              <v-chip :color="appealColor(appeal.status)" variant="tonal" size="small">
                {{ appealLabel(appeal.status) }}
              </v-chip>
            </div>
          </div>
        </template>

        <div class="banned-actions">
          <v-btn variant="text" prepend-icon="mdi-refresh" :loading="refreshing" @click="refreshStatus">
            刷新状态
          </v-btn>
          <v-btn variant="text" prepend-icon="mdi-logout" @click="logout">退出登录</v-btn>
        </div>
      </v-card>

      <p class="foot text-muted">如需帮助，请联系平台管理员；申诉处理结果会同步至本页。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { listMyAppeals, submitAppeal } from '@/api/appeals'
import { getWallet } from '@/api/wallet'
import { toApiError } from '@/api/client'
import type { Appeal } from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatNumber } from '@/utils/format'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()

const reason = computed(() => auth.user?.status_reason || '')
const changedAt = computed(() => auth.user?.status_changed_at || 0)
const pendingAppeal = computed(() => Boolean(auth.user?.pending_appeal))

const balance = ref(0)
const appeals = ref<Appeal[]>([])
const appealReason = ref('')
const submitting = ref(false)
const submitted = ref(false)
const refreshing = ref(false)
const error = ref('')
const formError = ref('')

onMounted(() => {
  if (auth.user?.status === 'active') {
    void router.replace('/')
    return
  }
  void load()
})

async function load(): Promise<void> {
  await Promise.allSettled([loadBalance(), loadAppeals()])
}

async function loadBalance(): Promise<void> {
  try {
    const wallet = await getWallet()
    balance.value = wallet.balance ?? 0
  } catch {
    balance.value = 0
  }
}

async function loadAppeals(): Promise<void> {
  try {
    const result = await listMyAppeals()
    appeals.value = result.items ?? []
  } catch (err) {
    const apiError = toApiError(err)
    if (apiError.status !== 404 && apiError.status !== 405) {
      error.value = errorMessage(apiError, '加载申诉记录失败')
    }
  }
}

async function submit(): Promise<void> {
  formError.value = ''
  const text = appealReason.value.trim()
  if (!text) {
    formError.value = '请填写申诉说明'
    return
  }
  submitting.value = true
  try {
    await submitAppeal({ target_type: 'user', reason: text })
    submitted.value = true
    appealReason.value = ''
    ui.notify('申诉已提交，等待管理员处理', 'success')
    await loadAppeals()
  } catch (err) {
    const apiError = toApiError(err)
    formError.value =
      apiError.status === 404 || apiError.status === 405
        ? '申诉接口尚未就绪，请稍后再试或联系管理员。'
        : errorMessage(apiError, '提交申诉失败')
  } finally {
    submitting.value = false
  }
}

async function refreshStatus(): Promise<void> {
  refreshing.value = true
  try {
    await auth.fetchMe()
    if (auth.user?.status === 'active') {
      ui.notify('账号已恢复，正在返回控制台', 'success')
      await router.replace('/')
      return
    }
    await load()
    ui.notify('状态已刷新', 'info')
  } finally {
    refreshing.value = false
  }
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace('/login')
}

function appealLabel(status: string): string {
  if (status === 'approved') return '已通过'
  if (status === 'rejected') return '已拒绝'
  return '待处理'
}

function appealColor(status: string): string {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'error'
  return 'warning'
}
</script>

<style scoped>
.banned-page {
  min-height: 100vh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  box-sizing: border-box;
  background: var(--console-bg);
  color: var(--console-text);
}

.banned-shell {
  width: 100%;
  max-width: 680px;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  padding-left: 4px;
}

.brand-name {
  font-size: 15px;
  font-weight: 650;
}

.banned-card {
  padding: 24px;
  background: var(--console-surface);
  border: 1px solid var(--console-border);
  border-radius: 12px;
}

.banned-head {
  margin-bottom: 16px;
}

.banned-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}

.banned-sub {
  margin: 4px 0 0;
  font-size: 12.5px;
  overflow-wrap: anywhere;
}

.status-box {
  padding: 12px 14px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
  background: var(--console-surface-variant);
}

.status-row {
  display: flex;
  gap: 12px;
  padding: 4px 0;
  font-size: 13px;
}

.status-label {
  flex: 0 0 72px;
}

.status-value {
  flex: 1;
  overflow-wrap: anywhere;
}

.section-title {
  font-size: 14px;
  font-weight: 650;
  margin: 0 0 4px;
}

.section-desc {
  margin: 0 0 8px;
  font-size: 12.5px;
  line-height: 1.6;
}

.appeal-list {
  border: 1px solid var(--console-border);
  border-radius: 8px;
  overflow: hidden;
}

.appeal-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--console-border);
}

.appeal-item:last-child {
  border-bottom: none;
}

.appeal-main {
  flex: 1;
  min-width: 0;
}

.appeal-reason {
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.appeal-meta {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.5;
}

.banned-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid var(--console-border);
}

.foot {
  margin: 14px 0 0;
  text-align: center;
  font-size: 11.5px;
}

@media (max-width: 599px) {
  .banned-page {
    padding: 20px 12px;
  }

  .banned-card {
    padding: 18px;
  }
}
</style>
