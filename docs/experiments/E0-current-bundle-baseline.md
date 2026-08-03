# E0 当前 bundle 基线（dev_v1，宽松诊断口径）

> **2026-08-04 最终复核纠偏：** 本报告保留原始运行结果，但 `accepted precision=89.0%` 只是在已匹配 proposal 中计算的条件 precision，不是业务端到端 accepted precision。将 2,190 个未匹配但 accepted 的 FP 纳入分母后，业务 accepted precision 为 **60.45%**。dev_v1 还存在 2 个经 Unicode/中英文括号规范化后与 batch2 重叠的门店别名，因此不能继续写成严格“未见门店”。正式训练准入以 [`2026-08-04-final-training-execution-gate.md`](../superpowers/plans/2026-08-04-final-training-execution-gate.md) 为准。

- experiment_id: E0-current-bundle-baseline
- bundle: `prod_20260804_v4_r2`
- code_commit: `3c0364e991077e3dfc03ea569c43d2cba3f52f07`（仅记录运行时 HEAD；E0/协议代码当时仍有未提交工作树，后续归入 `3f13fa6`，故不能只凭该字段完整复现代码）
- 评估集: `.data_protocol/dev_v1.json`（n=800；内部协议集间 ID/SHA/精确门店零交集，但有 2 个规范化门店别名与 batch2 重叠）
- 阈值: detector conf=0.18；classifier conf=0.6 / margin=0.05（来源: conf=bundle，margin=code_default）
- 匹配口径: 一对一 point-in-box（宽松诊断口径，正式 IoU 评估为后续任务）
- 耗时: 76.4s

## 指标

| 指标 | 值 |
|---|---:|
| 检测覆盖（GT 被 proposal 覆盖） | 25.5% |
| matched-conditional accepted precision | 89.0% |
| business accepted precision（含 unmatched accepted FP） | **60.45%** |
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

业务 accepted precision 的复核计算：

```text
4126 / (4126 + 439 + 70 + 2190) = 60.45%
```

其中 4,126 为 accepted correct，439 为 classifier confusion，70 为 unknown false accept，2,190 为未匹配 GT 的 accepted FP。

## 决策

promote / iterate / stop：**iterate，禁止 promote**。该结果用于定位检测覆盖和误接受瓶颈，不满足严格 IoU、严格未见门店或发布指标要求。
