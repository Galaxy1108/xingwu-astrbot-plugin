import { onBeforeUnmount, onMounted, ref } from 'vue'

export interface PollingOptions {
  /** 轮询间隔（毫秒），默认 2000。 */
  interval?: number
  /** 启动时立即执行一次，默认 true。 */
  immediate?: boolean
  /** 页面隐藏时暂停、恢复时立即补一次，默认 true。 */
  pauseWhenHidden?: boolean
}

/**
 * 轻量轮询：任务返回 true 表示停止。
 * 页面隐藏（visibilitychange）时暂停定时器，可见时立即补一次。
 */
export function usePolling(
  task: () => Promise<boolean | void> | boolean | void,
  options: PollingOptions = {},
) {
  const interval = options.interval ?? 2000
  const active = ref(false)
  const paused = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let inFlight = false
  let disposed = false

  function clearTimer(): void {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  function schedule(delay = interval): void {
    clearTimer()
    if (!active.value || paused.value || disposed) return
    timer = setTimeout(() => {
      void tick()
    }, delay)
  }

  async function tick(): Promise<void> {
    if (!active.value || paused.value || disposed) return
    if (inFlight) {
      schedule()
      return
    }
    inFlight = true
    let shouldStop = false
    try {
      shouldStop = (await task()) === true
    } catch {
      // 错误由任务的调用方记录，轮询继续
    } finally {
      inFlight = false
    }
    if (shouldStop) {
      stop()
      return
    }
    schedule()
  }

  function start(): void {
    if (active.value) return
    active.value = true
    paused.value = false
    if (options.immediate !== false) void tick()
    else schedule()
  }

  function stop(): void {
    active.value = false
    clearTimer()
  }

  function onVisibilityChange(): void {
    if (options.pauseWhenHidden === false) return
    const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden'
    paused.value = hidden
    if (hidden) {
      clearTimer()
    } else if (active.value) {
      void tick()
    }
  }

  onMounted(() => {
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange)
    }
  })

  onBeforeUnmount(() => {
    disposed = true
    stop()
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  })

  return { active, paused, start, stop, tick }
}
