# 00 泄漏根因审计（复现）

## M4 v2 holdout 来源组泄漏
复现：holdout 84 唯一来源组 vs QLoRA real-candidate 训练集 565 组 →
重叠 24（28.6%）。0.828 降级 EXPERIMENTAL_GROUP_LEAKED_EVALUATION（保留不删）。

## 项目 21 五键门禁缺失
build_demo_micro_gold_v1.py 仅比较输出 crop SHA；同源裁剪 SHA 必然不同 →
不能证明独立。canonical/hard/negative 为构建器命名，无质量/溯源证据。
→ SUPERSEDED_INVALID_INDEPENDENCE_AUDIT；标题 [SUPERSEDED-DO-NOT-REVIEW]。

## Artifact 数量
上轮报告 16 错；DB/API 实时 15（本轮起以实时对账为准，现 16 含新登记）。
