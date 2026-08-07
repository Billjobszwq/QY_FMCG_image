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

## 2026-08-08 本轮执行记录（Task 0–15 机器侧）

### 基线与纠偏（Task 0）
- 分支 `feat/nextgen-training-cycle-v2`（起点 ce6f614）。
- 本机 fresh：**1077 passed, 1 skipped, 6 deselected**（hermetic）；host_mps suite 独立。
  Codex 8 失败根因 = 宿主 MPS/sysctl 耦合；已 hermetic 化（G0 注入 + host_mps marker），
  不删测试不放宽断言。
- 服务：8091 prod_20260805_v5_r1 ✅；8400 已加载新控制面 API ✅；8092/8300 ✅。

### 数据链（Task 3/4/5）
- 三批对账：批1 2,947/84,459、批2 6,510/174,249、批3 22,664/571,404；
  **canonical points = 745,695 精确一致**；exact unique = 29,171（任务书 29,176，
  差额 5 = 批3 反光 reject 无 blob/SHA，已入缺失账本，不静默吞差）。
- 476 坐标差异实测 463（全为点数不同），ledger 已生成
  （reports/nextgen_v2/coordinate_discrepancy_ledger.json）。
- 批1/2 原图 URL 失效（返回 HTML 登录页）→ N2-ISSUE-004，等待用户提供数据访问；
  其坐标保留为 legacy_coordinate_verified。
- 严格质量全扫批3 22,659 图：hard_valid 22,652 / manual_review 5 / rejected 2
  （qpol_n2_v1 自动结论；人工校准门 ≥1,000 张待人工）。
- SKU 身份：745,695 点全量映射：mapped 705,104；other 22,650 / 百事other 9,720 /
  可乐other 8,216（不强映射）；alias_pending 5 点（2 个具体名待人工裁决）。

### SAM 数据引擎（Task 6）
- 点提示引擎（正点+ROI 负点+局部 box，几何门 fail-closed，断点续跑）；
  bounded 生成：894 照片 **5,981 accepted / 26 rejected**（99.6%），
  sam_verified_pseudo（非 gold）。mask audit ≥2,000 人工门待人工。

### 四 Snapshot（Task 7）
- D1 d1_detector_smoke_v1：894 图/5,981 SAM tight box（hash 33f55edb…）
- D2 d2_segmenter_smoke_v1：894 图/5,981 polygon（hash 65923cba…）
- D3 d3_classifier_smoke_v1：5,860 crops/201 类（hash b58288f1…）
- D4 d4_vlm_smoke_v1：200 samples mlx-vlm messages 格式（候选占位检索，禁 GT 签名）
- 契约测试：label tier 权重、pseudo 禁入 eval、五键零泄漏、原子发布（12 绿）。

### 四模型真实训练 smoke（Task 12，全部真实执行）
- M1 detector：yolo11n.pt(public) 1 epoch，63s，~3.5 it/s，mAP50=0.0035（smoke 口径），
  制品 sha 8d16bcac9e83ec8c。
- M2 segmenter：yolo11n-seg.pt(public) 1 epoch，80.4s，制品 sha 88d44c429be6ca49。
- M3 classifier：ResNet18 ImageNet(public) 1 epoch，39.6s，val_top1=0（smoke），
  制品 sha c2458cf803e7797a。
- M4 Qwen QLoRA：mlx-community/Qwen3-VL-4B-Instruct-4bit，2 iter，
  loss 9.70→6.23，峰值内存 6.16GB，tokens/s 360，adapter 真实产出
  sha 9bbcbf73561f6bc5（mlx_vlm 0.6.10，隔离 venv，MLX 独占）。
- 全部 candidate=false、evidence_level=smoke_pseudo_interim；正式 pilot/candidate
  需 mask audit + human gold + 单独授权。

### 控制面（Task 1/2/8/9/11）
- migration 023：cycle/node/event/plan/approval/run_attempt/artifact_v2/
  resource_benchmark_v1/recognition_profile_v1（事件与 artifact 禁删改）。
- TrainingCycleService：乐观版本、非法跃迁审计、幂等键、checkpoint 恢复。
- 四 Launcher：白名单、冻结 hash、G0 重跑、heavy lease、safe-stop 证据链。
- API：cycles/data-scope/quality/sam/snapshots/plans/approve/safe-stop/
  artifacts/resource-benchmarks/recognition-profiles（session+CSRF）。
- Recognition Profiles：5 个（production_legacy enabled，其余 disabled+blocker）。
- Apple 资源决定：**heavy concurrency=1**（未做组合并发实测，保持保守；
  四个 smoke 顺序执行，MPS/MLX 互斥经 lease；Qwen 独占 MLX）。

### 未完成/等待人工（诚实记录）
- Task 10 Web 七工作区：仅既有 TrainingControl 卡片 + profiles API；
  数据准备/SAM/Lineage/RunDetail/GraphRun 专属页面未建（下一轮）。
- 组合并发 benchmark 未实测（保持 concurrency=1）。
- 质量校准门（≥1,000）、mask audit（≥2,000）、5+5 验收、250 放量：全部待人工。
- 批1/2 原图缺失（N2-ISSUE-004）。
