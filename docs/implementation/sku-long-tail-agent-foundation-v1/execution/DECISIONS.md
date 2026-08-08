# DECISIONS

- D1：v1/v2 SAM decoder = EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE +
  SOURCE_SNAPSHOT_UNPROVABLE；不删不发布。
- D2：今后 run artifact 九要素（source commit/dirty diff/launcher hash/resolved command/
  env lock/data manifest/base hash/config/seed）写入 run 目录 manifest。
- D3：SAM loss = BCE + soft Dice（可导）；二值 Dice 仅 metric。
- D4：leakage_group_id = hash(原始照片 or SHA or near-dup or 门店@session@连拍@package)；
  裁剪图无法恢复来源 → fail-closed 出验证集，仅可训练。
- D5：Qwen 候选 = crop→OCR/embedding→KB 检索→排序；禁 GT 入参；候选不含 GT 时允许 abstain。
- D6：MPS heavy 并发 1；组合吞吐 ≥25% 且停止线全过才 2；MLX 永远独占。
