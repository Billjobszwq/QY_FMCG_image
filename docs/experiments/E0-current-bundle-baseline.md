# E0 当前 bundle 基线（dev_v1，未见门店）

- experiment_id: E0-current-bundle-baseline
- bundle: `prod_20260804_v4_r2`
- code_commit: `3c0364e991077e3dfc03ea569c43d2cba3f52f07`
- 评估集: `.data_protocol/dev_v1.json`（n=800，与训练门店/SHA 零交集，seen_by_current_model=false）
- 阈值: conf=0.6 / margin=0.05（来源: {'conf': 'bundle', 'margin': 'code_default'}）
- 匹配口径: 一对一 point-in-box（宽松诊断口径，正式 IoU 评估为后续任务）
- 耗时: 76.4s

## 指标

| 指标 | 值 |
|---|---:|
| 检测覆盖（GT 被 proposal 覆盖） | 25.5% |
| accepted precision | 89.0% |
| 端到端召回（accepted 且正确 / GT） | 20.3% |
| 已匹配中进入 review 比例 | 10.5% |
| FP / 照片 | 3.174 |
| 照片全对率（exact-set） | 0.0% |
| count MAE | 16.875 |

## 错误账本

{
  "missed_detection": 15135,
  "classifier_confusion": 439,
  "fp_accepted": 2190,
  "known_false_reject": 501,
  "fp_review": 349,
  "unknown_review": 42,
  "unknown_false_accept": 70
}

## 决策

promote / iterate / stop：见报告讨论（本文件由脚本生成，结论人工补充）。
