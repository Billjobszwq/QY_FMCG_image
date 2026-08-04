# Platform V2 — 统一框架持续可用建设 · STATUS

> 手册：`docs/superpowers/plans/2026-08-04-continuous-usable-framework-execution-manual.md`（唯一实施编排入口）
> 架构：`docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`（L0，不变）

| 项 | 值 |
|---|---|
| 当前状态 | M1 完成（2d9a4ef），进入 M2/W5 |
| 当前 HEAD | 2d9a4ef（feat/usable-platform-foundation） |
| 分支 | `feat/usable-platform-foundation` |
| 基线 commit | `c9998af`（feat/sam-reannotation） |
| 基线测试 | 170 passed；M1 验收后全量 **198 passed**（2.97s） |
| 生产 bundle | `prod_20260804_v4_r2`（16 文件校验通过，不修改） |
| production_switch | **false**（冻结） |
| training_started | **false**（冻结） |
| deleted_files | **false**（冻结） |
| 统一入口目标 | http://127.0.0.1:8400（✅ 运行中，degraded） |

## 服务实时快照（基线时刻）

| 端口 | 服务 | 状态 |
|---|---|---|
| 8091 | recognize（/v2，cascade_v3，bundle prod_20260804_v4_r2） | ✅ UP |
| 8092 | monitor（/api/live，看门狗守护） | ✅ UP |
| 8455 | omlx（内部，需 API key） | ✅ 进程在（/ 返回 404） |
| 8300 | Label Studio | ⛔ DOWN（M4 处理） |
| 8301 | LS ml-backend | ⛔ DOWN（M4 处理） |
| 8304 | orchestrator | ⛔ DOWN |
| 8400 | 统一平台 | ✅ UP（degraded：8300/8301 DOWN） |

## 里程碑状态

| 里程碑 | 状态 |
|---|---|
| M0 基线与保护 | DONE（f91c0e6） |
| M1 统一 Web Shell | DONE（97020d6 → 54cac63 → 2d9a4ef，198 passed） |
| M2 最小可信 Foundation | IN_PROGRESS（W5 PlatformStore） |
| M3 第一条真实 Graph | PENDING |
| M4 Label Studio 闭环 | PENDING |
| M5 数据集训练治理 | PENDING（训练需显式授权） |
| M6 PostgreSQL + 可靠 Worker | PENDING |
| M7 后续 Domain Pack | PENDING |

## 红线（任何阶段不得越过）

- 不删除/移动/覆盖原图、数据库、模型、数据集、审核、SAM、quality、eval、日志、备份、失败制品
- 不 `git add .` / `git add -A`；不自动 merge/push/deploy/force-push
- 不启动任何训练（3ep/10ep/classifier）；训练与发布是两个独立审批动作
- 不恢复 v6；不修改/发布 production bundle；旧 /retrain 的 auto_switch=true 不进新平台
- 8091/8092 保留，第一阶段不重写不切换生产入口
- 平台不依赖具体 Domain Pack（Manifest + Capability 注册）
- 不允许任意 SQL、shell、文件系统、Python import 能力
- 未跟踪制品 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不暂存、不清理
