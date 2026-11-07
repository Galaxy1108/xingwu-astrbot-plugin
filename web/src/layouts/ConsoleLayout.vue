<template>
  <v-navigation-drawer
    v-model="drawerOpen"
    :permanent="!isMobile"
    :temporary="isMobile"
    :width="245"
    class="console-drawer"
    elevation="0"
  >
    <div class="brand-row">
      <v-icon color="primary" size="26">mdi-robot-outline</v-icon>
      <span class="brand-name">AstrBot</span>
      <v-chip size="x-small" variant="tonal" color="primary" class="ml-auto">SaaS</v-chip>
    </div>
    <v-divider />
    <v-list nav density="compact" class="nav-list">
      <v-list-item
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        :prepend-icon="item.icon"
        :title="item.title"
        :exact="item.to === '/'"
        rounded="lg"
      />
      <template v-if="auth.isAdmin">
        <v-divider class="my-2" />
        <v-list-subheader class="admin-subheader">管理员</v-list-subheader>
        <v-list-item
          to="/admin"
          prepend-icon="mdi-shield-account-outline"
          title="管理后台"
          rounded="lg"
        />
      </template>
    </v-list>
    <template #append>
      <div class="drawer-footer">
        <div class="user-line">
          <v-icon size="16">mdi-account-circle-outline</v-icon>
          <span class="user-email" :title="auth.user?.email">{{ auth.user?.email || '未登录' }}</span>
        </div>
        <v-btn block variant="text" size="small" prepend-icon="mdi-logout" @click="onLogout">
          退出登录
        </v-btn>
      </div>
    </template>
  </v-navigation-drawer>

  <v-app-bar flat height="56" class="console-topbar">
    <v-app-bar-nav-icon v-if="isMobile" aria-label="打开导航" @click="drawerOpen = !drawerOpen" />
    <v-app-bar-title class="topbar-title">{{ currentTitle }}</v-app-bar-title>
    <v-spacer />
    <v-chip v-if="auth.isAdmin" size="small" variant="tonal" color="primary" class="mr-2">
      管理员
    </v-chip>
    <v-btn icon variant="text" aria-label="刷新页面" title="刷新页面" @click="refreshPage">
      <v-icon>mdi-refresh</v-icon>
    </v-btn>
  </v-app-bar>

  <v-main class="console-main">
    <div class="page-container">
      <router-view />
    </div>
  </v-main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()
const { smAndDown } = useDisplay()

const isMobile = computed(() => smAndDown.value)
const drawerOpen = ref(!isMobile.value)

watch(isMobile, (mobile) => {
  drawerOpen.value = !mobile
})

const navItems = [
  { to: '/', title: '总览', icon: 'mdi-view-dashboard-outline' },
  { to: '/connect', title: '扫码接入', icon: 'mdi-qrcode-scan' },
  { to: '/bots', title: '我的 Bot', icon: 'mdi-robot-outline' },
  { to: '/settings/privacy', title: '隐私与加密', icon: 'mdi-shield-lock-outline' },
  { to: '/billing', title: '额度', icon: 'mdi-wallet-outline' },
  { to: '/access-log', title: '访问记录', icon: 'mdi-file-eye-outline' },
]

const currentTitle = computed(() => {
  const title = route.meta.title
  return typeof title === 'string' && title ? title : '控制台'
})

async function onLogout(): Promise<void> {
  await auth.logout()
  ui.notify('已退出登录', 'info')
  await router.replace('/login')
}

function refreshPage(): void {
  window.location.reload()
}
</script>

<style scoped>
.console-drawer {
  border-right: 1px solid var(--console-border);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 56px;
  padding: 0 16px;
}

.brand-name {
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.nav-list {
  padding: 8px;
}

.admin-subheader {
  font-size: 0.72rem;
  text-transform: none;
  letter-spacing: 0.04em;
  min-height: 28px;
}

.drawer-footer {
  padding: 12px;
  border-top: 1px solid var(--console-border);
}

.user-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--console-text-muted);
  font-size: 0.8rem;
  margin-bottom: 4px;
  padding: 0 4px;
}

.user-email {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.console-topbar {
  border-bottom: 1px solid var(--console-border);
  background: var(--console-surface);
}

.topbar-title {
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0;
}

/* AstrBot 风格：桌面端页面自带标题，顶栏不再重复显示 */
@media (min-width: 960px) {
  .topbar-title {
    visibility: hidden;
  }
}

.console-main {
  background: var(--console-bg);
}
</style>
