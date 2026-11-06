<template>
  <div class="page-header">
    <div class="page-header__main">
      <div class="page-header__title-row">
        <v-btn
          v-if="backTo"
          :to="backTo"
          icon
          variant="text"
          size="small"
          aria-label="返回"
          class="back-btn"
        >
          <v-icon>mdi-arrow-left</v-icon>
        </v-btn>
        <h1 class="page-header__title">{{ title }}</h1>
        <slot name="badge" />
      </div>
      <p v-if="description" class="page-header__desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    backTo?: string
  }>(),
  { description: '', backTo: '' },
)
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.page-header__title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.page-header__title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 650;
  line-height: 1.35;
}

.back-btn {
  margin-left: -8px;
}

.page-header__desc {
  margin: 4px 0 0;
  color: var(--console-text-muted);
  font-size: 0.875rem;
  line-height: 1.5;
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 599px) {
  .page-header__actions {
    width: 100%;
  }

  .page-header__actions :deep(.v-btn) {
    flex: 1 1 auto;
  }
}
</style>
