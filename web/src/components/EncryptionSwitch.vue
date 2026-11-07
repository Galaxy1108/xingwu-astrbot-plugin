<template>
  <v-card class="encryption-switch">
    <div class="encryption-switch__row">
      <div class="encryption-switch__copy">
        <div class="encryption-switch__title">
          <v-icon size="18" color="primary">mdi-shield-lock-outline</v-icon>
          <span>对话与记忆加密</span>
        </div>
        <p class="encryption-switch__desc">
          开启后，对话内容与记忆条目在写入磁盘前加密；管理员查看明文会留下访问记录。
        </p>
      </div>
      <v-switch
        :model-value="enabled"
        :disabled="readonly || busy || inProgress"
        color="primary"
        hide-details
        inset
        :aria-label="enabled ? '关闭加密' : '开启加密'"
        @update:model-value="onToggle"
      />
    </div>

    <div class="encryption-switch__meta">
      <StatusChip :status="state" kind="encryption" />
      <span class="text-muted encryption-switch__hint">{{ stateHint }}</span>
    </div>

    <div v-if="inProgress && total > 0" class="encryption-switch__progress">
      <v-progress-linear
        :model-value="percent"
        :color="state === 'paused' ? 'error' : 'primary'"
        height="8"
        rounded
      />
      <span class="text-muted">{{ done }}/{{ total }}（{{ percent }}%）</span>
    </div>

    <v-alert
      v-if="isPlaintext"
      type="error"
      variant="tonal"
      density="compact"
      icon="mdi-alert"
      class="mt-3"
    >
      当前为明文存储，管理员可查看内容。
    </v-alert>

    <slot />
  </v-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StatusChip from './StatusChip.vue'
import { encryptionState } from '@/utils/format'
import type { EncryptionState } from '@/types'

const props = withDefaults(
  defineProps<{
    enabled: boolean
    state: EncryptionState
    done?: number
    total?: number
    eta?: number | null
    readonly?: boolean
    busy?: boolean
  }>(),
  { done: 0, total: 0, eta: null, readonly: true, busy: false },
)

const emit = defineEmits<{
  toggle: [enabled: boolean]
}>()

const isPlaintext = computed(() => !props.enabled || props.state === 'plaintext')
const inProgress = computed(
  () => props.state === 'decrypting' || props.state === 'encrypting' || props.state === 'paused',
)
const percent = computed(() => {
  if (!props.total) return props.enabled ? 100 : 0
  return Math.min(100, Math.round((props.done / props.total) * 100))
})

const stateHint = computed(() => {
  const meta = encryptionState(props.state)
  if (props.state === 'paused') return '任务已暂停，可重试'
  if (props.state === 'decrypting') return props.eta ? `预计 ${Math.ceil(props.eta / 60)} 分钟` : '正在解密'
  if (props.state === 'encrypting') return props.eta ? `预计 ${Math.ceil(props.eta / 60)} 分钟` : '正在加密'
  if (isPlaintext.value) return '明文存储'
  if (props.state === 'decrypted') return '已解密 · 明文存储'
  return '对话与记忆均加密存储'
})

function onToggle(value: boolean | null): void {
  if (props.readonly || props.busy) return
  emit('toggle', value === true)
}
</script>

<style scoped>
.encryption-switch {
  padding: 20px;
}

.encryption-switch__row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.encryption-switch__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 1rem;
  font-weight: 600;
}

.encryption-switch__desc {
  margin: 6px 0 0;
  font-size: 0.84rem;
  color: var(--console-text-muted);
  line-height: 1.6;
  max-width: 560px;
}

.encryption-switch__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.encryption-switch__hint {
  font-size: 0.8rem;
}

.encryption-switch__progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}

.encryption-switch__progress .v-progress-linear {
  flex: 1;
}

.encryption-switch__progress span {
  font-size: 0.78rem;
  white-space: nowrap;
}

.encryption-switch__readonly {
  margin: 14px 0 0;
  font-size: 0.78rem;
}
</style>
