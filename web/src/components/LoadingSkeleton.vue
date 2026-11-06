<template>
  <div class="loading-skeleton" aria-busy="true" aria-label="加载中">
    <template v-if="variant === 'detail'">
      <v-skeleton-loader type="article" />
    </template>
    <template v-else-if="variant === 'table'">
      <v-skeleton-loader type="table-heading" />
      <v-skeleton-loader v-for="index in rows" :key="index" type="table-row" />
    </template>
    <template v-else-if="variant === 'card'">
      <div class="page-grid page-grid--cards">
        <v-skeleton-loader v-for="index in rows" :key="index" type="article" />
      </div>
    </template>
    <template v-else>
      <v-skeleton-loader v-for="index in rows" :key="index" type="list-item-two-line" />
    </template>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'list' | 'detail' | 'table' | 'card'
    rows?: number
  }>(),
  { variant: 'list', rows: 4 },
)
</script>

<style scoped>
.loading-skeleton {
  width: 100%;
}

.loading-skeleton :deep(.v-skeleton-loader) {
  background: transparent;
}
</style>
