# Project Logic Chain V3 · STATUS

> 任务书：2026-08-07 主实施 Agent 任务（断链修复 + 逻辑链统一 + gold review v2）
> 实施计划：`docs/superpowers/plans/2026-08-07-project-logic-chain-and-gold-review-v2.md`

| 项 | 值（2026-08-07 现场重验） |
|---|---|
| 当前状态 | **S12b 完成：机器侧全部收口 → AWAITING_HUMAN_ACCEPTANCE**（12 步 commit 链完成 + API/批次门禁 active-only 残余断链已修；5+5 验收批已备，等待真人） |
| HEAD | 见 `git log`（分支 `feat/unified-workbench-training-readiness`；参考基线 7b2e268 → 本轮推进至 commit 链末尾 + S12b fix） |
| 测试基线 | 914 passed, 1 skipped（miniconda python3） |
| 生产 bundle | `prod_20260805_v5_r1`（8091 /v2/health 现场确认），本轮未切换 |
| 训练 | 未启动任何重训练；无 YOLO/QLoRA/classifier 进程（仅 omlx-server 与 8092 monitor） |
| 服务 | 8091 ✅ /v2/health；8092 ✅；8400 ✅（已重启加载统一状态源代码，日志 /tmp/platform_8400.log）；8300 ✅（LS） |
| DB | .platform/platform.sqlite integrity_check=ok；migration 001–019；备份 `.platform/backups/platform_before_rq_v1_invalidation.sqlite`（integrity ok） |
| 审核现状 | review_task_v1 = 500（rq_v1 250 **invalid 保留** + rq_v2 250 **active，250/250 配对**）；API active/history 分离（tasks-active=250 rq_v2；tasks-history=250 rq_v1 invalidated）；批次门禁只计 active；gold_region_v1 = 0 |
| LS | 项目 19 diag_v2_assisted（200）/ 20 diag_v2_blind（50）；旧项目 1/10~13 保留未动；blind 抽样 5/5 零泄漏 |
| 验收批 | `.review_queue/acceptance_batch_5plus5.json/.md`：5 assisted + 5 blind（2 组同图对照）；**AWAITING_HUMAN_ACCEPTANCE** |

## 本轮核心目标

1. 修复 diagnostic_v1 photo_id/sha256 独立排序 + 按位置 zip 造成的全链错配（P0）。
2. rq_v1 追加式失效（invalid_id_sha_mapping），发布正确 rq_v2（250/226/24 设计保留）。
3. 统一审核状态源：review_task_v1 + review_event_v1 + active queue version（DB 推导，弃静态 JSON）。
4. gold_region 状态机修复：原子提交/合法 bbox/双审 IoU 匹配/区域级仲裁/身份隔离。
5. V2 接入 Label Studio 新项目（不动 10~13），前端 regions 完整提交。
6. gold_region → diagnostic_v1_truebox_v2 正式不可变导出器，run_truebox_eval 直接消费。
7. zero-shot canonical identity 链（禁展示名比较）。
8. 5+5 小规模验收批 → AWAITING_HUMAN_ACCEPTANCE（真实框必须人提交，不伪造）。

## 红线快照

不删除/不覆盖历史制品；不改不可变表；不碰 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/`；
服务不中断；bundle 不切换；冻结集不进训练；prediction 不冒充 human_final；不降低门禁标准。

## Gate

当前 Gate = **AWAITING_HUMAN_ACCEPTANCE**：机器侧 15 项自检已完成，真实框与 SKU 结论必须由人提交（5+5 验收批链接见 `.review_queue/acceptance_batch_5plus5.md`）。250 条人工审核完成前：不启动任何训练、不做模型选择、不切换生产 bundle。
