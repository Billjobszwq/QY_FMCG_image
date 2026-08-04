# SAM 辅助重标注专项 · 状态

> 执行手册：`docs/superpowers/plans/2026-08-04-sam-assisted-reannotation-quality-filter-retraining.md`
> 最后更新：2026-08-04

## 当前阶段

- 阶段：**awaiting_human_review** —— 机器侧全部就绪，人工双审/盲抽未开始，不伪造结果、不启动训练
- 当前 Gate：**双审**（S0 ✅ / Q0 ✅批量演示 / S1 依赖人工对照）
- 分支：`feat/sam-reannotation`；提交链 db21bdd→bcd7576→a0f8b5d→8d1c11f→04f2c30→6e862a9→892624d→审核队列+评估器+数据集守卫
- 测试：170 passed

## 人工审核任务（awaiting_human_review）

- 队列文件：`.review_queue/review_queue_diag_v1.json`（250 项全部 pending）
- 待审核量：**250 张**（double_review 200 + blind_manual 50，seed=20260804）
- 任务链接：LS 容器不可用（docker pull 被 registry 拒绝，见 ISSUES SAM-002）；离线 payload 在 `.sam_runs/ls_import_*/ls_payload.json`，LS 恢复后导入项目 `sam_reannotation_diag_v1`（端口 8300）
- 阻断原因：人工双审与盲抽对照尚未开始；完成后才能导出 `diagnostic_v1_truebox_v1` 并重评 E0/P0/P1
- Gate D0 / E3 pilot 全部被阻断，不启动（用户要求#21/#26）


## 门禁状态总览

| Gate | 内容 | 状态 |
|---|---|---|
| 预检 | 文档通读 + 基线核对（74 测试 / bundle 16 文件） | ✅ 通过 |
| S0 | SAM 模型准入（MPS 门禁 + 5 张 smoke + 50 张/1000 点 benchmark，选最小达标模型） | ✅ PASS：选 sam2.1_hiera_small |
| S1 | SAM 标注质量（耗时降 40%、IoU≥0.75 候选≥90%、合并错误<5%、严重错框<0.5%） | ⬜ awaiting_human_review（需人工对照 50 张/1000 实例） |
| Q0 | 质量过滤（四级分流，reject precision 优先，单项弱指标不得自动 reject） | ✅ 已实现+校准（qa_v3）+120 张批量演示：accept 92 / manual_review 28 / reject 0 |
| 双审 | diagnostic_v1 前 200 张人工双审 + 50 张盲对照 | 🔴 awaiting_human_review（0/250 完成，队列已生成） |
| D0 | 2300 张审核 100%、抽检严重错标<0.5%、五键 0 泄漏、train/val 交集 0 | ⬜ 阻断于双审 |
| E3 | 3ep pilot（唯一变量=标签质量） | ⬜ 阻断于 D0（builder+守卫已就绪，fail-closed） |

## 机器侧已完成（等待人工输入）

- SAM 隔离 worker + prompts/candidates/scoring/evidence 契约（TDD）
- LS 导入（仅 prediction，从不写 annotation）+ 离线 payload
- 四级质量流水线（qpol_v1 / qa_v3，calibration_v1 校准，禁用 diagnostic 调阈）
- 人工双审队列生成器（前200双审 + 固定 seed 盲抽50，全部 pending）
- 真实框统一评估器（one-to-one matching，IoU .50/.75，recall@FP1/3/5，10 类错误账本）
- e3 truebox 数据集 builder + 守卫契约（同 e2 split、绝不覆盖、审核100%、五键、门店/session 隔离）

## 完成比例

- 机器侧实现：100%（T1–T10 代码/测试/驱动全部就绪）
- 人工环节：0%（双审 0/200，盲抽 0/50）

## 阻断项

- **硬阻断：人工双审与盲抽对照未开始**（状态 awaiting_human_review，不伪造、不继续训练）。
- LS 容器不可用（SAM-002）：离线 payload 已落盘，恢复后导入。
- 检测器对近拍单品照无输出（SAM-003）；硬约束通过率低的点源限制（SAM-004）。

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
