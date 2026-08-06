# Qwen3-VL 级联 Shadow 评估报告（占位：真实运行被门禁阻断）

- 日期：2026-08-01
- 分支：`feat/unified-workbench-training-readiness`
- 评估器版本：`cascade_shadow_v1`
- 状态：**真实 shadow 运行未执行**，本报告只记录评估方法、账本 schema、
  对照臂定义与晋级门；任何数字指标均未产生，不得据此晋级或发布。

## 1. 为什么没有真实数字

1. `sku_v7_sam` 训练仍在 Apple MPS 上运行。`shadow_execution_gate`
   检出活跃训练进程/租约时返回 `BLOCKED_BY_ACTIVE_TRAINING`，真实
   shadow 批量推理被 G-CURRENT 门禁拒绝。
2. MLX 未安装、`mlx-community/Qwen3-VL-4B-Instruct-4bit` 权重未下载
   （G-APPLE 未通过，用户未授权下载）。C2 臂无法真实运行。
3. 人工真值（truebox + SKU 人工核对）尚未建立足够规模；在人工真值
   不足时，`promotion_gate` 只能返回 `not_evaluable`，不得造 pass。

## 2. 四套对照臂定义（`define_arms`）

| 臂 | 内容 | 发布资格 |
|---|---|---|
| E0 | 当前生产 bundle | publishable_baseline=True（唯一现行生产） |
| E1 | sku_v7_sam experimental | 不发布 |
| C1 | S1–S3 级联，无 Qwen | 不发布 |
| C2 | S1–S4 级联，`qwen3-vl:4b` adapter | 不发布 |

四臂必须共享同一 `frozen_data_hash`、`registry_hash` 与 region
matching（one-to-one IoU，默认阈值 0.5）；`validate_arms` 在任何一项
不一致时拒绝评估。

## 3. 逐实例账本（`build_ledger`）

每条预测/真值入账一类标签：`correct_accepted`、`misclassification`、
`duplicate_box`、`background_fp`、`missed_truth`、`abstain`、
`unknown`、`new_package`、`manual_review`；同时记录 `latency_ms`、
`cost`、配对 IoU、人工真值标志。

指标口径（`evaluate_arm`）：

- `accepted_precision` 与 `coverage` 必须同时出现在结果中；
- coverage = 已配对人工真值 / 人工真值总数（含 abstain 配对）；
- `fp_per_photo`、`human_rate`、`p95_latency_ms`、`total_cost`、
  `unknown_or_new_rate` 全部汇总。

## 4. 晋级门（`promotion_gate`，默认批准线）

| 指标 | 线 |
|---|---|
| accepted precision | ≥ 0.95（专家档目标） |
| coverage | ≥ 0.90（必须与 precision 同时报告） |
| FP/photo | ≤ 0.10 |
| p95 延迟 | ≤ 12000 ms |
| 总成本 | ≤ 1000 |
| 人工率 | ≤ 0.20 |
| unknown+new_package 率 | ≤ 0.10 |
| 人工真值下限 | ≥ 20 条，否则 not_evaluable |

正式晋级前，阈值必须以独立审批文件为准；本表只是代码默认值。

## 5. 运行方式（真实执行被阻断）

```bash
# 纯计算（允许）：从已产出的账本 JSON 计算指标
python3 -m scripts.run_cascade_shadow_eval --mode evaluate \
    --input <ledger.json> --output <report.json>

# 真实运行（当前被阻断）：
python3 -m scripts.run_cascade_shadow_eval --mode run
# → 训练存在时退出码 2：BLOCKED_BY_ACTIVE_TRAINING
# → 无授权时退出码 3；授权但 MLX 未安装时退出码 4（G-APPLE fail-closed）
```

## 6. 结论

- 评估计算、四臂对照、晋级门与执行门禁已实现并有 27 项测试覆盖；
- 真实 shadow 运行状态：`BLOCKED_BY_ACTIVE_TRAINING`；
- 晋级状态：`not_evaluable`（人工真值不足，不得造 pass）；
- production bundle 保持 E0 不变，`production_switch=false`。
