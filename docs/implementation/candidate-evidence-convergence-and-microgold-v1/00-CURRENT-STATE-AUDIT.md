# 00 基线审计（2026-08-10，禁沿用旧数字）

HEAD 6d51460d；worktree 干净；Cycle=EVALUATED_CANDIDATES_READY_AWAITING_MICRO_GOLD（待纠正起始）；
投影 19；m3_tvt_e1/e5_v2=CANDIDATE_PENDING_EVALUATION（应 MICRO_GOLD 档）；
m3_ablation_e1/e5_v1=CANDIDATE_PENDING_EVALUATION（应 SUPERSEDED）；
M4 new=CANDIDATE_PENDING_MICRO_GOLD（证据不足待复核）；
profiles DB=7 vs API=10（双源冲突）；evaluation_registry=8（缺 M3 tvt 两项+M4 复核）；
taskboard m3_independent_test/m4_adjudication_eval=waiting（P1-1）；
M4 旧报告 tokens=0/p95 0.2-0.3s/无 raw output（P0-2）；
hermetic 上轮本机全绿但任务书指 3 测试 MPS 耦合（P1-2，需红测试复现）；
抽屉 KB blocker 过期显示（P1-3）。
