# 03 SAM 与四模型设计

## SAM 角色拆分（P0-2）
- SAM Teacher：生成 mask/tight box/context crop/证据（冻结）；
- YOLO-seg Student（M2）：学通过质量门的 SAM 伪 mask；
- SAM Adapter/Decoder Experiment：仅人工 mask gold 或独立人工评估后可成候选。
演示训练 evidence level = `pseudo_mask_interim`。
SAM loss：soft Dice（可导）+ BCE；二值 Dice 仅作 metric（P0-1）。

## 四 Lane
- M1 Detector：单类 product；公开 base；按尺寸/密度/遮挡/反光/场景/角度分桶；
  旧生产 = baseline/proposal teacher。
- M2 Segmenter：轻量 YOLO-seg student；按形状/边界/遮挡/密集/截断/透明反光分桶。
- M3 Classifier：共享主干 → 粗粒度头（族/品牌/容器/容量）→ 细粒度头
  （canonical SKU/package）→ 混淆族 specialist → unknown/abstain。
  消融 pilot（同 split 同预算，逐一叠加）：CE baseline / class-balanced loss /
  balanced sampler / logit-adjust or focal / metric-prototype 辅助。
  按 macro-F1、尾部 recall、校准、accepted precision 选方案。
- M4 Qwen3-VL 4B：mlx-vlm 实装能力为准；vision 冻结；真实检索 CandidateSet；
  按 Tier 平衡 episode；hard negatives；unknown/new-packaging/abstain；独占 lease。
