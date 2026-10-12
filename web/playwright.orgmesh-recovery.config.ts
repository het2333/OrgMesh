import { defineConfig } from "@playwright/test";
import existing from "./playwright.config";

// Existing auth state only. The normal global setup can create users and PATs.
// Keep this local configuration separate from the default suite.
export default defineConfig({
  ...existing,
  globalSetup: undefined,
  workers: 1,
  retries: 0,
  use: {
    ...existing.use,
    storageState:
      process.env.ORGMESH_TEST_AUTH_STATE || "orgmesh-existing-admin-auth.json",
  },
  projects: [
    {
      name: "recovery",
      use: {
        storageState:
          process.env.ORGMESH_TEST_AUTH_STATE ||
          "orgmesh-existing-admin-auth.json",
      },
    },
  ],
});
