<template>
  <v-navigation-drawer
    v-model="drawerOpen"
    :permanent="!isMobile"
    :temporary="isMobile"
    :width="232"
    class="admin-drawer"
    elevation="1"
  >
    <div class="brand-row">
      <v-icon color="primary" size="26">mdi-shield-account-outline</v-icon>
      <span class="brand-name">管理后台</span>
    </div>
    <v-divider />
    <v-list nav density="compact" class="nav-list">
      <v-list-item
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        :prepend-icon="item.icon"
        :title="item.title"
        rounded="lg"
      />
      <v-divider class="my-2" />
      <v-list-item to="/" prepend-icon="mdi-arrow-left" title="返回控制台" rounded="lg" />
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

watch(isMobile, (mobile) => {
  drawerOpen.value = !mobile
})

const navItems = [
  { to: '/admin/templates', title: '模板管理', icon: 'mdi-file-document-multiple-outline' },
  { to: '/admin/users', title: '用户管理', icon: 'mdi-account-group-outline' },
  { to: '/admin/bots', title: 'Bot 管理', icon: 'mdi-robot-outline' },
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
}

.nav-list {
  padding: 8px;
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

.admin-topbar {
  border-bottom: 1px solid var(--console-border);
  background: var(--console-surface);
}

.topbar-title {
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0;
}

.admin-main {
  background: var(--console-bg);
}
</style>
