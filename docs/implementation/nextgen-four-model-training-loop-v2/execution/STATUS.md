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


---

## 2026-08-08 本轮收口状态

| 项 | 值 |
|---|---|
| 分支 | `feat/nextgen-training-cycle-v2`（起点 ce6f614，HEAD 见 git log） |
| 测试 | hermetic **1077 passed, 1 skipped, 6 deselected**；host_mps 独立 suite；tsc 干净；vite build 成功 |
| 数据对账 | canonical points **745,695 ✓**；exact unique 29,171（29,176 差 5 = 批3 反光 reject，已入账本）；坐标差异 463 张已入账本 |
| 质量 | 批3 22,659 图全扫：hard_valid 22,652 / manual_review 5 / rejected 2（人工校准门待人工） |
| SAM | bounded 生成 894 图 / **5,981 accepted**（sam_verified_pseudo，mask audit 待人工） |
| 四 Snapshot | D1/D2/D3/D4 smoke 版已物化（manifest hash 齐全，目录存在拒绝） |
| 四模型 smoke | M1 63s / M2 80.4s / M3 39.6s / M4 Qwen QLoRA 2 iter（全部真实执行、制品 sha 登记、candidate=false） |
| 控制面 | migration 023 + Cycle/四 Launcher/控制 API/5 Profiles（生产 API 已加载） |
| Apple 资源 | heavy concurrency=1（保守决定）；MPS/MLX 互斥经 lease；Qwen 独占 |
| 生产 | prod_20260805_v5_r1 未切换；无 candidate 发布 |

**Gate = `WAITING_FOR_HUMAN_GATE`**

机器侧可自动完成的闭环（对账/质量/SAM/四快照/四 smoke/控制链）已完成；
后续全部依赖人工门：① 质量校准抽检 ≥1,000；② SAM mask audit ≥2,000 双审；
③ 5+5 验收与 250 放量产生 human gold；④ 批1/2 原图数据访问（N2-ISSUE-004）；
⑤ 具体 TrainingPlan 的单独授权。未达条件前不启动正式 pilot/candidate。
