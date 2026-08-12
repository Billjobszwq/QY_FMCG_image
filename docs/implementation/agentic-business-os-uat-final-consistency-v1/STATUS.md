# STATUS

更新时间：2026-08-12（T10 收口）。

## 唯一 Gate（机器计算，文档只引用）

`READY_FOR_REAL_DATA_UAT`

- 机器文件：`.eval/v3_uat_v3/gate.json`（evaluator 2.0.0，20/20 checks ok，
  evidence_hashes: uat_report/issue_ledger/test_report/browser_report）。
- API：GET /api/v1/control/gate；UI：/#/status 可展开证据。
- 不得写 ACCEPTED / COMPLETE / PRODUCTION_READY。

## 阶段进度

| 阶段 | 状态 |
|---|---|
| T0 现场复现+红测试 | VERIFIED_LOCAL（14 RED→GREEN） |
| T1 统一终态状态机 | VERIFIED_LOCAL（finalize_run CAS + 不变量） |
| T2 取消/并发竞态 | VERIFIED_LOCAL（原子 CAS + 协作式取消；并发 finalize 单方胜测试） |
| T3 Approval 关闭链 | VERIFIED_LOCAL（批准 done/拒绝 cancelled(rejected)/取消收敛） |
| T4 fixture 隔离 | VERIFIED_LOCAL（迁移 049 + TestDataService；residue=0；首页待办 0） |
| T5 证据驱动 Gate | VERIFIED_LOCAL（evaluate_gate_from_evidence → gate.json） |
| T6 validator 强化 | VERIFIED_LOCAL（fail-closed 全项；非 0 退出） |
| T7 工作流 model 链 | VERIFIED_LOCAL（command 节点工作流内 V4 识别，继承上下文） |
| T8 异常追问链 | VERIFIED_LOCAL（hit=true→Agent 追问→人工回答→resolved→报表 v2） |
| T9 Agent 失败账本 | VERIFIED_LOCAL（failed run/work/evidence/usage + UI 红色账本） |
| T10 UAT V3+QA+全量 | VERIFIED_LOCAL（47/47；17 张 CDP 截图；1386+6 测试全绿） |
