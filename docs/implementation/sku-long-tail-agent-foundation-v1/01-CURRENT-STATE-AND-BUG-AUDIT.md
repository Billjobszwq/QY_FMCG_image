# 01 现场状态与 Bug 审计（2026-08-09 重验）

## 现场事实
- HEAD `e95e3ca`，分支 `feat/nextgen-training-cycle-v2`；工作树仅受保护未跟踪资产。
- 两个 SAM 进程已**自然完成**（0 残留）：
  - 分割：20,338/20,338 masks，47.7min，exit 正常，日志完整；
  - decoder v2：1 epoch，train 0.1145 / val 0.0988，artifact 在位。
- **SOURCE_SNAPSHOT_UNPROVABLE**：两次运行启动时未保存 source commit/dirty diff/
  launcher hash → 不能用最终工作树脚本解释运行结果；v1/v2 均标记
  `EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE`，不删除不发布。
  今后每次训练 run artifact 必含：source commit、dirty diff hash、launcher source hash、
  resolved command、environment lock、data manifest、base model hash、config、seed。
- 服务：8091/8092/8300/8400 健康；SQLite integrity ok；production bundle 未切换。
- 83 类 / 20,338 crops；38 映射 / 45 pending；旧分类器 top1 83.3%（随机切分，偏乐观）。

## P0 Bug 清单
| ID | Bug | 状态 |
|---|---|---|
| P0-1 | SAM Dice 用阈值二值化切断梯度，Dice 项不训练 decoder | 红测试+soft Dice 修复 |
| P0-2 | SAM 自蒸馏被当真实提升 | 角色拆分+pseudo_mask_interim |
| P0-3 | 裁剪图随机 9:1 切分泄漏 | leakage_group_id grouped split+重评对比 |
| P0-4 | Qwen 候选保证含 GT | 真实检索链+recall@k/abstain/escape 报告 |
| P0-5 | 并发训练无统一租约 | ResourceLease+benchmark 决策 |
