<template>
  <Teleport to="body">
    <transition name="confirm-fade">
      <div
        v-if="modelValue"
        class="confirm-backdrop"
        @click.self="onCancel"
        @keydown.esc="onCancel"
      >
        <div
          ref="panel"
          class="confirm-panel"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
        >
          <h2 :id="titleId" class="confirm-title">{{ title }}</h2>
          <div class="confirm-body">
            <slot>
              <p class="confirm-message">{{ message }}</p>
            </slot>
            <div v-if="typeToConfirm" class="confirm-type">
              <label class="confirm-label" :for="inputId">
                请输入 <strong>{{ typeToConfirm }}</strong> 以确认
              </label>
              <input
                :id="inputId"
                ref="typeInput"
                v-model="typed"
                class="confirm-input"
                data-testid="confirm-input"
                type="text"
                autocomplete="off"
                :placeholder="typeToConfirm"
                @keydown.enter="onConfirm"
              />
              <p v-if="typed && !matched" class="confirm-error">输入内容与要求不一致</p>
            </div>
          </div>
          <div class="confirm-actions">
            <button
              ref="cancelButton"
              type="button"
              class="confirm-btn confirm-btn--ghost"
              data-testid="confirm-cancel"
              @click="onCancel"
            >
              {{ cancelText }}
            </button>
            <button
              type="button"
              class="confirm-btn"
              :class="danger ? 'confirm-btn--danger' : 'confirm-btn--primary'"
              data-testid="confirm-submit"
              :disabled="!canConfirm || loading"
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
import { computed, nextTick, ref, useId, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    message?: string
    confirmText?: string
    cancelText?: string
    danger?: boolean
    loading?: boolean
    typeToConfirm?: string
  }>(),
  {
    message: '',
    confirmText: '确认',
    cancelText: '取消',
    danger: false,
    loading: false,
    typeToConfirm: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: []
  cancel: []
}>()

const titleId = useId()
const inputId = useId()
const panel = ref<HTMLElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
const typeInput = ref<HTMLInputElement | null>(null)
const typed = ref('')

const matched = computed(() => !props.typeToConfirm || typed.value === props.typeToConfirm)
const canConfirm = computed(() => matched.value && !props.loading)

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      typed.value = ''
      await nextTick()
      cancelButton.value?.focus()
    }
  },
  { immediate: true },
)

watch(
  () => props.typeToConfirm,
  () => {
    typed.value = ''
  },
)

function onCancel(): void {
  if (props.loading) return
  emit('update:modelValue', false)
  emit('cancel')
}

function onConfirm(): void {
  if (!canConfirm.value) return
  emit('confirm')
}
</script>

<style scoped>
.confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 2400;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(16, 24, 40, 0.5);
  backdrop-filter: blur(2px);
}

.confirm-panel {
  width: 100%;
  max-width: 480px;
  background: var(--console-surface);
  border-radius: var(--console-radius);
  box-shadow: 0 16px 40px rgba(16, 24, 40, 0.24);
  padding: 20px;
  box-sizing: border-box;
  outline: none;
}

.confirm-title {
  margin: 0 0 10px;
  font-size: 1.05rem;
  font-weight: 650;
  line-height: 1.4;
}

.confirm-body {
  color: var(--console-text-muted);
  font-size: 0.875rem;
  line-height: 1.6;
}

.confirm-message {
  margin: 0;
  white-space: pre-line;
}

.confirm-type {
  margin-top: 14px;
}

.confirm-label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.82rem;
  color: var(--console-text);
}

.confirm-input {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  font-size: 0.9rem;
  color: var(--console-text);
  background: var(--console-surface);
  border: 1px solid var(--console-border);
  border-radius: var(--console-radius);
  outline: none;
}

.confirm-input:focus {
  border-color: var(--console-primary);
  box-shadow: 0 0 0 3px rgba(60, 150, 202, 0.18);
}

.confirm-error {
  margin: 6px 0 0;
  color: #c62828;
  font-size: 0.78rem;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

.confirm-btn {
  min-height: 40px;
  padding: 0 18px;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: var(--console-radius);
  border: 1px solid transparent;
  cursor: pointer;
}

.confirm-btn:focus-visible {
  outline: 2px solid var(--console-primary);
  outline-offset: 2px;
}

.confirm-btn--ghost {
  background: transparent;
  border-color: var(--console-border);
  color: var(--console-text);
}

.confirm-btn--ghost:hover {
  background: #f2f5f8;
}

.confirm-btn--primary {
  background: var(--console-primary);
  color: #fff;
}

.confirm-btn--primary:hover {
  background: var(--console-primary-dark);
}

.confirm-btn--danger {
  background: #c62828;
  color: #fff;
}

.confirm-btn--danger:hover {
  background: #a61f1f;
}

.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.confirm-fade-enter-active,
.confirm-fade-leave-active {
  transition: opacity 0.15s ease;
}

.confirm-fade-enter-from,
.confirm-fade-leave-to {
  opacity: 0;
}
</style>
