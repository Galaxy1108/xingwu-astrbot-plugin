import { computed, ref } from 'vue'
import { useTheme } from 'vuetify'

type ThemeMode = 'light' | 'dark'

const mode = ref<ThemeMode>('light')
const STORAGE_KEY = 'saas-theme'

function apply(next: ThemeMode): void {
  mode.value = next
  const theme = (window as any).__saasTheme
  if (theme) theme.global.name.value = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* ignore */
  }
  document.documentElement.dataset.theme = next
}

export function initTheme(): void {
  let next: ThemeMode = 'light'
  try {
    const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
    if (saved === 'light' || saved === 'dark') next = saved
    else if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) next = 'dark'
  } catch {
    /* ignore */
  }
  apply(next)
}

export function useThemeMode() {
  const theme = useTheme()
  ;(window as any).__saasTheme = theme
  theme.global.name.value = mode.value
  const isDark = computed(() => mode.value === 'dark')
  function toggle(): void {
    apply(isDark.value ? 'light' : 'dark')
    theme.global.name.value = mode.value
  }
  return { isDark, toggle, mode }
}
