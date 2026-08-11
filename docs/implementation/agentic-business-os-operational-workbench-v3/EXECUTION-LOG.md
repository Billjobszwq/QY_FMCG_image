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

## 2026-08-12 · 任务书建立

- Codex 独立审查撤销旧 `READY_FOR_USER_ACCEPTANCE` 判断；
- 重新打开工作流投影、任务多事实源、成功 run 残留 error、BI 版本重复四项数据一致性问题；
- 纳入用户现场体验的首页、主管布局、数据资产、问卷、位置、识别训练、BI、Workflow/Agent、IAM、主数据、Usage、文档和全局导入 14 项问题；
- 决定以 React Flow + ABOS 原生 Runtime 为主，Node-RED 仅作可选 Adapter；
- 当前 Gate：`OPERATIONAL_WORKBENCH_V3_NOT_STARTED`；
- 本次只生成任务文档，未修改代码、数据库、服务或模型。

