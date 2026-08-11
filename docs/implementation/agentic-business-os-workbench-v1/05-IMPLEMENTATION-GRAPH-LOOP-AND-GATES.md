# 实施 Graph、Loop 与完成门

## 一、执行原则

- 执行 Agent 必须先读文档、做现场对账、列出 implementation list，再改代码。
- 所有行为变更使用 TDD：红测试证明问题，最小实现变绿，再做浏览器验证。
- 一次只完成一个可回滚的纵向节点；禁止一次重写整个前端。
- 每个 Graph 节点有唯一 `logical_node`、幂等键、输入 hash、证据和终态。
- 历史 append-only；当前状态由 projection 计算；不能靠 README 或前端常量冒充事实。
- 不训练、不切 production、不删除历史、不清理未跟踪资产、不 merge/push/deploy。

## 二、执行 Graph

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
  → READY_FOR_NEXT_DOMAIN_PACK
```

## 三、节点任务

### T0 BaselineAndSafetyAudit

读取最新 Git、运行进程、服务、DB、模型、未跟踪资产、近期提交和全部本目录文档。输出：

- `execution/IMPLEMENTATION-LIST.md`
- `execution/STATUS.md`
- `execution/DECISIONS.md`
- `execution/ISSUES.md`
- `execution/EXECUTION-LOG.md`
- `execution/ACCEPTANCE.md`

记录当前生产 bundle、服务端口、无训练进程证据和工作树归属。发现用户未提交改动必须保留，不得 reset/checkout/覆盖。

### T1 CurrentUXBreakageReproduction

先写失败测试，覆盖：

- CSS variable 必须全部已定义；关键组件 class 必须存在；
- 一级导航不能来自 `App.tsx` 静态数组；
- 二级菜单 route 唯一，active 只能有一个；
- Profile 选择必须进入单图/批量/URL请求；
- Agent UIIntent、evidence、command preview 必须被前端消费；
- 页面不出现 `sku recognition`、`SKU 识别系统` 或过期 production 常量；
- Biz 不得读取训练报告冒充经营数据。

红测试和浏览器截图保存为 before evidence。

### T2 ProductIdentityCorrection

建立一个平台品牌/环境配置源，登录、标题、导航、footer、OpenAPI 和 Agent system prompt 统一为智能业务操作系统。识别只在 Vision Domain 中出现。

状态/production/Gate/项目 ID 一律从 API 或注册表读取；文档中的示例必须标为示例，当前事实通过状态端点查询。

### T3 ModuleManifestV2AndRegistryProjection

扩展现有 `src/platform/registry.py` 和组合根，不新增平行 `MODULES` 常量。推荐文件边界：

- `src/platform/registry.py`：Manifest schema 与注册；
- `src/platform/module_catalog.py`：只读投影与状态；
- `src/platform/api/modules_api.py`：消费 registry，不持有业务常量；
- `src/modules/<domain>/manifest.py`：各 Domain Pack 声明；
- `web/src/platform/moduleRegistry.ts`：API 类型/缓存，不硬编码模块；
- `web/src/platform/routes.tsx`：由已注册 UI module 映射 route。

必须用 `reference.echo` 非识别模块验证注册、导航、Agent、API、健康和卸载。

### T4 DesignSystemAndAppShell

建立 token 和基础组件层，清除 undefined variable/class。建议目录：

- `web/src/platform/design/tokens.css`
- `web/src/platform/design/base.css`
- `web/src/platform/components/*`
- `web/src/platform/shell/AppShell.tsx`
- `web/src/platform/shell/PrimaryNav.tsx`
- `web/src/platform/shell/TopBar.tsx`
- `web/src/platform/shell/SupervisorWorkspace.tsx`

不得继续在页面散落大段 inline style。先做组件实验页，再迁首页和识别页；其余旧页面通过兼容层逐步迁移。

### T5 ThreeLevelNavigationMigration

- 一级从 Module Registry 投影；
- 二级每项独立 route；
- 三级使用 ActionBar/Stepper/Drawer；
- 旧 route 提供 redirect 和 deprecated 标记；
- 直接打开深链接、刷新、前进/后退保持正确；
- 权限、feature flag、planned/degraded 状态影响可见性和可操作性。

### T6 SupervisorAndDomainAgentRuntime

移除 Supervisor 中过期硬编码事实，所有业务答案通过 Query Tool/Domain Service 获得。修复：

- 正确的通用 system prompt；
- Agent Manifest 与 Module Manifest 关联；
- UIIntent 前端执行器；
- evidence drawer；
- command preview + approve/reject；
- task/delegation 回执；
- 主管黄色便签待办区；
- 会话、消息、命令在服务端持久化，不能只依赖 localStorage；
- 高风险命令继续拒绝或人工批准。

先实现 Supervisor + Recognition Agent + Data Agent + System Agent 的真实最小能力；其它 Agent 注册为 planned，不伪造结果。

### T7 RecognitionProfileContract

端到端加入 `recognition_profile_id/service_tier/project_id/source/idempotency_key`。Profile resolve 在服务端完成，disabled/unknown/path input fail-closed。任务和响应回显冻结配置。

单图、批量、URL、API、Agent 使用同一 `RecognitionTaskService`；旧接口只作适配。新增契约测试证明前端选择确实改变 request，而不是视觉 state。

### T8 RecognitionEndToEndVerticalSlice

完成资产→质量→场景→识别 Graph→结果→历史→证据。现有最好 production 继续通过 legacy adapter；若高级能力不可用，按 Profile 策略降级或转人工，不能静默伪装。

使用合法样板照片跑 10 项演示验收，输出逐任务 ledger、截图、API payload、Run trail、服务日志和耗时。不得用 mock 结果通过真实验收。

### T9 HomeCommandCenter

首页改为真实任务中心：待办、审批、运行、异常、完成、笔记、快速目标和模块健康。数据来自统一 projection；没有数据就展示明确空状态，不写死 200、19/19 或 production。

### T10 FutureDomainSlots

注册数据仓库、问卷、Geo/Field、BI/Alert、Finance/Settlement、Strategy 等 manifest 骨架。只有真实后端的标 live；其它为 planned。移除 `/biz/m3bars` 这类跨域假 BI，改用 Data Product 契约与诚实空状态。

### T11 LocalStackRecoveryAndRunbook

提供受控的本机脚本或命令：`status/start/stop/restart/doctor`，覆盖 8091/8092/8300/8400 和必要 LLM 服务。要求：

- 重复执行幂等；
- 先检查端口、PID、模型、DB、磁盘、内存；
- 不启动训练；
- 日志路径清楚；
- 启动失败不残留假健康；
- 可恢复停止，只终止本项目明确 PID；
- 冷启动后 Web/API/Agent/识别验收可运行。

### T12 FullAutomatedVerification

执行后端、前端、契约、集成和 E2E 全套测试；测试不得依赖当前机器已有服务或隐式 localStorage。修复所有由本轮引入的问题；历史失败必须解释并登记，不能从命令中排除冒充通过。

### T13 BrowserHumanAcceptance

真实浏览器按 1440/1280/1024/768 验收登录、导航、首页、Agent、识别、任务历史、证据、planned 模块、系统状态。检查 console、network、键盘、对比度、loading/empty/error、刷新/深链接。保存 before/after 截图和报告。

### T14 DocumentationAndFinalReconciliation

完成用户手册、Operator Runbook、Developer Extension Guide、API examples、故障排查；更新文档索引。最后对账 Git/DB/API/Web/Agent/服务/生产/训练状态，生成最终报告。

## 四、完成状态

允许的当前 Gate：

- `BUSINESS_OS_REFRAME_IN_PROGRESS`
- `PLATFORM_SHELL_CONTRACT_READY`
- `RECOGNITION_E2E_READY`
- `WORKBENCH_UX_ACCEPTED`
- `READY_FOR_NEXT_DOMAIN_PACK`

若识别服务、模型或真实样板无法恢复：

- `BLOCKED_RECOGNITION_RUNTIME_UNAVAILABLE`

若 Module Registry 仍有并行事实源：

- `BLOCKED_PLATFORM_CONTRACT_DIVERGENCE`

只有 T0–T14 通过才能写 `READY_FOR_NEXT_DOMAIN_PACK`。页面好看但识别断链、Agent 只聊天或 API 不一致都不得写完成。

## 五、提交纪律

建议按节点小步提交；只暂存明确文件，禁止 `git add -A`。禁止 merge/push/deploy。提交前检查未跟踪模型、数据集、图片、`.superpowers/` 未被误暂存或修改。
