# Graph+Loop Training Control V1 · STATUS

> 2026-08-08 复核纠偏：V1 保留为历史契约基线；下一实施入口已切换为
> `docs/implementation/nextgen-four-model-training-loop-v2/`。V1 尚未形成真实四模型执行闭环。

> 任务书：`docs/implementation/graph-loop-training-control-v1/`（00/01/02/03 + AGENT-EXECUTION-PROMPT）
> 基线：分支 `feat/unified-workbench-training-readiness`；本轮起点 HEAD `c1d1d6f`（现场核验一致）

| 项 | 值（2026-08-08 现场重验） |
|---|---|
| 当前状态 | **V1_CONTRACT_BASELINE_COMPLETE / REAL_EXECUTION_CHAIN_INCOMPLETE** |
| 测试基线 | 交付报告 1010 passed；2026-08-08 Codex fresh **1002 passed, 8 failed, 1 skipped, 5 deselected**，hermetic/host 分层未完全关闭 |
| 生产 bundle | `prod_20260805_v5_r1`（CURRENT.json 现场核验），本轮未切换；production_legacy 登记在案 |
| DB | integrity_check=ok；migration 至 022（新增 020 supersession / 021 training control v2 / 022 legacy registry） |
| 训练 | 未启动任何真实训练；training_run_v2 生产库 0 行；training_authorized=false；V2 写执行链未接通 |
| 旧模型 | 14 模型只读 inventory + 不可变登记；文件零移动；证据 `.platform/legacy_model_inventory.json` |
| 人工链 | rq_v2 active 250；LS 19 = 1125 proposals + 13 no_proposal（append-only）；LS 20 零泄漏；gold_region_v1=0 |
| 服务 | 8091 ✅（prod v5_r1）/ 8092 ✅ / 8300 ✅ / 8400 **healthy**（ml_backend legacy/disabled，决策 D1） |
| Web | `/#/training` 有 V2 只读卡片；可执行按钮仍属 Legacy 区，不能视为四 Lane 可操作控制台 |
| 受保护目录 | `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 未触碰 |

## Gate

当前 Gate = **`CONTROL_CONTRACTS_PRESENT_BUT_EXECUTION_CHAIN_INCOMPLETE`**。

不是"训练完成"。下一步按 V2 目录补真实数据、持久化 Graph、API/Worker、Web/Profile，
重新处理三批照片并在新任务书的统一授权与 Gate 下运行四个实验 candidate。
candidate 评估、shadow、发布仍保持独立审批；production switch 始终 false。
