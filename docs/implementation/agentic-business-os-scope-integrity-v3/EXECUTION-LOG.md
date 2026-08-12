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

## T1–T11（2026-08-12 深夜–2026-08-13 凌晨）

1. T1/T2/T3/T4（003271e7）：scope.py V3（ExecutionContext/
   registry fail-closed/六维校验/原子创建/fail-fast scanner + 父链
   泄漏扫描）；受信端点前置校验；usage/analytics/home 全量
   effective 口径；迁移 054 attribution ledger。红测试 15/17 转绿。
2. T5（多次 --apply，全审计）：r0–r18 共 460+ 行纠偏；不可变
   Usage(96+5)/Evidence(65+5) 仅经 attribution；双向 integrity ok。
3. T6/T7/T8（cb5a11cb）：finalize/retry 节点收敛；Gate 3.0
   db_fingerprint + freshness；UAT V5 48/48，ids 24/24；
   迁移 055/056（finance/geofence scope 列）。
4. T9（13abb465/bb6802ef）：UI 12 项 + 浏览器语义证据 12/12 +
   console unexplained=0；browser 断言抓出并修复 answer_anomaly
   报表版本链丢 scope 的二次泄漏。
5. T10：API p50/p95 实测（最差 home/dashboard p95=28.2ms；
   control/gate freshness 复评 p95=8.6ms）；首页加载 p95=186ms
   <2s；chunk：echarts 模块化 1134KB→381+177KB，maplibre 独立
   949KB（单库不可拆，预算 gzip≤260KB，仅 Geo 路由加载）；
   git diff --check 干净；scope.py 无尾随空格。
6. 回归：hermetic 1425 passed（基线 1408 + 新增 17）；host MPS
   6 passed；四服务全程可用（仅 graceful restart，每次验证恢复）；
   CURRENT=prod_v4_best_r1 未切换；训练进程=0。
7. 提交链：6b5ea854 → 003271e7 → de3b6923 → 13abb465 → 18215671 →
   cb5a11cb → bb6802ef →（本轮文档收尾提交）。
