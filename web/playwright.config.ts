import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: ['**/*.spec.ts'],
  testIgnore: ['**/*.test.ts', '**/*.test.tsx'],
  use: {
    baseURL: 'http://127.0.0.1:3000',
  },
  webServer: {
    command: 'npm run dev',
    env: {
      NEXT_PUBLIC_ENABLE_DEMO_AUTH: 'true',
      NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:9999',
    },
    port: 3000,
    reuseExistingServer: true,
  },
})
