# EXECUTION LOG

本文件只追加，不覆盖历史。

## 2026-08-12 · T0 现场审计与安全基线

- 阅读完成：GLOBAL_AGENT_ROUTING.md、~/.codex/AGENTS.md、CODEX-PROJECT-HANDBOOK、
  USER-HANDBOOK、OPERATOR-RUNBOOK、MODULE-AGENT-DEV-GUIDE、docs/README、
  domain-packs-v2/ 全部 14 份、本目录 00–05 + 治理文档 + AGENT-EXECUTION-PROMPT。
- 现场：HEAD `47c01c43`，分支 `feat/nextgen-training-cycle-v2`，单 worktree；
  服务 8091/8092/8300/8400 全 UP；production `prod_20260805_v5_r1`；无训练进程。
- DB：integrity_check=ok；107 表；迁移至 040；备份
  `.platform/backups/platform_pre_v3_20260812_030918.sqlite`（integrity ok）。
- V4 制品定位：`best/sku_v4_best.pt` 133,135,871 字节，SHA256
  `84bf9936189377007898c942a3c9a87f605d52c2afe01b7db2a66269e5554975`；
  另有 `best/classifier_base_9295.pth`（45 MB）。
- 声明：未 merge/push/deploy；未启动训练；未删除历史资产；
  未跟踪训练/数据资产零触碰。before 状态以 00-CURRENT-STATE 审计 +
  V2 ACCEPTANCE 残留为准（首页/主管/任务/日历/进度不可运营）。

## 2026-08-12 · T1 统一控制面（commit a94cdc82）

- 红测试 8 项先红后绿（tests/platform/test_abos_v3_unification.py）：
  - ABOSV3-P0-001：投影器识别 workflow.succeeded/failed/cancelled +
    run.waiting_human/retried；事件重建后完成 WorkItem 不再退回 todo；
  - ABOSV3-P0-002：统一 /api/v1/control/current-work（WorkItemV2 主线 +
    遗留域工作）；/api/v1/workitems 同源消费 work_item_v2；
  - ABOSV3-P0-003：failed→retry→succeeded 后 run.current_error 与
    work.blockers 清除；旧错误仍在 run.failed 事件历史中；
  - ABOSV3-P0-004：BI 报表列表按 spec 去重取最新，新增
    list_report_versions + /reports/{id}/versions 端点（v1 不消失）；
  - ABOSV3-P1-015：IAM visible_customers 返回全部获授权客户列表；
    survey/analytics 列表按多客户集合过滤；报表多客户必须显式指定；
  - reconcile 对照 BusinessRun 业务事实（自愈漂移并计数 drift_fixed）。
- 投影重建基线改为 work_item_v2 全行（无事件的 approval/追问不丢失）。
- 全量 hermetic 1272 passed（后续 1277）。

## 2026-08-12 · T2 首页总控与主管布局（commit 90eaa7e9 / d9923cb5）

- migration 041：user_calendar_v1（日程专表 + 审计）/ user_note_v1（便签
  服务端化，关闭 ABOSV2-P2-001）；现场重启后已应用（109 表）。
- HomeCenter 服务：统一日历读取模型（用户日程 + WorkItem 截止 + 外勤任务 +
  问卷窗口）；活动日志业务投影（过滤 node.* 噪声）；进度同源聚合；
  真实容量读数；Agent 提醒；最近对象。
- API：/api/v1/home/dashboard、/calendar/events、/notes、/activity、
  /progress、/capacity、/home/agent-alerts、/home/recent（登录+CSRF）。
- 首页重建为八类真实卡片，点击直达同一对象；红测试 5 项先红后绿。
- 主管工作台：桌面 360–480 可拖拽调宽不覆盖主内容；≤1024 底部可关闭
  工作区；≤768 全屏对话；便签改服务端持久化。
- 现场验证：登录→dashboard 全段→创建日程 cal-df28d356c106/便签
  note-2873d41d81c7→刷新仍在；current-work 20 项（work_item_v2+labeling）；
  reconcile consistent=true（business_facts_checked=true）。
- 浏览器验收 5/5（截图 .eval/v3_home_1440/refresh/1280/1024/768.png，
  console 0 error）；两个观察项（UTC 显示偏移、极窄视口溢出）已修复。
- 诚实披露：浏览器 agent 窗口无法物理 resize，1440/1280 用同源 iframe
  精确断点仿真（方法与 V2 一致，已披露）；1024/768 为真实交互验证。

## 下一动作

- T3：Import Center（14 套 CSV/XLSX 模板、上传/映射/dry-run/逐行错误/
  提交/幂等/证据）+ IAM 自定义工作台 + 主数据完整 CRUD。

## 2026-08-12 · T3 Import Center + IAM 自定义 + 主数据（commit 419043d6）

- migration 042：import_batch_v1 / route_constraint_preset_v1 /
  knowledge_document_v1；ImportCenter 服务：14 套模板（CSV/XLSX 双格式，
  模板含字段说明且可 round-trip 重新解析）；上传→解析→自动映射→
  dry-run（逐行 insert/skip/conflict/error）→幂等提交（走 Domain
  Service，证据 bundle + 审计）。
- IAM：自定义角色（scope 白名单 fail-closed）+ 权限模拟器（能否/为什么）；
  主数据停用/启用 + 合并建议（规范化重名）。
- 现场 E2E：坏 fixture validation_failed（逐行错误）→修复→committed
  （uat-cust-a/b 落库，evidence+audit）。
- 测试：8 红测试绿 + 2 IAM/主数据测试；hermetic 1287 passed。

## 2026-08-12 · T4 真实 Agent Runtime（commit e2de6a7d 链）

- migration 043：agent_definition_v1（版本化 soul/prompt/tools/budget/
  approval）/ agent_asset_v1（Skill/Prompt/KB draft→发布）/
  agent_memory_v1（L0-L4 ACL）/ agent_run_v1。
- 有界工具目录 14 个；7 个 Agent（supervisor/modelops/data_steward/
  survey/analytics/fieldops/finance）seed 为 published 定义；
  health=有界探针（定义发布+事实查询+allowlist 有效）。
- Supervisor 对话优先走真实工具循环（写动作→待批准命令）；
  ABOSV3-P0-006 关闭（不再统一 ok=true）。
- 现场：7/7 healthy；8 类工具意图真实执行（进度/SKU/问卷/工作流 draft/
  缺坐标地址/识别预览/BI draft/Usage）；每次 invoke 落
  agent_run + event + usage。

## 2026-08-12 · T5 React Flow 可视化工作流（commit e7b3361c）

- @xyflow/react 画布为默认（JSON 仅高级视图）；Palette 来自 Registry；
  Inspector（wait 秒数/join 模式+quorum/agent_id/capability/loop）；
  工具栏 lint/模拟/批准/发布/新版本/测试运行；运行面板暂停/恢复/
  取消/重试。
- runtime：wait=持久化 timer（migration 044，10s 轮询恢复，重启可恢复）；
  join all/any/quorum（有界重排）；agent 节点调用指定 Agent；
  UI 坐标不参与定义 hash（migration 含 _workflow_hash strip_ui）。
- 现场 E2E：wf-701adc37a0 draft→lint→publish→run waiting_timer→
  自动点火→succeeded；浏览器验收 6/6（.eval/v3_workflow_canvas/
  inspector.png）。

## 2026-08-12 · T6 空白问卷 Builder（commit 37a45c53）

- 题型库（单选/多选/填空+数字/日期/打分/矩阵/拍照/说明）+ 画布
  （排序/复制/删除）+ 属性面板 + 跳题编辑 + 预览（桌面/移动）；
  后端新增 matrix/description 题型（lint fail-closed、逐行必填、
  逐行计分）；PUT draft 更新端点。
- 现场：svy-1a904ba6ba 空白→lint→发布→分配→矩阵响应→提交 score=5.0。

## 2026-08-12 · T7 地址/地理编码/地图/路线（commit 5c634489）

- ProviderGeocoder SPI（amap/tencent，无 Key 诚实降级+配置指引，
  不写假坐标）；手工/导入坐标确认（source 标注）；RouteSolver SPI
  （最近邻启发式诚实标注 + OR-Tools Adapter 预留）；migration 045
  route_plan 复合主键（plan_id,version）支持人工调整新版本；
  maplibre-gl 地图（可配置瓦片源，无瓦片诚实降级 SVG 散点）。
- 现场：geocode degraded→手工坐标 verified→规划 solver 标注→
  adjust v2→map-data points/fences/plans。

## 2026-08-12 · T8 V4 best 受控切换 + 实验 profile（commit 1fd048b8）

- 制品定位：best/sku_v4_best.pt sha256 84bf9936…（133,135,871 B）。
- prod_v4_best_r1 bundle 构建（detector=V4 best；classifier/registry/
  thresholds 与 v5 bundle 同 SHA 零变量）；shadow 对比 5 张失败样本：
  v4 在 prod v5 零检出的 2 张上检出 2/3 件，无错误（报告
  .eval/shadow_v4_best_report.json）。
- StandardProfileService：原子 CURRENT 切换 + CURRENT.previous 备份 +
  回滚 + hash fail-closed + 审计；制品状态 SHADOW_PENDING_SWITCH→
  CANDIDATE 驱动 v4_best_standard profile 启用。
- 实验 profile：exp_classifier_only（明示需 detector 组合）、
  exp_v4_detector_smoke、exp_m3_grouped_classifier——一律诚实 blocker。
- 现场：switch→rollback→switch 三次 API 验证；8091 重载
  bundle:prod_v4_best_r1；真实识别 task 83c5500a sku_count=6（profile
  v4_best_standard enabled）。
- 训练控制面：dry-run 对不可训练快照正确 fail-closed（gold=0 诚实）；
  四 Lane/Label Studio/数据集页面可达；本轮未启动长训练。

## 2026-08-12 · T9 BI 工作台（commit d64a436a）

- 受限公式 DSL（AST 白名单：仅注册指标引用+四则运算，禁任意 SQL/
  代码/字符串，除零保护，嵌套≤4）；指标下钻到 usage/survey/
  recognition 事实行；数据产品+血缘端点；migration 046
  bi_dashboard_v1 + CRUD；ECharts BIWorkbench 画布。
- 现场：uat.photo_x2 计算指标创建+求值；任意代码 409；
  dash-23362a611c 持久化；11 红测试绿。

## 2026-08-12 · T10 客户 Usage 工作台（commit bbeaa643）

- usage/summary（单位/日期/异常规则 day>3×mean 标注口径/未归属）、
  rows（run 状态+证据 bundle 下钻）、budgets（项目预算，计数口径
  标注）、export.csv；finance.read 作用域强制（跨客户 403）。
- 现场：uat-cust-a 汇总/明细/CSV 验证；4 红测试绿。

## 2026-08-12 · T11 帮助与系统管理拆分（commit 7fd64b66）

- 新 help 模块（全员）：可搜索角色/任务手册、导入模板说明（实时）、
  API Explorer、排障；system 更名“系统管理（仅管理员）”，导航
  按 me.role 过滤；integration ok=true（36 路由）。

## 2026-08-12 · T12 UAT 机器预演 + 收口

- scripts/v3_uat_rehearsal.py：05-UAT 七段预演 23/23 通过（报告
  .eval/v3_uat_rehearsal_report.json，全部来自 API/DB 不可手填）。
- 服务恢复：./bin/abos restart 四服务全部 UP；重启后 reconcile
  consistent=true（business_facts_checked）；CURRENT 保持
  prod_v4_best_r1；SQLite integrity ok。
- 安全快检：未登录 401；无 CSRF 写 403；跨客户 403（测试覆盖）。
- 测试基线：hermetic 1328 passed + host_mps 6 passed；前端 typecheck/
  build 通过。
- 浏览器巡检：9 页（home/import/studio/agents/survey/geo/analytics/
  finance/help）复检全过，console 0 error（首轮因会话缓存旧 JS 误报，
  强刷后复检通过；截图 .eval/v3_sweep_*.png）。
- 诚实披露：地理编码/地图瓦片未配置 Key（degraded，配置指引已内置）；
  训练长训练本轮未启动（红线）；浏览器视口部分用 CSS zoom/iframe 仿真
  （物理窗口受限，已披露）。

## 2026-08-12 · 任务书建立

- Codex 独立审查撤销旧 `READY_FOR_USER_ACCEPTANCE` 判断；
- 重新打开工作流投影、任务多事实源、成功 run 残留 error、BI 版本重复四项数据一致性问题；
- 纳入用户现场体验的首页、主管布局、数据资产、问卷、位置、识别训练、BI、Workflow/Agent、IAM、主数据、Usage、文档和全局导入 14 项问题；
- 决定以 React Flow + ABOS 原生 Runtime 为主，Node-RED 仅作可选 Adapter；
- 当前 Gate：`OPERATIONAL_WORKBENCH_V3_NOT_STARTED`；
- 本次只生成任务文档，未修改代码、数据库、服务或模型。

