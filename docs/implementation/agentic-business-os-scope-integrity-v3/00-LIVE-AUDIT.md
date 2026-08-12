# 00-LIVE-AUDIT · Scope Integrity V3（独立只读审计）

> 审计时间：2026-08-12（UTC+8 22:3x），全部为只读命令/只读 SQL 连接
> （`mode=ro`）产出。不信任旧报告：SI2（scope-isolation-v2）声称的
> READY_FOR_REAL_DATA_UAT 经本审计确认为**假阳性**。

## 1. Git / 服务 / 模型现场

- HEAD：`eb19425f`，分支：`feat/nextgen-training-cycle-v2`（与指令一致）
- 服务：8091 recognize UP、8092 monitor UP、8300 Label Studio UP、
  8400 app UP（`./bin/abos status`）；训练进程：无；看门狗：未运行
- `.models/bundles/CURRENT.json` = `prod_v4_best_r1`（未切换）
- worktree：tracked 干净；未跟踪资产（.datasets_nextgen/.micro_gold_*
  等）按红线不动

## 2. 数据库与备份

- 库：`.platform/platform.sqlite`（WAL）；`PRAGMA integrity_check`=ok
- 本轮备份：`.platform/backups/platform_pre_scope_v3_20260812T224724.sqlite`
  - SQLite backup API 生成；备份前后双向 integrity_check = ok
  - sha256 = `753a809362bd9b54979ce2e38d2d9c9d5e8b8d2196ff2a4f02b321ad671d15e4`

## 3. 独立 SQL 审计（scripts/scope_audit_v3.py，effective scope 口径）

证据：`.eval/scope_v3/before/before_audit.json`

| # | 指令项 | 数值 | 与指令基线 |
|---|---|---|---|
| 1 | fixture response → operational survey_media | **24** | ≈24 ✓ |
| 2 | fixture Run → operational WorkItem | **8** | ≈8 ✓ |
| 3 | fixture Run → operational recognition_task | **5** | ≈5 ✓ |
| 4 | fixture Agent → operational BI draft | **5**（严格因果口径）/11（时间窗宽口径） | ≈5 ✓ |
| 5 | fixture/测试客户下失败 Agent Run/Work/Usage operational | **5** | ≈5 ✓ |
| 6 | fixture Run → operational Usage | **89** | ≈80 ✓（含 9 条客户链） |
| 7 | is_test_fixture=1 且 data_scope=operational 客户 | **1**（uatv4_20260812212321_xi2clv_cust） | ≈1 ✓ |
| 8 | terminal Run 下 non-terminal workflow node | **39** | ≈39 ✓ |
| 19 | UAT V4 report.json ids | **{}（0 个）** | 空 ✓ |

补充口径：work_item_v2 current+UAT 标题 = 23；survey definition
父链 fixture = 2；fin_invoice 覆盖 fixture usage 客户 = 2。

第 4 项说明：`bi_report_spec_v1` 无 run_id 列（本身即是缺陷，见
SI3-004），Agent 工具 `analytics.report.draft` 调
`AnalyticsService.create_report_spec` 不透传 scope；5 条
"Agent 草稿：查询已注册的 BI 指标" draft 在 fixture Run 窗口内创建
却 data_scope=operational（严格口径：创建时刻唯一活跃 Run 为 fixture）。

## 4. 红测试（17/17 红）

证据：`tests/platform/test_si3_scope_integrity.py`、
`.eval/scope_v3/before/t1_red_results.txt`（17 failed）。
覆盖指令第三节 9-20 项与第四节全部契约：

- R1 media 继承 response scope；R2 work 父链隔离；R3 recognition
  继承；R4 Agent 工具 BI 继承；R5 失败 Agent 先解析 scope；
  R6 Usage API 隔离；R7 is_test_fixture 结构性 fixture；
  R8 cancelled Run 节点收敛；R9 archived/不存在 test_run fail-closed；
  R10 namespace 不可覆盖（409）；R11 父子 customer 冲突；
  R12 创建+绑定事务原子；R13 scanner 异常必须阻断；
  R14 Gate freshness（DB 变化→STALE）；R15 父链泄漏阻断 Gate；
  R16 UAT 报告 ids 必填；R17 问卷列表隔离。

## 5. 代码根因（只读定位）

1. **隔离只看行自身列**：`scope.py` `OPERATIONAL_FILTER =
   COALESCE(data_scope,'operational')='operational'`，不追父链
   （run/customer/response）。`operational_leakage()` 只查
   "自身 operational 且带 test_run_id" 或 "fixture 且 visibility=current"
   → work_item_v2（无 test_run_id 列）、survey_media（父 response
   fixture）、usage（父 run fixture）全部漏检。这是 Gate 假阳性的
   **核心根因**（指令三.13）。
2. **scanner 吞异常**：`ScopedQuery.recovery_residue/
   fixture_missing_test_run/operational_leakage` 与
   `test_data.archive_namespace` 均 `except Exception: continue`，
   删列/坏表即静默放行（指令三.14）。
3. **test_run_id 无 registry 校验**：`ScopeResolver.resolve` 接受
   任意字符串；`uat_test_run_v1` 的存在/状态/归属完全不查
   （指令三.15）。
4. **INSERT OR REPLACE 覆盖 namespace**：
   `test_data.create_test_run_context` 重复请求直接覆盖客户集
   （指令四.9、三.15）。
5. **先 commit 再 bind**：`bind_fixture_scope` 先
   `store._conn.commit()` 再查 rowcount，失败时对象已落库
   （指令三.17、四.8）。
6. **父链校验缺 customer/project**：`ScopePolicy.check_child`
   只比 data_scope/test_run_id，不比 customer/project/tenant
   （指令三.16、四.3）。
7. **创建路径无 scope 透传**：`survey.attach_media`（无 data_scope
   列写入）、`AnalyticsService.create_report_spec`（Agent 工具调用
   不带 scope）、`usage_api` 全端点零过滤、`iam.list_customers` /
   `survey.list_surveys` 零过滤。
8. **静态 Gate**：`control_plane_api.gate_current` 只读最新
   gate.json 文件，无 freshness；`evaluate_gate_from_evidence`
   无 DB 水位/fingerprint 绑定（指令三.18、九.3/4）。
9. **终态不收敛**：`cancel_run` 未收敛 node 执行行（39 条漂移）；
   Gate 的 `scan_terminal_drift` 只查 work/approval/timer/branch，
   不查 node（指令八）。
10. **UAT V4 报告 ids={}**：`_validate_uatv4` 不校验 ids 完整性，
    driver 也未写入 ids（指令三.19）。

## 6. 判定

- 当前 `READY_FOR_REAL_DATA_UAT` 为**假阳性**，不能作为真实数据
  UAT 放行依据。
- Gate 立即降级为 `BLOCKED_BY_SCOPE_INTEGRITY`
  （投影：`.eval/scope_v3/gate.json`；`/api/v1/control/gate` 已实时
  显示；旧 `.eval/uat_scope_v2/gate.json` 原样保留为假阳性证据）。
