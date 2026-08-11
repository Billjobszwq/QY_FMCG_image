# EXECUTION-LOG · Domain Packs V2（append-only）

> 任务书：`docs/implementation/agentic-business-os-domain-packs-v2/AGENT-EXECUTION-PROMPT.md`
> 时间均为本机 Asia/Shanghai。本文件只追加，不回改历史条目。

## 2026-08-11 · T0 现场冻结与安全基线

- 阅读完成：GLOBAL_AGENT_ROUTING.md、CODEX-PROJECT-HANDBOOK.md、docs/README.md、
  USER-HANDBOOK.md、OPERATOR-RUNBOOK.md、MODULE-AGENT-DEV-GUIDE.md、
  agentic-business-os-workbench-v1/（00–07 + README/STATUS/ISSUES/ACCEPTANCE）、
  project-logic-chain-v3/（STATUS/SOURCE-OF-TRUTH/CURRENT-LOGIC-CHAIN）、
  agentic-business-os-domain-packs-v2/ 全部文件。
- Git：branch `feat/nextgen-training-cycle-v2`，HEAD `d00953ad`
  （`docs: define continuous workflow and domain packs v2`，前一业务提交 `e5c4236d`）。
- worktree：仅主 worktree，无附加 worktree。tracked 工作树干净。
- 未跟踪资产（全部保护，不删不覆盖不移动不暂存）：`.datasets_nextgen/*`、
  `.micro_gold_v1/`、`.micro_gold_v2/`、`.micro_gold_v2_attempt1/`、`.quality/`、
  `.sam_checkpoints/`、`.sam_runs/`、`.superpowers/`、`adapter_config.json`、
  `cropped_images/`、`reports/nextgen_v2/*`。
- 服务：`./bin/abos status` → recognize/monitor/label_studio/app 全部 UP
  （recognize pid=59310 本脚本管理）；看门狗未运行。
- 训练进程：无（ps 核验仅有 8092 monitor 与 8301 yolo_backend 历史进程）。
- DB：`.platform/platform.sqlite` integrity_check=ok；63 张表；最新迁移
  `030_recognition_task_profile_contract`（028 state_projections_v2、029 profile_def_v1）。
- production：`.models/bundles/CURRENT.json` = `prod_20260805_v5_r1`（本轮不切换）。
- 运行事实快照（后续对账基准）：识别任务 11、Graph Runs 8、Agent Commands 5、
  Usage Event 1（来自 v2 审计文档，进入 Phase A 前将实时复核）。
- 声明：未 merge/push/deploy；未启动训练；未切换 production；未触碰用户资产。

## 下一动作

- Phase A-1：实时复现 ABOSV2-P0-001（主页旧 250 复活），写红测试。

## 2026-08-11 · A-1 / A-2 后端+前端完成并实跱验证

- A-1（commit `4af64f2d`）：migration 031 `work_item_supersession_v1`（append-only）；
  `/api/v1/workitems?projection=current|history|all`；幂等种子 rq_v2 → ls22_micro_gold_v2，
  legacy dry-run 以 `--dataset/--budget-minutes` 为判据。现场对账：current=2（labeling），
  superseded=254 入 history（human_review 250 + training 4）。红测试 7 项先红后绿；
  旧 test_review_status_source 两用例改用 rq_v3（契约变更已记 D-010）。
- A-2（commit `79b3a534`）：migration 032 `goal_draft_v1`；goals API（create/list/get/confirm，
  登录+CSRF，乐观锁）；confirm 调 Supervisor 形成计划/命令留痕（message/command_previews/trace）。
  前端：Home 先落服务端再携 goal_id 进主管；Supervisor 拉回 goal 文本，发送后 confirm；
  刷新可从 open goals 恢复。实跱 E2E：create(200) → open+1 → confirm(200, trace, 1 preview) → open-1。
- 8400 精确重启（仅 app，PID 文件管理），迁移 031/032 已应用；recognize/LS/monitor 未动。
- typecheck/build 通过；前端 dist 已重建。

## 下一动作

- A-3：识别任务统一详情（task/trace/tier/profile/错误/证据/usage/下一动作）。

## 2026-08-11 · Phase A 全部关闭（commit 15a39325），Gate G1 通过

- A-3：`GET /api/v1/recognition/tasks/{task_id}` 统一详情（契约/输入输出/错误/
  时间线/证据/usage/关联/下一动作）；未接入 Phase B 的区块诚实标注 note。
  Vision.tsx 任务行可点击（键盘可达）→ DetailDrawer（新共享组件，Esc 关闭）。
- A-4：Supervisor 默认打开阈值 1024→1440（1024–1439 收起为 ✦，打开为不透明
  临时抽屉）；一级导航 title/aria-label + 768 保留文字标签（132px 栏）；
  ≤1024 表格转 card（thead 隐藏 + data-label 列名）。
- A-5：fast/high/extreme 档位禁用并标注“未启用（无真实算力/SLA/价格差异）”
  + ABOSV2-P0-004 说明；standard 为唯一可用。
- A-6：跨层连续性测试 test_abos_v2_continuity.py：goal→supervisor 预览→
  会话落命令→批准→组合根钩子创建识别任务→详情 trace/profile/source 一致→
  重复批准 409→current 投影干净；拒绝命令不产生任务。另 3 条 UI 契约守卫。
- 浏览器四视口验收（Browser Agent 实机操作，iframe 精确断点法，方法已披露）：
  8/8 通过；截图 .eval/abosv2_home_1440.png / abosv2_goal_to_supervisor_1440.png /
  abosv2_goal_refresh_1440.png / abosv2_task_detail_1440.png /
  abosv2_tier_honest_1440.png / abosv2_home_1024.png / abosv2_nav_768.png /
  abosv2_tasks_768.png；console 0 错误。
- 浏览器验收发现回归 ABOSV2-P1-008：styles.css 旧兼容规则 `.topbar{display:none}`
  隐藏新壳顶栏 → 已删除并浏览器复验（.eval/abosv2_topbar_fix_1440.png）。
- 契约变更：test_end_to_end_review_chain 阶段 7/9 改用 projection=all 对照
  （rq_v2 supersession，D-010）；test_css_variables_all_defined 因 --paper
  未定义修复为 --surface。
- 全量 hermetic 回归：1191 passed, 1 skipped, 6 deselected（修复 3 个回归后
  目标子集 57 项复跑全绿）；typecheck/build 通过。

## 下一动作

- Phase B：统一 Work/Event/Usage Foundation（migration 033+）、Command Gateway、
  Outbox、投影重建对账、识别全链实跑报告 ID。

## 2026-08-11 · Phase B 完成（commit 13106320），Gate G2 通过

- migration 033：business_run_v1 / work_item_v2 / event_envelope_v1 /
  usage_event_v2 / evidence_bundle_v1 / outbox_v1；事件/用量/证据 append-only
  触发器；recognition_task 增加 run_id/work_id/correlation_id 回链。
- CommandGateway（src/platform/control_plane.py）：Web/API/Agent 共用命令入口
  POST /api/v1/commands；run 状态机（queued/running/succeeded/failed/cancelled，
  failed 只能经 retry 事件恢复，不得直接成功）；Transactional Outbox（事件+outbox
  同事务，幂等键去重）；retry/cancel 端点；投影 GET /api/v1/control/projection；
  对账 GET /api/v1/control/reconcile。
- 红测试 7 项先红后绿（test_abos_v2_control_plane.py）：schema 全字段、
  append-only、全链 ID 一致、幂等、失败→retry 恢复、cancel 状态机、API 同源。
- 实跑全链（B-6，真实 8091 production cascade，真实货架照片只读引用）：
  goal `goal-7bdbc18c2613` → run `run-827e9e90f63f4efb` / work
  `work-7482b3762cc24bd3` / corr `corr-9cb71622b785` → task
  `b85d64704f33b8a490fba48161dee859` / trace `tr-d0a89eac757f` /
  evidence `evid-2737faadd9354f19`；usage=recognition_photo×1 +
  model_compute_ms×58.61；timeline=created/completed/command.accepted/
  node.started/node.completed/run.succeeded；sku_count=4；
  reconcile consistent=true（hash e80ea04d…，event_count=11，outbox 全 dispatched）。
- 失败与恢复（B-7）：run `run-637bcd55272842c5` 因 adapter 未装配失败
  （错误留在同一 run 与事件链）→ 修复后 POST /commands/{run}/retry 补交输入
  → 同一 run succeeded，task `7807364dfc96f5cf297a3c4f780a070e`。
- 识别任务详情 API 已消费控制平面：relations.run_id/work_id、usage events、
  evidence refs、时间线融合 run 事件（不再诚实空）。
- 全量 hermetic 回归：1201 passed, 1 skipped, 6 deselected。
- 声明：未启动训练；production 未切换；用户资产只读引用（blob 未改动）。

## 下一动作

- Phase C：Workflow Studio MVP（canonical WorkflowDefinition/节点类型/
  生命周期/runtime checkpoint/Studio UI/Executor Adapter SPI）。

## 2026-08-11 · Phase C 完成（commit aa7ba378），Gate G3 通过

- migration 034：workflow_definition_v1（definition_id+version 主键，发布不可
  原地改）/ workflow_node_execution_v1（checkpoint）/ workflow_dead_letter_v1
  （append-only）。run 状态机扩展 paused / waiting_human。
- WorkflowService（src/platform/workflow.py）：
  - 生命周期 draft→linted→simulated→approved→published→deprecated；
    publish 必须先人工 approve（409 现场验证两次拦截）；
  - lint：未知 capability fail-closed、不可达节点、缺 trigger/end、
    loop 有界、subflow 必须已发布、connector 许可预警（warn）；
  - runtime：15 节点类型；command 节点经 Command Gateway（parent_run_id/
    correlation 贯通）；human_approval 生成 approval WorkItem 并等待，
    批准/拒绝是节点事件；checkpoint 每节点留痕；失败按 policy.retry
    自动重试，耗尽进死信 + run failed；pause/resume/cancel/retry 端点；
  - Workflow Agent：NL→draft 仅预览/模拟，发布必须人工（测试守卫）。
- WorkflowExecutorAdapter SPI：Native 完整；N8n/Dify adapter available()=False，
  start() 抛 WorkflowExecutorBlocked（许可未确认，诚实 blocked，无第三方代码）。
- 节点库：GET /api/v1/workflows/node-library 来自 Capability Registry +
  Gateway SUPPORTED_COMMANDS（fail-closed）；现场 15 类型 + 4 命令/模型节点。
- Studio 七页签（module_catalog workflow v1.1.0）：搭建/模板库/运行中心/
  待办与批准/连接器/Agent 与模型/证据与用量；浏览器验证 6/6 通过
  （截图通道 DevTools 超时，以 DOM/a11y 断言为准，已如实披露）。
- 实跑首批模板（G3 要求“只保存画布 JSON 不算完成”）：
  模板实例化 wf-d63bc03b2f → lint [] → simulate succeeded → approve →
  publish（published_at 非空）→ 真实货架照片运行：
  run-50adc9a8f9a6 succeeded；checkpoints start/recognize/check/end 全
  succeeded；子 run-912429a999484a9d（parent=wf run）→ task
  9c35e188f110a5ae0bbf6c07b0b808b2 / trace tr-d6f5c8e0e72a /
  evidence evid-732bb8cc9d484347；usage recognition_photo×1 +
  model_compute_ms×141.31；sku_count=1；reconcile consistent=true
  （17 事件全 dispatched）。
- 失败→人工批准→恢复/拒绝路径由 test_abos_v2_workflow.py 覆盖（waiting_human、
  approval WorkItem、denied→cancelled、approved→succeeded、connector→死信）。
- 全量 hermetic：1213 passed, 1 skipped, 6 deselected。

## 下一动作

- Phase D：IAM 与主数据（tenant/customer/project scope、角色/permission
  bundle、批准矩阵/审计；SKU/客户/项目库；两测试客户隔离证明）。

## 2026-08-11 · Phase D 完成（commit 55e71271），Gate G4 通过

- migration 035：iam_principal_v1（user/service_account/agent）/ iam_role_v1
  （11 内置角色）/ iam_permission_bundle_v1（13 版本化 scope）/
  iam_role_permission_v1 / iam_membership_v1（tenant/customer/project 作用域）/
  iam_audit_event_v1（append-only）/ iam_approval_matrix_v1 +
  md_customer_v1 / md_project_v1 / md_sku_v1 / md_sku_alias_v1。
- IAMService：seed 幂等；账号开设（agent 独立身份不得口令登录）；授权
  fail-closed（scope + customer/project 作用域）；批准矩阵（矩阵未收录动作
  非平台角色一律拒绝）；审计 append-only。
- MasterDataService：客户库（is_test_fixture 显式标记、保留策略）/项目库
  （必须挂客户）/SKU 库（canonical_name 身份、别名、客户显示名、有效期、
  新旧包装 supersede 链，历史不删）。
- gateway usage 写入携带 customer/project 作用域（隔离计费依据）。
- 现场 G4 隔离证明（两个 test fixture 客户 demo-cust-a/b）：
  各建项目/用户/agent 身份 + 各跑一条真实识别（task 2287e8e5… /
  aeb098c6…）；alice 登录只见 cust-a（fixture 标记 True）；
  overview cust-b → 403；projects cust-b → 403；
  agent_alice agent.query cust-a=True / cust-b=False；
  approval-check production.switch alice=False；
  usage_event_v2 按客户各 2 行无空作用域行。
- 浏览器验收：首轮发现 3 个真实缺陷（iamGet/iamPost 双斜杠 404、admin
  平台角色未传入列表过滤、列表组件缺错误分支）→ 修复后复验 5/5 通过
  （截图 .eval/abosv2_iam_fix_*）。
- 全量 hermetic：1222 passed, 1 skipped, 6 deselected。
- 声明：未启动训练；production 未切换；用户资产未触碰。

## 下一动作

- Phase E：问卷纵向切片（题型/版本/跳题 DAG/评分/发布/分配/填写/
  后台修正事件/拍照题证据 + 识别 suggestion→人工 final）。
