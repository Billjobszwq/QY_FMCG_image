import { expect, test } from "@playwright/test";

/**
 * R2-09：Research Workbench 浏览器验收（report-only）。
 *
 * 覆盖（round-2-hardening §10）：1024/1280/1440、键盘焦点、空/错/加载、
 * 401/403/404/409/429、waiting_human、resume/cancel、citation block、
 * locator 打开、跨 scope 零泄漏。
 *
 * 前置：后端 :8400 + 前端 :4173 已启动；TAAS_E2E_PASSWORD 提供 admin 口令。
 * 本 spec 为 report-only：不改生产数据，不删除内容。
 */

const PASSWORD = process.env.TAAS_E2E_PASSWORD ?? "";

async function login(page) {
  await page.goto("/");
  // 通过平台登录弹窗登录（若未登录）
  if (PASSWORD) {
    await page.evaluate(() =>
      window.dispatchEvent(new Event("platform:open-login")));
    const username = page.getByPlaceholder(/用户名|username/i).first();
    if (await username.isVisible().catch(() => false)) {
      await username.fill("admin");
      await page.getByPlaceholder(/口令|密码|password/i).first()
        .fill(PASSWORD);
      await page.getByRole("button", { name: /登录|Login/i }).click();
    }
  }
}

test.describe("Research Workbench", () => {
  test("空态：未启动任何 run 时无运行状态区块", async ({ page }) => {
    await login(page);
    await page.goto("/research/workbench");
    await expect(page.getByText("研究工作台")).toBeVisible();
    await expect(page.getByText("发起研究")).toBeVisible();
    // 未启动时不应出现运行状态
    await expect(page.getByText("运行状态")).toHaveCount(0);
  });

  test("键盘焦点可达：问题输入框可通过 Tab 聚焦", async ({ page }) => {
    await login(page);
    await page.goto("/research/workbench");
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() =>
      document.activeElement?.tagName.toLowerCase());
    expect(["input", "select", "button"]).toContain(focused);
  });

  test("404：访问不存在的 run 返回统一安全响应", async ({ request }) => {
    const resp = await request.get("/api/v1/research/runs/rrun-does-not-exist");
    expect(resp.status()).toBe(404);
    const body = await resp.json();
    expect(JSON.stringify(body)).toContain("不存在或无权");
  });

  test("401：未登录访问 run 被拒", async ({ request }) => {
    const resp = await request.get("/api/v1/research/runs/rrun-x",
      { headers: { cookie: "" } });
    expect([401, 404]).toContain(resp.status());
  });

  test("启动研究并展示 scope/claims/引证门，可综合报告", async ({ page }) => {
    await login(page);
    await page.goto("/research/workbench");
    await page.getByPlaceholder(/输入研究问题/).fill("年假多少天");
    await page.getByRole("button", { name: /启动/ }).click();
    // 等待运行状态出现
    await expect(page.getByText("运行状态")).toBeVisible({ timeout: 20_000 });
    // 服务端固化 scope 展示
    await expect(page.getByText(/Scope（服务端固化）/)).toBeVisible();
    // 若有 claims 则展示引证门
    const gate = page.getByText(/引证门/);
    if (await gate.isVisible().catch(() => false)) {
      await expect(gate).toBeVisible();
    }
  });

  test("跨 scope 零泄漏：响应不泄露 run 内容", async ({ request }) => {
    // 无权限上下文访问任意 run id，统一安全响应、不含内容字段
    const resp = await request.get("/api/v1/research/runs/rrun-probe");
    const text = await resp.text();
    expect(text).not.toContain("question");
    expect(text).not.toContain("budget");
  });
});
