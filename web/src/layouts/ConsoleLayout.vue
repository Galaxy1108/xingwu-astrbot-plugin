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
        <button
          v-if="isRail"
          type="button"
          class="rail-brand"
          aria-label="展开侧栏"
          @click="rail = false"
        >
          <BrandMark :size="26" />
        </button>
        <template v-else>
          <BrandMark :size="26" />
          <span class="brand-name">星坞</span>
          <v-chip size="x-small" variant="tonal" color="primary" class="brand-chip">Alpha</v-chip>
          <v-spacer />
          <v-btn
            v-if="!isMobile"
            icon
            size="small"
            variant="text"
            class="rail-toggle"
            aria-label="收起侧栏"
            @click="rail = true"
          >
            <v-icon size="18">mdi-menu-open</v-icon>
          </v-btn>
        </template>
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
        <div v-if="!isRail" class="version-line">星坞 {{ auth.version || '0.5.0' }} · Alpha</div>
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
    <UserMenu context="console" class="mr-1" />
    <v-btn icon variant="text" aria-label="刷新页面" title="刷新页面" @click="refreshPage">
      <v-icon>mdi-refresh</v-icon>
    </v-btn>
  </v-app-bar>

  <v-main class="console-main">
    <div class="content-shell">
      <div class="page-container">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </div>
  </v-main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useDisplay } from 'vuetify'
import BrandMark from '@/components/BrandMark.vue'
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

const navItems = [
  { to: '/', title: '总览', icon: 'mdi-view-dashboard-outline' },
  { to: '/bots', title: '我的 Bot', icon: 'mdi-robot-outline' },
  { to: '/settings/privacy', title: '隐私与加密', icon: 'mdi-shield-lock-outline' },
  { to: '/billing', title: '额度', icon: 'mdi-wallet-outline' },
  { to: '/settings/account', title: '账户设置', icon: 'mdi-account-cog-outline' },
]

const currentTitle = computed(() => {
  const title = route.meta.title
  return typeof title === 'string' && title ? title : '控制台'
})

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

.rail-brand {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 0;
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
}

.rail-brand:hover {
  background: var(--console-surface-variant);
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
