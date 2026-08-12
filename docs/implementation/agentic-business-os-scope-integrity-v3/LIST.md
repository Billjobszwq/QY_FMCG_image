# LIST · 工作项账本 · Scope Integrity V3

| ID | 阶段 | 事项 | 状态 | 证据 |
|---|---|---|---|---|
| SI3-T0-1 | T0 | 独立只读审计（SQL 审计器） | DONE | .eval/scope_v3/before/before_audit.json（24/8/5/5/5/89/1/39/ids=0 全复现） |
| SI3-T0-2 | T0 | DB 备份 + 双向 integrity | DONE | platform_pre_scope_v3_20260812T224724.sqlite（sha256=753a8093…）；回填前另备 platform_pre_backfill_v3_20260812T233822（f42cebe0…） |
| SI3-T0-3 | T0 | 红测试 17 项（首跑全红） | DONE | tests/platform/test_si3_scope_integrity.py；.eval/scope_v3/before/t1_red_results.txt |
| SI3-T0-4 | T0 | Gate 降级 BLOCKED_BY_SCOPE_INTEGRITY | DONE | .eval/scope_v3/gate.json；/control/gate 实时可见 |
| SI3-T0-5 | T0 | 治理文档 11 件 | DONE | 本目录 |
| SI3-T1-1 | T1 | ExecutionContext/Resolver/Policy V3 | DONE | 003271e7（registry fail-closed、六维校验、事务原子、namespace 不可覆盖） |
| SI3-T2-1 | T2 | 创建路径透传（media/Agent 工具/识别/失败账本/Usage/异常/BI 版本链） | DONE | 003271e7 + cb5a11cb + bb6802ef |
| SI3-T3-1 | T3 | 全表 Scope Registry（123/123） | DONE | src/platform/scope_registry.py；gate scope_registry_full |
| SI3-T4-1 | T4 | effective_scope 运营查询口径 | DONE | usage_api/_EFFECTIVE_OP、home、analytics、iam lists |
| SI3-T5-1 | T5 | 历史数据追加式纠偏 + attribution ledger + 审计 | DONE | scripts/scope_backfill_v3.py r0–r18；scope_backfill_audit_v1 + scope_attribution_ledger_v1；after_audit_final.json 全零 |
| SI3-T6-1 | T6 | 工作流终态不变量（node/timer/branch/approval/work 全层） | DONE | workflow.finalize_run/retry_run + scan_terminal_drift(node_open) |
| SI3-T7-1 | T7 | Gate 3.0（freshness/fingerprint/registry/负例） | DONE | gate_evaluator 3.0.0 + scripts/si3_gate_evaluate.py + UAT V5 注入负例 |
| SI3-T8-1 | T8 | UAT V5 全领域链 + report ids 100% | DONE | .eval/scope_v3/uatv5/report.json（48/48，ids 24/24，validator []） |
| SI3-T9-1 | T9 | UI 12 项 + 四视口 + console | DONE | 13abb465 + bb6802ef；.eval/scope_v3/browser/browser_evidence.json（12/12，unexplained=0） |
| SI3-T10-1 | T10 | 性能（chunk/p95/diff-check/空格） | DONE | api_perf.json（最差 p95=28.2ms）；home_load_perf.json（p95=186ms）；build warnings 仅 maplibre 单库（实测理由+预算）；diff --check 干净；scope.py 无尾随空格 |
| SI3-T11-1 | T11 | 最终回归 + FINAL-REPORT + handbook 更新 | DONE | hermetic 1425 passed；host_mps 6 passed；FINAL-REPORT.md |
