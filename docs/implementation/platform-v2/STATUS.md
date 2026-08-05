# Platform V2 — 统一管理与训练准备 · STATUS

> 手册：`docs/superpowers/plans/2026-08-05-unified-management-all-photo-training-execution-manual.md`（当前唯一实施入口）
> 架构：`docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`（L0，不变）
> 审计纠偏：2026-08-05 复核发现 M5 的 true FP/photo、训练命令和 DatasetSnapshot 均未达到验收口径，因此 M5 由 DONE 改为 **REOPENED**；历史 EXECUTION-LOG 保留原记录并追加纠偏。

| 项 | 值 |
|---|---|
| 当前状态 | U0+U1+U2+U3 全部完成；U4-1/U4-2/U4-3 DONE + U4-4 机制 DONE（6baa389）；U4 剩余为真实人工审核 250 诊断批（waiting_human）；U5-1 Loop 内核 DONE（ef1b4e1）；下一步 U5-2 第一条真实 Loop E2E；训练仍 NO-GO |
| 当前 HEAD | 分支基点 `9db9946`；实时值以 `git rev-parse HEAD` 为准 |
| 分支 | `feat/unified-workbench-training-readiness`（基于 `9db9946`，审计文档改动随本分支提交） |
| 任务清单 | `docs/implementation/platform-v2/IMPLEMENTATION-LIST.md`（U0–U5/T0–T2 逐项：ID/依赖/Owner/状态/测试/证据/Commit） |
| 基线测试 | **448 passed，1 skipped**（主机 miniconda python3，U5-1 后全量回归） |
| 生产 bundle | `prod_20260804_v4_r2`（16 文件校验通过，不修改） |
| production_switch | **false**（冻结） |
| training_started | **false**（冻结） |
| deleted_files | **false**（冻结） |
| 统一入口 | http://127.0.0.1:8400（✅ 运行中，degraded；当前为开发者原型，易用性和状态真实性待整改） |

## 服务实时快照（基线时刻）

| 端口 | 服务 | 状态 |
|---|---|---|
| 8091 | recognize（/v2，cascade_v3，bundle prod_20260804_v4_r2） | ✅ UP |
| 8092 | monitor（/api/live，看门狗守护） | ✅ UP |
| 8455 | omlx（内部，需 API key） | ✅ 进程在（/ 返回 404） |
| 8300 | Label Studio 1.23.0（sqlite，项目内数据目录） | ✅ UP |
| 8301 | LS ml-backend | ⛔ DOWN（M4 处理） |
| 8304 | orchestrator | ⛔ DOWN |
| 8400 | 统一平台 | ✅ UP（degraded：ml_backend/8301 不可用，非关键） |
| 5432 | PostgreSQL 16.14（brew 演练集群 platform_drill） | ✅ UP（M6 演练专用；生产切换待授权） |

## 里程碑状态

| 里程碑 | 状态 |
|---|---|
| M0 基线与保护 | DONE（f91c0e6） |
| M1 统一 Web Shell | DONE（97020d6 → 54cac63 → 2d9a4ef，198 passed） |
| M2 最小可信 Foundation | DONE（46d2f25 → 1dc4cc8，243 passed） |
| M3 第一条真实 Graph | DONE（fb55084 → 7afa0bf → 7450d23 → b7513dc，265 passed） |
| M4 Label Studio 闭环 | PARTIAL（机械对账 f42f882；人工标注/双审/仲裁/final box 未完成） |
| M5 数据集训练治理 | **REOPENED / NO-GO**（UMT-001～008 代码修复全部落地并测试；尚缺真实 Snapshot、人工 truebox 与 G 门禁机器证据） |
| M6 PostgreSQL + 可靠 Worker | DONE（49172d5 + PG 演练；生产切换待独立授权） |
| U2 统一管理 MVP | **全部完成**：U2-1/U2-2/U2-3/U2-4/U2-5 DONE（角色首页/数据中心真实台账/识别四入口/业务语言/幂等分页） |
| U3/U4 全照片与 SAM 审核 | U3-1～U3-6 DONE；U4-1 DONE（SAM lineage 不可变）；U4-2/U4-3 DONE（审核状态机 migration 014，250 条 pending 真实接入）；U4-4 机制 DONE（阶梯+质量门 6baa389，诊断批 0/250 诚实 waiting_human）；实际分批与标注推进需真实人工；qa_v3 仅 120 张 |
| U5 Graph+Loop v2 | 进行中：U5-1 Loop 内核 DONE（ef1b4e1，typed edges/条件路由/feedback/轮次预算/人工门/跨实例恢复，6/6 测试）；sequential v1（GraphEngine）保留不动；U5-2/U5-3 TODO |
| T0/T1/T2 训练 | BLOCKED（P0 修复后仅授权 1ep smoke + 3ep pilot） |

## 红线（任何阶段不得越过）

- 不删除/移动/覆盖原图、数据库、模型、数据集、审核、SAM、quality、eval、日志、备份、失败制品
- 不 `git add .` / `git add -A`；不自动 merge/push/deploy/force-push
- 在 UMT-001～008、真实 Snapshot、人工 truebox 与 MPS 门禁通过前不启动任何训练；通过后仅按新手册授权 1ep smoke + 3ep pilot，10ep/classifier/发布仍需新授权
- 不恢复 v6；不修改/发布 production bundle；旧 /retrain 的 auto_switch=true 不进新平台
- 8091/8092 保留，第一阶段不重写不切换生产入口
- 平台不依赖具体 Domain Pack（Manifest + Capability 注册）
- 不允许任意 SQL、shell、文件系统、Python import 能力
- 未跟踪制品 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不暂存、不清理

## 2026-08-05 训练阻断摘要

- `src/eval/truebox_eval.py` 仍按每图 top-K proposal 计算所谓 FP 预算，不是真实固定 FP/photo。
- 训练治理生成真实 CLI 不支持的 `--dataset`、`--budget-minutes`。
- 平台唯一 Snapshot 只有 2 train + 1 val 演示条目，不能代表 E2 或任何真实训练集。
- MPS dry-run 只检查 `sys.platform == darwin`，未做 torch MPS/矩阵/模型前向门禁。
- `start_training` 只标记 authorized，不会提交训练 Job；页面术语与真实动作不一致。
- 现有 250 条人工 truebox 审核全部 pending，不能伪造完成。

上述问题关闭并有机器证据前，`training_authorized` 必须保持 false。

**修复进展（2026-08-05 U1）**：上述六项中前五项代码层已修复并有测试证据（统一阈值扫描/真实 CLI 命令+预检/演示 Snapshot 标不可训练/MPS G0 实测/approve 与 enqueue 拆分 + 可信登录）；剩余关闭条件：真实 Snapshot（服务端 builder）、人工 truebox、G 门禁机器证据。前端登录与训练页分区已上线（87f16d5，浏览器 E2E 截图 `.eval/training_login_check_*.png`）。
