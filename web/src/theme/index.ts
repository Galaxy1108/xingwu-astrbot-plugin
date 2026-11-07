import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { tokens } from './tokens'

const lightTheme = {
  dark: false,
  colors: {
    background: tokens.colors.background,
    surface: tokens.colors.surface,
    primary: tokens.colors.primary,
    'primary-darken-1': tokens.colors.primaryHover,
    secondary: '#2f86bd',
    'secondary-darken-1': '#236b99',
    info: tokens.colors.info,
    success: tokens.colors.success,
    warning: tokens.colors.warning,
    error: tokens.colors.error,
    'surface-variant': '#eef2f6',
    'on-surface-variant': tokens.colors.textMuted,
  },
}

const darkTheme = {
  dark: true,
  colors: {
    background: '#1a1a1a',
    surface: '#242424',
    primary: '#5ba4d4',
    'primary-darken-1': '#3a8ab8',
    secondary: '#4a95c4',
    'secondary-darken-1': '#3a8ab8',
    info: '#03c9d7',
    success: '#52c41a',
    warning: '#faad14',
    error: '#ff4d4f',
    'surface-variant': '#2d2e30',
    'on-surface-variant': '#e0e0e0',
    'on-surface': '#e8eaed',
    'on-background': '#e8eaed',
  },
}

export const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'light',
    themes: { light: lightTheme, dark: darkTheme },
  },
  defaults: {
    global: { ripple: true },
    VBtn: { rounded: 'lg', density: 'comfortable' },
    VCard: { rounded: 'lg', elevation: 0, border: true },
    VTextField: { variant: 'outlined', density: 'comfortable', color: 'primary', rounded: 'lg', hideDetails: 'auto' },
    VSelect: { variant: 'outlined', density: 'comfortable', color: 'primary', rounded: 'lg', hideDetails: 'auto' },
    VTextarea: { variant: 'outlined', density: 'comfortable', color: 'primary', rounded: 'lg', hideDetails: 'auto' },
    VAutocomplete: { variant: 'outlined', density: 'comfortable', color: 'primary', rounded: 'lg', hideDetails: 'auto' },
    VChip: { size: 'small', rounded: 'md' },
    VDialog: { maxWidth: 560 },
    VNavigationDrawer: { width: 245 },
    VTable: { density: 'comfortable' },
  },
  display: {
    mobileBreakpoint: 'md',
    thresholds: { xs: 0, sm: 600, md: 960, lg: 1280, xl: 1920, xxl: 2560 },
  },
  icons: { defaultSet: 'mdi' },
})
