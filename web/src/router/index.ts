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
        meta: { title: '扫码接入' },
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
        path: 'settings/privacy',
        name: 'privacy',
        component: () => import('@/views/settings/PrivacyView.vue'),
        meta: { title: '隐私与加密' },
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
        path: 'bots',
        name: 'admin-bots',
        component: () => import('@/views/admin/BotsView.vue'),
        meta: { title: 'Bot 管理', role: 'admin' },
      },
      {
        path: 'audit',
        name: 'admin-audit',
        component: () => import('@/views/admin/AuditView.vue'),
        meta: { title: '审计日志', role: 'admin' },
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
    }
  },
  () => useAuthStore().ensureLoaded(),
)

export default router
