# STATUS · UAT Scope Isolation V2

当前 Gate：**BLOCKED_BY_UAT_FIXTURE_PROJECTION**
（投影：`.eval/uat_scope_v2/gate.json`；旧
`.eval/v3_uat_v3/gate.json` 保留为历史证据）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 现场审计 + 治理基线 + Gate 降级 | IN_PROGRESS |
| T1 | 红测试（22+ 项） | PENDING |
| T2 | ExecutionScopeV1 / ScopePolicy | PENDING |
| T3 | 迁移 051 + Legacy Backfill | PENDING |
| T4 | 全 Domain 默认 operational 查询 | PENDING |
| T5 | 测试与证据中心 | PENDING |
| T6 | Gate 2.1 | PENDING |
| T7 | 浏览器语义证据 | PENDING |
| T8 | UAT V4 机器预演 | PENDING |
| T9 | 前端拆包 + 警告收口 | PENDING |
| T10 | 回归 + 服务恢复 + 最终报告 | PENDING |

硬约束：未满足第九节 23 条硬条件前不得输出
READY_FOR_REAL_DATA_UAT；不得写 ACCEPTED/COMPLETE/
PRODUCTION_READY/PROMOTION_READY。
