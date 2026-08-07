# NextGen V2 · DECISIONS

## N2-D1 三批数据源定位
- 批1：`.training_data/manifest.json`（2,947 照片 / 84,459 点，与任务书预期精确一致）。
- 批2：`.eval/batch2/manifest.json`（6,510 / 174,249，精确一致）。
- 批3：`第三批训练数据.xlsx`（571,404 坐标行 = 任务书预期）+ `.batch3_clean/clean_manifest.json`
  （22,659 photo_id→sha256；原始 22,664 中的 5 张反光 reject 只作历史对照）。
- canonical 规则（任务书 §2.2）：批2 优先、批1 补 2 张独有、批3 独立；476 张差异写 ledger。

## N2-D2 hermetic 纠偏方式
- 不删测试、不放宽断言：test_m5 svc fixture 与 API e2e 注入 mock G0；
  test_sam_runtime 宿主真实探针标 host_mps，并新增注入 mock 的 hermetic 等价测试。
- 真实宿主 G0 覆盖由 host_mps suite（6 条）独立保证。
