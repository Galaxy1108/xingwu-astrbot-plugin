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
  margin-bottom: 24px;
}

.page-header__title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.page-header__title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: -0.2px;
}

.back-btn {
  margin-left: -8px;
}

.page-header__desc {
  margin: 5px 0 0;
  color: var(--console-text-muted);
  font-size: 13px;
  line-height: 1.55;
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.page-header__actions :deep(.v-btn) {
  min-height: 40px;
  font-size: 14px;
  padding-inline: 16px;
}

.page-header__actions :deep(.v-btn--icon) {
  min-width: 40px;
  padding-inline: 0;
}

.page-header__actions :deep(.v-btn .v-icon) {
  font-size: 18px;
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
