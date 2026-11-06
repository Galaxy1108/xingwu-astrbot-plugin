import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchMe as fetchMeApi, logoutRequest, requestOtp, verifyOtp } from '@/api/auth'
import { isApiError } from '@/api/client'
import type { Limits, MeResponse, User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const limits = ref<Limits | null>(null)
  const version = ref('')
  const status = ref<'idle' | 'loading' | 'ready'>('idle')
  const lastError = ref<string | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const role = computed(() => user.value?.role ?? null)
  const ready = computed(() => status.value === 'ready')

  function applyMe(me: MeResponse): void {
    user.value = me.user
    limits.value = me.limits ?? null
    version.value = me.version ?? ''
  }

  /** 启动时拉取会话；401 视为未登录，其它错误向上抛给调用方决定文案。 */
  async function fetchMe(): Promise<boolean> {
    status.value = 'loading'
    lastError.value = null
    try {
      const me = await fetchMeApi()
      applyMe(me)
      status.value = 'ready'
      return true
    } catch (error) {
      user.value = null
      limits.value = null
      status.value = 'ready'
      if (!(isApiError(error) && error.status === 401)) {
        lastError.value = isApiError(error) ? error.message : '无法确认登录状态'
      }
      return false
    }
  }

  let loadingPromise: Promise<boolean> | null = null

  async function ensureLoaded(): Promise<void> {
    if (status.value === 'ready') return
    if (!loadingPromise) {
      loadingPromise = fetchMe().finally(() => {
        loadingPromise = null
      })
    }
    await loadingPromise
  }

  async function loginRequest(email: string, invite?: string) {
    return requestOtp(email, invite)
  }

  async function loginVerify(payload: { email: string; code: string; invite?: string }) {
    const result = await verifyOtp(payload)
    user.value = result.user
    status.value = 'ready'
    // verify 后补一次 me 以拿到 limits/version（失败不影响登录）
    try {
      const me = await fetchMeApi()
      applyMe(me)
    } catch {
      /* ignore */
    }
    return result
  }

  async function logout(): Promise<void> {
    try {
      await logoutRequest()
    } finally {
      clear()
    }
  }

  function clear(): void {
    user.value = null
    limits.value = null
    version.value = ''
    status.value = 'ready'
    lastError.value = null
  }

  return {
    user,
    limits,
    version,
    status,
    lastError,
    ready,
    isAuthenticated,
    isAdmin,
    role,
    fetchMe,
    ensureLoaded,
    loginRequest,
    loginVerify,
    logout,
    clear,
  }
})
