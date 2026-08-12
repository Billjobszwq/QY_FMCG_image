# 00-LIVE-AUDIT · Operational Scope V4（独立只读审计）

> 审计时间：2026-08-13（UTC+8 02:3x），只读 SQL + 源码静态检查。
> 结论：Scope V3 的 READY 覆盖面不足，IAM/BI/Finance 运营面仍被
> UAT 数据污染。正确开工 Gate = BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE。

## 1. Git / 服务 / 模型现场

- 开工 HEAD：`63679be0`（指令复核期间 2b22b519→4bb0d49f→805fc796
  →63679be0 均为外部 TaaS 主题/推广文档提交，只改
  docs/promotion 与 tests/promotion，不触碰 scope 链；已审计 diff）
- 分支 `feat/nextgen-training-cycle-v2`；tracked 干净；未跟踪资产
  （.datasets_nextgen/.micro_gold_*/.sam_* 等）零触碰
- 8091/8092/8300/8400 UP；`PRAGMA integrity_check`=ok；
  CURRENT=prod_v4_best_r1；训练进程=0
- 备份：`.platform/backups/platform_pre_scope_v4_20260813T023659.sqlite`
  sha256=`e886123f96bab1944d846b5d651ae11268932e646f9dc08c8931bb885bb328b1`
  （SQLite backup API；源与备份双向 integrity=ok）

## 2. P0-001 IAM 测试身份（.eval/scope_v4/before_audit.json）

- `iam_principal_v1`：**85 个 UAT 用户全部 active**
  （uatv2_/uatv3_/uatv5_ 前缀）
- `iam_membership_v1`：**97 条 membership，全部带 customer 授权**
  （角色分布：read_only/project_manager/finance_operator/
  field_manager/analyst 各 17，survey_designer 12）
- `auth_sessions`：**85 条 UAT 会话记录**（登录面未收敛）
- 最新 UAT V5 五角色账号（pm/fw/an/fin/aud）归档后仍 active
- 正常"账号与角色"页面直接显示这些账号

## 3. P0-002 BI 数据产品物理计数

`/api/v1/analytics/data-products`（analytics_api.py `count()` 直读
`SELECT count(*)`，except 吞异常）与运营 API 对账：

| 数据产品 | 物理行数 | effective operational |
|---|---|---|
| master.customers_v1 | 37 | **0** |
| master.projects_v1 | 25 | **0** |
| master.skus_v1 | 22 | **0** |
| survey.responses_v1 | 25 | 2（待核父链） |
| vision.recognition_tasks | 50 | 18（待核父链） |
| usage.event_v2 | 195 | attribution+父链口径 |
| geo.addresses_v1 | 24 | **0** |
| import.batches_v1 | 20 | 表无 scope 列（逃逸面） |

## 4. P0-003 BI metric/dashboard 污染

- `bi_metric_v1` 14 个指标，其中 **8+ 个 UAT 指标**（uat.photo_x2、
  uatv2_*_rate ×4、uatv3_*_rate ×3…）且该表**无 scope 列**
- `bi_dashboard_v1` **无 scope 列**（结构性无法隔离）
- 运营 BI 页面直接展示这些指标

## 5. P1-001/002 前端测试默认值（源码静态，7 处）

- `web/src/pages/BIWorkbench.tsx:87` → `useState("uat-cust-a")`
- `web/src/pages/UsageWorkbench.tsx:8` → `useState("uat-cust-a")`
- `web/src/pages/Finance.tsx:26/96` → `useState("demo-cust-a")`
- `web/src/pages/Geo.tsx:73/159/305` → `useState("demo-cust-a")`

## 6. P1-003/004/005

- 浏览器证据只覆盖 home/customers/survey/vision/status，未覆盖
  IAM/BI/Finance → 旧 Gate 12/12 通过但运营面不干净
- Scope Registry 100% 是**物理表**覆盖；global_configuration/
  reference_registry/audit_only 分类未定义 UAT provenance 与归档
  生命周期 → 分类逃逸
- Scope V3 gate.json 绑定 `78f2e990`，HEAD 已前进，实时 Gate 已
  正确返回 STALE_GATE_EVIDENCE（freshness 机制工作正常）

## 7. 判定

- 不得进入真实数据 UAT；Gate 降级
  `BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE`
  （投影 `.eval/scope_v4/gate.json`，mtime 最新被 control/gate 选中）
- 修复顺序：IAM 身份生命周期 → BI effective 口径 → Finance/Usage
  上下文 → Registry 语义升级 → Gate 3.1 → UAT V6 → 浏览器 12 页验收
