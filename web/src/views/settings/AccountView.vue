<template>
  <div>
    <PageHeader
      title="账户设置"
      description="管理登录方式、密码与第三方账号；邮箱绑定后可用于找回密码。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">
          刷新
        </v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="loadError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ loadError }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !auth.user" variant="card" :rows="3" />

    <div v-else-if="auth.user" class="account-grid">
      <!-- 基本信息 -->
      <v-card class="account-card">
        <div class="card-head">
          <div>
            <h2 class="card-title">基本信息</h2>
            <p class="card-sub text-muted">用户名用于密码登录；昵称用于展示。</p>
          </div>
        </div>
        <v-alert v-if="profileError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ profileError }}
        </v-alert>
        <v-text-field
          v-model.trim="profile.displayName"
          label="昵称"
          variant="outlined"
          density="comfortable"
          counter="32"
          maxlength="32"
          :error-messages="profileErrors.display_name"
          class="mb-2"
          data-testid="account-display-name"
        />
        <v-text-field
          v-model.trim="profile.username"
          label="用户名"
          variant="outlined"
          density="comfortable"
          hint="3–32 位字母、数字、_ 或 -；可用于密码登录"
          persistent-hint
          :error-messages="profileErrors.username"
          class="mb-3"
          data-testid="account-username"
        />
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label text-muted">邮箱</span>
            <span>{{ auth.user.email || '未绑定' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label text-muted">邮箱状态</span>
            <v-chip v-if="auth.user.email_verified" size="small" color="success" variant="tonal">
              已验证
            </v-chip>
            <v-chip v-else size="small" color="warning" variant="tonal">未验证</v-chip>
          </div>
          <div class="meta-item">
            <span class="meta-label text-muted">密码</span>
            <span>{{ auth.user.has_password ? '已设置' : '未设置' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label text-muted">密码找回</span>
            <span>{{ auth.user.recovery_available ? '可用（邮箱已验证）' : '不可用' }}</span>
          </div>
        </div>
        <div class="card-actions">
          <v-btn color="primary" variant="tonal" :loading="savingProfile" data-testid="account-save-profile" @click="saveProfile">
            保存资料
          </v-btn>
        </div>
      </v-card>

      <!-- 修改密码 -->
      <v-card class="account-card">
        <div class="card-head">
          <div>
            <h2 class="card-title">{{ auth.user.has_password ? '修改密码' : '设置密码' }}</h2>
            <p class="card-sub text-muted">
              {{ auth.user.has_password ? '需要验证当前密码。' : '当前账号没有密码，可直接设置。' }}
            </p>
          </div>
        </div>
        <v-alert v-if="passwordError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ passwordError }}
        </v-alert>
        <v-alert v-if="passwordSuccess" type="success" variant="tonal" density="compact" class="mb-3">
          {{ passwordSuccess }}
        </v-alert>
        <v-text-field
          v-if="auth.user.has_password"
          v-model="passwordForm.current"
          label="当前密码"
          type="password"
          variant="outlined"
          density="comfortable"
          :error-messages="passwordFieldErrors.current"
          class="mb-2"
        />
        <v-text-field
          v-model="passwordForm.password"
          label="新密码（6–128 位）"
          type="password"
          variant="outlined"
          density="comfortable"
          :error-messages="passwordFieldErrors.password"
          class="mb-2"
        />
        <v-text-field
          v-model="passwordForm.confirm"
          label="确认新密码"
          type="password"
          variant="outlined"
          density="comfortable"
          :error-messages="passwordFieldErrors.confirm"
          class="mb-2"
        />
        <div class="card-actions">
          <v-btn color="primary" variant="tonal" :loading="savingPassword" data-testid="account-save-password" @click="savePassword">
            保存密码
          </v-btn>
        </div>
      </v-card>

      <!-- 绑定邮箱 -->
      <v-card class="account-card">
        <div class="card-head">
          <div>
            <h2 class="card-title">绑定邮箱</h2>
            <p class="card-sub text-muted">绑定并验证后可找回密码；不绑定邮箱的账号只能通过密码登录。</p>
          </div>
        </div>
        <v-alert v-if="emailError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ emailError }}
        </v-alert>
        <v-alert v-if="emailSuccess" type="success" variant="tonal" density="compact" class="mb-3">
          {{ emailSuccess }}
        </v-alert>
        <v-alert v-if="emailDevCode" type="info" variant="tonal" density="compact" class="mb-3">
          开发环境验证码：<strong class="text-mono">{{ emailDevCode }}</strong>
        </v-alert>

        <template v-if="auth.user.email && auth.user.email_verified">
          <div class="bound-email">
            <v-icon color="success" size="20">mdi-email-check-outline</v-icon>
            <span>{{ auth.user.email }}</span>
            <v-chip size="small" color="success" variant="tonal">已验证</v-chip>
          </div>
        </template>
        <template v-else>
          <v-text-field
            v-model.trim="bindForm.email"
            label="邮箱"
            variant="outlined"
            density="comfortable"
            :error-messages="emailFieldErrors.email"
            class="mb-2"
            :disabled="bindStep === 'code'"
            data-testid="account-email"
          />
          <v-btn
            v-if="bindStep === 'request'"
            color="primary"
            variant="tonal"
            :loading="binding"
            data-testid="account-email-request"
            @click="requestEmailBind"
          >
            发送验证码
          </v-btn>
          <template v-else>
            <v-text-field
              v-model.trim="bindForm.code"
              label="6 位验证码"
              variant="outlined"
              density="comfortable"
              :error-messages="emailFieldErrors.code"
              class="mb-2"
              data-testid="account-email-code"
            />
            <div class="inline-actions">
              <v-btn variant="text" @click="bindStep = 'request'">换个邮箱</v-btn>
              <v-btn
                color="primary"
                variant="tonal"
                :loading="binding"
                data-testid="account-email-bind"
                @click="confirmEmailBind"
              >
                验证并绑定
              </v-btn>
            </div>
          </template>
        </template>
      </v-card>

      <!-- 第三方账号 -->
      <v-card class="account-card">
        <div class="card-head">
          <div>
            <h2 class="card-title">第三方账号</h2>
            <p class="card-sub text-muted">绑定后可使用 GitHub 登录；解绑前请确保已有密码或已验证邮箱。</p>
          </div>
        </div>
        <v-alert v-if="oauthError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ oauthError }}
        </v-alert>
        <div v-if="oauthProviders.length" class="oauth-list">
          <div v-for="provider in oauthProviders" :key="provider.id" class="oauth-row">
            <div class="oauth-main">
              <v-icon size="20">mdi-github</v-icon>
              <span class="oauth-name">{{ provider.name }}</span>
              <v-chip v-if="!provider.enabled" size="small" variant="tonal">未启用</v-chip>
              <v-chip v-else-if="identityOf(provider.id)" size="small" color="success" variant="tonal">
                已绑定
              </v-chip>
            </div>
            <div class="oauth-actions">
              <template v-if="provider.enabled">
                <v-btn
                  v-if="!identityOf(provider.id)"
                  variant="tonal"
                  color="primary"
                  :loading="oauthBusy === provider.id"
                  data-testid="account-oauth-bind"
                  @click="bindOAuth(provider.id)"
                >
                  绑定
                </v-btn>
                <v-btn
                  v-else
                  variant="text"
                  color="error"
                  :loading="oauthBusy === provider.id"
                  data-testid="account-oauth-unbind"
                  @click="unbindOAuth(provider.id)"
                >
                  解绑
                </v-btn>
              </template>
            </div>
            <div v-if="!provider.enabled" class="oauth-disabled-hint">
              <span class="text-muted">
                由管理员在「管理后台 → 第三方登录」配置 Client ID/Secret 后启用。
              </span>
              <v-btn
                v-if="auth.isAdmin"
                size="small"
                variant="text"
                color="primary"
                to="/admin/settings/oauth"
                data-testid="oauth-admin-config"
              >
                去配置
              </v-btn>
              <span v-else class="text-muted">请联系管理员启用。</span>
            </div>
          </div>
          <div v-if="oauthIdentities.length" class="oauth-identities text-muted">
            已绑定：
            <span v-for="identity in oauthIdentities" :key="identity.provider">
              {{ identity.provider }}（{{ identity.login || identity.email || '已连接' }}）
            </span>
          </div>
        </div>
        <EmptyState
          v-else
          icon="mdi-github"
          title="第三方登录未启用"
          description="管理员配置 GitHub OAuth 后可在这里绑定。"
        />
      </v-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import {
  bindEmail,
  getMyOAuth,
  getOAuthProviders,
  requestEmailBind as requestEmailBindApi,
  setMyPassword,
  startOAuth,
  unbindOAuth as unbindOAuthApi,
} from '@/api/auth'
import type { OAuthIdentity, OAuthProvider } from '@/types'
import { errorCode, errorMessage, fieldError } from '@/utils/errors'

const auth = useAuthStore()
const ui = useUiStore()

const loading = ref(false)
const loadError = ref('')

const profile = reactive({ displayName: '', username: '' })
const profileErrors = reactive<Record<string, string>>({})
const profileError = ref('')
const savingProfile = ref(false)

const passwordForm = reactive({ current: '', password: '', confirm: '' })
const passwordFieldErrors = reactive<Record<string, string>>({})
const passwordError = ref('')
const passwordSuccess = ref('')
const savingPassword = ref(false)

const bindForm = reactive({ email: '', code: '' })
const emailFieldErrors = reactive<Record<string, string>>({})
const bindStep = ref<'request' | 'code'>('request')
const emailError = ref('')
const emailSuccess = ref('')
const emailDevCode = ref('')
const binding = ref(false)

const oauthProviders = ref<OAuthProvider[]>([])
const oauthIdentities = ref<OAuthIdentity[]>([])
const oauthError = ref('')
const oauthBusy = ref('')

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    await auth.refreshMe()
    syncForms()
    await Promise.allSettled([loadOAuthProviders(), loadOAuthIdentities()])
  } catch (error) {
    loadError.value = errorMessage(error, '加载账户信息失败')
  } finally {
    loading.value = false
  }
}

function syncForms(): void {
  if (!auth.user) return
  profile.displayName = auth.user.display_name || ''
  profile.username = auth.user.username || ''
  bindForm.email = auth.user.email || ''
}

async function saveProfile(): Promise<void> {
  profileError.value = ''
  for (const key of Object.keys(profileErrors)) profileErrors[key] = ''
  savingProfile.value = true
  try {
    await auth.updateProfileFields({
      display_name: profile.displayName,
      username: profile.username,
    })
    ui.notify('账户资料已更新', 'success')
  } catch (error) {
    const display = fieldError(error, 'display_name')
    const username = fieldError(error, 'username')
    if (display) profileErrors.display_name = display
    if (username) profileErrors.username = username
    if (!display && !username) {
      profileError.value =
        errorCode(error) === 'username_taken'
          ? '用户名已被占用'
          : errorMessage(error, '保存资料失败')
    }
  } finally {
    savingProfile.value = false
  }
}

async function savePassword(): Promise<void> {
  passwordError.value = ''
  passwordSuccess.value = ''
  for (const key of Object.keys(passwordFieldErrors)) passwordFieldErrors[key] = ''
  if (passwordForm.password.length < 6 || passwordForm.password.length > 128) {
    passwordFieldErrors.password = '密码需为 6–128 位'
    return
  }
  if (passwordForm.password !== passwordForm.confirm) {
    passwordFieldErrors.confirm = '两次输入的密码不一致'
    return
  }
  savingPassword.value = true
  try {
    const result = await setMyPassword({
      new_password: passwordForm.password,
      current_password: auth.user?.has_password ? passwordForm.current : undefined,
    })
    if (auth.user && result.user) auth.user = { ...auth.user, ...result.user }
    passwordForm.current = ''
    passwordForm.password = ''
    passwordForm.confirm = ''
    passwordSuccess.value = '密码已保存'
    ui.notify('密码已更新', 'success')
    await auth.refreshMe()
  } catch (error) {
    const field = fieldError(error, 'current_password')
    if (field) passwordFieldErrors.current = field
    else if (fieldError(error, 'new_password')) {
      passwordFieldErrors.password = fieldError(error, 'new_password') || ''
    } else {
      passwordError.value =
        errorCode(error) === 'invalid_credentials'
          ? '当前密码不正确'
          : errorMessage(error, '保存密码失败')
    }
  } finally {
    savingPassword.value = false
  }
}

async function requestEmailBind(): Promise<void> {
  emailError.value = ''
  emailSuccess.value = ''
  emailDevCode.value = ''
  for (const key of Object.keys(emailFieldErrors)) emailFieldErrors[key] = ''
  if (!auth.user) return
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(bindForm.email)) {
    emailFieldErrors.email = '请输入有效的邮箱地址'
    return
  }
  binding.value = true
  try {
    const result = await requestEmailBindApi(bindForm.email)
    emailDevCode.value = result.dev_code ?? ''
    bindStep.value = 'code'
    emailSuccess.value = '验证码已发送，请输入邮件中的 6 位验证码。'
  } catch (error) {
    const field = fieldError(error, 'email')
    if (field) emailFieldErrors.email = field
    else emailError.value = errorMessage(error, '发送验证码失败')
  } finally {
    binding.value = false
  }
}

async function confirmEmailBind(): Promise<void> {
  emailError.value = ''
  emailSuccess.value = ''
  for (const key of Object.keys(emailFieldErrors)) emailFieldErrors[key] = ''
  if (!bindForm.code.trim()) {
    emailFieldErrors.code = '请输入验证码'
    return
  }
  binding.value = true
  try {
    const result = await bindEmail({ email: bindForm.email, code: bindForm.code.trim() })
    if (auth.user && result.user) auth.user = { ...auth.user, ...result.user }
    await auth.refreshMe()
    bindStep.value = 'request'
    emailSuccess.value = '邮箱已绑定并验证'
    ui.notify('邮箱已绑定', 'success')
  } catch (error) {
    const code = fieldError(error, 'code')
    if (code) emailFieldErrors.code = code
    else emailError.value = errorMessage(error, '绑定邮箱失败')
  } finally {
    binding.value = false
  }
}

async function loadOAuthProviders(): Promise<void> {
  try {
    const result = await getOAuthProviders()
    oauthProviders.value = result.providers ?? []
  } catch {
    oauthProviders.value = []
  }
}

async function loadOAuthIdentities(): Promise<void> {
  try {
    const result = await getMyOAuth()
    oauthIdentities.value = result.items ?? []
  } catch {
    oauthIdentities.value = []
  }
}

function identityOf(provider: string): OAuthIdentity | undefined {
  return oauthIdentities.value.find((item) => item.provider === provider)
}

async function bindOAuth(provider: string): Promise<void> {
  oauthError.value = ''
  oauthBusy.value = provider
  try {
    const result = await startOAuth(provider, 'bind', { redirect: '/settings/account' })
    window.location.assign(result.authorize_url)
  } catch (error) {
    oauthError.value = errorMessage(error, '发起绑定失败')
  } finally {
    oauthBusy.value = ''
  }
}

async function unbindOAuth(provider: string): Promise<void> {
  oauthError.value = ''
  oauthBusy.value = provider
  try {
    await unbindOAuthApi(provider)
    await loadOAuthIdentities()
    ui.notify('已解绑第三方账号', 'success')
  } catch (error) {
    oauthError.value =
      errorCode(error) === 'last_login_method'
        ? '这是当前账号唯一的登录方式，请先设置密码或绑定邮箱'
        : errorMessage(error, '解绑失败')
  } finally {
    oauthBusy.value = ''
  }
}
</script>

<style scoped>
.account-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.account-card {
  padding: 20px;
  height: fit-content;
}

.card-head {
  margin-bottom: 14px;
}

.card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
}

.card-sub {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
  margin-bottom: 14px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.meta-label {
  font-size: 11.5px;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
}

.bound-email {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.inline-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.oauth-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.oauth-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--console-border);
  border-radius: 8px;
}

.oauth-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.oauth-name {
  font-size: 13px;
  font-weight: 600;
}

.oauth-disabled-hint {
  flex-basis: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11.5px;
  line-height: 1.5;
}

.oauth-identities {
  font-size: 11.5px;
  line-height: 1.5;
}

@media (max-width: 959px) {
  .account-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 599px) {
  .account-card {
    padding: 16px;
  }

  .meta-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
