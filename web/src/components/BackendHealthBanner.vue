<template>
  <transition name="health-fade">
    <div v-if="status !== 'ok'" class="health-banner" :class="`health-banner--${status}`">
      <v-icon size="18">{{ status === 'offline' ? 'mdi-lan-disconnect' : 'mdi-alert-outline' }}</v-icon>
      <div class="health-copy">
        <strong>{{ title }}</strong>
        <span>{{ detail }}</span>
      </div>
      <v-btn size="small" variant="text" :loading="checking" @click="check">重试</v-btn>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { HealthInfo } from '@/types'

const status = ref<'ok' | 'offline' | 'degraded'>('ok')
const checking = ref(false)
const title = ref('')
const detail = ref('')
let timer: number | null = null

async function check(): Promise<void> {
  checking.value = true
  try {
    const health = await api.get<HealthInfo>('/health')
    if (health.status === 'ok' && health.db === 'ok') {
      status.value = 'ok'
    } else {
      status.value = 'degraded'
      title.value = '后端服务降级'
      detail.value = health.db !== 'ok' ? '数据库不可用，部分功能可能失败。' : '部分依赖不可用。'
    }
  } catch {
    status.value = 'offline'
    title.value = '后端连接失败'
    detail.value = '无法连接控制台后端，请确认 AstrBot / 服务进程已启动；恢复后可点重试。'
  } finally {
    checking.value = false
  }
}

onMounted(() => {
  void check()
  timer = window.setInterval(check, 30_000)
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.health-banner {
  position: fixed;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3000;
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: min(720px, calc(100vw - 32px));
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--console-danger-border);
  background: var(--console-surface);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
}
.health-banner--degraded {
  border-color: rgba(230, 160, 40, 0.5);
}
.health-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12.5px;
  min-width: 0;
}
.health-copy strong {
  font-size: 13px;
}
.health-copy span {
  color: var(--console-text-muted);
}
.health-fade-enter-active,
.health-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.health-fade-enter-from,
.health-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}
</style>
