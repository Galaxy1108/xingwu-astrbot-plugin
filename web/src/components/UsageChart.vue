<template>
  <div class="usage-chart">
    <svg
      v-if="points.length"
      class="usage-chart__svg"
      :viewBox="`0 0 ${WIDTH} ${height}`"
      role="img"
      :aria-label="`近 ${points.length} 天余额走势`"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity="0.28" />
          <stop offset="100%" :stop-color="color" stop-opacity="0.02" />
        </linearGradient>
      </defs>

      <g class="usage-chart__grid">
        <g v-for="line in gridLines" :key="line.value">
          <line :x1="pad.left" :x2="WIDTH - pad.right" :y1="line.y" :y2="line.y" />
          <text :x="pad.left - 8" :y="line.y + 4" text-anchor="end">{{ line.label }}</text>
        </g>
      </g>

      <path :d="areaPath" :fill="`url(#${gradientId})`" stroke="none" />
      <path :d="linePath" fill="none" :stroke="color" stroke-width="2" stroke-linejoin="round" />

      <g v-if="points.length <= 31">
        <circle
          v-for="(point, index) in points"
          :key="point.date"
          :cx="x(index)"
          :cy="y(point.balance)"
          r="2.5"
          :fill="color"
          class="usage-chart__dot"
        >
          <title>{{ point.date }} · 余额 {{ point.balance }}（{{ sign(point.delta) }}）</title>
        </circle>
      </g>

      <g class="usage-chart__x">
        <text
          v-for="tick in xTicks"
          :key="tick.index"
          :x="x(tick.index)"
          :y="height - 6"
          :text-anchor="tick.anchor"
        >
          {{ tick.label }}
        </text>
      </g>
    </svg>
    <div v-else class="usage-chart__empty text-muted">暂无可用数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { UsagePoint } from '@/types'

const props = withDefaults(
  defineProps<{
    points: UsagePoint[]
    height?: number
    color?: string
  }>(),
  { height: 190, color: '#3c96ca' },
)

const WIDTH = 640
const pad = { top: 16, right: 16, bottom: 28, left: 48 }
const gradientId = `usage-grad-${Math.random().toString(36).slice(2, 8)}`
const PAD = pad

const values = computed(() => props.points.map((point) => point.balance))
const bounds = computed(() => {
  if (!values.value.length) return { min: 0, max: 1 }
  let min = Math.min(...values.value)
  let max = Math.max(...values.value)
  if (min === max) {
    min -= 1
    max += 1
  }
  const span = max - min
  return { min: min - span * 0.08, max: max + span * 0.08 }
})

function x(index: number): number {
  const count = Math.max(1, props.points.length - 1)
  return pad.left + (index / count) * (WIDTH - pad.left - pad.right)
}

function y(value: number): number {
  const { min, max } = bounds.value
  const usable = props.height - pad.top - pad.bottom
  return pad.top + ((max - value) / (max - min)) * usable
}

const linePath = computed(() =>
  props.points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(point.balance).toFixed(1)}`)
    .join(' '),
)

const areaPath = computed(() => {
  if (!props.points.length) return ''
  const bottom = props.height - pad.bottom
  return `${linePath.value} L${x(props.points.length - 1).toFixed(1)},${bottom} L${x(0).toFixed(1)},${bottom} Z`
})

const gridLines = computed(() => {
  const { min, max } = bounds.value
  return Array.from({ length: 4 }, (_, index) => {
    const value = min + ((max - min) * index) / 3
    return {
      value,
      y: pad.top + ((props.height - pad.top - pad.bottom) * (3 - index)) / 3,
      label: formatCompact(value),
    }
  })
})

const xTicks = computed(() => {
  const points = props.points
  if (!points.length) return []
  const indexes = points.length === 1 ? [0] : [0, Math.floor((points.length - 1) / 2), points.length - 1]
  return [...new Set(indexes)].map((index, order, list) => ({
    index,
    label: points[index].date.slice(5),
    anchor: order === 0 ? 'start' : order === list.length - 1 ? 'end' : 'middle',
  }))
})

function formatCompact(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`
  return String(Math.round(value))
}

function sign(value: number): string {
  return value > 0 ? `+${value}` : String(value)
}
</script>

<style scoped>
.usage-chart {
  width: 100%;
}

.usage-chart__svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.usage-chart__grid line {
  stroke: var(--console-border);
  stroke-dasharray: 3 4;
  stroke-width: 1;
}

.usage-chart__grid text,
.usage-chart__x text {
  fill: var(--console-text-muted);
  font-size: 11px;
}

.usage-chart__dot {
  cursor: default;
}

.usage-chart__empty {
  padding: 32px 0;
  text-align: center;
  font-size: 0.85rem;
}
</style>
