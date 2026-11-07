<template>
  <v-menu location="bottom end" :offset="6">
    <template #activator="{ props }">
      <v-btn
        v-bind="props"
        variant="text"
        class="user-menu-btn"
        :aria-label="`用户菜单：${displayName}`"
        data-testid="user-menu"
      >
        <v-avatar color="primary" variant="tonal" size="28" class="user-avatar">
          <span class="user-initial">{{ initial }}</span>
        </v-avatar>
        <span class="user-name">{{ displayName }}</span>
        <v-icon size="16" class="user-chevron">mdi-chevron-down</v-icon>
      </v-btn>
    </template>

    <v-list density="comfortable" min-width="248" class="user-menu-list">
      <v-list-item class="user-summary">
        <template #prepend>
          <v-avatar color="primary" variant="tonal" size="36">
            <span class="user-initial">{{ initial }}</span>
          </v-avatar>
        </template>
        <v-list-item-title class="summary-name">{{ displayName }}</v-list-item-title>
        <v-list-item-subtitle class="summary-email" :title="auth.user?.email">
          {{ auth.user?.email || '未登录' }}
        </v-list-item-subtitle>
      </v-list-item>
      <v-divider class="my-1" />

      <v-list-item
        v-if="context === 'console' && auth.isAdmin"
        to="/admin"
        prepend-icon="mdi-shield-account-outline"
        title="管理后台"
        data-testid="user-menu-admin"
      />
      <v-list-item
        v-else-if="context === 'admin'"
        to="/"
        prepend-icon="mdi-arrow-left"
        title="返回控制台"
        data-testid="user-menu-console"
      />
      <v-list-item
        v-if="auth.isAdmin && auth.astrbotDashboardUrl"
        prepend-icon="mdi-open-in-new"
        title="AstrBot 后台"
        data-testid="user-menu-astrbot"
        @click="openDashboard"
      />
      <v-list-item
        prepend-icon="mdi-account-edit-outline"
        title="编辑用户名"
        data-testid="user-menu-edit-name"
        @click="openEditName"
      />
      <v-divider class="my-1" />
      <v-list-item
        prepend-icon="mdi-logout"
        title="退出登录"
        data-testid="user-menu-logout"
        @click="onLogout"
      />
    </v-list>
  </v-menu>

  <v-dialog v-model="editOpen" max-width="420" persistent>
    <v-card class="dialog-card">
      <v-card-title class="dialog-title">编辑用户名</v-card-title>
      <v-card-text>
        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
          {{ error }}
        </v-alert>
        <v-text-field
          v-model.trim="draft"
          label="用户名"
          counter="32"
          maxlength="32"
          hint="1–32 个字符；仅影响控制台显示"
          persistent-hint
          data-testid="profile-display-name"
          autofocus
          @keyup.enter="save"
        />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="saving" @click="editOpen = false">取消</v-btn>
        <v-btn
          color="primary"
          variant="tonal"
          :loading="saving"
          data-testid="profile-save"
          @click="save"
        >
          保存
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { errorMessage } from '@/utils/errors'

const props = withDefaults(
  defineProps<{
    context?: 'console' | 'admin'
  }>(),
  { context: 'console' },
)

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()

const displayName = computed(() => auth.user?.display_name || auth.user?.email?.split('@')[0] || '用户')
const initial = computed(() => displayName.value.trim().slice(0, 1).toUpperCase() || 'U')

const editOpen = ref(false)
const draft = ref('')
const saving = ref(false)
const error = ref('')

function openEditName(): void {
  draft.value = auth.user?.display_name || ''
  error.value = ''
  editOpen.value = true
}

async function save(): Promise<void> {
  error.value = ''
  const name = draft.value.trim()
  if (name.length < 1 || name.length > 32) {
    error.value = '用户名需为 1–32 个字符'
    return
  }
  saving.value = true
  try {
    await auth.updateDisplayName(name)
    editOpen.value = false
    ui.notify('用户名已更新', 'success')
  } catch (err) {
    error.value = errorMessage(err, '更新用户名失败')
  } finally {
    saving.value = false
  }
}

function openDashboard(): void {
  if (!auth.astrbotDashboardUrl) return
  window.open(auth.astrbotDashboardUrl, '_blank', 'noopener,noreferrer')
}

async function onLogout(): Promise<void> {
  await auth.logout()
  ui.notify('已退出登录', 'info')
  await router.replace('/login')
}
</script>

<style scoped>
.user-menu-btn {
  min-width: 0;
  padding-inline: 8px;
  text-transform: none;
}

.user-avatar {
  margin-inline-end: 8px;
}

.user-initial {
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
}

.user-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 500;
}

.user-chevron {
  margin-inline-start: 4px;
  opacity: 0.7;
}

.user-summary {
  pointer-events: none;
}

.summary-name {
  font-size: 14px;
  font-weight: 600;
}

.summary-email {
  font-size: 12px !important;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dialog-card {
  padding: 8px;
}

.dialog-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

@media (max-width: 599px) {
  .user-name,
  .user-chevron {
    display: none;
  }

  .user-avatar {
    margin-inline-end: 0;
  }
}
</style>
