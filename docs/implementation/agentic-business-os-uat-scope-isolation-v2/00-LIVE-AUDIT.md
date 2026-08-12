# 00-LIVE-AUDIT（只读现场审计）· UAT Scope Isolation V2

> 审计时间：2026-08-12（UTC+8 20:1x 起），全部为只读命令产出。
> 依据：独立审查纠偏指令第一节"开始前必须现场核对"。

## 1. Git 现场

- HEAD：`9f3554e7`（与预期一致）
- 分支：`feat/nextgen-training-cycle-v2`（与预期一致）
- worktree：tracked 干净；未跟踪资产为数据/模型/快照目录
  （`.datasets_nextgen/`、`.micro_gold_*`、`.sam_*`、`.quality/` 等），
  按红线不动。
- 最近 30 个 commits 已通读（链见 EXECUTION-LOG T0 段），关键脉络：
  uatcc(T0..T8) → ufc(T0..T10) → 本轮 scope-isolation-v2。

## 2. 服务现场（`./bin/abos status`）

| 端口 | 服务 | 状态 |
|---|---|---|
| 8091 | recognize（级联识别） | UP |
| 8092 | monitor | UP |
| 8300 | Label Studio | UP |
| 8400 | 统一 API + Web Shell | UP |

- 训练进程：无（`abos status` 输出"训练进程：无"）。
- 看门狗：未运行。

## 3. 模型现场

- `.models/bundles/CURRENT.json` → `prod_v4_best_r1`（与预期一致）。
- detector.pt SHA256：
  `84bf9936189377007898c942a3c9a87f605d52c2afe01b7db2a66269e5554975`（与预期一致）。

## 4. 数据库现场

- 库：`.platform/platform.sqlite`（WAL）。
- `PRAGMA integrity_check` = ok。
- migrations：50 条（最新 `050_anomaly_followup`），带 sha256 篡改校验。
- 备份（本轮迁移前）：
  `.platform/backups/platform_pre_scope_v2_20260812202343.sqlite`
  - integrity_check = ok
  - sha256 = `7d65b1ced2ddefd2fa2cbad77aac9986c5e416ad7edddde1ce904551e783a41c`

### 4.1 fixture/operational 统计（before）

| 表/口径 | 数值 | 说明 |
|---|---|---|
| business_run_v1 | operational=65，uat_fixture=79 | — |
| fixture runs 的 test_run_id | **0/79** | P1-001 确认（指令口径 0/27，实际库中全部 fixture run 均缺失） |
| md_customer_v1 | uat_fixture=20 | 全部 fixture 客户 |
| work_item_v2 | operational/current=72，uat_fixture/history=88 | WorkItem 域已收敛 |
| field_task_v1 | 总 14，未完成 13；归属 fixture 客户 **14/14** | 无 data_scope 列 |
| survey_assignment_v1 | 总 15，active 2；归属 fixture 客户 **14/15** | 无 data_scope 列 |
| md_project_v1 | 总 14；归属 fixture 客户 **14/14** | 无 data_scope 列 |
| user_calendar_v1 | 总 5；UAT 痕迹 **3/5** | 无 data_scope 列 |
| workflow_definition_v1 | 总 46；名称含 UAT **40** | 无 data_scope 列 |
| bi_report_spec_v1 | 总 20；名称含 UAT **10** | 无 data_scope 列 |
| recognition_task | 40 | 无 data_scope 列 |
| usage_event_v2 | 140 | 无 data_scope 列 |
| evidence_bundle_v1 | 132 | 无 data_scope 列 |
| bi_anomaly_v1 | 4 | — |
| workflow_node_execution_v1 | 235 | 无 data_scope 列 |
| workflow_timer_v1 | 19 | — |
| workflow_branch_v1 | 52 | — |
| agent_run_v1 | 90（business_run agent.invoke=78） | — |

结论：除 customer/business_run/work_item 外，所有 Domain 表
**没有结构化 scope 字段**，与指令 P0-001/P1-001 完全吻合。

## 5. 首页污染量化（before，只读 SQL）

`HomeCenterService.calendar_events()` 直读四源、零过滤：

- 外勤任务（status 未终态）13 条全部可见 → 其中 14 条 fixture 归属；
- 问卷分配 active 2 条可见（fixture 归属 14 条在历史窗口）；
- 用户日程 5 条全量可见（3 条 UAT 痕迹）；
- `recent_objects()` 直读 6 张表无 scope 过滤：40/46 工作流、10/20 BI
  报表、14/14 fixture 项目全部进"最近对象"；
- `activity()` 无 scope 过滤（事件表含全部 UAT run 事件）。

首页当前 fixture 污染截图：见 `.eval/uat_scope_v2/before/`
（T0 内由浏览器工具补充；本文件先固化 SQL 证据）。

## 6. Gate 漏检证据（before）

- `.eval/v3_uat_v3/gate.json` = `READY_FOR_REAL_DATA_UAT`（20 检查全绿）。
- 漏检 1：`operational_uat_residue_zero` 只统计
  `work_item_v2.data_scope='uat_fixture' AND visibility='current'`
  （见 `src/platform/test_data.py:operational_residue`），
  不覆盖 field_task/survey/calendar/workflow/BI/agent/recognition。
- 漏检 2：该检查 evidence 显示 `"None"`（Python falsy/or 逻辑），
  违反"0 必须显示为 0"（P2-001 复现）。
- 漏检 3：`source_commit=6664022f`，而 HEAD=`9f3554e7`，
  Gate 与代码状态脱钩（P1-004 复现）。
- 漏检 4：浏览器检查只有 `browser_screenshots_exist` +
  `browser_console_clean`，无对象 ID/文本断言（P1-003 复现）。

## 7. 前端 bundle（before）

- `web/dist/assets/index-D4GiXudI.js` = 2,712,322 B（≈2.69 MB），
  css 119,916 B；单 bundle、无路由级拆包（P2-002 复现）。
- `web/vite.config.ts` 无 manualChunks/lazy 配置。

## 8. 代码根因定位（只读 grep/read 结论）

1. `src/platform/test_data.py`：TestDataService 只处理
   customer/business_run/work_item 三表；`archive_namespace` 回退到
   `customer_id LIKE namespace%`（P1-002 复现）。
2. `src/platform/home_center.py`：calendar_events/activity/
   recent_objects/agent_alerts 无 scope 过滤。
3. `src/platform/gate_evaluator.py` v2.0.0：检查面窄、不绑定
   HEAD/代码树 hash、residue evidence 可为 None。
4. `src/platform/control_plane.py` / `agents/runtime.py` /
   `workflow.py`：创建 BusinessRun/Work 时无 scope 解析与继承，
   无 fail-closed 校验。
5. `TestDataService` 类名触发 pytest collection warning（P2-003）。

## 9. 判定

- 当前 `READY_FOR_REAL_DATA_UAT` **不能作为真实数据 UAT 放行依据**。
- 本轮 Gate 立即降级为 `BLOCKED_BY_UAT_FIXTURE_PROJECTION`
  （投影写入 `.eval/uat_scope_v2/gate.json`，旧 gate.json 原样保留）。
