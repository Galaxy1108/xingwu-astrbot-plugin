<template>
  <div
    ref="root"
    class="usage-chart"
    @mousemove="onMove"
    @mouseleave="hoverIndex = -1"
    @touchmove.passive="onTouch"
  >
    <svg
      v-if="points.length"
      class="usage-chart__svg"
      :viewBox="`0 0 ${chartWidth} ${height}`"
      role="img"
      :aria-label="`近 ${points.length} 天${valueLabel}`"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity="0.26" />
          <stop offset="100%" :stop-color="color" stop-opacity="0.01" />
        </linearGradient>
      </defs>

      <g class="usage-chart__grid">
        <g v-for="line in gridLines" :key="line.value">
          <line :x1="pad.left" :x2="chartWidth - pad.right" :y1="line.y" :y2="line.y" />
          <text :x="pad.left - 8" :y="line.y + 4" text-anchor="end">{{ line.label }}</text>
        </g>
      </g>

      <path v-if="areaPath" :d="areaPath" :fill="`url(#${gradientId})`" stroke="none" />
      <path v-if="linePath" :d="linePath" fill="none" :stroke="color" stroke-width="2" stroke-linejoin="round" />

      <line
        v-if="hoverIndex >= 0"
        class="usage-chart__cursor"
        :x1="x(hoverIndex)"
        :x2="x(hoverIndex)"
        :y1="pad.top"
        :y2="height - pad.bottom"
      />
      <circle
        v-if="hoverIndex >= 0"
        :cx="x(hoverIndex)"
        :cy="y(value(hoverIndex))"
        r="4"
        :fill="color"
        stroke="var(--console-surface)"
        stroke-width="2"
      />
      <circle
        v-else-if="points.length"
        :cx="x(points.length - 1)"
        :cy="y(value(points.length - 1))"
        r="3.5"
        :fill="color"
      />

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

    <div v-if="allZero" class="usage-chart__empty text-muted">
      暂无{{ valueLabel }}记录
    </div>

    <div
      v-if="hoverIndex >= 0 && points[hoverIndex]"
      class="usage-chart__tooltip"
      :style="tooltipStyle"
    >
      <div class="tooltip-date">{{ formatFullDate(points[hoverIndex].date) }}</div>
      <div class="tooltip-row">
        <span class="tooltip-dot" :style="{ background: color }" />
        <span class="tooltip-label">{{ valueLabel }}</span>
        <strong>{{ formatNumber(value(hoverIndex)) }} {{ unit }}</strong>
      </div>
      <div v-if="points[hoverIndex].tokens" class="tooltip-row tooltip-row--sub">
        <span class="tooltip-label">Tokens</span>
        <span>{{ formatNumber(points[hoverIndex].tokens) }}</span>
      </div>
      <div v-if="points[hoverIndex].requests" class="tooltip-row tooltip-row--sub">
        <span class="tooltip-label">请求</span>
        <span>{{ formatNumber(points[hoverIndex].requests) }} 次</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { UsageDailyPoint } from '@/types'
import { formatNumber } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    points: UsageDailyPoint[]
    height?: number
    color?: string
    valueLabel?: string
    unit?: string
  }>(),
  { height: 210, color: '#3c96ca', valueLabel: '消耗', unit: '点' },
)

const chartWidth = ref(720)
const pad = { top: 18, right: 18, bottom: 28, left: 52 }
const gradientId = `usage-grad-${Math.random().toString(36).slice(2, 8)}`
const root = ref<HTMLElement | null>(null)
const hoverIndex = ref(-1)

function value(index: number): number {
  return Number(props.points[index]?.points ?? 0)
}

const maxValue = computed(() => {
  const max = Math.max(0, ...props.points.map((point) => Number(point.points || 0)))
  return max > 0 ? max * 1.15 : 1
})

const allZero = computed(() => props.points.every((point) => !Number(point.points || 0)))

function x(index: number): number {
  const count = Math.max(1, props.points.length - 1)
  return pad.left + (index / count) * (chartWidth.value - pad.left - pad.right)
}

function y(v: number): number {
  const usable = props.height - pad.top - pad.bottom
  return pad.top + (1 - Math.min(1, v / maxValue.value)) * usable
}

const linePath = computed(() =>
  props.points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(value(index)).toFixed(1)}`)
    .join(' '),
)

const areaPath = computed(() => {
  if (!props.points.length) return ''
  const bottom = props.height - pad.bottom
  return `${linePath.value} L${x(props.points.length - 1).toFixed(1)},${bottom} L${x(0).toFixed(1)},${bottom} Z`
})

const gridLines = computed(() =>
  Array.from({ length: 4 }, (_, index) => {
    const ratio = index / 3
    const v = maxValue.value * (1 - ratio)
    return {
      value: v,
      y: pad.top + (props.height - pad.top - pad.bottom) * ratio,
      label: formatCompact(v),
    }
  }),
)

const xTicks = computed(() => {
  const points = props.points
  if (!points.length) return []
  const last = points.length - 1
  const indexes =
    points.length <= 3
      ? points.map((_, index) => index)
      : chartWidth.value < 460
        ? [0, Math.floor(last / 2), last]
        : [0, Math.floor(last / 3), Math.floor((last * 2) / 3), last]
  return [...new Set(indexes)].map((index, order, list) => ({
    index,
    label: points[index].date.slice(5),
    anchor: order === 0 ? 'start' : order === list.length - 1 ? 'end' : 'middle',
  }))
})

const tooltipStyle = computed(() => {
  const index = hoverIndex.value
  if (index < 0 || !props.points.length) return {}
  const pointX = x(index)
  const pointY = y(value(index))
  const half = 110
  const left = Math.min(
    Math.max(half, pointX),
    Math.max(half, chartWidth.value - half),
  )
  // 点太靠上时翻到点下方，避免 tooltip 溢出容器顶部
  const showBelow = pointY < 90
  return {
    left: `${left}px`,
    top: `${showBelow ? pointY + 14 : pointY - 10}px`,
    transform: showBelow ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
  }
})

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  const element = root.value
  if (!element) return
  chartWidth.value = Math.max(320, Math.round(element.clientWidth || 720))
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? element.clientWidth
      if (width > 0) chartWidth.value = Math.max(320, Math.round(width))
    })
    resizeObserver.observe(element)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})

function onMove(event: MouseEvent): void {
  if (!props.points.length || !root.value) return
  const rect = root.value.getBoundingClientRect()
  const relative = ((event.clientX - rect.left) / rect.width) * chartWidth.value
  const count = Math.max(1, props.points.length - 1)
  const index = Math.round(((relative - pad.left) / (chartWidth.value - pad.left - pad.right)) * count)
  hoverIndex.value = Math.max(0, Math.min(props.points.length - 1, index))
}

function onTouch(event: TouchEvent): void {
  const touch = event.touches[0]
  if (touch) onMove({ clientX: touch.clientX } as MouseEvent)
}

function formatCompact(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`
  if (Number.isInteger(value)) return String(value)
  if (abs >= 10) return String(Math.round(value))
  return value.toFixed(1)
}

function formatFullDate(date: string): string {
  const [year, month, day] = date.split('-')
  return `${year}-${month}-${day}`
}
</script>

<style scoped>
.usage-chart {
  position: relative;
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
  font-size: 9px;
}

.usage-chart__cursor {
  stroke: var(--console-text-muted);
  stroke-width: 1;
  stroke-dasharray: 4 3;
  opacity: 0.6;
}

.usage-chart__empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 13px;
  pointer-events: none;
}

.usage-chart__tooltip {
  position: absolute;
  z-index: 2;
  min-width: 178px;
  max-width: 230px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--console-surface);
  border: 1px solid var(--console-border);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  font-size: 12px;
  pointer-events: none;
}

.tooltip-date {
  margin-bottom: 6px;
  font-weight: 600;
  color: var(--console-text);
}

.tooltip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--console-text);
}

.tooltip-row--sub {
  margin-top: 3px;
  color: var(--console-text-muted);
  font-size: 11.5px;
}

.tooltip-row strong {
  margin-left: auto;
  font-weight: 650;
}

.tooltip-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.tooltip-label {
  color: var(--console-text-muted);
}
</style>
