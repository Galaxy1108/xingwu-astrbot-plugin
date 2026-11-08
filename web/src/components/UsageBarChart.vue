<template>
  <div ref="root" class="usage-bar" :style="{ height: `${height}px` }" @mouseleave="hover = -1">
    <div class="bar-grid">
      <span v-for="line in 4" :key="line" />
    </div>
    <div class="bar-columns">
      <button
        v-for="(point, index) in points"
        :key="point.date"
        type="button"
        class="bar-column"
        :class="{ 'is-hover': hover === index }"
        :aria-label="`${point.date}：${formatNumber(point.points)} 点`"
        @mouseenter="hover = index"
        @focus="hover = index"
      >
        <span class="bar-fill" :style="{ height: `${barHeight(point.points)}%` }" />
      </button>
    </div>
    <div class="bar-labels">
      <span>{{ points[0]?.date?.slice(5) }}</span>
      <span>{{ points[points.length - 1]?.date?.slice(5) }}</span>
    </div>
    <div v-if="hover >= 0 && points[hover]" class="bar-tooltip" :style="tooltipStyle">
      <div class="bar-tooltip-date">{{ points[hover].date }}</div>
      <div class="bar-tooltip-row"><span>消耗</span><strong>{{ formatNumber(points[hover].points) }} 点</strong></div>
      <div class="bar-tooltip-row sub"><span>请求</span><span>{{ formatNumber(points[hover].requests) }} 次</span></div>
      <div class="bar-tooltip-row sub"><span>Tokens</span><span>{{ formatNumber(points[hover].tokens) }}</span></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { UsageDailyPoint } from '@/types'
import { formatNumber } from '@/utils/format'

const props = withDefaults(
  defineProps<{ points: UsageDailyPoint[]; height?: number }>(),
  { height: 260 },
)
const root = ref<HTMLElement | null>(null)
const hover = ref(-1)
const maxValue = computed(() =>
  Math.max(1, ...props.points.map((point) => Number(point.points || 0))),
)

function barHeight(value: number): number {
  return Math.max(value > 0 ? 3 : 0, (Number(value || 0) / maxValue.value) * 88)
}

const tooltipStyle = computed(() => {
  const index = hover.value
  if (index < 0 || !props.points.length) return {}
  const left = ((index + 0.5) / props.points.length) * 100
  return {
    left: `${Math.min(90, Math.max(10, left))}%`,
    transform: left > 70 ? 'translateX(-100%)' : 'translateX(0)',
  }
})
</script>

<style scoped>
.usage-bar {
  position: relative;
  padding: 6px 4px 22px;
}
.bar-grid {
  position: absolute;
  inset: 6px 4px 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}
.bar-grid span {
  border-top: 1px dashed var(--console-border);
}
.bar-columns {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 100%;
}
.bar-column {
  flex: 1;
  min-width: 2px;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: flex-end;
}
.bar-fill {
  width: 100%;
  min-height: 0;
  border-radius: 3px 3px 0 0;
  background: linear-gradient(180deg, #5ba4d4, #3c96ca);
  transition: height 280ms cubic-bezier(0.22, 1, 0.36, 1), opacity 150ms ease;
  opacity: 0.82;
}
.bar-column.is-hover .bar-fill {
  opacity: 1;
  box-shadow: 0 0 0 1px rgba(60, 150, 202, 0.4);
}
.bar-labels {
  position: absolute;
  left: 4px;
  right: 4px;
  bottom: 0;
  display: flex;
  justify-content: space-between;
  color: var(--console-text-muted);
  font-size: 11.5px;
}
.bar-tooltip {
  position: absolute;
  top: 0;
  z-index: 2;
  min-width: 150px;
  padding: 9px 11px;
  border-radius: 9px;
  border: 1px solid var(--console-border);
  background: var(--console-surface);
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.14);
  font-size: 12px;
  pointer-events: none;
}
.bar-tooltip-date {
  margin-bottom: 5px;
  font-weight: 600;
}
.bar-tooltip-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.bar-tooltip-row span {
  color: var(--console-text-muted);
}
.bar-tooltip-row.sub {
  margin-top: 3px;
  font-size: 11.5px;
}
</style>
