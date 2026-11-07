<template>
  <Teleport to="body">
    <transition name="reason-fade">
      <div v-if="modelValue" class="reason-backdrop" @click.self="onCancel" @keydown.esc="onCancel">
        <div class="reason-panel" role="dialog" aria-modal="true" :aria-labelledby="titleId">
          <h2 :id="titleId" class="reason-title">{{ title }}</h2>
          <p v-if="message" class="reason-message">{{ message }}</p>
          <label class="reason-label" :for="inputId">{{ label }}</label>
          <textarea
            :id="inputId"
            ref="textarea"
            v-model="reason"
            class="reason-input"
            rows="4"
            :placeholder="placeholder"
            :maxlength="maxlength"
          />
          <p v-if="error" class="reason-error">{{ error }}</p>
          <div class="reason-actions">
            <button type="button" class="reason-btn reason-btn--ghost" data-testid="reason-cancel" @click="onCancel">
              {{ cancelText }}
            </button>
            <button
              type="button"
              class="reason-btn"
              :class="danger ? 'reason-btn--danger' : 'reason-btn--primary'"
              data-testid="reason-confirm"
              :disabled="loading"
              @click="onConfirm"
            >
              {{ loading ? '处理中…' : confirmText }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, ref, useId, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    message?: string
    label?: string
    placeholder?: string
    confirmText?: string
    cancelText?: string
    danger?: boolean
    loading?: boolean
    required?: boolean
    maxlength?: number
  }>(),
  {
    message: '',
    label: '原因',
    placeholder: '请填写原因（会记录到审计与通知中）',
    confirmText: '确认',
    cancelText: '取消',
    danger: false,
    loading: false,
    required: true,
    maxlength: 500,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [reason: string]
  cancel: []
}>()

const titleId = useId()
const inputId = useId()
const textarea = ref<HTMLTextAreaElement | null>(null)
const reason = ref('')
const error = ref('')

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      reason.value = ''
      error.value = ''
      await nextTick()
      textarea.value?.focus()
    }
  },
  { immediate: true },
)

function onCancel(): void {
  if (props.loading) return
  emit('update:modelValue', false)
  emit('cancel')
}

function onConfirm(): void {
  if (props.loading) return
  const value = reason.value.trim()
  if (props.required && !value) {
    error.value = '请填写原因'
    return
  }
  emit('confirm', value)
}
</script>

<style scoped>
.reason-backdrop {
  position: fixed;
  inset: 0;
  z-index: 2500;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(16, 24, 40, 0.52);
  backdrop-filter: blur(2px);
}

.reason-panel {
  width: 100%;
  max-width: 500px;
  background: var(--console-surface);
  color: var(--console-text);
  border: 1px solid var(--console-border);
  border-radius: 12px;
  box-shadow: 0 16px 40px rgba(16, 24, 40, 0.24);
  padding: 22px;
  box-sizing: border-box;
}

.reason-title {
  margin: 0 0 10px;
  font-size: 18px;
  font-weight: 650;
  line-height: 1.4;
}

.reason-message {
  margin: 0 0 12px;
  color: var(--console-text-muted);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-line;
}

.reason-label {
  display: block;
  margin-bottom: 6px;
  font-size: 12.5px;
  color: var(--console-text);
}

.reason-input {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  padding: 10px 12px;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  color: var(--console-text);
  background: var(--console-surface);
  border: 1px solid var(--console-border);
  border-radius: 8px;
  outline: none;
}

.reason-input:focus {
  border-color: var(--console-primary);
  box-shadow: 0 0 0 3px rgba(60, 150, 202, 0.18);
}

.reason-error {
  margin: 6px 0 0;
  color: var(--console-danger);
  font-size: 12px;
}

.reason-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
}

.reason-btn {
  min-height: 40px;
  padding: 0 18px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
}

.reason-btn--ghost {
  background: transparent;
  border-color: var(--console-border);
  color: var(--console-text);
}

.reason-btn--ghost:hover {
  background: rgba(120, 120, 120, 0.08);
}

.reason-btn--primary {
  background: var(--console-primary);
  color: #fff;
}

.reason-btn--danger {
  background: var(--console-danger-soft);
  border-color: var(--console-danger-border);
  color: var(--console-danger);
}

.reason-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.reason-fade-enter-active,
.reason-fade-leave-active {
  transition: opacity 0.15s ease;
}

.reason-fade-enter-from,
.reason-fade-leave-to {
  opacity: 0;
}
</style>
