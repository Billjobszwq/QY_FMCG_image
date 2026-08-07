# Project Logic Chain V3 · STATUS

> 任务书：2026-08-07 主实施 Agent 任务（断链修复 + 逻辑链统一 + gold review v2）
> 实施计划：`docs/superpowers/plans/2026-08-07-project-logic-chain-and-gold-review-v2.md`

| 项 | 值（2026-08-07 现场重验） |
|---|---|
| 当前状态 | S1 文档基线建立；P0 根因现场复现完成；等待红测试 → 修复序列 |
| HEAD | `7b2e268`，分支 `feat/unified-workbench-training-readiness` |
| 测试基线 | 819 passed, 1 skipped（miniconda python3，21.33s） |
| 生产 bundle | `prod_20260804_v4_r2` 未切换（production_switch=false） |
| 训练 | 未启动任何重训练；无 YOLO/QLoRA/classifier 进程 |
| 服务 | 8092 ✅ / 8400 ✅ / 8300 ✅（LS）/ 8091 存活（/health 返回 not found，健康端点待核） |
| DB | .platform/platform.sqlite integrity_check=ok；migration 001–018 齐全 |
| 审核现状 | review_task_v1 = 250（rq_v1，**ID/SHA 配对 0/250 错误**）；review_event_v1 = 1（1 claim）；gold_region_v1 = 0 |

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

当前 Gate = **P0 错配修复 + rq_v2 发布**；人工 250 审核放行前必须先过 5+5 小规模验收。
