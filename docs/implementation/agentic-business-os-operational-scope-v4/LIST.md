# LIST · 工作项账本 · Operational Scope V4

| ID | 阶段 | 事项 | 状态 | 证据 |
|---|---|---|---|---|
| SI4-T0-1 | T0 | 现场审计（含外部 commits 审计） | DONE | .eval/scope_v4/before/before_audit.json |
| SI4-T0-2 | T0 | DB 备份 + 双向 integrity | DONE | platform_pre_scope_v4_20260813T023659（e886123f…） |
| SI4-T0-3 | T0 | Gate 降级 BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE | DONE | .eval/scope_v4/gate.json（初版） |
| SI4-T0-4 | T0 | 治理目录 16 件 | DONE | 本目录 |
| SI4-T1-1 | T1 | 红测试 15 项（P0-001…P2-002） | DONE | test_si4_operational_surface.py（fe7a543c） |
| SI4-T2-1 | T2 | IAM 身份生命周期（迁移 057/登录拒绝/归档收敛） | DONE | 9fd80c7c |
| SI4-T3-1 | T3 | BI effective 口径（迁移 058/data-products 对账） | DONE | 9fd80c7c |
| SI4-T4-1 | T4 | Finance/Usage 上下文（默认值/invoice provenance） | DONE | 9fd80c7c/b1dded1c |
| SI4-T5-1 | T5 | Registry 语义升级（7 项生命周期声明） | DONE | 9fd80c7c |
| SI4-T5-2 | T5 | live 历史收敛 r20–r23（全审计） | DONE | scope_backfill_audit_v1 + 705024ec/a4fb3f7f |
| SI4-T6-1 | T6 | Gate 3.1 检查 + 22 负例 | DONE | gate_evaluator + gate_negative_tests.json |
| SI4-T7-1 | T7 | UAT V6（57/57，ids 30/30） | DONE | b1dded1c + .eval/scope_v4/uatv6/report.json |
| SI4-T8-1 | T8 | UI/UX（浮层/IAM 列表）+ 12 页浏览器 30/30 | DONE | a4fb3f7f + .eval/scope_v4/browser/ |
| SI4-T9-1 | T9 | 性能/安全 + 全量回归 | DONE | 1447 passed/host MPS 6/tsc 干净 |
| SI4-T10-1 | T10 | FINAL-REPORT（47 项）+ handbook | DONE | FINAL-REPORT.md + CODEX-PROJECT-HANDBOOK.md |
