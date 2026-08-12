# EXECUTION-LOG · Scope Integrity V3

## T0（2026-08-12 22:2x-22:5x）

1. 强制阅读（进行中）：已完成 GLOBAL_AGENT_ROUTING（全局）、
   scope-isolation-v2 全部 13 件文档、.eval/uat_scope_v2/{gate.json,
   uatv4/report.json}、src/platform/{scope,test_data,gate_evaluator,
   home_center,survey}.py、api/usage_api.py、agents/runtime.py、
   control_plane_api.py、iam.py（MasterDataService）、最近 35 个
   commit；CODEX-PROJECT-HANDBOOK/USER-HANDBOOK/OPERATOR-RUNBOOK/
   MODULE-AGENT-DEV-GUIDE/browser_evidence.json 于 T1 开工前补齐。
   注：项目根无 AGENTS.md / GLOBAL_AGENT_ROUTING.md（find 验证），
   以全局 routing 文件为准。
2. 现场：HEAD=eb19425f、branch=feat/nextgen-training-cycle-v2、
   四服务 UP、CURRENT=prod_v4_best_r1、训练进程=0。
3. 独立 SQL 审计器 scripts/scope_audit_v3.py（只读连接）：
   media=24、work=8、recognition=5、BI=5（严格口径）、
   failed_agent=5、usage=89、fixture_customer=1、node 漂移=39、
   uatv4 ids=0 —— 与指令基线全部吻合（00-LIVE-AUDIT §3）。
4. DB 备份：SQLite backup API →
   .platform/backups/platform_pre_scope_v3_20260812T224724.sqlite；
   源与备份 integrity_check 均 ok；sha256=753a809362bd9b54…
5. 红测试 17/17 红：tests/platform/test_si3_scope_integrity.py
   （首跑证据 .eval/scope_v3/before/t1_red_results.txt）。
6. Gate 降级投影 .eval/scope_v3/gate.json；curl /control/gate
   确认显示 BLOCKED_BY_SCOPE_INTEGRITY。
7. 治理文档 11 件落盘（本目录）。
8. 提交：si3(T0)。

## T1+ （持续更新）
