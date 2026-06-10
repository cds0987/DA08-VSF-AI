import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  reporter: 'line',
  use: {
    baseURL: 'http://127.0.0.1:3001',
    browserName: 'chromium',
    channel: 'chrome',
    headless: true,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:3001/login',
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        NUXT_PUBLIC_USER_SERVICE_URL: 'http://127.0.0.1:8000',
        NUXT_PUBLIC_DOCUMENT_SERVICE_URL: 'http://127.0.0.1:8002',
        NUXT_PUBLIC_QUERY_SERVICE_URL: 'http://127.0.0.1:8001',
        NUXT_PUBLIC_ADMIN_APP_URL: 'http://127.0.0.1:3001',
        NUXT_PUBLIC_CHAT_APP_URL: 'http://127.0.0.1:3000',
      },
    },
    {
      command: 'npm --prefix ../chat run dev',
      url: 'http://127.0.0.1:3000/login',
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        NUXT_PUBLIC_USER_SERVICE_URL: 'http://127.0.0.1:8000',
        NUXT_PUBLIC_DOCUMENT_SERVICE_URL: 'http://127.0.0.1:8002',
        NUXT_PUBLIC_QUERY_SERVICE_URL: 'http://127.0.0.1:8001',
        NUXT_PUBLIC_ADMIN_APP_URL: 'http://127.0.0.1:3001',
        NUXT_PUBLIC_CHAT_APP_URL: 'http://127.0.0.1:3000',
      },
    },
  ],
})
