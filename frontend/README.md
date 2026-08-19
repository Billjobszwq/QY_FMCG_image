# TaaS Frontend

v3 产品前端：桌面式窗口系统 + 设计系统（Design System）+ 30 个真实数据模块页面。
一切业务数据走同源 `/api/v1/*`（`src/lib/api.ts`），无样本 / 假数据；
与既有业务接通的工作台 `web/` 并存（见仓库根 README）。

> 设计价值观：品味 > 抛光 · 手工感与反主流 · 实用主义（信息密度 / 键盘优先）· 克制的拟物趣味。

## 运行

```bash
cd frontend
npm install
npm run dev           # 开发：http://localhost:5173（Vite 同源代理 /api → :8400）
npm run build         # 类型检查 + 生产构建（输出 dist/）
node server/serve.mjs # 生产：http://127.0.0.1:4173（零依赖静态服务 + /api 反代 :8400）
npm run lint          # ESLint（扁平配置，Vite 模板同款规则集）
npm test              # Vitest（windowStore / utils 单测）
npm run icons:derive  # 由 favicon.svg 派生 apple-touch-icon / manifest PNG
```

要求 Node ≥ 20（`package.json` engines 与 `.nvmrc` 已约束）。
`server/serve.mjs` 可用 `--port <n>` 覆盖端口（缺省 4173，登记于
`docs/services.json` 的 `frontend` 条目）；健康探活 `GET /` 或 `/health`。

## 产品桌面壳（v4 交互范式）

PostHog 式桌面交互：顶部菜单栏 + 桌面图标双击开窗 + 窗口层 + Taskbar(底)：

- 登录闸门「无壳」：`me` 为 null 时仅点阵桌面 + 居中登录窗（`id="login"`、
  `closable=false`），无菜单栏/图标/任务栏；登录成功进入完整桌面并默认打开
  `/home` 与 `/status`；
- 顶部菜单栏：左=品牌刺猬+平台名+版本；十组模块下拉菜单（已打开条目带选中圆点，
  Esc/外部点击收起）；右=服务健康点（点击开 /status）+用户名+退出；
- 桌面图标：模块按组分区平铺为桌面图标；**单击选中、双击开窗**（Enter/Space 同双击），
  双击桌面空白清除选中；已打开模块图标带选中圆点；
- 路由键唯一事实源：`src/modules/registry.tsx`（十组导航，与 web 端
  `MODULE_ROUTES` 对齐）；页面一律 `React.lazy` 进窗口，Suspense 兜底刺猬加载；
- 401 → 页面以 `NeedLoginState`（serious/warn 徽章 + “打开登录窗口”按钮）呈现；
  网络错误 → `ErrorState` + 重试。

## 技术栈

React 19 + TypeScript · Vite 7 · Tailwind CSS v4（CSS 自定义属性即设计令牌）·
Radix UI（Slot 等底层原语）· Framer Motion（拖拽 / 缩放 / 过渡）· Zustand（窗口全局状态）·
React Router · ESLint 9（typescript-eslint / react-hooks / react-refresh）·
Vitest + jsdom · @fontsource 字体自托管 · sharp（图标派生脚本）。

## 目录结构

```
frontend
├── index.html                # meta（theme-color / color-scheme / OG / manifest）；字体自托管无 CDN
├── server/serve.mjs          # 生产静态服务器（零依赖 node）：dist + /api→:8400、/orchestrator→:8304 反代，:4173
├── public/
│   ├── favicon.svg           # 近黑圆角方 + 奶油刺猬剪影（与 HedgehogMark 同源 path）
│   ├── manifest.webmanifest  # PWA manifest（SVG + 派生 PNG 图标）
│   └── *.png                 # 由 npm run icons:derive 派生，不手改
├── scripts/derive-icons.mjs  # sharp：favicon.svg → 180/192/512 PNG
├── eslint.config.js
└── src
    ├── main.tsx              # 入口；@fontsource 字体导入
    ├── App.tsx               # 路由壳 + <MotionConfig reducedMotion="user">
    ├── styles/index.css      # 设计令牌（@theme → :root）+ 基础/组件层 + reduced-motion
    ├── lib/api.ts            # 同源 typed client（fetchXxx，/api/v1/*；mutation 带 CSRF）
    ├── lib/utils.ts          # cn / clamp（含单测）
    ├── store/auth.ts         # 登录会话 store（useAuth：me / login / logout / refresh）
    ├── store/windowStore.ts  # 全局窗口管理器（Zustand，含单测）
    ├── modules/registry.tsx  # 模块注册表：十组导航路由 → 懒加载页面（唯一事实源）
    ├── hooks/                # useDesktopSize / useKeyboardShortcuts
    ├── components/
    │   ├── window/           # AppWindow / TitleBar / ResizeHandle（指针 + 键盘）
    │   ├── desktop/          # Desktop / Taskbar / TopMenuBar / DesktopIcon
    │   ├── ui/               # button / badge / kbd / input / select / loader（刺猬动画）/ mascot / LoginWindow
    │   ├── data/             # 数据原语：ApiTable / KV / PageHeader / StatusBadge / ErrorState / NeedLoginState
    │   ├── charts/primitives.tsx # 图表原语（ChartCard / StatTile / VBars / StackedBars / HBars）
    │   └── icons/index.tsx   # 手工几何 SVG 图标库（统一 16 网格 / currentColor）
    └── pages/
        ├── DemoDesktop.tsx   # 产品桌面壳：顶部菜单栏 + 桌面图标双击开窗 + Taskbar（登录会话闸门）
        ├── core/             # Home / SystemStatus / Help
        ├── vision/           # Recognize / Tasks / Annotation / Datasets / Models / Evidence
        ├── data/             # Import / Assets / Quality
        ├── workflow/         # Runs / Templates / Agents / Approvals / Connectors
        ├── master/           # Accounts / Audit / Customers / Projects / Skus
        ├── analytics/        # Reports / Anomalies / Semantics
        └── biz/              # Survey / Geo / Finance（页内页签分组）
```

## 设计令牌

全部定义于 `src/styles/index.css` 的 `@theme`（Tailwind v4 配置即 CSS 自定义属性，
编译后同样输出到 `:root`，任意 CSS 可用 `var(--color-accent)` 引用）。

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--color-background` | `#fdfdf8` | 鼠尾草奶油白，主背景 |
| `--color-surface` | `#f8f8f0` | 面板 / 窗口背景 |
| `--color-text-primary` | `#4d4f46` | 橄榄墨色正文 |
| `--color-text-secondary` | `#6b6e63` | 次级文本 |
| `--color-accent` | `#f54e00` | 品牌橙，**仅** hover / focus / 选中态 |
| `--color-border` / `--color-border-strong` | `#e2e4da` / `#cfd2c2` | 边框 / 聚焦窗口边框 |
| `--color-button-bg` / `--color-button-text` | `#1e1f23` / `#fff` | 主按钮 |
| `--color-series-1/2/3` | `#1d4aff` / `#dc9300` / `#8a4fd8` | 图表类目序列色：顺序固定蓝→黄→紫，不得循环复用 |
| `--color-ramp-1…5` | `#d6defe` → `#1d4aff` | 图表 sequential 蓝五阶（浅→深，仅表达数值大小） |
| `--color-success` / `--color-warning` / `--color-serious` | `#3e6b21` / `#9a6a00` / `#a3341f` | 状态保留色：仅 StatusBadge 图标 + 文字，禁挪作系列色 / 静态装饰 |
| `--font-display` | IBM Plex Sans | 标题 / 展示（自托管 400/700） |
| `--font-sans` | 系统栈 | 正文 |
| `--font-squeak` | Caveat（可变 400–700） | 手写趣味：吉祥物台词牌 / 空态标语 / Badge |
| `--titlebar-height` / `--taskbar-height` / `--window-radius` | 40px / 48px / 8px | 窗口几何 |

规则：**无渐变背景**（桌面点阵为纹理，非渐变填充）；橙色不得用作静态装饰色；
间距使用 Tailwind 4px 基准尺度（8/12/16/20/24/32/48/64）。
图表系列色已验证（dataviz 六检查）；颜色一律先在 `@theme` 定义令牌再引用，
数值 / 标签 / 图例文字不穿系列色（仅 text-primary / text-secondary）。

## 添加一个新窗口

模块窗口由顶部菜单栏下拉与桌面图标（双击）依据 `modules/registry.tsx` 打开
（路由键即窗口 id）；其他场景可在任意组件中调用 `openWindow`（幂等：同 id 重复调用仅置前）：

```tsx
import { useWindowManager } from "@/store/windowStore";

function Launcher() {
  const openWindow = useWindowManager((s) => s.openWindow);

  return (
    <button
      onClick={() =>
        openWindow({
          id: "/home",                   // 唯一 id（模块窗口用注册表路由键）
          title: "首页",
          content: <HomePage />,         // 页面组件（懒加载需自包 Suspense）
          defaultPosition: { x: 120, y: 96 },
          defaultSize: { width: 960, height: 640 },
          minWidth: 560,                 // 可选，默认 320
          minHeight: 420,                // 可选，默认 200
          resizable: true,               // 可选，默认 true；false = 固定大小
          closable: true,                // 可选，默认 true
        })
      }
    >
      打开首页
    </button>
  );
}
```

`<AppWindow>` 由 `Desktop` 按 store 状态自动渲染，通常无需手动使用；
其属性即上表字段（`title / defaultPosition / defaultSize / minWidth / minHeight /
resizable / closable`），另含运行时状态 `position / size / isMinimized / isMaximized / zIndex`。

其他管理器方法：`closeWindow(id)` · `minimizeWindow(id)` · `restoreWindow(id)` ·
`toggleMaximize(id)` · `bringToFront(id)` · `setActive(id | null)` ·
`syncMaximizedSizes()`（视口变化时最大化窗口跟随）。

## 交互与快捷键

- 拖拽标题栏移动；越界橡皮筋回弹，标题栏始终可触达
- 右下角手柄调整大小（`resizable: false` 时无手柄）；手柄可聚焦，
  方向键步进 16px、Shift ×4（键盘与指针双通道）
- 双击标题栏或 □ 按钮最大化 / 还原；— 最小化到任务栏；× 关闭
- 点击窗口置前；任务栏点击：最小化→还原 / 聚焦→最小化 / 其余→置前
- `⌘/Ctrl + W` 关闭聚焦窗口 · `⌘/Ctrl + M` 最小化 · `Esc` 取消聚焦
  （任务栏提示按平台渲染 ⌘ / Ctrl；注：个别浏览器保留 `⌘W` 关闭标签页的系统行为）
- 打开动画 `scale(0.95→1) + 淡入 200ms ease-out`；按钮按下 `scale(0.97)` 回弹
- 所有可点击元素默认无橙色，hover / focus 0.2s 过渡到 `--color-accent`
- 页面滚动锁定，滚动仅发生在窗口内部
- 减弱动态效果：`App.tsx` 以 `<MotionConfig reducedMotion="user">` 包裹路由；
  `AppWindow` 的命令式补间经 `useReducedMotion` 归零；CSS 侧
  `@media (prefers-reduced-motion: reduce)` 停掉加载动画与按压缩放

## 无障碍约定

- 窗口外层 `role="dialog"` + `aria-label={标题}`；最小化时 `inert` + `aria-hidden`
- 任务栏项与桌面图标均用 `aria-pressed` 表达打开 / 聚焦状态
- 缩放手柄 `role="button"` + 24×24 命中区 + 方向键步进
- 品牌刺猬 `HedgehogMark` 为 button 语义（预留开始菜单入口）

## 组件与替换约定

- `Button / Badge / Kbd / HedgehogLoader / PulseDots / HedgehogMascot` 见 `components/ui/`。
  加载状态使用手绘刺猬或脉冲点，拒绝通用旋转圈；**空态统一复用 `HedgehogMascot`**
  （静态吉祥物 + Caveat 手写台词牌），不再引入临时占位图形
- 图标库 `components/icons/index.tsx`：统一 16×16 网格、`stroke="currentColor"`、
  圆头线帽的手工几何 SVG。清单：`CloseGlyph / MinimizeGlyph / MaximizeGlyph /
  RestoreGlyph`（标题栏）· `AppGlyph / DocGlyph / ChartGlyph / TableGlyph /
  TerminalGlyph / FolderGlyph / SearchGlyph / SettingsGlyph / HelpGlyph` ·
  `HedgehogMark`（品牌刺猬，32 网格，与 favicon 同源 path）
- 字体自托管：`@fontsource/ibm-plex-sans`（400/700）与 `@fontsource-variable/caveat`，
  随构建打包、无 CDN 依赖；如需替换字体族，改 `main.tsx` 导入与 `--font-*` 令牌即可
- Favicon 与位图：`public/favicon.svg` 为唯一手绘源；`npm run icons:derive`
  派生 `apple-touch-icon.png`(180) / `icon-192.png` / `icon-512.png`（manifest + OG 引用）

## 待办与替换清单

- [ ] 正式图标库到位后替换 `components/icons/index.tsx`（保持导出名即可无缝切换）
- [ ] 打开 / 置前窗口时的焦点管理（focus 移入窗口 + aria-live 播报激活变化）
- [ ] CI 加入 `npm ci && npm run lint && npm test && npm run build` 防回归
- [x] v3 集成完成：30 个模块页面全部接入真实数据（同源 `/api/v1/*`），
  样机页面（dashboard / catalog / console / review / experiments）与
  `src/data/sample.ts` 已删除
- [x] 生产静态服务器 `server/serve.mjs`（零依赖：dist 服务 + `/api` 同源反代
  `:8400`，正式端口 :4173，登记于 `docs/services.json`）

## 浏览器支持

Chrome / Firefox / Safari 最新两个大版本。布局使用标准 CSS（color-mix 等均已被
三大浏览器最新版支持）；拖拽与缩放手柄基于 Pointer Events。
