# EXECUTION-LOG · UAT Scope Isolation V2

## T0（2026-08-12）

1. Git 核对：HEAD=9f3554e7、分支=feat/nextgen-training-cycle-v2，
   tracked 干净（与指令预期一致）。
2. `./bin/abos status`：recognize/monitor/label_studio/app 全 UP；
   production=prod_v4_best_r1；训练进程=无。
3. 模型 hash：detector.pt sha256=84bf9936…554975（与预期一致）。
4. DB：integrity ok；50 migrations；fixture 统计见 00-LIVE-AUDIT。
5. 备份：.platform/backups/platform_pre_scope_v2_20260812202343.sqlite
   （integrity ok，sha256=7d65b1ce…3a41c）。
6. 复现 P0-001/P0-002/P1-001..004/P2-001..003（证据在 00-LIVE-AUDIT
   与 ISSUES.md）。
7. Gate 降级投影：写入 .eval/uat_scope_v2/gate.json =
   BLOCKED_BY_UAT_FIXTURE_PROJECTION（旧 gate.json 保留）。
8. 建立治理文档：AGENT-EXECUTION-PROMPT/00/01/02/03/04/STATUS/
   ISSUES/DECISIONS/LIST/EXECUTION-LOG/FINAL-REPORT/READING-LIST。

最近 30 commits（git log --oneline -30）：
9f3554e7 ufc(final) / 6664022f ufc(T9/T10c) / 16629042 feat brand /
8beb2695、2590dc88 docs TaaS / 53022a54 ufc(T10b) / 4d157035 feat
三受众 / b9a1723e ufc(T10a UAT V3 driver) / 9ef9a022、5eb69088 docs /
803e9342 ufc(T7,T8) / 9900ac33 ufc(T4 fixture isolation 049) /
0e0905f8 ufc(T1-T3,T5,T6,T9) / 98ce420f、efd96fa1、21326f47、96e5354c
docs / 99e2ca5f ufc(T0) / 6cbca9c0 uatcc(T8-final) / 0f447e81、
22142f5f uatcc(T8) / 4e9bcc2f uatcc(T7) / 33bd4bcb uatcc(T4) /
50398320 uatcc(T5) / 98653f31 uatcc(T6) / ecd03ffa uatcc(T0.5) /
1de259aa uatcc(T3) / e0a478d3 uatcc(T2) / bd56676e uatcc(T1) /
f44c0f76 uatcc(T0)。

（后续阶段按 T1..T10 追加。）

## T1（红测试）

- tests/platform/test_si2_scope_isolation.py：22 项，首跑全红
  （ModuleNotFoundError src.platform.scope），结果存
  .eval/uat_scope_v2/t1_red_results.txt（commit 5183cd83）。

## T2-T4/T6（scope 单事实源 + 默认 operational + Gate 2.1）

- commit 013efe3a：scope.py（Resolver/Policy/ScopedQuery/
  bind_fixture_scope）、迁移 051（20 表 + uat_test_run_v1 +
  scope_backfill_audit_v1 + 派生视图）、创建路径继承（gateway/
  workflow node-timer-branch/AgentRuntime 含失败账本）、默认
  operational 查询（home/agent/BI/finance）、Gate 2.1.0（STALE 绑定/
  scope lineage 重算/浏览器语义/数字证据）；22/22 转绿，全量
  hermetic 1399 passed。

## T3（迁移 + Legacy Backfill）

- commit 9548cc30：scripts/si2_legacy_backfill.py（幂等；审计入
  scope_backfill_audit_v1）：79 fixture runs 补 test_run_id（0 缺失）；
  14 项目/14 外勤/14 分配/15 响应/3 日程/161 节点执行/15 timer/
  20 branch/22 识别/37 agent run 结构化；40 wf 定义+10 BI+10 问卷
  名称线索（内嵌 namespace 精化）；3 条父子不一致修复；不可变账本
  （usage/evidence）经来源 run 查询侧判定；20 fixture 客户补
  test_run_id；live scan：leakage={} missing=0 mismatch=0。

## T5（测试与证据中心）

- commit 52b9069b：/api/v1/test-data/center（Test Run 历史/对象计数/
  一致性扫描/backfill 账本）+ /api/v1/test-data/run（先建上下文）；
  SystemStatus Web 区块接入。

## T8（UAT V4 机器预演）

- commit fbeac0f3：scripts/uatv4_rehearsal.py 31/31 通过（最终轮
  namespace uatv4_20260812214006_d1wfbc；含门头负例/正例、工作流
  wait/parallel/join/loop/approval/command(V4 识别)/agent、失败账本、
  归档后泄漏=0、中心仍可见）；报告 .eval/uat_scope_v2/uatv4/
  report.json（protocol=uatv4）。

## T9（前端拆包 + 警告收口）

- commit b38d9421：路由级 lazy + vendor-react 拆分；初始 JS
  2,712,322 B→index 63.77KB + vendor 164.52KB（gzip 818KB→72KB）；
  重型 chunk 异步并披露（BIWorkbench gzip 382KB=echarts 全量；
  Geo 255KB=maplibre）；未动 warningLimit；typecheck/build 干净。

## T7（浏览器语义证据）

- scripts/si2_browser_evidence.py：10 pages（4 语义断言 + 6 响应式），
  视口 1440/1280/1024/768，expected/actual 对象 ID + 文本 + 截图
  sha256；证据 .eval/uat_scope_v2/browser/browser_evidence.json。

## T10（回归 + Gate 正负例 + 收尾）

- hermetic 全量：1399 passed, 1 skipped（.eval/uat_scope_v2/
  test_report.json）；host_mps：6 passed。
- Gate 负例 12/12 阻断（gate_negative_tests.json）。
- Gate 2.1 检查项 26；正例评估见 FINAL-REPORT 与
  .eval/uat_scope_v2/gate.json。
