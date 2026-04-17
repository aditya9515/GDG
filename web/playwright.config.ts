import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: ['**/*.spec.ts'],
  testIgnore: ['**/*.test.ts', '**/*.test.tsx'],
  use: {
    baseURL: 'http://127.0.0.1:3100',
  },
  webServer: {
    command: 'npm run build && npm run start -- --port 3100',
    env: {
      NEXT_PUBLIC_ENABLE_DEMO_AUTH: 'true',
      NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:9999',
    },
    port: 3100,
    reuseExistingServer: false,
  },
})
