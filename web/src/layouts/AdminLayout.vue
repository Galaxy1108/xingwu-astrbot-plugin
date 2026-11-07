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
        <v-list-item
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="isRail ? undefined : item.title"
          rounded="lg"
          color="primary"
          class="nav-item"
          :aria-label="item.title"
        />
        <v-divider class="my-2" />
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

  <v-app-bar flat height="56" class="admin-topbar">
    <v-app-bar-nav-icon v-if="isMobile" aria-label="打开导航" @click="drawerOpen = !drawerOpen" />
    <v-app-bar-title class="topbar-title">{{ currentTitle }}</v-app-bar-title>
    <v-spacer />
    <v-chip size="small" variant="tonal" color="primary" class="mr-2">管理员模式</v-chip>
  </v-app-bar>

  <v-main class="admin-main">
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
const rail = ref(false)
const isRail = computed(() => rail.value && !isMobile.value)

watch(isMobile, (mobile) => {
  drawerOpen.value = !mobile
})

const navItems = [
  { to: '/admin/templates', title: '模板管理', icon: 'mdi-file-document-multiple-outline' },
  { to: '/admin/users', title: '用户管理', icon: 'mdi-account-group-outline' },
  { to: '/admin/bots', title: 'Bot 管理', icon: 'mdi-robot-outline' },
  { to: '/admin/models', title: '模型与定价', icon: 'mdi-robot-happy-outline' },
  { to: '/admin/settings', title: '记忆 API 设置', icon: 'mdi-api-cog' },
  { to: '/admin/audit', title: '审计日志', icon: 'mdi-clipboard-text-clock-outline' },
  { to: '/admin/orders', title: '手动充值', icon: 'mdi-cash-plus' },
]

const currentTitle = computed(() => {
  const title = route.meta.title
  return typeof title === 'string' && title ? title : '管理后台'
})

async function onLogout(): Promise<void> {
  await auth.logout()
  ui.notify('已退出登录', 'info')
  await router.replace('/login')
}
</script>

<style scoped>
.admin-drawer {
  border-right: 1px solid rgba(0, 0, 0, 0.06);
  background: #fff;
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
  color: rgba(0, 0, 0, 0.45);
}

.nav-list {
  padding: 6px 8px;
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
  border-top: 1px solid rgba(0, 0, 0, 0.07);
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
  color: rgba(0, 0, 0, 0.38);
}

.admin-topbar {
  border-bottom: 1px solid rgba(0, 0, 0, 0.07);
  background: #fff;
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
