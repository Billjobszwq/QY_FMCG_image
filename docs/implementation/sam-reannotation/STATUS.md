# SAM 辅助重标注专项 · 状态

> 执行手册：`docs/superpowers/plans/2026-08-04-sam-assisted-reannotation-quality-filter-retraining.md`
> 最后更新：2026-08-01

## 当前阶段

- 阶段：S0 准备（文档/基线完成 → 开始 TDD 契约）
- 当前 Gate：**尚未进入 Gate S0 执行**（SAM 环境/checkpoint/smoke 均未开始）
- 分支：`feat/sam-reannotation`（自 main @ 3f55991 切出）

## 门禁状态总览

| Gate | 内容 | 状态 |
|---|---|---|
| 预检 | 文档通读 + 基线核对（74 测试 / bundle 16 文件） | ✅ 通过 |
| S0 | SAM 模型准入（MPS 门禁 + 5 张 smoke + 50 张/1000 点 benchmark，选最小达标模型） | ⬜ 未开始 |
| S1 | SAM 标注质量（耗时降 40%、IoU≥0.75 候选≥90%、合并错误<5%、严重错框<0.5%） | ⬜ 未开始 |
| Q0 | 质量过滤（四级分流，reject precision 优先，单项弱指标不得自动 reject） | ⬜ 未开始 |
| 双审 | diagnostic_v1 前 200 张人工双审 + 50 张盲对照 | ⬜ awaiting_human_review |
| D0 | 2300 张审核 100%、抽检严重错标<0.5%、五键 0 泄漏、train/val 交集 0 | ⬜ 未开始 |
| E3 | 3ep pilot（唯一变量=标签质量） | ⬜ 未开始（需 D0 全过） |

## 完成比例

- 阶段 0（准备）：~90%（剩：六文档提交）
- 其余阶段：0%

## 阻断项

- 无硬阻断。
- 待办依赖：SAM 2.1 checkpoint 下载（hiera_small / hiera_base_plus）需要网络。
- 人工环节（双审/盲对照）需要真实人工参与，机器侧完成后状态写 `awaiting_human_review` 并给出任务链接与待审数量。

## 基线事实（2026-08-01 核对）

- HEAD(main) = `3f559911f95d0e9d7215a031d1cd79cd649b6b80`
- 测试：74 passed（2.42s）
- 生产 bundle `prod_20260804_v4_r2` verify：ok，16 文件
- 生产 bundle 保持不变；classifier 训练继续暂停；不切换 8091。

## 关键约束速查（详见 DECISIONS.md）

- diagnostic_v1 只诊断，严禁训练/调参/hard-negative mining。
- SAM 输出 = LS prediction only；最终框必须人工确认 + 第二人审核。
- 禁止 `PYTORCH_ENABLE_MPS_FALLBACK=1`，禁止静默 CPU fallback。
- SAM 依赖装隔离 venv，不动主环境 torch/torchvision/ultralytics。
- 固定比例框（0.07×0.18）只作粗 ROI 与历史对照，不再当真实框。
- 原图永远保留；reject 仅"不可恢复"；困难可识别图保留为 hard-valid。
- 不删除、不覆盖历史制品、不恢复 v6、不自动发布。
