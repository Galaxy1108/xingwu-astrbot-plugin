<template>
  <v-chip
    :color="meta.color"
    :prepend-icon="meta.icon"
    variant="tonal"
    size="small"
    class="status-chip"
  >
    {{ meta.label }}
  </v-chip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { botStatus, encryptionState, qrStatusMeta, userStatus } from '@/utils/format'
import type { QrStatus } from '@/types'

const props = withDefaults(
  defineProps<{
    status: string
    kind?: 'bot' | 'qr' | 'user' | 'encryption'
  }>(),
  { kind: 'bot' },
)

const meta = computed(() => {
  switch (props.kind) {
    case 'qr':
      return qrStatusMeta[props.status as QrStatus] ?? { label: props.status, color: 'default', icon: 'mdi-help-circle' }
    case 'user':
      return userStatus(props.status)
    case 'encryption':
      return encryptionState(props.status)
    default:
      return botStatus(props.status)
  }
})
</script>

<style scoped>
.status-chip {
  font-weight: 500;
}
</style>
