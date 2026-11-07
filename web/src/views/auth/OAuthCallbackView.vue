<template>
  <div class="callback-page">
    <div class="callback-card">
      <BrandMark :size="32" />
      <template v-if="loading">
        <v-progress-circular indeterminate color="primary" class="mt-4" />
        <h1 class="callback-title">正在完成登录…</h1>
        <p class="callback-sub text-muted">正在校验第三方账号并建立会话，请稍候。</p>
      </template>
      <template v-else-if="error">
        <v-icon size="48" color="error" class="mt-4">mdi-alert-circle-outline</v-icon>
        <h1 class="callback-title">第三方登录失败</h1>
        <p class="callback-sub text-muted">{{ error }}</p>
        <v-btn color="primary" variant="tonal" class="mt-3" to="/login">返回登录</v-btn>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BrandMark from '@/components/BrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { errorCode, errorMessage } from '@/utils/errors'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const error = ref('')

const ERROR_TEXT: Record<string, string> = {
  oauth_state_invalid: '登录状态已失效，请重新发起登录',
  oauth_code_invalid: '授权码无效，请重新发起登录',
  oauth_provider_error: '第三方平台返回异常，请稍后重试',
  oauth_not_configured: 'GitHub 登录尚未启用',
  oauth_email_unverified: '第三方账号邮箱未验证，无法登录',
  oauth_already_bound: '该 GitHub 账号已绑定其他用户',
  oauth_not_supported: '不支持的第三方登录方式',
}

onMounted(async () => {
  const rawError = route.query.error
  const errorValue = Array.isArray(rawError) ? rawError[0] : rawError
  if (typeof errorValue === 'string' && errorValue) {
    error.value = ERROR_TEXT[errorValue] || '第三方登录失败，请稍后重试'
    loading.value = false
    return
  }
  try {
    const ok = await auth.refreshMe()
    if (!ok || !auth.user) {
      error.value = '登录会话未建立，请返回登录页重试'
      loading.value = false
      return
    }
    if (auth.user.status === 'disabled') {
      await router.replace('/banned')
      return
    }
    await router.replace(safeNext())
  } catch (err) {
    error.value =
      errorCode(err) === 'oauth_state_invalid'
        ? '登录状态已失效，请重新发起登录'
        : errorMessage(err, '第三方登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
})

function safeNext(): string {
  const raw = route.query.next
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) return value
  return '/'
}
</script>

<style scoped>
.callback-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  box-sizing: border-box;
  background: var(--console-bg);
  color: var(--console-text);
}

.callback-card {
  width: 100%;
  max-width: 420px;
  padding: 32px 28px;
  border: 1px solid var(--console-border);
  border-radius: 12px;
  background: var(--console-surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.callback-title {
  margin: 14px 0 0;
  font-size: 20px;
  font-weight: 700;
}

.callback-sub {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
}
</style>
