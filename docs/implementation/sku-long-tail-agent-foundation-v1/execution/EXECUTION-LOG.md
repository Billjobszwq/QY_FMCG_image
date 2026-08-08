# EXECUTION-LOG

## 2026-08-09 T0
- 现场：HEAD e95e3ca；0 SAM 残留进程；分割 20,338 masks（47.7min，exit 正常）；
  decoder v2 loss 0.1145/0.0988；脚本 sha：train_sam_decoder=1928a2e8…，
  run_sam_crop_seg=8593eb84…。
- 判定：两 run 均 SOURCE_SNAPSHOT_UNPROVABLE（启动时无源码快照）。
- 服务 8091/8092/8300/8400 健康；SQLite integrity ok；bundle 未切换。
- 文档目录 + 六件套建立；AGENT-EXECUTION-PROMPT 原样保存。

## 2026-08-09 实施记录（P0-1..P0-5, §5-§14）

- P0-1 soft Dice：tests/unit/test_sam_soft_dice.py 7 绿；sam_losses.py；
  v1/v2 run 标记 EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE +
  SOURCE_SNAPSHOT_UNPROVABLE。
- P0-3 grouped split：9,736 leakage groups；旧分类器 random val 82.4% vs
  grouped val **34.7%**（Δ47.7pp 泄漏偏差）；grouped 重训 val 30.7%（诚实基线）。
- P0-4 真实检索链：38 样本 OCR→embedding→KB top-8；gt_in_kb=0（KB 仅 27 三得利系，
  百事系覆盖 0）→ recall@k=null（分母 0 诚实 null）；p95 75.3s。
- P0-5 leases：5 绿；benchmark 门控并发 2（≥25% 且停止线全过）；未实测组合并发→并发=1。
- §5 Tier：B=31/C=7/D=45/A=0；head-tail gap 235；policy hash 入
  reports/nextgen_v2/sku_data_readiness_policy_v1.json。
- §7：flow_supersession_v1（m024）两条 SUPERSEDED_FOR_DEMO_TRAINING；500 行未删。
- §8：LS 19/20 taxonomy 补 45 pending〔pending-new-packaging〕；
  registry 208⊆taxonomy ✓；mapped 38/38、pending 45/45 可见；越界 0。
- §9：四 snapshot v3 冻结 hash：det 684aeb06…/seg ba2ab49a…/cls 20a2850e…/vlm d723617c…。
- §10：M3 grouped 重训 10ep 671.6s val 30.7%；M1/M2 smoke、M4 pilot 既有。
- §11/12：AgentRegistry 4 内置 Agent；blackboard append-only 6 绿；memory ACL/supersedes。
- §13：SupervisorDrawer（黄色抽屉）+ TaskBoard 五列；浏览器 QA 全过，console 无 error；
  截图 .eval/sltf_drawer_open.png / sltf_taskboard.png / sltff_training…（见 .eval/）。
- §14：7 profiles；production_legacy 唯一 enabled；其余 disabled+blocker。
- 全量：**1095 passed, 1 skipped, 6 deselected**；tsc 干净；vite build 成功。
- 8400 重启加载 agents API（/api/v1/agents 4 agents；/api/v1/taskboard 五列）。
