import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E configuration for TaskFlow.
 *
 * Covers:
 * - TypeScript support
 * - Isolated browser project (Desktop Chromium)
 * - Explicit test discovery scoped strictly to tests/e2e/*.spec.ts
 * - Automatic failure diagnostics (trace, screenshot, video on failure)
 * - Deterministic timeouts and webServer coordination
 */
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60000,
  },
});
