import type { MemoryKind } from '@/types'

const meta: Record<MemoryKind, { label: string; color: string; icon: string }> = {
  fact: { label: '事实', color: 'info', icon: 'mdi-information-outline' },
  preference: { label: '偏好', color: 'primary', icon: 'mdi-heart-outline' },
  event: { label: '事件', color: 'success', icon: 'mdi-calendar-star-outline' },
  note: { label: '笔记', color: 'warning', icon: 'mdi-note-text-outline' },
}

/** 记忆类型 → 中文标签 / chip 颜色 / 图标（与后端 kind_label 保持一致）。 */
export function useMemoryKindMeta() {
  function kindColor(kind: string): string {
    return meta[kind as MemoryKind]?.color ?? 'default'
  }

  function kindIcon(kind: string): string {
    return meta[kind as MemoryKind]?.icon ?? 'mdi-tag-outline'
  }

  function kindLabel(kind: string): string {
    return meta[kind as MemoryKind]?.label ?? kind
  }

  return { kindColor, kindIcon, kindLabel }
}
