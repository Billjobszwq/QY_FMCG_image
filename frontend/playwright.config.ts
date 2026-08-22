import { defineConfig, devices } from "@playwright/test";

/**
 * R2-09：Research Workbench 浏览器验收（report-only 场景固定）。
 * 运行前置：`npm i -D @playwright/test && npx playwright install chromium`，
 * 并启动后端（:8400）+ 前端（:4173）。未安装时本 spec 不执行。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.TAAS_E2E_BASE_URL ?? "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-1024", use: { ...devices["Desktop Chrome"],
      viewport: { width: 1024, height: 768 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"],
      viewport: { width: 1280, height: 800 } } },
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"],
      viewport: { width: 1440, height: 900 } } },
  ],
});
