# STATUS · Scope Integrity V3

当前 Gate：以 `.eval/scope_v3/gate.json` 机器文件为准（Gate 3.0，
evidence-driven + DB fingerprint freshness；`/api/v1/control/gate`
实时复评，DB/代码变化即 STALE_GATE_EVIDENCE）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 独立审计 + 红测试 17 项 + 备份 + Gate 降级 + 文档 | DONE（6b5ea854） |
| T1 | ExecutionContext/Resolver/Policy V3 | DONE（003271e7） |
| T2 | 创建路径 scope 透传（全链路） | DONE（003271e7/cb5a11cb/bb6802ef） |
| T3 | 全表 Scope Registry（123/123） | DONE（003271e7） |
| T4 | effective_scope 运营查询口径 | DONE（003271e7） |
| T5 | 历史数据追加式纠偏 + attribution ledger | DONE（8cad7acc/bb6802ef，审计在库） |
| T6 | 工作流终态不变量（全层收敛） | DONE（cb5a11cb） |
| T7 | Gate 3.0（freshness + 负例 14 项） | DONE（cb5a11cb） |
| T8 | UAT V5 全领域链（48/48，ids 24/24） | DONE（cb5a11cb） |
| T9 | UI 12 项 + 四视口 + console 0 | DONE（13abb465/bb6802ef） |
| T10 | 性能（p95/chunk/diff-check） | DONE |
| T11 | 最终回归 + FINAL-REPORT + handbook | DONE |

放行判定：指令第十二节全部指标达成（详见 FINAL-REPORT.md）。
Gate 结论由机器评估给出；本轮不写 ACCEPTED/COMPLETE/
PRODUCTION_READY——真实数据 UAT 与人工验收仍由用户执行。
