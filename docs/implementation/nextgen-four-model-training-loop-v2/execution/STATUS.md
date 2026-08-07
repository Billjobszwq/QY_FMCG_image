# NextGen 四模型训练闭环 V2 · STATUS

> 任务书：`docs/implementation/nextgen-four-model-training-loop-v2/`（V2.0-frozen）
> 分支：`feat/nextgen-training-cycle-v2`（基线 `ce6f614`）

| 项 | 值（2026-08-08 现场重验） |
|---|---|
| 当前状态 | Task 0 完成：基线纠偏 + hermetic 分层关闭；数据源三方定位完成 |
| 测试 | 默认 hermetic **1010 passed, 1 skipped, 6 deselected**；host MPS suite **6 passed**（Codex 环境 8 失败的宿主耦合已 hermetic 化：test_m5 svc fixture/API e2e 注入 G0，test_sam_runtime 真实探针移 host_mps + hermetic mock 版） |
| 生产 bundle | `prod_20260805_v5_r1` 未切换 |
| 数据源 | 批1=`.training_data/manifest.json`（2,947/84,459 点）；批2=`.eval/batch2/manifest.json`（6,510/174,249 点）；批3=`第三批训练数据.xlsx`（571,404 坐标行）+ `.batch3_clean/clean_manifest.json`（22,659 SHA）+ `照片1106/照片1107/百事&可口` 本地原图 |
| Cycle | DRAFT（持久化 cycle 待 Task 1） |

## Gate
进行中。最终状态只能是任务书规定的五种之一。
