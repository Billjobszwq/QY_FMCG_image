/**
 * M9（G8）：模型管理浏览器验收（Playwright；1024/1280/1440）。
 *
 * 依赖：@playwright/test + chromium（与 R2-09 相同，安装需授权）。
 * 前置：
 *   1) scripts/qa_model_management_server.py --port 8400（QA 副本库）；
 *   2) frontend dev server（vite，/api 代理 8400）或等价静态服务。
 *
 * 验收项（04 §7）：
 * - 管理员（含 models scope）：桌面出现“模型管理”图标，窗口五页签；
 * - 普通员工：无图标、无窗口；直接 API 403（后端强制，非前端隐藏）；
 * - 密钥：提交后输入框清空；DOM 与网络响应无明文；
 * - maker 无“批准”动作；
 * - /vision/models 别名解析到 /models/local；
 * - 三档宽度无横向溢出；空态/401/403 诚实。
 */
import { expect, test } from "@playwright/test";

const BASE = process.env.QA_BASE_URL ?? "http://127.0.0.1:5173";
const ADMIN = { username: "admin", password: "qa-admin-pw" };
const EMP = { username: "emp", password: "qa-emp-pw" };

for (const width of [1024, 1280, 1440]) {
  test.describe(`模型管理 @ ${width}px`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("管理员可见图标与五个页签；员工不可见且 API 403",
      async ({ page, context }) => {
        await page.goto(BASE);
        // 登录（桌面登录窗）
        await page.getByPlaceholder(/用户名|账号/).first()
          .fill(ADMIN.username);
        await page.getByPlaceholder(/口令|密码/).first()
          .fill(ADMIN.password);
        await page.getByRole("button", { name: /登录/ }).click();
        await expect(page.getByText("模型管理").first()).toBeVisible();
        await page.getByText("模型管理").first().dblclick();
        for (const tab of ["连接管理", "模型目录", "能力分配",
                           "运行治理", "本地模型"]) {
          await expect(page.getByRole("tab", { name: tab }))
            .toBeVisible();
        }
        // 无横向溢出
        const overflow = await page.evaluate(() =>
          document.documentElement.scrollWidth
          - document.documentElement.clientWidth);
        expect(overflow).toBeLessThanOrEqual(0);

        // 员工独立上下文：无图标 + 直接 API 403
        const empPage = await context.newPage();
        await empPage.goto(BASE);
        await empPage.getByPlaceholder(/用户名|账号/).first()
          .fill(EMP.username);
        await empPage.getByPlaceholder(/口令|密码/).first()
          .fill(EMP.password);
        await empPage.getByRole("button", { name: /登录/ }).click();
        await expect(empPage.getByText("模型管理")).toHaveCount(0);
        const apiResp = await empPage.request.get(
          `${BASE}/api/v1/models/connections`);
        expect(apiResp.status()).toBe(403);
      });

    test("密钥 write-only：提交后清空且 DOM/响应无明文",
      async ({ page }) => {
        const SECRET = "pw-browse-qa-secret-777";
        await page.goto(BASE);
        await page.getByPlaceholder(/用户名|账号/).first()
          .fill(ADMIN.username);
        await page.getByPlaceholder(/口令|密码/).first()
          .fill(ADMIN.password);
        await page.getByRole("button", { name: /登录/ }).click();
        await page.getByText("模型管理").first().dblclick();
        await page.getByRole("tab", { name: "连接管理" }).click();
        await page.getByRole("button", { name: "新增连接" }).click();
        await page.getByTestId("field-name").fill("qa-conn");
        await page.getByTestId("field-secret").fill(SECRET);
        // 记录网络响应，断言无明文
        const responses: string[] = [];
        page.on("response", async (r) => {
          try {
            const t = await r.text();
            if (t.includes(SECRET)) responses.push(r.url());
          } catch { /* ignore */ }
        });
        await page.getByTestId("save-draft").click();
        await page.waitForTimeout(800);
        expect(responses).toHaveLength(0);
        // 重新打开表单：密钥输入为空
        await page.getByRole("button", { name: "新增连接" }).click();
        await expect(page.getByTestId("field-secret")).toHaveValue("");
        const html = await page.content();
        expect(html).not.toContain(SECRET);
      });
  });
}
