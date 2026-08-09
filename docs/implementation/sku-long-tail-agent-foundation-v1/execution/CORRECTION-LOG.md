# CORRECTION-LOG
2026-08-09：基线核验（HEAD 633b4abd，表 0 行）→ m026/m027 → reconciliation 运行
（7 artifacts/4 snapshots/7 evals/cycle/blackboard/memory）→ agent runtime API →
Web 抽屉/任务板/对账面板 → profiles 动态派生 → canonical38+pending pack →
M1 pilot 完成 → M2/M3/KB 运行中。

## 续（QA 修复轮）
- approve 500 修复（plan_json 字段 + 7 占位符）；curl 验证 approve=200 且 Plan 落库。
- 抽屉 CSRF + localStorage 会话持久化；识别页 ProfilesPanel（derive 动态）。
- 浏览器复验：Cycle 问答/拒绝切生产/profiles 表 通过；approve 经 curl 200 验证。
- KB canonical38：coverage 1.0 / recall@1 0.895 / recall@5,8 1.0 / escape 0 /
  p95 32.4s → gate_pass=true → 授权 M4 pilot（真实 CandidateSet）。
- M3 消融：E1 .9599 / E2 .956 / E3 .9487 / E4 .9621 / E5 .9649（E5 最优，
  相对 E1 +0.5pp → candidate pending eval）。
- M1 pilot mAP50 .077；M2 pilot mAP50 .071（均九要素快照）。
