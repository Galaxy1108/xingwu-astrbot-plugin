import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { installGuards } from './guards'
import ConsoleLayout from '@/layouts/ConsoleLayout.vue'
import AdminLayout from '@/layouts/AdminLayout.vue'
import AuthLayout from '@/layouts/AuthLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: AuthLayout,
    meta: { guestOnly: true },
    children: [
      {
        path: '',
        name: 'login',
        component: () => import('@/views/auth/LoginView.vue'),
        meta: { title: '登录', guestOnly: true },
      },
    ],
  },
  {
    path: '/',
    component: ConsoleLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '总览' },
      },
      {
        path: 'connect',
        name: 'connect',
        component: () => import('@/views/connect/ConnectView.vue'),
        meta: { title: '添加机器人' },
      },
      {
        path: 'bots',
        name: 'bots',
        component: () => import('@/views/bots/BotListView.vue'),
        meta: { title: '我的 Bot' },
      },
      {
        path: 'bots/:id',
        name: 'bot-detail',
        component: () => import('@/views/bots/BotDetailView.vue'),
        meta: { title: 'Bot 详情' },
      },
      {
        path: 'bots/:id/conversations',
        name: 'bot-conversations',
        component: () => import('@/views/bots/ConversationsView.vue'),
        meta: { title: '对话历史' },
      },
      {
        path: 'bots/:id/notes',
        name: 'bot-notes',
        component: () => import('@/views/bots/NotesView.vue'),
        meta: { title: '笔记' },
      },
      {
        path: 'bots/:id/memory',
        name: 'bot-memory',
        component: () => import('@/views/memory/MemoryView.vue'),
        meta: { title: '记忆' },
      },
      {
        path: 'settings/privacy',
        name: 'privacy',
        component: () => import('@/views/settings/PrivacyView.vue'),
        meta: { title: '隐私与加密' },
      },
      {
        path: 'settings/account',
        name: 'account-settings',
        component: () => import('@/views/settings/AccountView.vue'),
        meta: { title: '账户设置' },
      },
      {
        path: 'billing',
        name: 'billing',
        component: () => import('@/views/billing/BillingView.vue'),
        meta: { title: '额度' },
      },
      {
        path: 'access-log',
        name: 'access-log',
        component: () => import('@/views/access/AccessLogView.vue'),
        meta: { title: '访问记录' },
      },
      {
        path: '403',
        name: 'forbidden',
        component: () => import('@/views/errors/ForbiddenView.vue'),
        meta: { title: '无权限' },
      },
    ],
  },
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAuth: true, role: 'admin' },
    children: [
      { path: '', redirect: '/admin/templates' },
      {
        path: 'templates',
        name: 'admin-templates',
        component: () => import('@/views/admin/TemplatesView.vue'),
        meta: { title: '模板管理', role: 'admin' },
      },
      {
        path: 'users',
        name: 'admin-users',
        component: () => import('@/views/admin/UsersView.vue'),
        meta: { title: '用户管理', role: 'admin' },
      },
      {
        path: 'invites',
        name: 'admin-invites',
        component: () => import('@/views/admin/InvitesView.vue'),
        meta: { title: '邀请码', role: 'admin' },
      },
      {
        path: 'bots',
        name: 'admin-bots',
        component: () => import('@/views/admin/BotsView.vue'),
        meta: { title: 'Bot 管理', role: 'admin' },
      },
      {
        path: 'models',
        name: 'admin-models',
        component: () => import('@/views/admin/ModelsView.vue'),
        meta: { title: '模型与定价', role: 'admin' },
      },
      {
        path: 'settings/oauth',
        name: 'admin-oauth-settings',
        component: () => import('@/views/admin/OAuthSettingsView.vue'),
        meta: { title: '第三方登录' },
      },
      {
        path: 'settings',
        name: 'admin-settings',
        component: () => import('@/views/admin/SettingsView.vue'),
        meta: { title: '记忆 API 设置', role: 'admin' },
      },
      {
        path: 'appeals',
        name: 'admin-appeals',
        component: () => import('@/views/admin/AppealsView.vue'),
        meta: { title: '申诉处理', role: 'admin' },
      },
      {
        path: 'audit',
        name: 'admin-audit',
        component: () => import('@/views/admin/AuditView.vue'),
        meta: { title: '审计日志', role: 'admin' },
      },
      {
        path: 'redemption-codes',
        name: 'admin-redemption-codes',
        component: () => import('@/views/admin/RedemptionCodesView.vue'),
        meta: { title: '兑换码', role: 'admin' },
      },
      {
        path: 'orders',
        name: 'admin-orders',
        component: () => import('@/views/admin/OrdersView.vue'),
        meta: { title: '手动充值', role: 'admin' },
      },
    ],
  },
  {
    path: '/oauth/callback',
    name: 'oauth-callback',
    component: () => import('@/views/auth/OAuthCallbackView.vue'),
    meta: { title: '第三方登录', public: true },
  },
  {
    path: '/share/:token',
    name: 'public-share',
    component: () => import('@/views/share/PublicShareView.vue'),
    meta: { title: '对话分享', public: true },
  },
  {
    path: '/banned',
    name: 'banned',
    component: () => import('@/views/auth/BannedView.vue'),
    meta: { title: '账号已被封禁', requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/errors/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory('/console/'),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

installGuards(
  router,
  () => {
    const auth = useAuthStore()
    return {
      ready: auth.status === 'ready',
      isAuthenticated: auth.isAuthenticated,
      role: auth.role,
      status: auth.user?.status ?? null,
    }
  },
  () => useAuthStore().ensureLoaded(),
)

export default router
