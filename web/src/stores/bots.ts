import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as botsApi from '@/api/bots'
import { toApiError, type ApiError } from '@/api/client'
import type { Bot, BotCreatePayload, BotPatchPayload, QrSession } from '@/types'

export const useBotsStore = defineStore('bots', () => {
  const items = ref<Bot[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<ApiError | null>(null)
  const current = ref<Bot | null>(null)
  const currentLoading = ref(false)
  const currentError = ref<ApiError | null>(null)
  const qr = ref<QrSession | null>(null)
  const qrError = ref<ApiError | null>(null)

  const total = computed(() => items.value.length)
  const readyBots = computed(() => items.value.filter((bot) => bot.status === 'ready'))

  async function fetchBots(force = false): Promise<Bot[]> {
    if (loaded.value && !force) return items.value
    loading.value = true
    error.value = null
    try {
      const result = await botsApi.listBots()
      items.value = result.items ?? []
      loaded.value = true
      return items.value
    } catch (err) {
      error.value = toApiError(err)
      throw error.value
    } finally {
      loading.value = false
    }
  }

  async function loadBot(id: string, force = false): Promise<Bot> {
    if (!force && current.value?.id === id) return current.value
    currentLoading.value = true
    currentError.value = null
    try {
      const result = await botsApi.getBot(id)
      current.value = result.bot
      qr.value = result.bot.qr ?? null
      upsert(result.bot)
      return result.bot
    } catch (err) {
      currentError.value = toApiError(err)
      current.value = null
      throw currentError.value
    } finally {
      currentLoading.value = false
    }
  }

  function upsert(bot: Bot): void {
    const index = items.value.findIndex((item) => item.id === bot.id)
    if (index >= 0) items.value.splice(index, 1, bot)
    else items.value.unshift(bot)
  }

  async function createBot(payload: BotCreatePayload): Promise<Bot> {
    const result = await botsApi.createBot(payload)
    upsert(result.bot)
    return result.bot
  }

  async function updateBot(id: string, payload: BotPatchPayload): Promise<Bot> {
    const result = await botsApi.patchBot(id, payload)
    upsert(result.bot)
    if (current.value?.id === id) current.value = result.bot
    return result.bot
  }

  async function removeBot(id: string, confirmName: string): Promise<void> {
    await botsApi.deleteBot(id, confirmName)
    items.value = items.value.filter((bot) => bot.id !== id)
    if (current.value?.id === id) current.value = null
  }

  async function startQr(id: string): Promise<QrSession> {
    qrError.value = null
    try {
      const result = await botsApi.startQr(id)
      qr.value = result.qr
      if (current.value?.id === id) current.value = { ...current.value, qr: result.qr }
      return result.qr
    } catch (err) {
      qrError.value = toApiError(err)
      throw qrError.value
    }
  }

  async function pollQr(id: string): Promise<{ qr: QrSession; message?: string }> {
    try {
      const result = await botsApi.pollQr(id)
      qr.value = result.qr
      return result
    } catch (err) {
      qrError.value = toApiError(err)
      throw qrError.value
    }
  }

  async function finalizeQr(id: string): Promise<Bot> {
    const result = await botsApi.finalizeQr(id)
    qr.value = null
    upsert(result.bot)
    if (current.value?.id === id) current.value = result.bot
    return result.bot
  }

  function resetCurrent(): void {
    current.value = null
    currentError.value = null
    qr.value = null
    qrError.value = null
  }

  return {
    items,
    loading,
    loaded,
    error,
    current,
    currentLoading,
    currentError,
    qr,
    qrError,
    total,
    readyBots,
    fetchBots,
    loadBot,
    createBot,
    updateBot,
    removeBot,
    startQr,
    pollQr,
    finalizeQr,
    resetCurrent,
  }
})
