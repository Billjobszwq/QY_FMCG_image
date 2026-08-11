# Agentic Business OS 工作台重构、识别首域打通与完整自验执行指令

你现在需要在当前项目中实际完成实现，不是继续写一份空泛建议，也不是只调整几处颜色。用户要交付的是一套像样、可理解、可运行、可演示、可扩展的智能业务操作系统工作台。

本轮设计已经批准。你必须完整执行本提示词，并在机器侧可以完成的工作全部闭环后再报告。不要每完成一点就停下来向用户要下一段提示词。

---

## 一、系统唯一定位

本项目不是识别系统，也不是传统 SaaS。它是一套：

> 以 Graph+Loop 为智能执行内核、以模块化 Domain Pack 为业务能力、以共享数据与证据底座为可信事实源、由主管 Agent 和领域 Agent 协作完成工作的智能业务操作系统。

图像识别、标注和训练只是第一个 Domain Pack。未来还会接入：

- 数据仓库；
- 问卷设置与回收；
- 地址管理、地理位置分析、电子围栏、任务推荐；
- 路线/线库规划；
- BI 报表；
- 数据告警；
- 数据深度对话；
- 工作流编排；
- 财务对账；
- 深度问题抽象与策略分析；
- 客户定制模块。

所有模块共用一套身份、租户、客户、项目、数据、资产、证据、任务、Graph、Agent、审计、权限、计费和 API 底座。禁止为新模块复制第二套平台。

---

## 二、强制阅读与工作方法

修改任何代码前完整阅读：

1. `/Users/zhangweiqi/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/implementation/agentic-business-os-workbench-v1/` 全部文件
3. `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`
4. `docs/superpowers/specs/2026-08-04-location-field-operations-design.md`
5. `docs/implementation/project-logic-chain-v3/` 全部文件
6. `docs/implementation/micro-gold-v2-leakage-rebuild/` 全部文件
7. `docs/CODEX-PROJECT-HANDBOOK.md`
8. `docs/USER-HANDBOOK.md`
9. `src/platform/registry.py`
10. `src/platform/kernel/`、`src/platform/agents/`、`src/platform/api/`、`src/platform/data/store.py`
11. `src/modules/fmcg/`、`src/recognize/`、`src/platform/adapters/legacy/recognition.py`
12. `web/src/App.tsx`、`web/src/styles.css`、`web/src/api.ts`、`web/src/pages/` 全部文件
13. 相关测试、最近至少 30 个 commits、当前数据库 schema、现有服务和未跟踪资产。

必须使用：

- Superpowers writing-plans / executing-plans；
- test-driven-development；
- systematic-debugging；
- verification-before-completion；
- gstack 工程架构审查；
- gstack 设计计划审查；
- 完成后先做 qa-only、再做代码 review。

先建立并持续更新：

`docs/implementation/agentic-business-os-workbench-v1/execution/`

至少包含：

- `IMPLEMENTATION-LIST.md`
- `STATUS.md`
- `DECISIONS.md`
- `ISSUES.md`
- `EXECUTION-LOG.md`
- `ACCEPTANCE.md`
- `BROWSER-QA.md`
- `FINAL-REPORT.md`

每个节点开始、发现问题、测试、修复、证据、状态变化都写入日志。不得最后凭记忆补写。

---

## 三、安全边界

本轮允许修改平台、Web、Agent、模块注册、识别链路、测试和文档。

本轮严禁：

1. 重新训练 YOLO、SAM、Classifier、Qwen 或 QLoRA；
2. 自动切换 production bundle；
3. 删除任何历史项目、数据集、模型、报告、证据或备份；
4. 清理或暂存 `.superpowers/`、大模型、数据集和用户未跟踪资产；
5. 使用 `git reset --hard`、`git checkout --`、宽泛 `rm` 或 `git add -A`；
6. merge、push、deploy；
7. 为让页面显示正常而写假数据、假健康、假任务或硬编码当前数字；
8. 用模型训练指标冒充经营 BI 数据；
9. 让 Agent 直接执行 SQL、直接写客户数据或绕过领域服务；
10. 因第三方 UI 好看而逐像素/逐模块死板照抄。

现有最好生产模型必须保留，通过兼容 adapter 提供识别。任何 production 变化都需要用户另行明确授权。

---

## 四、先冻结现场基线

必须现场重新核验，不盲信文档中的旧 HEAD 和数字：

- Git HEAD、branch、worktree、最近 commits；
- 用户已有修改和未跟踪资产；
- 当前训练进程；
- 8091/8092/8300/8400 及其它必要服务；
- SQLite integrity、migration、模块/Agent/Capability 数量；
- 当前 production；
- Web 构建产物与源码是否一致；
- 当前测试；
- 当前浏览器实际效果和 console/network。

把 before 截图、API payload、服务探测和静态审计保存为证据。发现已有训练在运行时，不得停止或抢占；本任务先完成不干扰的代码/文档工作，并明确资源边界。

已知需要现场复现的重点问题：

1. 登录页、页脚、Supervisor prompt 仍将平台叫作 SKU 识别系统；
2. `App.tsx`、`modules_api.py`、Capability Registry、Agent Registry 多事实源；
3. 多个二级菜单指向同一路由，属于假三级菜单；
4. Recognition Profile 只改变前端 local state，没有进入识别请求；
5. Supervisor 返回 UIIntent/command/evidence，但 AgentChat 不消费；
6. `SupervisorDrawer.tsx` 为孤儿组件；
6.1 Supervisor 存在前置通用 M4 分支吞掉后续 qwen/M4 分支、`Path` 未导入且异常被宽泛捕获的问题；
7. CSS 使用未定义变量和未定义组件类，导致透明/无样式模块；
8. `/biz/m3bars` 使用模型训练报告冒充 BI；
9. 页面有过期 production/项目 ID/完成数硬编码；
10. 当前服务可能全部未启动，系统不能冷启动演示。

每个问题先写红测试或可重复检查，再修复。

---

## 五、建立唯一 Module Manifest V2

不得新建第四套注册常量。扩展现有 `src/platform/registry.py`，让一个 `ModuleManifestV2` 同时驱动：

- 一级模块和色系；
- 二级 route；
- 三级 actions；
- Domain Agent；
- capabilities；
- commands/queries/events；
- API prefix/OpenAPI tag；
- data products；
- permission scopes；
- UI slots；
- feature flags；
- dependencies/compatibility；
- billing units；
- health checks；
- live/beta/planned/degraded/disabled 状态。

硬要求：

- `web/src/App.tsx` 不再持有手写一级模块清单；
- `src/platform/api/modules_api.py` 不再持有第二份业务模块常量；
- Module 和 Agent Manifest 有可校验关联；
- route、module_id、capability_id、agent_id 冲突 fail-closed；
- 缺依赖的模块显示 degraded/disabled，不伪造 live；
- 使用 `reference.echo` 非识别模块证明平台内核没有绑定 FMCG；
- 禁用模块后历史 Run、证据和账本仍可读，其它模块正常。

未来一级模块按文档建议注册：主管工作台、数据与资产、调研与问卷、位置与外勤、智能识别、分析与 BI、工作流与 Agent、财务与结算、系统与开发者。当前没有真实后端的模块标 `planned`，只提供诚实插槽和契约。

---

## 六、重建工作台壳层，但不要重写全部业务

采用中性操作界面 + 模块 accent 色，不再使用营销页式跑马灯、巨型 footer、巨幅标题和彩虹色大块导航。

建立：

- Design tokens；
- AppShell；
- TopBar；
- PrimaryNav；
- SecondaryNav；
- PageHeader；
- ActionBar；
- Status/Empty/Error/Loading；
- Table/Form/Upload；
- Drawer/Dialog；
- EvidenceDrawer；
- AgentMessage/CommandPreview/ApprovalCard；
- ImageViewer/BoxOverlay。

硬要求：

- 一个模块一个稳定色系，但颜色主要作为 accent/soft surface；
- 状态色与模块色分离；
- 所有使用的 CSS variable 已定义；
- 关键 class/component 没有孤儿引用；
- 页面不再散落大量 inline style；
- 1440/1280/1024/768 均可用；
- 键盘、focus-visible、Esc、focus trap、reduced motion、WCAG AA；
- loading/empty/error/blocked/permission/stale 都有明确下一步；
- 不得为了视觉统一删除现有真实功能。

先用组件实验页验证，再迁首页和识别页，再迁其余页面。保留旧 route redirect，禁止大爆炸式替换。

---

## 七、实现真实三级信息架构

一级 = Module Manifest 业务域。
二级 = 独立、可深链接、可刷新恢复的功能 route。
三级 = 页面工具栏/步骤条/抽屉中的结构化操作。

识别域至少提供：

- `/vision/recognize`
- `/vision/tasks`
- `/vision/annotation`
- `/vision/datasets`
- `/vision/models`
- `/vision/evidence`

禁止多个标签指向同一 URL；禁止 route 全部渲染同组件后永远回到默认 tab；权限、feature flag 和模块状态必须控制可见与可用。

---

## 八、让主管 Agent 真正控制全局

主管 Agent 是首页和全局右侧工作区，不只是聊天泡泡。采用用户之前确认的黄色便签/任务板视觉语言，包含：

- 今日待办；
- 需要批准；
- 正在运行；
- 异常/阻塞；
- 最近完成；
- 固定笔记；
- 对话；
- 领域 Agent 委派记录。

统一 Agent 响应必须包含并被前端实际消费：

- message；
- evidence_refs；
- ui_intents；
- command_previews；
- tasks；
- delegations；
- memory_updates；
- requires_approval；
- trace_id。

要求：

- UIIntent 只能使用白名单，前端真实执行 navigate/open/filter/highlight/compare/pin/show_evidence；
- 禁止 HTML/JS 注入；
- command preview 展示影响、成本、参数、权限、幂等键和回滚；
- approve/reject 真实落库并有审计；
- 会话和命令服务端持久化，不只依赖 localStorage；
- Supervisor 不硬编码过期业务答案，使用 Query Tool/Domain Service；
- DeepSeek/LLM 不可用时明确降级，不伪装智能回答；
- production switch、删除、发布、财务终结继续需要人工独立批准。

先做真实可用的 Supervisor、Recognition Agent、Data Agent、System Agent。其它领域 Agent 可注册 planned，但不能伪造回答。

---

## 九、一次性打通识别首域

本轮不训练，只使用当前最好 production，通过统一 Graph/Domain Service 打通：

```text
输入照片/批量/URL/Asset
  → 资产登记与去重
  → 质量判断与证据
  → 场景/价签
  → 识别 Profile 与档位路由
  → detector / classifier / SAM / retrieval / VLM（按 Profile 可用性）
  → 融合、拒识、人工兜底
  → 结果、证据、任务历史、计费
```

### 识别请求必须包含

- `recognition_profile_id`
- `service_tier`
- `source`
- `project_id/customer_id`
- `idempotency_key`
- upload/url/asset_id 之一

前端选择必须真正进入请求。服务端只接受已注册 profile ID，拒绝任意权重路径。任务和结果回显冻结后的 graph/model/policy/threshold/profile/bundle 版本。

### Web/API/Agent 三入口同源

- 单图也写统一任务历史；
- 批量和 URL 使用同一 service；
- Agent 先生成命令预览，批准后调用同一 API；
- 旧接口保留 adapter 和 deprecation，不保留第二套业务逻辑；
- 结果页显示叠框、SKU、置信、拒识/人工、质量、场景、耗时、成本、证据；
- 可导出 JSON/CSV/标注图；
- 0 检出、服务过载、模型不可用、质量拒绝、URL 失败都诚实返回；
- production、bundle 和服务状态均来自实时 API，不硬编码。

使用仓库内合法样板照片完成真实演示验收；不得把样板加入训练或金标准，不得用 mock 通过真实 E2E。

---

## 十、首页改为真实主管工作台

首页必须优先显示：

1. 今日待办；
2. 需要批准；
3. 正在运行；
4. 异常与告警；
5. 最近完成；
6. 固定笔记；
7. 快速目标输入；
8. 模块和 Agent 健康。

全部从 Domain Service/projection 读取。没有数据时展示诚实空状态，禁止硬编码“200 条、19/19、项目 22、某个 production”冒充当前事实。

---

## 十一、未来模块的处理方式

本轮建立可插拔骨架，不伪造业务完成：

- 数据仓库注册真实已有资产/血缘能力；
- 问卷、Geo/Field、BI、告警、财务、策略没有后端时标 planned；
- 为每个模块留 Manifest、Agent、API、Data Product、Graph、UI Slot、权限和计费接口；
- 删除或停用 `/api/v1/biz/m3bars` 这种识别训练指标伪装经营数据的做法；
- planned 页面说明目标、依赖、可接入 Data Product 和下一实施包，不显示假图表。

---

## 十二、本机运行与系统手册

提供可验证的本机：

- `status`
- `start`
- `stop`
- `restart`
- `doctor`

覆盖 8091/8092/8300/8400 和必要 LLM 服务。脚本幂等、只操作明确 PID、不启动训练、日志路径清楚、失败不报假健康。

必须重写/补齐：

1. 用户使用手册；
2. 本机运维 Runbook；
3. 模块与 Agent 开发指南；
4. Quick Start；
5. Troubleshooting Matrix；
6. API 示例；
7. 当前模块帮助入口。

手册操作命令必须实跑验证。会变化的项目 ID、Gate、数量和 production 不硬编码为当前事实。

---

## 十三、Graph+Loop 执行顺序

严格按下列节点推进，不得绕过：

```text
BaselineAndSafetyAudit
  → CurrentUXBreakageReproduction
  → ProductIdentityCorrection
  → ModuleManifestV2AndRegistryProjection
  → DesignSystemAndAppShell
  → ThreeLevelNavigationMigration
  → SupervisorAndDomainAgentRuntime
  → RecognitionProfileContract
  → RecognitionEndToEndVerticalSlice
  → HomeCommandCenter
  → FutureDomainSlots
  → LocalStackRecoveryAndRunbook
  → FullAutomatedVerification
  → BrowserHumanAcceptance
  → DocumentationAndFinalReconciliation
```

每个 logical_node：

- 唯一；
- 幂等；
- 有输入 hash；
- 有 acceptance；
- 有证据；
- 失败 fail-closed；
- 重启后可恢复；
- 历史 append-only；
- 当前 projection 不重复。

每完成一个节点，运行相关测试并更新执行日志。若发现根因不在当前假设，先做 systematic debugging，再更新 Decision，不要堆补丁。

---

## 十四、强制测试与自我验证

### 后端 hermetic

```bash
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy \
/Users/zhangweiqi/miniconda3/bin/python -m pytest \
-q -p no:cacheprovider -m "not host_mps"
```

### Host MPS

```bash
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy \
/Users/zhangweiqi/miniconda3/bin/python -m pytest \
-q -p no:cacheprovider -m host_mps
```

分别报告 pass/skip/deselect，不得把 deselected 当通过。

### 前端

```bash
cd web
npm run typecheck
npm run build
```

补充前端单元/集成/E2E 测试，覆盖：

- Registry 驱动导航；
- 二级 route 唯一；
- 三级操作；
- Agent response 渲染和 UIIntent；
- command approve/reject；
- Profile 进入单图/批量/URL请求；
- loading/empty/error/permission/degraded；
- 深链接与刷新；
- 响应式和键盘。

### 数据与服务

- SQLite integrity；
- migration 幂等；
- Module/Agent/API/Web 数量与 ID 对账；
- 8091/8092/8300/8400 健康；
- 8400 聚合状态一致；
- current production 未切换；
- 无训练进程；
- 识别 task/run/evidence/usage 按 trace_id 对账。

### 浏览器 QA

必须真实浏览器测试 1440/1280/1024/768：

- 登录；
- 一级/二级/三级导航；
- 首页；
- 主管 Agent；
- 识别单图/批量/URL/历史/证据；
- planned 模块；
- 系统状态和帮助；
- 服务中断与恢复。

检查 console、network、404、未处理 promise、对比度、focus、遮挡、横向滚动、长文本、空态和错误态。保存带 route/viewport/commit/时间的 before/after 截图。

最后运行 gstack qa-only 和代码 review。发现问题要修复并重验，不能只把 QA 报告交给用户。

---

## 十五、性能和安全门

- 记录 App 首次可交互、路由切换、大表格和识别 p50/p95；
- 长任务异步，可离开和恢复；
- 后台轮询降频；
- 1000 行数据分页/虚拟化；
- 大图不进入全局 state；
- Agent 有等待、超时、取消反馈；
- URL 下载防 SSRF/重定向/超大响应；
- 身份不能用客户端 header 自证；
- 高风险命令两阶段批准；
- API 有 idempotency、rate limit、size limit；
- evidence 不泄漏密钥和跨租户路径；
- 不允许 Agent 写输入型客户数据库。

---

## 十六、完成状态

允许的状态：

- `BUSINESS_OS_REFRAME_IN_PROGRESS`
- `PLATFORM_SHELL_CONTRACT_READY`
- `RECOGNITION_E2E_READY`
- `WORKBENCH_UX_ACCEPTED`
- `READY_FOR_NEXT_DOMAIN_PACK`

阻断状态：

- `BLOCKED_RECOGNITION_RUNTIME_UNAVAILABLE`
- `BLOCKED_PLATFORM_CONTRACT_DIVERGENCE`

只有全部满足才可写 `READY_FOR_NEXT_DOMAIN_PACK`：

1. 平台定位已统一；
2. Module/Agent/API/Web 单一事实源；
3. 三级菜单真实；
4. 没有透明/未定义样式；
5. Supervisor 能真实控制 UI/证据/命令/委派；
6. 识别 Web/API/Agent 端到端同源；
7. 当前最好 production 能冷启动演示；
8. planned 模块没有假数据；
9. 全量测试、构建、DB、服务、浏览器、性能、安全通过；
10. 三份手册和开发指南可操作；
11. production 未切换；
12. 没有启动训练；
13. 文档、状态、截图和证据完成对账。

“页面能打开”“typecheck 通过”“有一张截图”均不等于完成。

---

## 十七、提交纪律

建议按 Graph 节点小步提交。每次只 `git add` 明确文件，禁止 `git add -A`。提交前检查模型、数据集、截图大资产、`.superpowers/` 和用户未跟踪目录未被误暂存。禁止 merge/push/deploy。

---

## 十八、最终报告格式

最终报告至少包含以下 50 项：

1. HEAD、branch、worktree
2. 本轮 commit 链
3. 完整阅读文件
4. 初始服务/进程/DB/production
5. 初始 UI before 截图
6. 初始 P0/P1 复现
7. 产品定位修复前后
8. 平台级硬编码清理结果
9. Module Manifest V2 schema
10. Module Registry 数量和状态
11. Agent Registry 数量和关联
12. Capability 数量和关联
13. API/Web/Agent 四方一致性
14. reference non-vision module 验收
15. 一级导航结果
16. 二级 route 清单
17. 三级 action 清单
18. 旧 route 兼容结果
19. Design token 定义/使用审计
20. 未定义 variable/class 数量（必须 0）
21. 组件系统清单
22. 1440/1280/1024/768 结果
23. 键盘/无障碍/对比度结果
24. 首页真实数据源
25. 待办/审批/运行/异常/完成/笔记结果
26. Supervisor 对话结果
27. UIIntent 执行结果
28. Evidence Drawer 结果
29. Command approve/reject 结果
30. Domain Agent 委派结果
31. 会话和记忆持久化结果
32. Recognition Profile 请求证据
33. disabled/unknown profile 拒绝证据
34. 单图识别结果
35. 批量识别结果
36. URL 识别结果
37. Agent 发起识别结果
38. 任务历史一致性
39. Graph trail/evidence/usage 对账
40. 识别故障与恢复测试
41. planned 模块诚实状态
42. 本地 status/start/stop/restart/doctor
43. 用户手册路径
44. 运维 Runbook 路径
45. 模块/Agent 开发指南路径
46. Hermetic/Host MPS/前端测试
47. SQLite/API/四服务/浏览器 QA
48. 性能与安全结果
49. production 未切换、未启动训练声明
50. 当前 Gate、未关闭问题和用户下一步

报告中的数量和状态必须来自最终实时对账。若有阻断，明确阻断节点、已完成机器工作、复现证据和恢复条件；不得写完成，不得把机器侧整理工作重新推回给用户。
