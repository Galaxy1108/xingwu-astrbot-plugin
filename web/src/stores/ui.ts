import { defineStore } from 'pinia'
import { reactive } from 'vue'

export type ToastColor = 'success' | 'error' | 'info' | 'warning'

export interface SnackbarState {
  show: boolean
  text: string
  color: ToastColor
  timeout: number
}

export const useUiStore = defineStore('ui', () => {
  const snackbar = reactive<SnackbarState>({
    show: false,
    text: '',
    color: 'success',
    timeout: 4000,
  })

  function notify(text: string, color: ToastColor = 'success', timeout = 4000): void {
    snackbar.text = text
    snackbar.color = color
    snackbar.timeout = timeout
    snackbar.show = true
  }

  function notifyError(text: string): void {
    notify(text, 'error', 6000)
  }

  function close(): void {
    snackbar.show = false
  }

  return { snackbar, notify, notifyError, close }
})
