<template>
  <div>
    <PageHeader
      title="第三方登录"
      description="配置 GitHub OAuth；启用后用户可在登录页与账户设置中使用 GitHub。"
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

    <LoadingSkeleton v-if="loading && !loaded" variant="card" :rows="3" />

    <v-card v-else class="settings-card oauth-card">
      <div class="section-head">
        <div>
          <h2 class="section-title">GitHub OAuth</h2>
          <p class="section-sub text-muted">Client ID / Secret 由 GitHub OAuth App 提供；Secret 只在服务端加密保存。</p>
        </div>
        <v-chip :color="form.enabled ? 'success' : 'default'" variant="tonal" size="small">
          {{ form.enabled ? '已启用' : '未启用' }}
        </v-chip>
      </div>

      <v-alert v-if="loadUnavailable" type="info" variant="tonal" density="compact" class="mb-4">
        管理员 OAuth 设置接口尚未就绪，当前显示默认值；保存会提示失败。
      </v-alert>
      <v-alert v-if="saveError" type="error" variant="tonal" density="compact" class="mb-4">
        {{ saveError }}
      </v-alert>
      <v-alert v-if="saved" type="success" variant="tonal" density="compact" class="mb-4">
        第三方登录设置已保存
      </v-alert>

      <div class="switch-row">
        <div>
          <div class="switch-label">启用 GitHub 登录</div>
          <div class="text-muted switch-hint">启用前请确保 Client ID/Secret 与回调地址已正确配置。</div>
        </div>
        <v-switch v-model="form.enabled" color="primary" inset hide-details data-testid="oauth-enabled" />
      </div>

      <v-row dense class="mt-2">
        <v-col cols="12" md="6">
          <v-text-field v-model.trim="form.clientId" label="Client ID" data-testid="oauth-client-id" />
        </v-col>
        <v-col cols="12" md="6">
          <v-text-field
            v-model="form.clientSecret"
            label="Client Secret"
            type="password"
            :placeholder="hasSecret ? '已配置（留空不修改）' : '未配置'"
            data-testid="oauth-client-secret"
          />
        </v-col>
        <v-col cols="12">
          <v-text-field
            v-model.trim="form.redirectUri"
            label="回调地址"
            placeholder="https://your-domain/api/auth/oauth/github/callback"
            hint="需与 GitHub OAuth App 中配置的 Authorization callback URL 完全一致"
            persistent-hint
            data-testid="oauth-redirect-uri"
          />
        </v-col>
      </v-row>

      <div class="savebar">
        <span class="text-muted">Secret 留空表示保持原值</span>
        <v-btn color="primary" variant="tonal" :loading="saving" data-testid="oauth-save" @click="save">
          保存设置
        </v-btn>
      </div>
    </v-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { getAdminOAuthSettings, updateAdminOAuthSettings } from '@/api/admin'
import { toApiError } from '@/api/client'
import { errorMessage } from '@/utils/errors'

const loading = ref(false)
const loaded = ref(false)
const loadUnavailable = ref(false)
const error = ref('')
const saveError = ref('')
const saved = ref(false)
const saving = ref(false)
const hasSecret = ref(false)

const form = reactive({
  enabled: false,
  clientId: '',
  clientSecret: '',
  redirectUri: '',
})

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  loadUnavailable.value = false
  saved.value = false
  try {
    const raw = (await getAdminOAuthSettings()) as Record<string, unknown>
    const github = (raw.github ?? raw) as Record<string, unknown>
    form.enabled = Boolean(github.enabled)
    form.clientId = String(github.client_id ?? '')
    form.redirectUri = String(github.redirect_uri || github.callback_url || '')
    hasSecret.value = Boolean(github.has_client_secret || github.has_secret)
    form.clientSecret = ''
    loaded.value = true
  } catch (err) {
    const apiError = toApiError(err)
    if (apiError.status === 404 || apiError.status === 405) {
      loadUnavailable.value = true
      loaded.value = true
    } else {
      error.value = errorMessage(apiError, '加载第三方登录设置失败')
    }
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  saveError.value = ''
  saved.value = false
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      enabled: form.enabled,
      client_id: form.clientId.trim(),
      redirect_uri: form.redirectUri.trim(),
    }
    if (form.clientSecret) payload.client_secret = form.clientSecret
    const updated = (await updateAdminOAuthSettings(payload as never)) as Record<string, unknown>
    const github = (updated.github ?? updated) as Record<string, unknown>
    if (Object.keys(github).length) {
      form.enabled = Boolean(github.enabled)
      hasSecret.value = Boolean(github.has_client_secret || github.has_secret) || hasSecret.value
    }
    form.clientSecret = ''
    saved.value = true
  } catch (err) {
    const apiError = toApiError(err)
    saveError.value =
      apiError.status === 404 || apiError.status === 405
        ? '管理员 OAuth 设置接口尚未就绪，无法保存。'
        : errorMessage(apiError, '保存第三方登录设置失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.oauth-card {
  padding: 22px;
  max-width: 880px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
}

.switch-label {
  font-size: 14px;
  font-weight: 600;
}

.switch-hint {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.5;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.section-sub {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

.savebar {
  position: sticky;
  bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
  padding: 10px 12px;
  border: 1px solid var(--console-border);
  border-radius: 10px;
  background: var(--console-surface);
}
</style>
