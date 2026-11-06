<template>
  <div class="qr-panel">
    <div class="qr-panel__header">
      <StatusChip :status="status" kind="qr" />
      <span v-if="refreshCount > 0" class="text-muted qr-refresh">
        已自动刷新 {{ refreshCount }}/3 次
      </span>
    </div>

    <div class="qr-panel__stage">
      <template v-if="status === 'created'">
        <v-icon size="64" color="success">mdi-check-decagram-outline</v-icon>
        <p class="qr-stage-text">已确认，正在完成接入…</p>
        <v-progress-circular indeterminate color="success" size="28" />
      </template>

      <template v-else-if="status === 'expired'">
        <v-icon size="64" color="error">mdi-qrcode-remove</v-icon>
        <p class="qr-stage-text">二维码已过期（自动刷新已达上限），请重新生成。</p>
        <v-btn color="primary" :loading="busy" @click="emit('regenerate')">重新生成二维码</v-btn>
      </template>

      <template v-else>
        <div class="qr-frame" :class="{ 'qr-frame--scanned': status === 'scanned' }">
          <v-img
            v-if="image"
            :src="image"
            width="220"
            height="220"
            alt="扫码登录二维码"
            class="qr-image"
          />
          <div v-else class="qr-placeholder">
            <v-progress-circular indeterminate color="primary" />
          </div>
          <div v-if="status === 'scanned'" class="qr-scanned-overlay">
            <v-icon size="56" color="success">mdi-check-circle</v-icon>
            <span>已扫码</span>
          </div>
        </div>

        <p class="qr-stage-text">
          {{ status === 'scanned' ? '请在手机上确认登录' : '请使用对应 App 扫描二维码' }}
        </p>
        <p v-if="expiresAt" class="qr-countdown">
          二维码有效期
          <strong>{{ formatSeconds(remaining) }}</strong>
        </p>
        <v-btn variant="tonal" size="small" color="primary" :loading="busy" @click="emit('regenerate')">
          重新生成二维码
        </v-btn>
      </template>
    </div>

    <v-alert v-if="message" type="info" variant="tonal" density="compact" class="mt-3">
      {{ message }}
    </v-alert>
    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mt-3">
      {{ error }}
    </v-alert>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import StatusChip from './StatusChip.vue'
import { formatSeconds } from '@/utils/format'
import type { QrStatus } from '@/types'

const props = withDefaults(
  defineProps<{
    status: QrStatus
    image?: string | null
    expiresAt?: number | null
    refreshCount?: number
    message?: string | null
    error?: string | null
    busy?: boolean
  }>(),
  {
    image: null,
    expiresAt: null,
    refreshCount: 0,
    message: null,
    error: null,
    busy: false,
  },
)

const emit = defineEmits<{
  regenerate: []
}>()

const now = ref(Math.floor(Date.now() / 1000))
let timer: ReturnType<typeof setInterval> | null = null

const remaining = computed(() => {
  if (!props.expiresAt) return 0
  return Math.max(0, props.expiresAt - now.value)
})

function startTimer(): void {
  stopTimer()
  timer = setInterval(() => {
    now.value = Math.floor(Date.now() / 1000)
  }, 1000)
}

function stopTimer(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function onVisibilityChange(): void {
  if (typeof document === 'undefined') return
  if (document.visibilityState === 'hidden') {
    stopTimer()
  } else {
    now.value = Math.floor(Date.now() / 1000)
    startTimer()
  }
}

onMounted(() => {
  startTimer()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  stopTimer()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.qr-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.qr-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.qr-refresh {
  font-size: 0.78rem;
}

.qr-panel__stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 20px 12px;
  background: #fafbfc;
  border: 1px dashed var(--console-border);
  border-radius: var(--console-radius);
  text-align: center;
}

.qr-frame {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 240px;
  height: 240px;
  padding: 10px;
  background: #fff;
  border: 1px solid var(--console-border);
  border-radius: var(--console-radius);
}

.qr-frame--scanned {
  opacity: 0.6;
}

.qr-image {
  border-radius: 4px;
}

.qr-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.qr-scanned-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: #2e7d32;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.72);
  border-radius: var(--console-radius);
}

.qr-stage-text {
  margin: 0;
  font-size: 0.85rem;
  color: var(--console-text-muted);
  line-height: 1.5;
}

.qr-countdown {
  margin: 0;
  font-size: 0.82rem;
  color: var(--console-text-muted);
}

.qr-countdown strong {
  color: var(--console-primary);
  font-variant-numeric: tabular-nums;
}
</style>
