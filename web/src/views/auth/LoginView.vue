<template>
  <div class="login-view">
    <div class="login-head">
      <h1 class="login-title">登录控制台</h1>
      <p class="login-subtitle">使用邮箱验证码登录；首次注册需要邀请码。</p>
    </div>

    <v-alert
      v-if="formError"
      type="error"
      variant="tonal"
      density="compact"
      class="mb-4"
      data-testid="login-error"
    >
      {{ formError }}
    </v-alert>
    <v-alert v-if="devCode" type="info" variant="tonal" density="compact" class="mb-4">
      开发环境验证码：<strong class="text-mono">{{ devCode }}</strong>
    </v-alert>

    <v-form v-if="step === 'request'" @submit.prevent="onRequest">
      <v-text-field
        v-model.trim="email"
        label="邮箱"
        type="email"
        autocomplete="email"
        inputmode="email"
        prepend-inner-icon="mdi-email-outline"
        :error-messages="emailError"
        :disabled="loading"
        autofocus
      />
      <div class="invite-toggle">
        <v-btn variant="text" size="small" color="primary" @click="showInvite = !showInvite">
          {{ showInvite ? '隐藏邀请码' : '首次注册？填写邀请码' }}
        </v-btn>
      </div>
      <v-expand-transition>
        <v-text-field
          v-if="showInvite"
          v-model.trim="invite"
          label="邀请码（仅新用户需要）"
          prepend-inner-icon="mdi-ticket-outline"
          :error-messages="inviteError"
          hint="已注册账号可留空"
          persistent-hint
        />
      </v-expand-transition>
      <v-btn
        type="submit"
        block
        color="primary"
        size="large"
        class="mt-4"
        :loading="loading"
        data-testid="login-request"
      >
        发送验证码
      </v-btn>
    </v-form>

    <v-form v-else @submit.prevent="onVerify">
      <p class="sent-hint">
        验证码已发送至 <strong>{{ email }}</strong>（10 分钟内有效）
      </p>
      <v-text-field
        v-model.trim="code"
        label="6 位验证码"
        inputmode="numeric"
        maxlength="6"
        autocomplete="one-time-code"
        prepend-inner-icon="mdi-shield-key-outline"
        :error-messages="codeError"
        :disabled="loading"
        autofocus
      />
      <v-expand-transition>
        <v-text-field
          v-if="showInvite"
          v-model.trim="invite"
          label="邀请码（新用户必填）"
          prepend-inner-icon="mdi-ticket-outline"
          :error-messages="inviteError"
        />
      </v-expand-transition>
      <v-btn
        type="submit"
        block
        color="primary"
        size="large"
        class="mt-4"
        :loading="loading"
        :disabled="code.length < 6"
        data-testid="login-verify"
      >
        验证并登录
      </v-btn>
      <div class="login-actions">
        <v-btn variant="text" size="small" :disabled="loading" @click="backToEmail">更换邮箱</v-btn>
        <v-btn
          variant="text"
          size="small"
          :disabled="countdown > 0 || loading"
          @click="resend"
        >
          {{ countdown > 0 ? `重新发送（${countdown}s）` : '重新发送' }}
        </v-btn>
      </div>
    </v-form>

    <p class="login-foot text-muted">
      会话使用 HttpOnly Cookie 保存；如邀请码不可用，请联系管理员。
    </p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { errorCode, errorMessage, isFieldError } from '@/utils/errors'
import type { ApiError } from '@/api/client'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const step = ref<'request' | 'verify'>('request')
const email = ref('')
const invite = ref('')
const showInvite = ref(false)
const code = ref('')
const loading = ref(false)
const formError = ref('')
const emailError = ref('')
const codeError = ref('')
const inviteError = ref('')
const devCode = ref('')
const countdown = ref(0)

let timer: ReturnType<typeof setInterval> | null = null

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

onMounted(() => {
  if (auth.isAuthenticated) {
    void router.replace('/')
  }
})

onBeforeUnmount(() => {
  stopCountdown()
})

function stopCountdown(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function startCountdown(seconds: number): void {
  stopCountdown()
  countdown.value = Math.max(0, Math.floor(seconds || 60))
  if (countdown.value <= 0) return
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) stopCountdown()
  }, 1000)
}

function clearErrors(): void {
  formError.value = ''
  emailError.value = ''
  codeError.value = ''
  inviteError.value = ''
}

function isInviteError(error: unknown): boolean {
  const codeName = errorCode(error)
  return typeof codeName === 'string' && codeName.startsWith('invite_')
}

function handleError(error: unknown): void {
  const codeName = errorCode(error)
  if (isFieldError(error, 'email')) emailError.value = errorMessage(error)
  if (isFieldError(error, 'code')) codeError.value = '验证码无效或已过期'
  if (isFieldError(error, 'invite') || isInviteError(error)) {
    showInvite.value = true
    inviteError.value = '邀请码无效、已过期或已用尽'
  }
  if (codeName === 'otp_rate_limited') {
    formError.value = '验证码发送过于频繁，请稍后再试'
    startCountdown(60)
    return
  }
  if (codeName === 'otp_invalid') {
    codeError.value = '验证码无效或已过期，请重新获取'
    return
  }
  if (codeName === 'otp_attempts_exceeded') {
    codeError.value = '验证次数过多，请重新获取验证码'
    return
  }
  if (!emailError.value && !codeError.value && !inviteError.value) {
    formError.value = errorMessage(error, '登录失败，请稍后重试')
  }
}

async function onRequest(): Promise<void> {
  clearErrors()
  devCode.value = ''
  if (!EMAIL_PATTERN.test(email.value)) {
    emailError.value = '请输入有效的邮箱地址'
    return
  }
  loading.value = true
  try {
    const result = await auth.loginRequest(email.value, invite.value || undefined)
    devCode.value = result.dev_code ?? ''
    step.value = 'verify'
    startCountdown(result.resend_after ?? 60)
  } catch (error) {
    handleError(error)
  } finally {
    loading.value = false
  }
}

async function onVerify(): Promise<void> {
  clearErrors()
  if (code.value.length !== 6) {
    codeError.value = '请输入 6 位验证码'
    return
  }
  loading.value = true
  try {
    await auth.loginVerify({
      email: email.value,
      code: code.value,
      invite: invite.value || undefined,
    })
    await router.replace(safeRedirect())
  } catch (error) {
    handleError(error)
  } finally {
    loading.value = false
  }
}

async function resend(): Promise<void> {
  clearErrors()
  loading.value = true
  try {
    const result = await auth.loginRequest(email.value, invite.value || undefined)
    devCode.value = result.dev_code ?? ''
    startCountdown(result.resend_after ?? 60)
  } catch (error) {
    handleError(error)
  } finally {
    loading.value = false
  }
}

function backToEmail(): void {
  clearErrors()
  code.value = ''
  step.value = 'request'
}

function safeRedirect(): string {
  const raw = route.query.redirect
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) return value
  return '/'
}
</script>

<style scoped>
.login-view {
  padding: 28px;
}

.login-head {
  margin-bottom: 20px;
}

.login-title {
  margin: 0;
  font-size: 1.3rem;
  font-weight: 650;
}

.login-subtitle {
  margin: 6px 0 0;
  font-size: 0.85rem;
  color: var(--console-text-muted);
  line-height: 1.6;
}

.invite-toggle {
  margin: 2px 0 6px;
}

.sent-hint {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: var(--console-text-muted);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.login-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
}

.login-foot {
  margin: 20px 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
}

@media (max-width: 599px) {
  .login-view {
    padding: 20px;
  }
}
</style>
