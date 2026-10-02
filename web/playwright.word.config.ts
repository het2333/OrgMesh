import { defineConfig, devices } from "@playwright/test";

// Live-stack acceptance. Use an authenticated test user's existing storage state.
export default defineConfig({
  testDir: "./tests/e2e/orgmesh-documents",
  testMatch: "manual-flow.spec.ts",
  timeout: 120000,
  expect: { timeout: 20000 },
  workers: 1,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    storageState: process.env.ORGMESH_WORD_STORAGE_STATE ?? "admin_auth.json",
    trace: "retain-on-failure",
  },
});
