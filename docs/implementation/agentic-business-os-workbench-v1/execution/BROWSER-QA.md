# Browser QA（T13）

日期：2026-08-11 · HEAD：b5e27547 之后（修复提交见 git log）· 服务：bin/abos 冷启动后四服务 healthy。

## 验收矩阵（真实浏览器，Browser agent 执行）

| 场景 | 结果 | 证据 |
|---|---|---|
| 登录（品牌=Agentic Business OS，无 SKU 字样） | pass | browser/browser-login-1440.png |
| 首页主管工作台（待办 100/批准/运行/异常/完成 + 模块健康表 + 快速目标） | pass | browser/browser-home-1440.png |
| 一级导航 9 模块 + 状态徽章（Registry 投影） | pass | browser/browser-vision-1440.png |
| 智能识别二级 6 项（/#/vision/*） | pass | 同上 |
| Profile 选择器（1 enabled / 10 disabled 带 blockers） | pass | browser/browser-vision-1440.png |
| 任务历史（profile/来源列，10→11 条） | pass | browser/browser-vision-tasks-1440.png |
| Agent UIIntent 执行（"打开识别任务"→真实跳转 /vision/tasks） | pass | browser/browser-agent-command-1440.png |
| Agent 命令预览 + 批准 → 真实创建任务 a05e038b… | pass | browser/browser-agent-approved-1440.png |
| planned 模块诚实插槽（无假图表） | pass | browser/browser-planned-1440.png |
| 系统状态（healthy；production_switch=false 等冻结标志） | pass | browser/browser-status-1440.png |
| 深链接 /#/vision/tasks 刷新直达 | pass | — |
| 旧路由 /#/recognition → 重定向 /#/vision/recognize | pass | — |
| 1280/1024/768 视口 | partial（浏览器工具无法设定视口，实际 934–1383px 程序化验证无横向滚动） | browser-home-1280/vision-1024/home-768.png |

## Console / Network

- 仅 1 条登录前 `/api/v1/auth/me` 401（预期探测行为）；登录后无 console 错误。
- Network 无 4xx/5xx（除上述 401）。

## QA 发现并已修复的问题

| 问题 | 修复 |
|---|---|
| Agent 回答“识别任务共 0 条”（ORDER BY id → no such column，宽泛异常吞错） | supervisor.py QueryTool 改 ORDER BY rowid；复测回答“共 11 条” |
| ≤1024px 右侧面板遮挡主内容 | SupervisorWorkspace 增加收起/展开（✦ 悬浮按钮），窄屏默认收起 |
| 批准后按钮状态不持久 | CommandPreviewCard 增加 resolved 终态渲染 |
| Profile 卡片长文本溢出 | .tile 增加 overflow-wrap: anywhere |
| 登录页输入框对比度低（旧营销样式） | .login-card input 覆盖为中性样式 |

## 残留（已登记，不阻断）

- 首页运行概览刷新瞬间显示“服务：未知”（health 加载前瞬态，返回后恢复 healthy）。
- 视口尺寸受浏览器工具限制未能精确 1440/1280/1024/768；CSS media query 已在 1280/1024/768 断点编写并经程序化无横向滚动验证。
