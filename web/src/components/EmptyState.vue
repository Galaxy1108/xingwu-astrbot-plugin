<template>
  <div class="empty-state">
    <v-icon class="empty-state__icon" size="48">{{ icon }}</v-icon>
    <h3 class="empty-state__title">{{ title }}</h3>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
    <div v-if="$slots.actions || actions?.length" class="empty-state__actions">
      <slot name="actions">
        <v-btn
          v-for="action in actions"
          :key="action.label"
          :to="action.to"
          :color="action.color || 'primary'"
          :variant="action.variant || 'flat'"
          @click="action.onClick?.()"
        >
          {{ action.label }}
        </v-btn>
      </slot>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    icon?: string
    actions?: Array<{
      label: string
      to?: string
      color?: string
      variant?: 'flat' | 'text' | 'outlined' | 'tonal'
      onClick?: () => void
    }>
  }>(),
  {
    description: '',
    icon: 'mdi-inbox-outline',
    actions: () => [],
  },
)
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
  color: var(--console-text-muted);
}

.empty-state__icon {
  color: var(--console-primary);
  opacity: 0.55;
  margin-bottom: 8px;
}

.empty-state__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--console-text);
}

.empty-state__desc {
  margin: 6px 0 0;
  max-width: 460px;
  font-size: 0.85rem;
  line-height: 1.6;
}

.empty-state__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 16px;
}
</style>
