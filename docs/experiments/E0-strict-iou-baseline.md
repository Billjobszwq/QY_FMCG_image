# E0 严格 IoU 基线（dev_v2，G5 口径纠正版）

- experiment_id: E0-strict-iou-baseline
- bundle: `prod_20260804_v4_r2`
- code_commit: `409a56a256dea8d848b55c22c89d3884436c78ba`
- 评估集: `.data_protocol/dev_v2.json`（n=801）
- 匹配口径: 严格 one-to-one IoU ≥ 0.5（GT 框 = 锚点 + SKU 比例盒，与训练标签同一生成规则）
- detector conf: 0.18
- 阈值: conf=0.6 / margin=0.05（来源: {'conf': 'bundle', 'margin': 'code_default'}）
- 耗时: 64.8s

## 指标（G5 口径）

| 指标 | 值 |
|---|---:|
| 检测覆盖（IoU≥0.5 匹配） | 23.5% |
| business accepted precision（含 FP） | **59.2%** |
| matched precision（旧口径，仅诊断） | 93.1% |
| 端到端召回（accepted 且正确 / GT） | 19.9% |
| FP / 照片 | 3.684 |
| 照片全对率（exact-set） | 0.0% |
| count MAE | 16.873 |

## 错误账本

{
  "missed_detection": 15563,
  "classifier_confusion": 246,
  "fp_accepted": 2490,
  "known_false_reject": 410,
  "fp_review": 461,
  "unknown_false_accept": 54,
  "unknown_review": 20
}

## 口径说明（G5）

business accepted precision 分母 = accepted_correct + accepted_wrong +
unknown_false_accept + **fp_accepted**（旧口径漏掉 fp_accepted，会高估发布就绪度）。
本报告不覆盖旧 E0 产物，两份并存供对照。
