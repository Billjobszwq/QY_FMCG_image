# Graph+Loop Training Control V1 · STATUS

> 任务书：`docs/implementation/graph-loop-training-control-v1/`（00/01/02/03 + AGENT-EXECUTION-PROMPT）
> 基线：分支 `feat/unified-workbench-training-readiness`；本轮起点 HEAD `c1d1d6f`（现场核验一致）

| 项 | 值（2026-08-08 现场重验） |
|---|---|
| 当前状态 | **Task 0–12 机器侧全部完成 → Gate = FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION** |
| 测试基线 | 默认 hermetic **1010 passed, 1 skipped**（5 host 测试 deselected）；host MPS suite **5 passed** |
| 生产 bundle | `prod_20260805_v5_r1`（CURRENT.json 现场核验），本轮未切换；production_legacy 登记在案 |
| DB | integrity_check=ok；migration 至 022（新增 020 supersession / 021 training control v2 / 022 legacy registry） |
| 训练 | 未启动任何真实训练；training_run_v2 生产库 0 行；training_authorized=false；四 lane 全部诚实 blocked（gold=0） |
| 旧模型 | 14 模型只读 inventory + 不可变登记；文件零移动；证据 `.platform/legacy_model_inventory.json` |
| 人工链 | rq_v2 active 250；LS 19 = 1125 proposals + 13 no_proposal（append-only）；LS 20 零泄漏；gold_region_v1=0 |
| 服务 | 8091 ✅（prod v5_r1）/ 8092 ✅ / 8300 ✅ / 8400 **healthy**（ml_backend legacy/disabled，决策 D1） |
| Web | `/#/training` 新控制台：production legacy 与 nextgen 四 lane 视觉隔离；浏览器 QA 全过（截图 reports/gltc_web_qa_training_console.png） |
| 受保护目录 | `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 未触碰 |

## Gate

当前 Gate = **`FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION`**。

不是"训练完成"。下一步（人工）：
1. 完成 5+5 真人验收与 rq_v2 250 条审核，产生真实 human_final/gold_verified gold；
2. 四个 DatasetSnapshot 分别达到各自真值门（D3 需真实 mask gold 才可脱离 calibration）；
3. 用户对具体 TrainingPlan 单独授权后，才可提交真实训练 Job（一次一个 heavy lease）；
4. candidate 评估、shadow、发布保持独立审批；production switch 始终 false。
