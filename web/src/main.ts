import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import '@/styles/global.css'
import App from './App.vue'
import router from './router'
import { vuetify } from './theme'
import { setForbiddenHandler, setUnauthorizedHandler } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(vuetify)

const auth = useAuthStore(pinia)
const ui = useUiStore(pinia)

// 任意接口 401：清 store → 跳登录（登录页本身不跳，避免循环）
setUnauthorizedHandler(() => {
  auth.clear()
  const current = router.currentRoute.value
  if (current.path === '/login') return
  const query: Record<string, string> = {}
  if (current.meta.requiresAuth) query.redirect = current.fullPath
  void router.replace({ path: '/login', query })
})

// 403：只提示无权限，不登出
setForbiddenHandler(() => {
  ui.notifyError('没有权限执行该操作')
})

app.use(router)
app.mount('#app')
