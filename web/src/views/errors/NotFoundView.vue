<template>
  <div class="not-found">
    <v-icon size="64" color="primary">mdi-map-search-outline</v-icon>
    <h1 class="not-found-title">404 · 页面不存在</h1>
    <p class="not-found-desc">链接可能已失效，或该资源不属于当前账号。</p>
    <v-btn color="primary" to="/" variant="tonal">返回总览</v-btn>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
.not-found {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  text-align: center;
  background: var(--console-bg);
}

.not-found-title {
  margin: 8px 0 0;
  font-size: 1.4rem;
  font-weight: 650;
}

.not-found-desc {
  margin: 0 0 12px;
  color: var(--console-text-muted);
  font-size: 0.9rem;
}
</style>
