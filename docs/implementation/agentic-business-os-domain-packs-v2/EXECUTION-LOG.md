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

## 2026-08-11 · Phase E 完成（commit fde1b4ae），Gate G5 通过

- migration 036：survey_definition_v1（survey_id+version，发布不可原地改）/
  survey_assignment_v1 / survey_response_v1（评分版本化）/
  survey_answer_correction_v1（append-only 触发器）/ survey_media_v1
  （位置/时间/设备/质量证据 + suggestion 状态机）。
- SurveyService：样板模板含全部首批题型（单选/多选/填空/打分/拍照，
  预留类型 lint 报错不伪造）；跳题 DAG lint（循环/不可达/冲突/缺失默认
  分支）；visible_questions 按答案求值；分配绑定已发布版本（新版本草稿
  不影响进行中的填写）；提交前必填校验（含拍照最少张数）。
- 拍照→识别 suggestion：经统一 Command Gateway（真实 run/evidence/usage），
  pending→人工 accept/reject/modify 才成 final；反馈事件
  survey.suggestion.reviewed 恒带 training_truth=false（不自动成训练真值）。
- 后台修正：只走 correction 通道（原值/新值/原因/操作者/批准人）+
  评分重算 score_version+1；已提交响应禁止绕过修正直接改。
- 实跑 G5 E2E：svy-c481cfc33d（lint [] → published → v2 draft）→
  asg-5094bf3e6f02（demo-cust-a）→ rsp-0a90b4f6b56d；真实货架照片
  med-35f34f603e42（lat/lng/设备/质量证据）→ 识别 run-72dc41349c3c +
  evidence_bundle → 人工接受 → 提交评分 13.0（v1，sum 公式，含输入证据）
  → 修正（原因+批准人）→ 15.0（v2）→ 报表输入 submitted=1 avg=15 max_sv=2。
- 浏览器验收 5/5（截图 .eval/abosv2_survey_*）；小改进项：报表下拉同名
  问卷多版本未标注版本号（记录，不阻塞 G5）。
- 契约变更：test_module_manifest_v2 的 survey planned→live 断言更新
  （真实后端已存在，诚实状态）。
- 全量 hermetic：1230 passed, 1 skipped, 6 deselected。

## 下一动作

- Phase F：BI 语义层 + 异常追问闭环（G6）→ 位置外勤（G7）→ 财务（G8）。

## 2026-08-12 · Phase F 完成（commit c0be4098），Gate G6/G7/G8 通过

### G6 · BI 纵向切片
- migration 037：bi_metric_v1 / bi_report_spec_v1（版本化）/ bi_anomaly_v1 /
  bi_followup_answer_v1。注册制指标 6 个（recognition.photos/compute_ms/tasks、
  survey.submitted/avg_score、workflow.runs），只求值注册定义（未注册 fail-closed，
  禁任意 SQL）。
- ReportSpec：draft→approved→published（现场 409 拦截未批准发布）；评估实时
  + project 维度拆分；Analytics Agent NL→仅映射注册指标的 draft。
- 异常闭环实跑：survey.avg_score lt 20 命中（observed=15）→ 追问 WorkItem
  work-b9c6e060fb13 → 回答 → 异常 resolved + 工作项 done + 报表刷新 v2
  （draft，旧 v1 published 保留不覆盖）。

### G7 · 位置与外勤纵向切片
- migration 038：geo_address_v1 / geo_employee_v1 / field_task_v1 /
  route_plan_v1 / geofence_v1 / geofence_event_v1 / field_visit_evidence_v1 /
  travel_cost_v1。
- GeocoderAdapter 候选+置信度；**低置信度地址不自动派发**（现场 409：
  “低置信度地址未人工确认，不得自动派发”）；人工确认后规划/派发。
- VRP MVP：最近邻 + max_km 约束 + 多项目硬隔离（未分配原因留痕）；
  成本 = km × 单价可解释。MapProviderAdapter 诚实 blocked（无瓦片回退列表）。
- 围栏到店：半径+精度校验（现场：围栏外 5560m>200m 拒绝；精度 200m 拒绝）；
  门头必拍（缺证据完成 409）；自拍默认关闭（人脸比对默认不自动触发，现场 409）。
- 实跑全链：addr-6e4347a42350 → ft-f6b4b52ab4eb → plan（1 站 10.472 km）→
  dispatched → fence-f12e776b683a enter → 门头证据 fev-f35617de4789 →
  completed → 差旅费 20.94 元（10.472 km × 2.0）。

### G8 · 财务纵向切片
- migration 039：fin_rate_card_v1（版本化）/ fin_contract_v1 / fin_invoice_v1 /
  fin_invoice_line_v1 / fin_adjustment_v1（append-only 触发器）。
- 账单严格从 immutable usage_event_v2 生成（D-008）；行下钻 usage_id/run_id/
  work_id/node/source_evidence；同期间幂等（已计费 usage 跳过、月订阅只计一次）；
  开票绑定 rate card 版本，新价格不改已开票金额；结算后禁止调整。
- 实跑：ct-422cc8c1f4a6（hybrid）→ inv-02275a438bb9：subscription 100 +
  recognition_photo 2×0.5 + model_compute_ms 166.57×0.001 = 101.1666，
  下钻到 G4 真实 run-86150aa544…/recognition_task:2287e8e…；regenerate 空行
  （幂等）；开票 → 折扣 -10 → net 91.1666；rate card v2（涨价）后已开票
  total 不变（v1）；settle 后调整 409。
- 前端：BI 三页签 / 外勤三页签 / 财务两页签（全部真实 API）；planned 插槽
  全部被真实路由取代；浏览器验收 8 张截图（围栏列表区块按审查意见补齐）。
- 测试：G6 5 项 + G7 5 项 + G8 6 项红转绿；全量 hermetic 1246 passed。
- 声明：未启动训练；production 未切换；用户资产未触碰。

## 剩余（T9/Z）

- Z-1：Manifest/Capability/UI slot/节点库/tool registry/OpenAPI 全量交叉验证
  （当前已部分：节点库同源、manifest 契约测试）；
- Z-2：Workflow/IAM/Survey/Analytics/FieldOps/Finance 六个 Domain Agent
  独立身份/allowlist/预算/记忆 ACL（当前 Supervisor+Workflow Agent draft 受控）；
- 最终验证套件：host_mps 分层、安全（越权/CSRF/SSRF/注入/rate limit）、
  性能 p50/p95、冷启动、四手册更新（USER-HANDBOOK 需按角色重写操作流）。

## 2026-08-12 · T9 系统级收口完成（commit db1692a4）

### Z-1 集成契约交叉验证（P1-002/P1-003 关闭）
- `src/platform/integration.py` + `GET /api/v1/platform/integration`：
  agents↔清单、scopes↔IAM、commands↔Gateway/平台命令注册表、导航路由↔
  UI 组件注册表、api_prefix↔OpenAPI 五环交叉验证，缺失 fail-closed。
- 现场首跑即捕获 2 个真实漂移（vision/system api_prefix）→ 修复后 ok=true
  （12 agents / 34 UI 路由 / 190 OpenAPI 路径 / 33 命令）。
- ModuleUIRegistry（web/src/platform/ui_registry.tsx）取代 App 手写模块路由
  （P1-003）；前端↔后端镜像↔目录三方一致性由 14 项契约测试强制。
- Manifest 投影补 commands/queries/events（P1-002）。

### Z-2 六个 Domain Agent
- workflow/iam/survey/analytics/fieldops/finance_agent 注册（独立身份、
  capability allowlist 在 GRANTABLE_SCOPES 白名单内、数据 scope、approval
  规则：human_approval_for_publish / human_final_answer_required /
  face_compare_requires_explicit_consent / usage_only_billing）。
- 诚实披露：Agent 执行为 manifest/契约层身份化；独立对话运行时仍由
  Supervisor 承载（P1-004 未完全关闭，列入残余）。

### Z-3 最终验证
- hermetic：1260 passed, 1 skipped, 6 deselected；host_mps：6 passed（单独执行）。
- SQLite integrity ok；迁移幂等至 039（重启自动应用）；reconcile consistent=true。
- 安全：无 session 读/写 401；无 CSRF 写 403；有 CSRF 200；identity 无敏感泄漏。
  rate limit 未实现（诚实记录为残余项）。
- 性能：workitems p50=4.6ms/p95=4.8ms；recognition list p95=1.1ms；
  reconcile p95=1.3ms（本机 60 次采样）。
- 服务：四服务 UP；冷启动经 ./bin/abos start 幂等；production 未切换。

### Z-4 四手册
- USER-HANDBOOK v3：按五个角色（平台管理员/客户管理员/外勤/分析师/财务）
  给出登录→完成任务操作流；OPERATOR-RUNBOOK 增补对账/集成体检/端点表；
  MODULE-AGENT-DEV-GUIDE 增补 ABOSV2 接入契约；CODEX-HANDBOOK 追加接续节。

### 残余项（诚实记录，不阻塞用户验收评估）
- P1-004：Supervisor 工具化规划运行时（六 Agent 独立对话运行时）；
- P2-001/002/003：便签服务端化、event SSE、profile 信息架构；
- rate limit 未实现；地图瓦片供应商未选（blocked 诚实展示）。
