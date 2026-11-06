<template>
  <v-card class="stat-card" :class="{ 'stat-card--loading': loading }">
    <div class="stat-card__body">
      <v-avatar :color="color" variant="tonal" size="42" rounded="lg">
        <v-icon size="22">{{ icon }}</v-icon>
      </v-avatar>
      <div class="stat-card__content">
        <div class="stat-card__label">{{ label }}</div>
        <div class="stat-card__value">
          <v-skeleton-loader v-if="loading" type="text" width="72" />
          <template v-else>{{ value }}</template>
        </div>
        <div v-if="hint" class="stat-card__hint">{{ hint }}</div>
      </div>
    </div>
    <slot />
  </v-card>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string
    value: string | number
    hint?: string
    icon?: string
    color?: string
    loading?: boolean
  }>(),
  {
    hint: '',
    icon: 'mdi-chart-box-outline',
    color: 'primary',
    loading: false,
  },
)
</script>

<style scoped>
.stat-card {
  padding: 16px;
}

.stat-card__body {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.stat-card__content {
  min-width: 0;
  flex: 1;
}

.stat-card__label {
  font-size: 0.8rem;
  color: var(--console-text-muted);
  line-height: 1.4;
}

.stat-card__value {
  font-size: 1.55rem;
  font-weight: 650;
  line-height: 1.3;
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.stat-card__hint {
  margin-top: 2px;
  font-size: 0.75rem;
  color: var(--console-text-muted);
  line-height: 1.4;
}
</style>
