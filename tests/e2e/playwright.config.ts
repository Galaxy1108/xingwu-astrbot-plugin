import { defineConfig, devices } from '@playwright/test'

/**
 * M1 浏览器验收。
 *
 * 直接打已在运行的 dev server（FakeAstrBot + SQLCipher + web/dist），
 * 不使用 vite dev server（5273 端口可能被占用）。
 *
 * 运行：
 *   cd tests/e2e && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
 *   npx playwright test
 *
 * 环境变量：
 *   E2E_BASE_URL       默认 http://127.0.0.1:6180
 *   E2E_ADMIN_EMAIL    默认 admin@example.com
 *   E2E_CHROMIUM       默认 /usr/bin/chromium
 */
export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 150_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'artifacts/playwright-report', open: 'never' }],
  ],
  outputDir: 'artifacts/test-results',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:6180',
    viewport: { width: 1440, height: 960 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
    launchOptions: {
      executablePath: process.env.E2E_CHROMIUM || '/usr/bin/chromium',
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
