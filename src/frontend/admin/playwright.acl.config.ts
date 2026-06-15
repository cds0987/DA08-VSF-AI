import { defineConfig } from '@playwright/test'

// Lightweight config for ACL smoke tests — starts only the admin dev server,
// not the chat app, so tests can run without the full stack.
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  reporter: 'line',
  use: {
    baseURL: 'http://127.0.0.1:3001',
    browserName: 'chromium',
    channel: 'chrome',
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:3001/login',
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      NUXT_HOST: '127.0.0.1',
      NUXT_PUBLIC_USER_SERVICE_URL: 'http://127.0.0.1:8000',
      NUXT_PUBLIC_DOCUMENT_SERVICE_URL: 'http://127.0.0.1:8002',
      NUXT_PUBLIC_QUERY_SERVICE_URL: 'http://127.0.0.1:8001',
      NUXT_PUBLIC_HR_SERVICE_PATH: '/api/hr',
      NUXT_PUBLIC_ADMIN_APP_URL: 'http://127.0.0.1:3001',
      NUXT_PUBLIC_CHAT_APP_URL: 'http://127.0.0.1:3000',
    },
  },
})
