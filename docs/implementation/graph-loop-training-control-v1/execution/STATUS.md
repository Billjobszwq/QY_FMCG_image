# Graph+Loop Training Control V1 · STATUS

> 任务书：`docs/implementation/graph-loop-training-control-v1/`（00/01/02/03 + AGENT-EXECUTION-PROMPT）
> 基线：分支 `feat/unified-workbench-training-readiness`，HEAD `c1d1d6f`（现场核验一致）

| 项 | 值（2026-08-08 现场重验） |
|---|---|
| 当前状态 | Task 0 执行中：现场基线复核完成，执行账本已建立 |
| 测试基线 | 普通 Terminal 全量 **914 passed, 1 skipped**（无 MPS 失败；Codex 受限环境的 10 个失败为宿主探针环境限制，见 EXECUTION-LOG T0） |
| 生产 bundle | `prod_20260805_v5_r1`（CURRENT.json 现场核验），本轮不切换 |
| DB | `.platform/platform.sqlite` integrity_check=ok；migration 至 019 |
| 训练 | 无活动训练；training_run 表 4 行历史 dry-run（含旧 `--dataset/--budget-minutes`，待追加式 legacy 标记）；training_authorized=false |
| 人工链 | rq_v2 active 250；LS 19 assisted（无 proposal，待接生产 bundle）/ 20 blind（零 prediction）；gold_region_v1=0 |
| 服务 | 8091 ✅ / 8092 ✅ / 8300 ✅；8400 degraded（唯一原因：ml_backend 8301 不可用 → 决策 D1 收敛 proposal 写入口到平台识别能力） |
| 受保护目录 | `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不触碰 |

## Gate

当前 Gate = 机器侧框架建设进行中；完成后合法 Gate 只能是
`FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION`。
不得宣称训练完成；不得启动真实全量训练；不得切换生产 bundle。
