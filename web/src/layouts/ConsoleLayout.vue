<template>
  <v-navigation-drawer
    v-model="drawerOpen"
    :permanent="!isMobile"
    :temporary="isMobile"
    :rail="isRail"
    rail-width="56"
    :width="245"
    class="console-drawer"
    elevation="0"
  >
    <div class="sidebar-container">
      <div class="brand-row" :class="{ 'brand-row--rail': isRail }">
        <v-icon color="primary" size="22">mdi-robot-outline</v-icon>
        <template v-if="!isRail">
          <span class="brand-name">AstrBot</span>
          <v-chip size="x-small" variant="tonal" color="primary" class="brand-chip">SaaS</v-chip>
        </template>
        <v-spacer v-if="!isRail" />
        <v-btn
          v-if="!isMobile"
          icon
          size="small"
          variant="text"
          class="rail-toggle"
          :aria-label="isRail ? '展开侧栏' : '收起侧栏'"
          @click="rail = !rail"
        >
          <v-icon size="18">mdi-menu-open</v-icon>
        </v-btn>
      </div>

      <v-list nav density="compact" class="nav-list">
        <v-list-item
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="isRail ? undefined : item.title"
          :exact="item.to === '/'"
          rounded="lg"
          color="primary"
          class="nav-item"
          :aria-label="item.title"
        />
        <template v-if="auth.isAdmin">
          <div v-if="!isRail" class="nav-group-title">管理员</div>
          <v-divider v-else class="my-2" />
          <v-list-item
            to="/admin"
            prepend-icon="mdi-shield-account-outline"
            :title="isRail ? undefined : '管理后台'"
            rounded="lg"
            color="primary"
            class="nav-item"
            aria-label="管理后台"
          />
        </template>
      </v-list>

      <v-spacer />

      <div class="sidebar-footer">
        <div v-if="!isRail" class="user-line">
          <v-icon size="16">mdi-account-circle-outline</v-icon>
          <span class="user-email" :title="auth.user?.email">{{ auth.user?.email || '未登录' }}</span>
        </div>
        <v-btn
          block
          variant="text"
          size="small"
          :prepend-icon="isRail ? undefined : 'mdi-logout'"
          class="footer-btn"
          aria-label="退出登录"
          @click="onLogout"
        >
          <span v-if="!isRail">退出登录</span>
          <v-icon v-else size="18">mdi-logout</v-icon>
        </v-btn>
        <div v-if="!isRail" class="version-line">AstrBot SaaS {{ auth.version || '0.3.0' }}</div>
      </div>
    </div>
  </v-navigation-drawer>

  <v-app-bar flat height="56" class="console-topbar">
    <v-app-bar-nav-icon v-if="isMobile" aria-label="打开导航" @click="drawerOpen = !drawerOpen" />
    <v-app-bar-title class="topbar-title">{{ currentTitle }}</v-app-bar-title>
    <v-spacer />
    <v-btn icon variant="text" :aria-label="isDark ? '切换浅色主题' : '切换深色主题'" @click="toggleTheme">
      <v-icon>{{ isDark ? 'mdi-weather-night' : 'mdi-white-balance-sunny' }}</v-icon>
    </v-btn>
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
import { useThemeMode } from '@/composables/useThemeMode'

const auth = useAuthStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()
const { smAndDown } = useDisplay()
const { isDark, toggle: toggleTheme } = useThemeMode()

const isMobile = computed(() => smAndDown.value)
const drawerOpen = ref(!isMobile.value)
const rail = ref(false)
const isRail = computed(() => rail.value && !isMobile.value)

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
  background: var(--console-surface);
}

.sidebar-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 56px;
  padding: 0 12px 0 22px;
}

.brand-row--rail {
  justify-content: center;
  padding: 0;
}

.brand-name {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.2px;
  color: var(--console-text);
}

.brand-chip {
  height: 18px;
  font-size: 10px;
}

.rail-toggle {
  margin-left: auto;
  color: var(--console-text-muted);
}

.nav-list {
  padding: 6px 8px;
}

.nav-group-title {
  padding: 14px 12px 6px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--console-text-muted);
}

:deep(.nav-item) {
  min-height: 40px;
  margin: 1px 0;
  border-radius: 8px;
}

:deep(.nav-item .v-list-item__prepend > .v-icon) {
  font-size: 18px;
  opacity: 0.82;
}

:deep(.nav-item .v-list-item-title) {
  font-size: 14px;
  font-weight: 500;
  line-height: 20px;
}

:deep(.nav-item.v-list-item--active) {
  background: rgba(60, 150, 202, 0.11);
}

:deep(.nav-item.v-list-item--active .v-list-item__prepend > .v-icon) {
  opacity: 1;
}

.sidebar-footer {
  border-top: 1px solid var(--console-border);
  padding: 10px 12px 12px;
}

.user-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--console-text-muted);
  font-size: 12.5px;
  margin-bottom: 2px;
  padding: 0 4px;
  min-width: 0;
}

.user-email {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-line {
  padding: 4px 4px 0;
  font-size: 11px;
  color: var(--console-text-muted);
}

.console-topbar {
  border-bottom: 1px solid var(--console-border);
  background: var(--console-surface);
}

.topbar-title {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0;
}

/* 页面自带标题，桌面端顶栏只留操作区 */
@media (min-width: 960px) {
  .topbar-title {
    visibility: hidden;
  }
}

.console-main {
  background: var(--console-bg);
}
</style>
