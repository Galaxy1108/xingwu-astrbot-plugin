/**
 * 设计 tokens：从 demo 主题收敛而来，页面与组件只引用这里，不写散落颜色值。
 */
export const tokens = {
  colors: {
    primary: '#3c96ca',
    primaryHover: '#2f7ba6',
    primarySoft: '#eaf4fa',
    background: '#f5f7fa',
    surface: '#ffffff',
    text: '#1b1c1d',
    textMuted: '#5f6368',
    border: '#dfe3e8',
    success: '#2e7d32',
    warning: '#ed6c02',
    error: '#c62828',
    info: '#0277bd',
  },
  layout: {
    topbar: 56,
    sidebar: 232,
    contentMax: 1280,
    gutter: 24,
    gutterCompact: 16,
  },
  radius: {
    sm: 4,
    md: 8,
    lg: 12,
    pill: 999,
  },
  shadow: {
    card: '0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.1)',
    popover: '0 8px 24px rgba(16, 24, 40, 0.16)',
  },
  breakpoints: {
    sm: 600,
    md: 960,
  },
} as const

export type DesignTokens = typeof tokens
