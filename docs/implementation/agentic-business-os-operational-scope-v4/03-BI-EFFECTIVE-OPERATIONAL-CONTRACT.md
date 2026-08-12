# 03-BI-EFFECTIVE-OPERATIONAL-CONTRACT · BI effective 口径

## 1. BI Query Context（统一，禁止报表自拼 SQL）

所有 BI 读取（metric 求值/data-products/dashboard/report/anomaly/
Agent 分析）必须经过统一上下文：
tenant、customer、project、effective data scope、time window、
permission、metric version、source evidence。

实现：`analytics.py` 内统一 `effective_operational_where(table)`
辅助 + data-products 专用 effective 计数函数；API 层禁止裸
`SELECT count(*)`。

## 2. data-products 对账契约

`/api/v1/analytics/data-products` 的 rows 必须等于对应运营口径：
- master.customers_v1.rows == `/master/customers`.count（operational）
- master.projects_v1.rows == operational projects count
- master.skus_v1.rows == operational skus count
- survey.responses_v1.rows == operational responses（含父链）
- vision.recognition_tasks.rows == operational recognition tasks
- usage.event_v2.rows == effective operational usage（attribution+父链）
- geo.addresses_v1.rows == operational addresses
- import.batches_v1.rows == operational import batches（补 scope 列）

Gate 断言：两口径逐项相等，否则 BLOCKED。

## 3. Metric 生命周期（迁移 058）

`bi_metric_v1` 追加：data_scope、test_run_id、status、archived_at、
created_by、customer_id、version、formula_hash。
- UAT 创建的 metric 必须携带 test_run（受信创建路径校验）。
- 归档后：不进运营指标目录、不用于看板/异常规则/Agent 分析/正式
  报告；仅测试中心可追溯。
- 历史 UAT metric（8+）一次性回绑 + 归档（审计）。

## 4. Dashboard / Report / Anomaly / Follow-up

- `bi_dashboard_v1` 追加 data_scope/test_run_id（迁移 058）。
- report/version/anomaly/follow-up 继承 Query Context 与 Test Run
  scope（SI3 已部分实现，本轮补 dashboard 与创建端点校验）。
- Agent BI draft：无明确 customer/project 时只生成命令预览，不直接
  落库（DEC-SI4-004）。

## 5. BI 默认客户

删除 `uat-cust-a` 硬编码。默认策略：
- 有且仅有一个可见运营客户 → 可预选；
- 无运营客户 → 诚实空态 + "先创建/导入客户"入口；
- 多个运营客户 → 要求人工选择；
- 永不自动回退 UAT/demo 客户。
