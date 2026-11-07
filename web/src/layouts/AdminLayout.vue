<template>
  <v-navigation-drawer
    v-model="drawerOpen"
    :permanent="!isMobile"
    :temporary="isMobile"
    :rail="isRail"
    rail-width="56"
    :width="245"
    class="admin-drawer"
    elevation="0"
  >
    <div class="sidebar-container">
      <div class="brand-row" :class="{ 'brand-row--rail': isRail }">
        <v-icon color="primary" size="22">mdi-shield-account-outline</v-icon>
        <span v-if="!isRail" class="brand-name">管理后台</span>
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
        <template v-for="group in navGroups" :key="group.title">
          <div v-if="!isRail" class="nav-group-title">{{ group.title }}</div>
          <v-divider v-else-if="group.title !== navGroups[0].title" class="my-2" />
          <v-list-item
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            :prepend-icon="item.icon"
            :title="isRail ? undefined : item.title"
            rounded="lg"
            color="primary"
            class="nav-item"
            :aria-label="item.title"
          />
        </template>

        <v-divider class="my-2" />
        <v-list-item
          v-if="auth.isAdmin && auth.astrbotDashboardUrl"
          prepend-icon="mdi-open-in-new"
          :title="isRail ? undefined : 'AstrBot 后台'"
          rounded="lg"
          color="primary"
          class="nav-item"
          aria-label="AstrBot 后台"
          data-testid="admin-astrbot-dashboard"
          @click="openDashboard"
        />
        <v-list-item
          to="/"
          prepend-icon="mdi-arrow-left"
          :title="isRail ? undefined : '返回控制台'"
          rounded="lg"
          color="primary"
          class="nav-item"
          aria-label="返回控制台"
        />
      </v-list>

      <v-spacer />

      <div class="sidebar-footer">
        <div v-if="!isRail" class="version-line">AstrBot SaaS {{ auth.version || '0.4.0' }}</div>
      </div>
    </div>
  </v-navigation-drawer>

  <v-app-bar flat height="56" class="admin-topbar">
    <v-app-bar-nav-icon v-if="isMobile" aria-label="打开导航" @click="drawerOpen = !drawerOpen" />
    <v-app-bar-title class="topbar-title">{{ currentTitle }}</v-app-bar-title>
    <v-spacer />
    <v-btn icon variant="text" :aria-label="isDark ? '切换浅色主题' : '切换深色主题'" @click="toggleTheme">
      <v-icon>{{ isDark ? 'mdi-weather-night' : 'mdi-white-balance-sunny' }}</v-icon>
    </v-btn>
    <UserMenu context="admin" class="mr-1" />
  </v-app-bar>

  <v-main class="admin-main">
    <div class="page-container">
      <router-view />
    </div>
  </v-main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useDisplay } from 'vuetify'
import { useAuthStore } from '@/stores/auth'
import { useThemeMode } from '@/composables/useThemeMode'
import UserMenu from '@/components/UserMenu.vue'

const auth = useAuthStore()
const route = useRoute()
const { smAndDown } = useDisplay()
const { isDark, toggle: toggleTheme } = useThemeMode()

const isMobile = computed(() => smAndDown.value)
const drawerOpen = ref(!isMobile.value)
const rail = ref(false)
const isRail = computed(() => rail.value && !isMobile.value)

watch(isMobile, (mobile) => {
  drawerOpen.value = !mobile
})

const navGroups = [
  {
    title: '运营管理',
    items: [
      { to: '/admin/templates', title: '模板管理', icon: 'mdi-file-document-multiple-outline' },
      { to: '/admin/users', title: '用户管理', icon: 'mdi-account-group-outline' },
      { to: '/admin/bots', title: 'Bot 管理', icon: 'mdi-robot-outline' },
      { to: '/admin/orders', title: '手动充值', icon: 'mdi-cash-plus' },
    ],
  },
  {
    title: '系统设置',
    items: [
      { to: '/admin/models', title: '模型与定价', icon: 'mdi-robot-happy-outline' },
      { to: '/admin/settings', title: '记忆 API 设置', icon: 'mdi-tune-variant' },
      { to: '/admin/audit', title: '审计日志', icon: 'mdi-clipboard-text-clock-outline' },
    ],
  },
]

const currentTitle = computed(() => {
  const title = route.meta.title
  return typeof title === 'string' && title ? title : '管理后台'
})

function openDashboard(): void {
  if (!auth.astrbotDashboardUrl) return
  window.open(auth.astrbotDashboardUrl, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.admin-drawer {
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

.admin-topbar {
  border-bottom: 1px solid var(--console-border);
  background: var(--console-surface);
}

.topbar-title {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0;
}

@media (min-width: 960px) {
  .topbar-title {
    visibility: hidden;
  }
}

.admin-main {
  background: var(--console-bg);
}
</style>
