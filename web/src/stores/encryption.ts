import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getEncryptionStatus } from '@/api/privacy'
import { toApiError, type ApiError } from '@/api/client'
import type { EncryptionStatus } from '@/types'

export const useEncryptionStore = defineStore('encryption', () => {
  const status = ref<EncryptionStatus | null>(null)
  const loading = ref(false)
  const error = ref<ApiError | null>(null)

  const enabled = computed(() => status.value?.enabled ?? true)
  const state = computed(() => status.value?.state ?? 'encrypted')
  const isPlaintext = computed(() => state.value === 'plaintext' || status.value?.enabled === false)
  const inProgress = computed(
    () => state.value === 'decrypting' || state.value === 'encrypting' || state.value === 'paused',
  )
  const percent = computed(() => {
    const total = status.value?.total ?? 0
    if (total <= 0) return state.value === 'encrypted' || state.value === 'decrypted' ? 100 : 0
    return Math.min(100, Math.round(((status.value?.done ?? 0) / total) * 100))
  })

  async function fetchStatus(): Promise<EncryptionStatus> {
    loading.value = true
    error.value = null
    try {
      const result = await getEncryptionStatus()
      status.value = result
      return result
    } catch (err) {
      error.value = toApiError(err)
      throw error.value
    } finally {
      loading.value = false
    }
  }

  return { status, loading, error, enabled, state, isPlaintext, inProgress, percent, fetchStatus }
})
