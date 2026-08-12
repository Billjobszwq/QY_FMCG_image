# LIST · 工作项账本 · Scope Integrity V3

| ID | 阶段 | 事项 | 状态 | 证据 |
|---|---|---|---|---|
| SI3-T0-1 | T0 | 独立只读审计（SQL 审计器） | DONE | .eval/scope_v3/before/before_audit.json |
| SI3-T0-2 | T0 | DB 备份 + 双向 integrity | DONE | platform_pre_scope_v3_20260812T224724.sqlite（sha256=753a8093…） |
| SI3-T0-3 | T0 | 红测试 17 项（首跑全红） | DONE | tests/platform/test_si3_scope_integrity.py；.eval/scope_v3/before/t1_red_results.txt |
| SI3-T0-4 | T0 | Gate 降级 BLOCKED_BY_SCOPE_INTEGRITY | DONE | .eval/scope_v3/gate.json；/control/gate 实时可见 |
| SI3-T0-5 | T0 | 治理文档 11 件 | DONE | 本目录 |
| SI3-T1-1 | T1 | ExecutionContext/Resolver/Policy V3（registry fail-closed、六维校验、事务原子、namespace 不可覆盖） | TODO | — |
| SI3-T2-1 | T2 | 创建路径透传：survey media/Agent 工具/recognition/失败账本/Usage | TODO | — |
| SI3-T3-1 | T3 | 全表 Scope Registry + Gate 覆盖率检查 | TODO | — |
| SI3-T4-1 | T4 | effective_scope 查询口径（home/lists/usage/finance/BI） | TODO | — |
| SI3-T5-1 | T5 | 历史数据追加式纠偏 + attribution ledger + 审计 | TODO | — |
| SI3-T6-1 | T6 | 工作流终态不变量（node/timer/branch/approval/work 全层） | TODO | — |
| SI3-T7-1 | T7 | Gate 3.0（freshness/fingerprint/负例 12+） | TODO | — |
| SI3-T8-1 | T8 | UAT V5 全领域链 + report ids 100% | TODO | — |
| SI3-T9-1 | T9 | UI 12 项 + 四视口 + console | TODO | — |
| SI3-T10-1 | T10 | 性能（chunk/p95/diff-check/空格） | TODO | — |
| SI3-T11-1 | T11 | 最终回归 + FINAL-REPORT + handbook 更新 | TODO | — |
