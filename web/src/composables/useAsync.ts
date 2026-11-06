import { ref, shallowRef } from 'vue'
import { toApiError, type ApiError } from '@/api/client'

/** 通用异步加载状态：data / loading / error / run。 */
export function useAsync<T>(loader: () => Promise<T>) {
  const data = shallowRef<T | null>(null)
  const loading = ref(false)
  const error = ref<ApiError | null>(null)

  async function run(): Promise<T | null> {
    loading.value = true
    error.value = null
    try {
      data.value = await loader()
      return data.value
    } catch (err) {
      error.value = toApiError(err)
      return null
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, run }
}
