import { onBeforeUnmount, ref } from 'vue'

/** 复制到剪贴板，2 秒后恢复“复制”态。 */
export function useClipboard(resetAfter = 2000) {
  const copied = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  async function copy(text: string): Promise<boolean> {
    if (!text) return false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        fallbackCopy(text)
      }
      copied.value = true
      if (timer !== null) clearTimeout(timer)
      timer = setTimeout(() => {
        copied.value = false
      }, resetAfter)
      return true
    } catch {
      const ok = fallbackCopy(text)
      copied.value = ok
      return ok
    }
  }

  function fallbackCopy(text: string): boolean {
    if (typeof document === 'undefined') return false
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    document.body.removeChild(textarea)
    return ok
  }

  onBeforeUnmount(() => {
    if (timer !== null) clearTimeout(timer)
  })

  return { copied, copy }
}
