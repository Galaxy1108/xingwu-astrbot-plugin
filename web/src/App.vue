<template>
  <v-app>
    <BackendHealthBanner />
    <router-view />
    <v-snackbar
      v-model="ui.snackbar.show"
      :color="ui.snackbar.color"
      :timeout="ui.snackbar.timeout"
      location="top right"
      rounded="lg"
      elevation="4"
    >
      <span class="snackbar-text">{{ ui.snackbar.text }}</span>
      <template #actions>
        <v-btn variant="text" density="comfortable" @click="ui.close()">关闭</v-btn>
      </template>
    </v-snackbar>
  </v-app>
</template>

<script setup lang="ts">
import BackendHealthBanner from '@/components/BackendHealthBanner.vue'
import { useUiStore } from '@/stores/ui'
import { useThemeMode } from '@/composables/useThemeMode'

const ui = useUiStore()
useThemeMode()
</script>

<style scoped>
.snackbar-text {
  line-height: 1.5;
}
</style>
