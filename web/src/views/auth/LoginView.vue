<template>
  <div class="login-page">
    <aside class="login-aside">
      <div class="aside-top">
        <div class="brand-mark">A</div>
        <span class="brand-word">AstrBot <em>SaaS</em></span>
      </div>

      <div class="aside-main">
        <h1 class="aside-title">把 Bot 托管到<br />AstrBot 云端。</h1>
        <p class="aside-sub">
          一台 AstrBot，托管你的所有机器人。扫码接入微信 / QQ，记忆加密存储，额度与用量一目了然。
        </p>
        <ul class="aside-list">
          <li v-for="feature in features" :key="feature.title">
            <v-icon size="18" color="white">{{ feature.icon }}</v-icon>
            <div>
              <div class="li-title">{{ feature.title }}</div>
              <div class="li-desc">{{ feature.desc }}</div>
            </div>
          </li>
        </ul>
      </div>

      <div class="aside-foot">© 2026 AstrBot SaaS · 内测阶段，仅限受邀用户</div>
    </aside>

    <main class="login-main">
      <div class="login-box">
        <div class="mobile-brand">
          <div class="brand-mark">A</div>
          <span class="brand-word">AstrBot <em>SaaS</em></span>
        </div>

        <h2 class="login-title">{{ step === 'email' ? '登录控制台' : '输入验证码' }}</h2>
        <p class="login-sub">
          {{
            step === 'email'
              ? '使用邮箱收取一次性验证码，无需密码。'
              : `验证码已发送至 ${email}（10 分钟内有效）`
          }}
        </p>

        <v-alert
          v-if="formError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4 login-alert"
          data-testid="login-error"
        >
          {{ formError }}
        </v-alert>
        <v-alert v-if="devCode" type="info" variant="tonal" density="compact" class="mb-4 login-alert">
          开发环境验证码：<strong class="text-mono">{{ devCode }}</strong>
        </v-alert>

        <template v-if="step === 'email'">
          <v-text-field
            v-model.trim="email"
            label="邮箱"
            placeholder="you@example.com"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-email-outline"
            :error-messages="emailError"
            hide-details="auto"
            class="mb-3"
            @keyup.enter="onRequest"
          />

          <v-text-field
            v-if="mode === 'register'"
            v-model.trim="invite"
            label="邀请码"
            placeholder="INV-XXXX-XXXX"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-ticket-confirmation-outline"
            hint="内测阶段仅限受邀用户注册"
            persistent-hint
            :error-messages="inviteError"
            class="mb-4"
          />

          <v-btn
            block
            color="primary"
            size="large"
            variant="flat"
            :loading="loading"
            class="mt-4"
            data-testid="login-request"
            @click="onRequest"
          >
            发送验证码
          </v-btn>

          <div class="mode-switch text-body-2">
            <span class="muted">{{ mode === 'login' ? '还没有账号？' : '已有账号？' }}</span>
            <v-btn variant="text" size="small" color="primary" class="px-1" @click="toggleMode">
              {{ mode === 'login' ? '用邀请码注册' : '直接登录' }}
            </v-btn>
          </div>
        </template>

        <template v-else>
          <div class="otp-label">6 位验证码</div>
          <div class="otp-row" @paste.prevent="onPaste">
            <input
              v-for="(digit, index) in digits"
              :key="index"
              :ref="(el) => (inputs[index] = el as HTMLInputElement)"
              :value="digit"
              class="otp-cell"
              :class="{ 'otp-cell--error': !!codeError }"
              inputmode="numeric"
              autocomplete="one-time-code"
              maxlength="1"
              :aria-label="`验证码第 ${index + 1} 位`"
              @input="onInput(index, $event)"
              @keydown.backspace.prevent="onBackspace(index)"
              @keydown.left.prevent="focusPrev(index)"
              @keydown.right.prevent="focusNext(index)"
            />
          </div>
          <p v-if="codeError" class="otp-hint otp-hint--error">{{ codeError }}</p>
          <p v-else class="otp-hint">输入满 6 位即可登录，支持直接粘贴。</p>

          <v-expand-transition>
            <v-text-field
              v-if="needsInvite"
              v-model.trim="invite"
              label="邀请码（新用户必填）"
              prepend-inner-icon="mdi-ticket-confirmation-outline"
              :error-messages="inviteError"
              hint="仅首次注册需要；已有账号可直接登录"
              persistent-hint
              class="mt-4"
            />
          </v-expand-transition>

          <v-btn
            block
            color="primary"
            size="large"
            variant="flat"
            class="mt-6"
            :loading="loading"
            data-testid="login-verify"
            @click="onVerify"
          >
            验证并登录
          </v-btn>

          <div class="resend-row text-body-2">
            <v-btn variant="text" size="small" class="px-1" @click="backToEmail">换个邮箱</v-btn>
            <span class="muted">{{ countdown > 0 ? `${countdown}s 后可重发` : '' }}</span>
            <v-btn
              variant="text"
              size="small"
              color="primary"
              class="px-1"
              :disabled="countdown > 0 || loading"
              @click="resend"
            >
              重新发送
            </v-btn>
          </div>
        </template>

        <v-divider class="my-6" />
        <p class="terms muted">
          登录即表示同意
          <a href="#" @click.prevent>服务条款</a> 与 <a href="#" @click.prevent>隐私政策</a>。
        </p>
        <p class="version muted">AstrBot SaaS {{ auth.version || '0.4.0' }} · 加密记忆库</p>
      </div>
    </main>

    <v-snackbar v-model="toast.show" :timeout="2400" location="top" rounded="lg" color="error">
      {{ toast.text }}
    </v-snackbar>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { errorCode, errorMessage, isFieldError } from '@/utils/errors'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const features = [
  { icon: 'mdi-robot-outline', title: '一人多 Bot', desc: '每个 Bot 独立人格、配置与平台实例。' },
  { icon: 'mdi-qrcode-scan', title: '扫码即接入', desc: '微信个人号 / QQ 官方，手机确认即可上线。' },
  { icon: 'mdi-shield-lock-outline', title: '加密与留痕', desc: '记忆库 SQLCipher 加密，管理员访问留痕。' },
]

const mode = ref<'login' | 'register'>('login')
const step = ref<'email' | 'code'>('email')
const email = ref('')
const invite = ref('')
const digits = reactive(['', '', '', '', '', ''])
const inputs: HTMLInputElement[] = []
const loading = ref(false)
const emailError = ref('')
const inviteError = ref('')
const codeError = ref('')
const formError = ref('')
const devCode = ref('')
const countdown = ref(0)
const needsInvite = ref(false)
const toast = reactive({ show: false, text: '' })

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

function toggleMode(): void {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  emailError.value = ''
  inviteError.value = ''
}

function clearErrors(): void {
  formError.value = ''
  emailError.value = ''
  inviteError.value = ''
  codeError.value = ''
}

function handleError(error: unknown): void {
  const codeName = errorCode(error)
  if (isFieldError(error, 'email')) emailError.value = errorMessage(error)
  if (isFieldError(error, 'code')) codeError.value = '验证码无效或已过期'
  if (isFieldError(error, 'invite') || (typeof codeName === 'string' && codeName.startsWith('invite_'))) {
    needsInvite.value = true
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
  if (mode.value === 'register' && !invite.value.trim()) {
    inviteError.value = '内测阶段需要邀请码'
    return
  }
  loading.value = true
  try {
    const result = await auth.loginRequest(
      email.value,
      mode.value === 'register' ? invite.value.trim() || undefined : undefined,
    )
    devCode.value = result.dev_code ?? ''
    step.value = 'code'
    needsInvite.value = false
    startCountdown(result.resend_after ?? 60)
    await nextTick()
    inputs[0]?.focus()
  } catch (error) {
    handleError(error)
  } finally {
    loading.value = false
  }
}

function focusNext(index: number): void {
  inputs[Math.min(index + 1, 5)]?.focus()
}

function focusPrev(index: number): void {
  inputs[Math.max(index - 1, 0)]?.focus()
}

function onInput(index: number, event: Event): void {
  const target = event.target as HTMLInputElement
  const value = target.value.replace(/\D/g, '').slice(-1)
  digits[index] = value
  target.value = value
  codeError.value = ''
  if (value && index < 5) focusNext(index)
  if (digits.join('').length === 6) void onVerify()
}

function onBackspace(index: number): void {
  if (digits[index]) {
    digits[index] = ''
    return
  }
  focusPrev(index)
  digits[Math.max(index - 1, 0)] = ''
}

function onPaste(event: ClipboardEvent): void {
  const text = (event.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, 6)
  for (let index = 0; index < 6; index += 1) digits[index] = text[index] || ''
  codeError.value = ''
  inputs[Math.min(text.length, 5)]?.focus()
  if (text.length === 6) void onVerify()
}

async function onVerify(): Promise<void> {
  clearErrors()
  const code = digits.join('')
  if (code.length !== 6) {
    codeError.value = `请输入完整的 6 位验证码（当前 ${code.length} 位）`
    return
  }
  loading.value = true
  try {
    await auth.loginVerify({
      email: email.value,
      code,
      invite: invite.value.trim() || undefined,
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
    const result = await auth.loginRequest(
      email.value,
      mode.value === 'register' ? invite.value.trim() || undefined : undefined,
    )
    devCode.value = result.dev_code ?? ''
    startCountdown(result.resend_after ?? 60)
    toast.text = '验证码已重新发送'
    toast.show = true
  } catch (error) {
    handleError(error)
  } finally {
    loading.value = false
  }
}

function backToEmail(): void {
  clearErrors()
  digits.fill('')
  needsInvite.value = false
  step.value = 'email'
}

function safeRedirect(): string {
  const raw = route.query.redirect
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) return value
  return '/'
}
</script>

<style scoped>
.login-page {
  display: flex;
  min-height: 100dvh;
  background: var(--console-bg);
}

.login-aside {
  width: 44%;
  max-width: 620px;
  padding: 40px 48px;
  display: flex;
  flex-direction: column;
  color: #fff;
  background:
    radial-gradient(900px 500px at 15% 0%, rgba(255, 255, 255, 0.18), transparent 55%),
    linear-gradient(155deg, #2b7fb4 0%, #1f6b9c 45%, #123f63 100%);
  position: relative;
  overflow: hidden;
}

.login-aside::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(circle at 30% 20%, #000 20%, transparent 75%);
  pointer-events: none;
}

.aside-top,
.aside-main,
.aside-foot {
  position: relative;
  z-index: 1;
}

.aside-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: #fff;
  color: #1f6b9c;
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 16px;
}

.brand-word {
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.2px;
}

.brand-word em {
  font-style: normal;
  opacity: 0.7;
  font-weight: 500;
  margin-left: 4px;
}

.aside-main {
  margin-top: auto;
}

.aside-title {
  font-size: 34px;
  line-height: 1.35;
  font-weight: 700;
  margin: 0 0 14px;
}

.aside-sub {
  font-size: 14px;
  line-height: 1.7;
  opacity: 0.82;
  margin: 0 0 28px;
  max-width: 420px;
}

.aside-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.aside-list li {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.li-title {
  font-weight: 600;
  font-size: 14px;
}

.li-desc {
  font-size: 12.5px;
  opacity: 0.72;
  line-height: 1.6;
}

.aside-foot {
  margin-top: auto;
  padding-top: 40px;
  font-size: 12px;
  opacity: 0.55;
}

.login-main {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 32px 24px;
}

.login-box {
  width: 100%;
  max-width: 400px;
}

.login-title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.3;
  margin: 0 0 6px;
  color: var(--console-text);
}

.login-sub {
  font-size: 13.5px;
  color: var(--console-text-muted);
  margin: 0 0 24px;
  line-height: 1.6;
}

.login-alert {
  border-radius: 8px;
}

.mode-switch {
  display: flex;
  align-items: center;
  margin-top: 18px;
}

.otp-label {
  font-size: 12px;
  color: var(--console-text-muted);
  margin-bottom: 6px;
}

.otp-row {
  display: flex;
  gap: 10px;
}

.otp-cell {
  width: 100%;
  height: 56px;
  border: 1px solid var(--console-border);
  border-radius: 12px;
  background: transparent;
  color: var(--console-text);
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.otp-cell:focus {
  border-color: var(--console-primary);
  box-shadow: 0 0 0 3px rgba(60, 150, 202, 0.16);
}

.otp-cell--error {
  border-color: #f44336;
}

.otp-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--console-text-muted);
}

.otp-hint--error {
  color: #f44336;
}

.resend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
}

.terms {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
}

.terms a {
  color: var(--console-primary);
  text-decoration: none;
}

.version {
  margin: 8px 0 0;
  font-size: 11.5px;
}

.mobile-brand {
  display: none;
  align-items: center;
  gap: 10px;
  margin-bottom: 28px;
}

@media (max-width: 960px) {
  .login-aside {
    display: none;
  }

  .mobile-brand {
    display: flex;
  }

  .login-main {
    align-items: flex-start;
    padding-top: 56px;
  }
}
</style>
