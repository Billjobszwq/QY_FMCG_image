# STATUS · UAT Scope Isolation V2

当前 Gate：以 `.eval/uat_scope_v2/gate.json` 机器文件为准
（Gate 2.1，26 检查，evidence-driven；旧 `.eval/v3_uat_v3/gate.json`
保留为历史证据）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 现场审计 + 治理基线 + Gate 降级 | DONE（18ac09d0） |
| T1 | 红测试 22 项（首跑全红→全绿） | DONE（5183cd83） |
| T2 | ExecutionScopeV1 / ScopePolicy（单事实源） | DONE（013efe3a） |
| T3 | 迁移 051/052/053 + Legacy Backfill（审计账本） | DONE（9548cc30） |
| T4 | 全 Domain 默认 operational 查询 | DONE（013efe3a） |
| T5 | 测试与证据中心（API + Web 区块） | DONE（52b9069b） |
| T6 | Gate 2.1（26 检查 + HEAD/树/migration 绑定 + STALE） | DONE |
| T7 | 浏览器语义证据（10 pages，4 视口） | DONE |
| T8 | UAT V4 机器预演 31/31 | DONE（fbeac0f3） |
| T9 | 前端路由级拆包（初始 gzip 818KB→72KB）+ 警告收口 | DONE（b38d9421） |
| T10 | 回归 + host_mps + Gate 正负例（12/12）+ 最终报告 | DONE |

硬约束复核（指令第九节 23 项）：P0=0、P1=0（ISSUES 全 CLOSED）；
全 Domain 泄漏=0；scope binding/test_run_id/父子一致率=100%；
首页/Agent/BI/财务/最近/活动默认不含 fixture；测试中心可查全历史；
UAT V4 全链完成；浏览器语义全过；Gate 绑定 HEAD 与代码树；
worktree 干净；SQLite ok；测试全过；host_mps 过；typecheck/build 过；
四服务恢复；CURRENT=prod_v4_best_r1；训练进程=0；生产未切换；
未导入正式数据；未删历史资产；Gate 正负例全验证。

不得写 ACCEPTED/COMPLETE/PRODUCTION_READY/PROMOTION_READY——真实数据
UAT 与人工验收由用户执行。
