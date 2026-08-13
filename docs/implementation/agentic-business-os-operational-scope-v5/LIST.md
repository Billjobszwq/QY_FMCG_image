# LIST · 工作项账本 · Operational Scope V5

| ID | 阶段 | 事项 | 状态 | 证据 |
|---|---|---|---|---|
| OSV5-T0-1 | T0 | 现场审计（基线核对+独立复现） | DONE | .eval/scope_v5/before/before_audit_v5.json |
| OSV5-T0-2 | T0 | DB 备份 + 双向 integrity | DONE | platform_pre_scope_v5_20260813T124408（f1f92091…） |
| OSV5-T0-3 | T0 | Gate 经真实 evaluator 降级 | IN-PROGRESS | .eval/scope_v5/gate.json |
| OSV5-T0-4 | T0 | 治理目录 16 件 | IN-PROGRESS | 本目录 |
| OSV5-T1-1 | T1 | 红测试 30 类 | PENDING | tests/platform/test_osv5_import_scope.py |
| OSV5-T2-1 | T2 | 迁移 059：import 生命周期列 + 客户关联表 | PENDING | store.py |
| OSV5-T2-2 | T2 | ImportCenter 作用域创建链（upload/test_run/授权） | PENDING | import_center.py |
| OSV5-T3-1 | T3 | Import API 权限/作用域/DTO/脱敏/下载授权 | PENDING | import_api.py |
| OSV5-T4-1 | T4 | Registry 类型化 + schema validator | PENDING | scope_registry.py |
| OSV5-T4-2 | T4 | scanner/archiver/operational-filter/Test Center/Gate 由 Registry 派生 | PENDING | scope.py/test_data.py/gate_evaluator.py |
| OSV5-T5-1 | T5 | 历史 20 条 classification plan（只读） | PENDING | scripts/scope_reconcile_imports_v5.py |
| OSV5-T5-2 | T5 | 绑定/quarantine 执行（幂等+审计） | PENDING | scope_backfill_audit_v1 |
| OSV5-T6-1 | T6 | Gate 3.2（18 检查/12 负例/evaluator 3.2.0） | PENDING | gate_evaluator.py |
| OSV5-T7-1 | T7 | UAT V7 真实经 Import Center（20 检查） | PENDING | scripts/uatv7_rehearsal.py |
| OSV5-T8-1 | T8 | 浏览器验收（5 角色×4 视口×8 页，对象级对账） | PENDING | scripts/osv5_browser_evidence.py |
| OSV5-T9-1 | T9 | Session 过期清理（有界+审计+bill 豁免） | PENDING | auth.py |
| OSV5-T10-1 | T10 | 全量回归（hermetic/MPS/tsc/build/重启） | PENDING | EXECUTION-LOG |
| OSV5-T10-2 | T10 | FINAL-REPORT（53 项）+ handbook/runbook/guide 更新 | PENDING | FINAL-REPORT.md |
