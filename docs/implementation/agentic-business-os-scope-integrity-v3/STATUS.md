# STATUS · Scope Integrity V3

当前 Gate：`BLOCKED_BY_SCOPE_INTEGRITY`（机器投影
`.eval/scope_v3/gate.json`；`/api/v1/control/gate` 实时展示）。
旧 READY（SI2，假阳性）不得作为任何放行依据。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 独立审计 + 红测试 17 项 + 备份 + Gate 降级 + 文档 | DONE |
| T1 | ExecutionContext/Resolver/Policy V3 | IN_PROGRESS |
| T2 | 创建路径 scope 透传（media/Agent 工具/识别/失败账本/Usage） | TODO |
| T3 | 全表 Scope Registry（100% 覆盖） | TODO |
| T4 | effective_scope 运营查询口径 | TODO |
| T5 | 历史数据追加式纠偏 + attribution ledger | TODO |
| T6 | 工作流终态不变量 | TODO |
| T7 | Gate 3.0（freshness + 负例 12+） | TODO |
| T8 | UAT V5 全领域链 | TODO |
| T9 | UI 12 项 + 四视口 | TODO |
| T10 | 性能（chunk/p95/diff-check/空格） | TODO |
| T11 | 最终回归 + FINAL-REPORT | TODO |

放行条件（在此之前不得写 READY/ACCEPTED/COMPLETE/PRODUCTION_READY）：
见指令第十二节全部指标（泄漏=0、Registry 100%、UAT V5 ids 100%、
Gate 负例全阻断、hermetic ≥1408、host MPS 6、typecheck/build、
四视口、四服务健康、CURRENT=prod_v4_best_r1、无训练进程）。
