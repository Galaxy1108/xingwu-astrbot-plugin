<template>
  <div class="login-page">
    <aside class="login-aside">
      <div class="aside-top">
        <BrandMark :size="32" />
        <span class="brand-word">星坞 <em>Alpha</em></span>
      </div>

      <div class="aside-main">
        <h1 class="aside-title">把 Bot 托管到<br />星坞云端。</h1>
        <p class="aside-sub">
          一个托管后端，管理你的所有机器人。扫码接入微信 / QQ，记忆加密存储，额度与用量一目了然。
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

      <div class="aside-foot">© 2026 星坞 Xingwu · Alpha 内测阶段，仅限受邀用户</div>
    </aside>

    <main class="login-main">
      <div class="login-box">
        <div class="mobile-brand">
          <BrandMark :size="32" />
          <span class="brand-word">星坞 <em>Alpha</em></span>
        </div>

        <template v-if="view === 'login'">
          <h2 class="login-title">登录控制台</h2>
          <p class="login-sub">选择验证码或密码登录；Alpha 内测阶段仅限受邀用户。</p>

          <div
            class="auth-tabs"
            :class="`auth-tabs--${loginMethod}`"
            role="tablist"
            aria-label="登录方式"
          >
            <button
              type="button"
              class="auth-tab"
              :class="{ 'auth-tab--active': loginMethod === 'otp' }"
              role="tab"
              :aria-selected="loginMethod === 'otp'"
              data-testid="auth-tab-otp"
              @click="switchLoginMethod('otp')"
            >
              验证码登录
            </button>
            <button
              type="button"
              class="auth-tab"
              :class="{ 'auth-tab--active': loginMethod === 'password' }"
              role="tab"
              :aria-selected="loginMethod === 'password'"
              data-testid="auth-tab-password"
              @click="switchLoginMethod('password')"
            >
              密码登录
            </button>
          </div>

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

          <!-- OTP 登录 / 邮箱验证码注册 -->
          <template v-if="loginMethod === 'otp'">
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
                v-if="otpRegister"
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
              <v-alert
                v-if="otpRegister"
                type="warning"
                variant="tonal"
                density="compact"
                icon="mdi-flask-outline"
                class="mb-4 login-alert"
              >
                <strong>Alpha 内测</strong>：邮箱验证码注册需要邀请码；注册后可在账户设置绑定密码。
              </v-alert>

              <v-btn
                block
                color="primary"
                size="large"
                variant="tonal"
                :loading="loading"
                class="mt-4"
                data-testid="login-request"
                @click="onRequest"
              >
                发送验证码
              </v-btn>

              <div class="mode-switch text-body-2">
                <span class="muted">还没有账号？</span>
                <v-btn variant="text" size="small" color="primary" class="px-1" @click="goRegister">
                  用邀请码注册
                </v-btn>
                <v-btn
                  v-if="!otpRegister"
                  variant="text"
                  size="small"
                  color="primary"
                  class="px-1"
                  @click="enableOtpRegister"
                >
                  邮箱验证码注册
                </v-btn>
              </div>
            </template>

            <template v-else>
              <p class="code-hint text-muted">验证码已发送至 {{ email }}（10 分钟内有效）</p>
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
                  v-if="needsInvite || otpRegister"
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
                variant="tonal"
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
          </template>

          <!-- 密码登录 -->
          <template v-else>
            <v-text-field
              v-model.trim="identifier"
              label="邮箱或用户名"
              placeholder="you@example.com / username"
              variant="outlined"
              density="comfortable"
              prepend-inner-icon="mdi-account-outline"
              :error-messages="identifierError"
              hide-details="auto"
              class="mb-3"
              data-testid="password-identifier"
              @keyup.enter="onPasswordLogin"
            />
            <v-text-field
              v-model="password"
              label="密码"
              type="password"
              variant="outlined"
              density="comfortable"
              prepend-inner-icon="mdi-lock-outline"
              :error-messages="passwordError"
              hide-details="auto"
              class="mb-2"
              data-testid="password-input"
              @keyup.enter="onPasswordLogin"
            />
            <div class="forgot-row">
              <v-btn variant="text" size="small" color="primary" class="px-0" @click="forgotOpen = true">
                忘记密码？
              </v-btn>
            </div>
            <v-btn
              block
              color="primary"
              size="large"
              variant="tonal"
              :loading="loading"
              data-testid="password-submit"
              @click="onPasswordLogin"
            >
              密码登录
            </v-btn>
            <div class="mode-switch text-body-2">
              <span class="muted">还没有账号？</span>
              <v-btn variant="text" size="small" color="primary" class="px-1" @click="goRegister">
                用邀请码注册
              </v-btn>
            </div>
          </template>

          <div v-if="oauthProviders.length" class="oauth-section">
            <v-divider class="my-5" />
            <p class="oauth-title text-muted">或使用第三方账号</p>
            <v-btn
              v-for="provider in oauthProviders"
              :key="provider.id"
              block
              variant="outlined"
              class="mb-2"
              prepend-icon="mdi-github"
              :loading="oauthLoading === provider.id"
              data-testid="oauth-login-button"
              @click="startOAuthLogin(provider)"
            >
              使用 {{ provider.name }} 登录
            </v-btn>
          </div>
        </template>

        <!-- 无邮箱密码注册 -->
        <template v-else>
          <h2 class="login-title">创建账号</h2>
          <p class="login-sub">使用邀请码注册；不绑定邮箱也可以先开始使用。</p>

          <v-alert
            type="warning"
            variant="tonal"
            density="compact"
            icon="mdi-email-alert-outline"
            class="mb-4 login-alert"
            data-testid="register-no-email-warning"
          >
            不绑定邮箱将<strong>无法找回密码</strong>；注册后可在「账户设置」绑定邮箱。Alpha 内测阶段功能与数据可能调整。
          </v-alert>

          <v-alert v-if="formError" type="error" variant="tonal" density="compact" class="mb-4 login-alert">
            {{ formError }}
          </v-alert>

          <v-text-field
            v-model.trim="registerForm.invite"
            label="邀请码"
            placeholder="INV-XXXX-XXXX"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-ticket-confirmation-outline"
            :error-messages="registerErrors.invite"
            hide-details="auto"
            class="mb-3"
          />
          <v-text-field
            v-model.trim="registerForm.username"
            label="用户名"
            placeholder="3–32 位字母、数字、_ 或 -"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-account-outline"
            :error-messages="registerErrors.username"
            hide-details="auto"
            class="mb-3"
          />
          <v-text-field
            v-model.trim="registerForm.displayName"
            label="昵称（可选）"
            placeholder="展示给其他用户的名字"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-badge-account-outline"
            hide-details="auto"
            class="mb-3"
          />
          <v-text-field
            v-model="registerForm.password"
            label="密码"
            type="password"
            placeholder="6–128 位"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-lock-outline"
            :error-messages="registerErrors.password"
            hide-details="auto"
            class="mb-3"
          />
          <v-text-field
            v-model="registerForm.confirm"
            label="确认密码"
            type="password"
            variant="outlined"
            density="comfortable"
            prepend-inner-icon="mdi-lock-check-outline"
            :error-messages="registerErrors.confirm"
            hide-details="auto"
            class="mb-4"
          />

          <v-btn
            block
            color="primary"
            size="large"
            variant="tonal"
            :loading="loading"
            data-testid="register-submit"
            @click="onPasswordRegister"
          >
            注册并登录
          </v-btn>

          <div class="mode-switch text-body-2">
            <span class="muted">已有账号？</span>
            <v-btn variant="text" size="small" color="primary" class="px-1" @click="view = 'login'">
              返回登录
            </v-btn>
            <v-btn variant="text" size="small" color="primary" class="px-1" @click="goOtpRegister">
              邮箱验证码注册
            </v-btn>
          </div>
        </template>

        <v-divider class="my-6" />
        <p class="terms muted">
          登录即表示同意
          <a href="#" @click.prevent>服务条款</a> 与 <a href="#" @click.prevent>隐私政策</a>。
        </p>
        <p class="version muted">星坞 {{ auth.version || '0.5.0' }} · Alpha 内测</p>
      </div>
    </main>

    <!-- 忘记密码 -->
    <v-dialog v-model="forgotOpen" max-width="480" persistent>
      <v-card class="forgot-dialog">
        <v-card-title class="forgot-title">找回密码</v-card-title>
        <v-card-text>
          <p class="forgot-sub text-muted">
            通过已验证邮箱收取验证码；若邮箱未绑定，请联系管理员。
          </p>
          <v-alert v-if="forgotError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ forgotError }}
          </v-alert>
          <v-alert v-if="forgotSuccess" type="success" variant="tonal" density="compact" class="mb-3">
            {{ forgotSuccess }}
          </v-alert>
          <v-alert v-if="forgotDevCode" type="info" variant="tonal" density="compact" class="mb-3">
            开发环境验证码：<strong class="text-mono">{{ forgotDevCode }}</strong>
          </v-alert>

          <template v-if="forgotStep === 'request'">
            <v-text-field
              v-model.trim="forgotEmail"
              label="邮箱"
              variant="outlined"
              density="comfortable"
              prepend-inner-icon="mdi-email-outline"
              hide-details="auto"
              class="mb-3"
            />
          </template>
          <template v-else>
            <v-text-field
              v-model.trim="forgotCode"
              label="6 位验证码"
              variant="outlined"
              density="comfortable"
              prepend-inner-icon="mdi-shield-key-outline"
              hide-details="auto"
              class="mb-3"
            />
            <v-text-field
              v-model="forgotPassword"
              label="新密码（6–128 位）"
              type="password"
              variant="outlined"
              density="comfortable"
              prepend-inner-icon="mdi-lock-reset"
              hide-details="auto"
              class="mb-3"
            />
          </template>
        </v-card-text>
        <v-card-actions>
          <v-btn variant="text" @click="forgotOpen = false">取消</v-btn>
          <v-spacer />
          <v-btn
            v-if="forgotStep === 'request'"
            color="primary"
            variant="tonal"
            :loading="forgotLoading"
            @click="requestReset"
          >
            发送验证码
          </v-btn>
          <v-btn
            v-else
            color="primary"
            variant="tonal"
            :loading="forgotLoading"
            @click="confirmReset"
          >
            重置密码
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="toast.show" :timeout="2400" location="top" rounded="lg" color="error">
      {{ toast.text }}
    </v-snackbar>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BrandMark from '@/components/BrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import {
  getOAuthProviders,
  requestPasswordReset,
  resetPassword,
  startOAuth,
} from '@/api/auth'
import type { OAuthProvider } from '@/types'
import { errorCode, errorMessage, fieldError, isFieldError } from '@/utils/errors'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const features = [
  { icon: 'mdi-robot-outline', title: '一人多 Bot', desc: '每个 Bot 独立人格、配置与平台实例。' },
  { icon: 'mdi-qrcode-scan', title: '扫码即接入', desc: '微信官方机器人 / QQ 官方，手机确认即可上线。' },
  { icon: 'mdi-shield-lock-outline', title: '加密与留痕', desc: '记忆库 SQLCipher 加密，管理员访问留痕。' },
]

const view = ref<'login' | 'register'>('login')
const loginMethod = ref<'otp' | 'password'>('otp')
const step = ref<'email' | 'code'>('email')
const otpRegister = ref(false)
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

const identifier = ref('')
const password = ref('')
const identifierError = ref('')
const passwordError = ref('')

const registerForm = reactive({
  invite: '',
  username: '',
  displayName: '',
  password: '',
  confirm: '',
})
const registerErrors = reactive<Record<string, string>>({})

const oauthProviders = ref<OAuthProvider[]>([])
const oauthLoading = ref('')

const forgotOpen = ref(false)
const forgotStep = ref<'request' | 'reset'>('request')
const forgotEmail = ref('')
const forgotCode = ref('')
const forgotPassword = ref('')
const forgotDevCode = ref('')
const forgotError = ref('')
const forgotSuccess = ref('')
const forgotLoading = ref(false)

let timer: ReturnType<typeof setInterval> | null = null
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const USERNAME_PATTERN = /^[A-Za-z0-9_-]{3,32}$/

onMounted(async () => {
  if (auth.isAuthenticated) {
    if (auth.user?.status === 'disabled') {
      await router.replace('/banned')
    } else {
      await router.replace(safeRedirect())
    }
    return
  }
  try {
    const result = await getOAuthProviders()
    oauthProviders.value = (result.providers ?? []).filter((provider) => provider.enabled)
  } catch {
    oauthProviders.value = []
  }
})

onBeforeUnmount(stopCountdown)

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

function switchLoginMethod(method: 'otp' | 'password'): void {
  loginMethod.value = method
  clearErrors()
  step.value = 'email'
  otpRegister.value = false
  devCode.value = ''
}

function goRegister(): void {
  view.value = 'register'
  clearErrors()
  registerErrors.invite = ''
  registerErrors.username = ''
  registerErrors.password = ''
  registerErrors.confirm = ''
}

function enableOtpRegister(): void {
  view.value = 'login'
  loginMethod.value = 'otp'
  otpRegister.value = true
  step.value = 'email'
  clearErrors()
}

function goOtpRegister(): void {
  enableOtpRegister()
}

function clearErrors(): void {
  formError.value = ''
  emailError.value = ''
  inviteError.value = ''
  codeError.value = ''
  identifierError.value = ''
  passwordError.value = ''
}

function handleOtpError(error: unknown): void {
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
  if (otpRegister.value && !invite.value.trim()) {
    inviteError.value = '内测阶段需要邀请码'
    return
  }
  loading.value = true
  try {
    const result = await auth.loginRequest(
      email.value,
      otpRegister.value ? invite.value.trim() || undefined : undefined,
    )
    devCode.value = result.dev_code ?? ''
    step.value = 'code'
    needsInvite.value = false
    startCountdown(result.resend_after ?? 60)
    await nextTick()
    inputs[0]?.focus()
  } catch (error) {
    handleOtpError(error)
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
      invite: otpRegister.value ? invite.value.trim() || undefined : invite.value.trim() || undefined,
    })
    await redirectAfterLogin()
  } catch (error) {
    handleOtpError(error)
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
      otpRegister.value ? invite.value.trim() || undefined : undefined,
    )
    devCode.value = result.dev_code ?? ''
    startCountdown(result.resend_after ?? 60)
    toast.text = '验证码已重新发送'
    toast.show = true
  } catch (error) {
    handleOtpError(error)
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

function mapLoginError(error: unknown): string {
  const codeName = errorCode(error)
  switch (codeName) {
    case 'invalid_credentials':
      return '账号或密码错误，请重试'
    case 'password_not_set':
      return '该账号尚未设置密码，请使用验证码登录或先设置密码'
    case 'username_taken':
      return '用户名已被占用'
    case 'email_taken':
      return '邮箱已被使用'
    case 'last_login_method':
      return '这是当前账号唯一登录方式，请先设置密码或绑定邮箱'
    case 'invite_invalid':
    case 'invite_expired':
    case 'invite_exhausted':
      return '邀请码无效、已过期或已用尽'
    default:
      return errorMessage(error, '操作失败，请稍后重试')
  }
}

async function onPasswordLogin(): Promise<void> {
  clearErrors()
  if (!identifier.value.trim()) {
    identifierError.value = '请输入邮箱或用户名'
    return
  }
  if (!password.value) {
    passwordError.value = '请输入密码'
    return
  }
  loading.value = true
  try {
    await auth.loginPassword(identifier.value, password.value)
    await redirectAfterLogin()
  } catch (error) {
    const field = isFieldError(error, 'identifier')
      ? 'identifier'
      : isFieldError(error, 'password')
        ? 'password'
        : ''
    if (field === 'identifier') identifierError.value = errorMessage(error)
    else if (field === 'password') passwordError.value = errorMessage(error)
    else formError.value = mapLoginError(error)
  } finally {
    loading.value = false
  }
}

async function onPasswordRegister(): Promise<void> {
  clearErrors()
  for (const key of Object.keys(registerErrors)) registerErrors[key] = ''
  const inviteValue = registerForm.invite.trim()
  const username = registerForm.username.trim()
  if (!inviteValue) registerErrors.invite = '请输入邀请码'
  if (!USERNAME_PATTERN.test(username)) {
    registerErrors.username = '用户名需为 3–32 位字母、数字、_ 或 -'
  }
  if (registerForm.password.length < 6 || registerForm.password.length > 128) {
    registerErrors.password = '密码需为 6–128 位'
  }
  if (registerForm.password !== registerForm.confirm) {
    registerErrors.confirm = '两次输入的密码不一致'
  }
  if (Object.values(registerErrors).some(Boolean)) return

  loading.value = true
  try {
    await auth.registerPassword({
      invite: inviteValue,
      username,
      password: registerForm.password,
      display_name: registerForm.displayName.trim() || undefined,
    })
    await redirectAfterLogin()
  } catch (error) {
    const mapping: Array<[string, string]> = [
      ['invite', 'invite'],
      ['username', 'username'],
      ['password', 'password'],
    ]
    let mapped = false
    for (const [field, key] of mapping) {
      const message = fieldError(error, field)
      if (message) {
        registerErrors[key] = message
        mapped = true
      }
    }
    if (!mapped) formError.value = mapLoginError(error)
  } finally {
    loading.value = false
  }
}

async function startOAuthLogin(provider: OAuthProvider): Promise<void> {
  oauthLoading.value = provider.id
  clearErrors()
  try {
    const result = await startOAuth(provider.id, 'login', { redirect: safeRedirect() })
    window.location.assign(result.authorize_url)
  } catch (error) {
    formError.value = mapLoginError(error)
  } finally {
    oauthLoading.value = ''
  }
}

async function requestReset(): Promise<void> {
  forgotError.value = ''
  forgotSuccess.value = ''
  forgotDevCode.value = ''
  if (!EMAIL_PATTERN.test(forgotEmail.value)) {
    forgotError.value = '请输入有效的邮箱地址'
    return
  }
  forgotLoading.value = true
  try {
    const result = await requestPasswordReset(forgotEmail.value)
    forgotSuccess.value = '如果该邮箱已注册，验证码已发送；请检查收件箱。'
    forgotDevCode.value = result.dev_code ?? ''
    forgotStep.value = 'reset'
  } catch (error) {
    forgotError.value = errorMessage(error, '发送失败，请稍后重试')
  } finally {
    forgotLoading.value = false
  }
}

async function confirmReset(): Promise<void> {
  forgotError.value = ''
  if (!forgotCode.value.trim()) {
    forgotError.value = '请输入验证码'
    return
  }
  if (forgotPassword.value.length < 6 || forgotPassword.value.length > 128) {
    forgotError.value = '密码需为 6–128 位'
    return
  }
  forgotLoading.value = true
  try {
    await resetPassword({
      email: forgotEmail.value,
      code: forgotCode.value.trim(),
      password: forgotPassword.value,
    })
    forgotOpen.value = false
    toast.text = '密码已重置，请用新密码登录'
    toast.show = true
    forgotStep.value = 'request'
    forgotCode.value = ''
    forgotPassword.value = ''
    loginMethod.value = 'password'
  } catch (error) {
    forgotError.value = mapLoginError(error)
  } finally {
    forgotLoading.value = false
  }
}

async function redirectAfterLogin(): Promise<void> {
  if (auth.user?.status === 'disabled') {
    await router.replace('/banned')
    return
  }
  await router.replace(safeRedirect())
}

function safeRedirect(): string {
  const raw = route.query.redirect
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) return value
  return '/'
}
</script>

<style scoped>
@keyframes login-rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

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

.login-aside::before {
  content: '';
  position: absolute;
  width: 540px;
  height: 540px;
  left: -160px;
  top: -180px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.28), transparent 65%);
  filter: blur(10px);
  animation: aside-blob-drift 18s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes aside-blob-drift {
  0% {
    transform: translate3d(0, 0, 0) scale(1);
  }
  100% {
    transform: translate3d(70px, 90px, 0) scale(1.18);
  }
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
  animation: login-rise 0.6s ease both;
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
  animation: login-rise 0.68s 0.08s ease both;
  font-size: 34px;
  line-height: 1.35;
  font-weight: 700;
  margin: 0 0 14px;
}

.aside-sub {
  animation: login-rise 0.68s 0.16s ease both;
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
  animation: login-rise 0.5s ease both;
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
  animation: login-rise 0.5s 0.1s ease both;
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


.auth-tabs {
  position: relative;
  display: flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 18px;
  border-radius: 10px;
  background: var(--console-surface-variant);
}

.auth-tabs::before {
  content: '';
  position: absolute;
  top: 4px;
  left: 4px;
  width: calc(50% - 6px);
  height: 40px;
  border-radius: 8px;
  background: var(--console-surface);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  transition: transform 240ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
}

.auth-tabs--password::before {
  transform: translateX(calc(100% + 4px));
}

.auth-tab {
  position: relative;
  z-index: 1;
  flex: 1;
  height: 40px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--console-text-muted);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.auth-tab {
  transition: color 160ms ease;
}

.auth-tab--active {
  background: transparent;
  color: var(--console-primary);
}

.code-hint {
  margin: -2px 0 12px;
  font-size: 12px;
  line-height: 1.5;
}

.forgot-row {
  display: flex;
  justify-content: flex-end;
  margin: -2px 0 10px;
}

.oauth-section {
  margin-top: 14px;
}

.oauth-title {
  margin: 0 0 10px;
  text-align: center;
  font-size: 12px;
}

.forgot-dialog {
  padding: 6px;
}

.forgot-title {
  font-size: 18px;
  font-weight: 650;
  padding: 14px 20px 4px;
}

.forgot-sub {
  margin: 0 0 12px;
  font-size: 12.5px;
  line-height: 1.5;
}

@media (max-width: 599px) {
  .login-main {
    padding-left: 16px;
    padding-right: 16px;
  }

  .login-box {
    padding-left: 0;
    padding-right: 0;
  }

  .auth-tabs {
    margin-bottom: 14px;
  }
}

</style>
