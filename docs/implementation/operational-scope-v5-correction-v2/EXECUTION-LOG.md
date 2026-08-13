# EXECUTION-LOG — operational-scope-v5-correction-v2

## 2026-08-13/14 实施记录

- 基线：8cb51dcf（V5.1 收尾 HEAD）；DB 备份
  platform_pre_osv52_20260813T231549.sqlite（integrity ok）。
- 复现 QA ISSUE-001：gate.json 记录 negative=3dd868a16e585276，QA
  重跑负例后当前文件=52da2afd4f9579f4，实时 Gate 仍 READY（断链
  实证；before-snapshots/ 留存）。
- 红测试 16 项（哈希重校验 11 + Registry 5）先行（2268aa02）。
- 评估器 3.3.0→3.4.0：freshness 复评新增 evidence_manifest 重读重算；
  路径安全（绝对越界/..穿越/符号链接逃逸拒绝）；分层校验（整文件/
  binding/result_hash）。
- 迁移 061 gate_run_v1 + gate_registry（CAS 激活/协议防接管/
  supersedes）+ 实时端点改造（只读 active，fail-closed）+ 激活端点
  （平台角色+approved+CAS）+ /gate/runs 账本（d9fe9657）。
- 修复期间实时 Gate 无 active run → BLOCKED_BY_GATE_EVIDENCE
  （诚实阻断，不再显示 V5.1 旧 READY）。
- Import Center URL 单一事实源（0a574772）；测试质量（abb241da）；
  首页 H1（abb241da）。
- OSV51-013：旧实现 1500 轮并发实证 1301 轮双写覆盖 → 条件 UPDATE/
  CAS；复测 1500/1500 恰一赢家 0 覆盖；7 测试 + 63 workflow 回归绿
  （28589e90/1d6cf060）。
- 负例账本 21→27：新增篡改族 6 项（rewrite negative/test/browser、
  delete uat、keep-binding-tamper-body、symlink escape），全部经实时
  freshness 复评路径 ALL_BLOCKED。
- Active Gate API 契约测试 8 项绿（fail-closed/approved/未知 run/
  协议防接管/激活元数据/supersede/非平台角色 403）。

## 验收链（最终 HEAD 上执行）

见 ACCEPTANCE.md 与 machine_facts.json（.eval/scope_v5/）。
