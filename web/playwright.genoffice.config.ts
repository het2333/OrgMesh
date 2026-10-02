import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests/e2e/orgmesh-documents', testMatch: 'browser-port.spec.ts',
  timeout: 60000, expect: { timeout: 15000 }, workers: 1,
  use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:5178', trace: 'retain-on-failure', launchOptions: process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {} },
  webServer: { command: 'cd ../vendor/genoffice/apps/docs && ../../node_modules/.bin/vite --config vite.browser-test.config.ts', url: 'http://127.0.0.1:5178/office/docs/', reuseExistingServer: false },
})
