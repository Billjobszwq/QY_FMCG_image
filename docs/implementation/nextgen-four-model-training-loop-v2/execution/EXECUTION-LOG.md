# NextGen V2 · EXECUTION-LOG

## 2026-08-08 Task 0 基线纠偏

- 分支 `feat/nextgen-training-cycle-v2`（起点 `ce6f614`，与任务书基线一致）。
- fresh 测试：本机默认 **1010 passed, 1 skipped, 5 deselected**（MPS 真实可用）；
  Codex 受限环境 8 失败不可在本机复现（宿主 Metal 真实可用），按 01 审计定位
  宿主耦合点并 hermetic 化：
  - tests/platform/test_m5_training_gov.py：svc fixture 注入 G0 pass；
    test_training_api_e2e monkeypatch service.run_mps_g0；
  - tests/unit/test_sam_runtime.py：宿主探针测试标 host_mps + 新增注入 mock 等价测试。
  - 修复后：默认 **1010 passed, 6 deselected**；host suite **6 passed**。
- 数据源三方定位（N2-D1）：批1 `.training_data/manifest.json` 2,947/84,459；
  批2 `.eval/batch2/manifest.json` 6,510/174,249；批3 `第三批训练数据.xlsx`
  571,404 行（表头 ID/SCode/SName/CreateTime/ItemName/TypeName/TypeValue/URL/费用/
  name/code/x/y...，photo_id=ID 列，SKU=name 列）；批3 SHA 源 `.batch3_clean/clean_manifest.json`
  22,659 条。一/二批与任务书预期精确一致。
- 原图本地目录：照片1106（213）/照片1107（489）/百事&可口（341）为小样本；
  三批全量原图经 URL 或 CAS/blobs 获取（批3 blobs 在 .batch3_clean/blobs）。
  批1/批2 原图落地情况待 Task 3 对账（sha256 字段在 manifest image.sha256）。
- 服务/DB/bundle：8091 prod_20260805_v5_r1；8092/8300/8400 健康；
  platform.sqlite integrity ok（migration 022）。
