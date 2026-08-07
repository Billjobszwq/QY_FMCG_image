# Codex 项目接续手册

> 用途：这是 Codex 自己使用的长期项目索引、进度快照和方法论手册，用于会话切换、上下文压缩和后续复盘。
>
> 权威边界：本文件不是产品 L0 架构、实施计划、训练启动授权或线上状态接口。它只负责把权威文件、已经发生的工作和下一步入口串起来。若本文件与权威文件或当前代码冲突，以权威文件和重新验证的当前事实为准，并立即修订本文件。
>
> 当前快照时间：2026-08-08，Asia/Shanghai。

---

## 0. 上下文恢复时先读这里

### 0.1 五分钟恢复顺序

每次上下文压缩、重新打开任务或切回本项目时，按顺序执行：

1. 阅读本文件第 1、2、5、6、7、8、12 章。
2. 执行只读状态检查：

   ~~~bash
   cd /Users/zhangweiqi/Documents/QY/项目/LLM-Image
   git status --short
   git branch --show-current
   git rev-parse HEAD
   git log --oneline -8
   ~~~

3. 阅读当前任务对应的权威文件，不从本手册复制可能过期的命令。
4. 若要改代码，先运行 fresh baseline：

   ~~~bash
   XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 \
   /Users/zhangweiqi/miniconda3/bin/python3 \
   -m pytest -p no:cacheprovider -q
   ~~~

5. 对照 `git status` 区分用户改动、历史未跟踪文件和本轮改动。
6. 先确认当前授权：审查、修 Bug、训练、实施 Foundation、启动服务、发布、删除分别是不同权限。
7. 将本次真实 HEAD、测试数、任务目标和停止点写入当前执行日志。

### 0.2 当前接续锚点

| 项目 | 当前快照 |
|---|---|
| Repository | `/Users/zhangweiqi/Documents/QY/项目/LLM-Image` |
| Branch | `feat/unified-workbench-training-readiness` |
| 当前代码基线 HEAD | `c1d1d6fe5980b84bfd85ec851dd7194936205200`；本轮只新增/更新文档，后续以实时 `git rev-parse HEAD` 为准 |
| 最近交付报告测试 | `914 passed, 1 skipped`；但 2026-08-08 Codex 受限环境 fresh run 为 `904 passed, 10 failed, 1 skipped`，失败集中于宿主 MPS 探针和授权错误优先级，必须在普通 Terminal 复核 |
| Python | `/Users/zhangweiqi/miniconda3/bin/python3`，3.13.2 |
| 工作树 | 四个受保护未跟踪目录 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/`；不得修改、暂存、清理或删除 |
| 当前生产 bundle | `prod_20260805_v5_r1`，继续使用；本轮不得切换 |
| 人工审核 | rq_v2 active 250；LS 项目 19 assisted / 20 blind；`gold_region_v1=0`；Gate=`AWAITING_HUMAN_ACCEPTANCE` |
| 训练 | 无活动真实训练；`training_authorized=false`；当前仅有历史 dry-run 和不可训练 E2 snapshot |
| Foundation 实现 | Platform/Graph+Loop/统一 Web/FMCG cascade/审核链已经有实际代码，不再是“只有文档”；训练控制仍需四通道重构 |
| 当前工作主题 | 实施 `graph-loop-training-control-v1`：旧模型隔离、四数据集、四训练 lane、统一 Web；机器框架与人工 gold 并行 |

这些值会变化。任何新会话必须先实时验证，不得把快照当作永远有效的事实。

## 1. 用户目标与合作方式

### 1.1 产品目标

项目最终不是一个单纯 SKU 识别工具，也不是传统 SaaS。目标是一套以 Graph+Loop 为智能执行主干的业务操作系统：

- 统一 Web 管理端；
- FMCG 照片接入、质量、识别、标注、审核、训练和模型治理；
- 地址、定位、路线、电子围栏、导航、任务推荐和外勤执行；
- 问卷、数据库、BI 和跨域数据分析；
- 低、中、高、极高服务档位与平台 token 商品化；
- 客户定制 Graph+Loop 高级服务；
- 本机优先，成熟后可拆分、上云和扩展多客户。

识别是第一个业务 Domain Pack，不是平台中心。平台中心是受权限、预算、证据、计量和人工节点约束的 Graph+Loop。

### 1.2 用户的长期偏好

1. 证据链、数据正确性和历史可追溯性优先于“先跑起来”。
2. 不删除任何业务文件、历史制品、失败产物、备份或临时证据，除非用户明确批准具体删除目标。
3. 不覆盖原图、SQLite 历史、模型、训练结果、审核记录和评估结果。
4. 复杂系统先明确业务规则、数据所有权、权限和门禁，再扩展代码。
5. 报告必须区分：代码存在、测试通过、制品已重建、进程已加载、业务指标达标。
6. 不猜财务值、不伪造训练效果、不用平均指标掩盖长尾和失败路径。
7. 抽象方法论需要配一个可以执行的具体案例。
8. 模型不能只是可用，必须验证效率、准确率、MPS 资源、吞吐和成本。

### 1.3 权限边界

- “审查/诊断”只允许只读检查和报告，不自动修复。
- “修 Bug”允许修改明确范围内代码并验证，不自动发布或清理。
- “训练”必须有单独授权并通过训练门禁，不因硬件可用就自动开始。
- “完成平台”按 Stage 门禁实施，不代表允许一次性大爆炸开发。
- “保管手册/记忆”允许维护本文件和记忆索引，不允许把客户数据写入记忆。

## 2. 权威文件层级

### 2.0 当前最高优先接续入口（2026-08-08）

| 文件 | 作用 |
|---|---|
| `docs/implementation/project-logic-chain-v3/` | 当前 22 层运行逻辑、事实源、rq_v2/LS/gold 状态和验收链 |
| `docs/implementation/graph-loop-training-control-v1/` | 下一阶段旧模型隔离、四数据集、四训练通道、统一控制台实施任务 |
| `docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md` | 已批准的 S0–S5 级联、客户档位、Qwen 和 Apple 资源契约 |
| `.platform/platform.sqlite` | 当前本机运行唯一事实源；文档不得覆盖其事实 |

### 2.1 系统架构和实施

| 等级 | 文件 | 作用 |
|---|---|---|
| L0 | `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md` | 唯一总体架构与产品边界 |
| L1 | `docs/superpowers/plans/2026-08-04-full-project-execution-program.md` | Stage 0–9 总实施顺序、门禁和 Agent 提示词 |
| L1 | `docs/superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md` | Stage 0–1 代码级 Task 1–26 |
| L1 | `docs/superpowers/specs/2026-08-04-location-field-operations-design.md` | Geo & Field Operations Domain Pack 规格 |
| L2 | `docs/README.md` | 全项目文档索引和当前入口 |

### 2.2 当前识别、Bug 和训练

| 文件 | 正确用法 |
|---|---|
| `docs/superpowers/plans/2026-08-04-final-training-execution-gate.md` | 当前训练唯一执行门；必须结合最新勾选状态阅读 |
| `docs/experiments/E2-detector-pilot.md` | Phase C pilot 的真实结果和不晋级证据 |
| `docs/experiments/E0-strict-iou-baseline.md` | dev_v2 严格 one-to-one IoU 基线 |
| `docs/experiments/G0-mps-gate-evidence.md` | Apple MPS 真实终端准入证据 |
| `docs/training-history-and-decisions.md` | 历史训练演进；部分状态已落后于后续 commit |
| `docs/project-reaudit-performance-training-optimization-2026-08-04.md` | 旧 RA-001～RA-024 证据库；状态必须重新核验，不能直接照搬 |
| `docs/project-issue-register-and-remediation.md` | 原 20 项 Bug 清单；Open 状态是历史快照，不代表当前状态 |
| `docs/handbook.md` | 现有系统说明；部分训练状态早于 `abe2630/63aa58f/277b2ee` |
| `docs/runbook.md`、`docs/structure.md`、`docs/architecture.md` | 现有运行和结构背景；与目标架构冲突时用 Adapter 迁移 |

### 2.3 冲突处理

目标架构冲突优先级：L0 → Stage 总纲 → 当前 Stage 计划 → Domain Pack 规格。

运行事实冲突优先级：实时命令/当前代码/当前制品 → 最新实验报告 → 最新门禁 → handbook → 历史报告。

训练事实冲突优先级：当前模型/数据 hash 和实验产物 → E2/E0/G0 报告 → final training gate → training history。

## 3. 截止目前完成的工作

### 3.1 现有系统整改与训练治理

关键实施提交：

| Commit | 已完成 |
|---|---|
| `abe2630` | 关闭训练 G2–G6 的代码门：五键协议守卫、store 规范化、dev_v2、安全数据构建、严格 IoU、run 防覆盖、classifier 显式 data-dir |
| `63aa58f` | 执行 Apple MPS detector pilot、增加 E2 严格评估、记录 G0 证据并作出不晋级判定 |
| `277b2ee` | 把 G0–G6、pilot 完成、Phase D 不晋级写回最终训练门禁 |

当前代码侧实际进展：

- 新增 `src/data/protocol_guard.py`，对 photo ID、SHA、规范门店、模糊别名和 session 做 fail-closed 隔离。
- 新增 `src/data/store_norm.py`，使用 NFKC、标点/括号统一、空白压缩和 casefold。
- 新增 `src/training/build_dataset_v7.py`，使用 staging、原子发布和 build audit。
- 新增 `src/eval/e0_strict_iou.py` 和 `src/eval/e2_detector_eval.py`。
- `train_v1.py` 已存在 run 拒绝覆盖，并修正 pilot metadata 写入时机。
- classifier/finetune 需要显式指定数据目录，避免默认读取旧制品。
- 在 2026-08-04 阶段，测试曾从历史 22/46 项增加到 `74 passed`；该数字只保留作历史里程碑。

### 3.2 最终平台架构（历史冻结结论，代码已进入后续阶段）

关键文档提交：

| Commit | 已完成 |
|---|---|
| `409a56a` | 将平台定位改为 Graph+Loop 智能核心 |
| `f5d43e0` | 完成位置与外勤 Domain Pack 设计 |
| `94a6e71` | 将两份设计统一为一套 Foundation + Domain Packs |
| `4dac8f8` | 完成 Stage 0–9 总纲和 Stage 0–1 代码级计划 |

已经冻结的架构结论：

1. 一套 Foundation，不建立识别、外勤、问卷各自的平行平台。
2. 本地优先模块化单体 + 隔离 Worker，成熟后按契约拆分。
3. Foundation 提供 Module SDK、IAM、Graph、Job、Data、CAS、Billing、Audit 和 Web Shell。
4. Domain Pack 独立开发、测试、迁移、启停和维护，但共享底座。
5. PostgreSQL 是新平台事实库；CAS 保存不可变文件和证据；旧 SQLite 只读兼容。
6. 跨模块只用 API、Capability、DomainCommand、事件、DataProduct、ResourceRef 和 WorkItemProjection。
7. Agent 不允许任意 SQL、shell、文件系统或直接客户源表写入。
8. Foundation 必须先通过双模块验证和隔离门，后续模块才能开工。

### 3.3 已交付实施文档与当前代码推进

- `docs/superpowers/plans/2026-08-04-full-project-execution-program.md`：540 行，Stage 0–9、需求映射、Agent 启动提示词和审查清单。
- `docs/superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md`：Task 1–26 的代码级 TDD 计划。
- Stage 0–1 涵盖 Graph Kernel、Module SDK、IAM、CAS、Job、DataProduct、Billing、Audit、Web Shell、双模块隔离、备份恢复和性能安全门。

历史说明“Foundation 尚未实现”已过期。当前已经存在并通过大量测试的 `src/platform`、`src/modules`、Graph Kernel、PlatformStore、统一 Web、Job/Worker、FMCG 级联、审核状态机、模型驻留和计费代码。是否达到商用 Foundation 仍需按当前验收门判断，不能把“代码存在”说成“全部完成”。

### 3.4 2026-08-07/08 逻辑链 V3 收口

- 修复 protocol photo_id/SHA 位置 zip 全链错配；rq_v1 追加式失效，rq_v2 250 条成为唯一 active 队列。
- 平台 API、批次门禁和任务列表已收敛到 active-only；失效历史只读保留。
- LS 项目 19 assisted、20 blind 已创建；blind 零 prediction；assisted 当前无 proposal，等待接入当前生产模型。
- `gold_region_v1` 原子双审/仲裁状态机和 truebox 导出链已实现，当前真实 gold 数仍为 0。
- zero-shot canonical identity 已修复，当前主要数据短板是候选 KB/alias 覆盖，而非 registry escape。
- 统一 Web/Graph+Loop/SQLite 是当前正式控制链；旧 `src/labeling`、rq_v1 和旧 LS 项目只读保留。

## 4. 当前系统现实与目标架构的差距

### 4.1 当前代码现实（2026-08-08）

当前仓库仍由识别项目演进而来，但平台底座已经实际存在：

- `src/cascade`
- `src/catalog`
- `src/data`
- `src/eval`
- `src/field`
- `src/labeling`
- `src/ls_ml_backend`
- `src/ls_platform`
- `src/models`
- `src/recognize`
- `src/training`
- `src/platform`
- `src/modules`
- `src/composition`
- `web/src/pages`

它仍不是最终商用 Foundation。当前主要断点已经从“完全没有底座”转为“模块存在但训练、标注、过滤和四数据集控制面尚未统一”。不能因为页面和模块存在，就对用户说端到端已经完成。

### 4.2 目标结构

目标结构由 Stage 0–1 计划锁定：

~~~text
src/platform/{kernel,modules,iam,data,assets,jobs,billing,audit,api,observability}
src/modules/{reference_echo,fmcg_vision,...}
contracts/
migrations/platform/
migrations/modules/<module_id>/
web/src/platform/
web/src/modules/<module_id>/
~~~

下一阶段以 `docs/implementation/graph-loop-training-control-v1/` 为边界实施训练控制面。必须继续使用 Adapter/Capability/Graph Hook，不能把四条训练逻辑塞回单体 `Training.tsx`、`service.py` 或 shell 分支。

## 5. 当前训练状态

> 本章 5.3/5.4 的 E0/E2 数字是 2026-08-04 历史实验基线，用于对照，不代表当前 production bundle 的同口径业务指标。

### 5.1 硬件

- Apple M3 Max，arm64，16 CPU core、40 GPU core、128 GB 统一内存。
- Python 3.13.2、PyTorch MPS 已在真实 Terminal 通过。
- MPS tensor 与当前级联 MPS 推理已经成功。
- Apple 硬件不是阻断项；数据、标签、评估和算法收益才是阻断项。
- 禁止静默 CPU fallback；新的训练会话必须重新跑 G0。
- Codex/沙箱进程可能看不到 MPS 或 sysctl；测试必须区分 hermetic mock 与普通 Terminal 的 host G0，真实启动只能接受后者。

### 5.2 数据与门禁

- 历史 E2 的 G0–G6 已关闭，不自动授权任何新 lineage。
- `dev_v2` 为 801 张；协议五键守卫对 active 集命中为 0。
- `e2_product_pilot_v1`：2,000 train + 300 val，单类 `product`，manifest hash `35f70f0a0cfd53b8`。
- 训练标签和 dev_v2 GT 仍包含锚点/比例生成的合成框；`diagnostic_v1` 的完整人工真实矩形框未完成。
- 旧 `.datasets/sku_v6`、`crop_dataset`、`crop_dataset_yolo` 不能恢复为新 lineage 正式制品。
- 旧 v6 权重只作历史对照，不得恢复训练。
- rq_v2/LS 审核链已经建立，但 `gold_region_v1=0`；这阻止真实训练数据发布，不阻止机器侧训练控制框架建设。
- 当前 platform DB 只有 `e2_product_pilot@v1` snapshot，且 `trainable=0`；training run 仅有 4 个历史 dry-run，`training_authorized=false`。

### 5.3 E0 基线

dev_v2 严格 one-to-one IoU≥0.5：

| 指标 | 当前生产 v4 |
|---|---:|
| 检测覆盖 | 23.5% |
| business accepted precision | 59.2% |
| matched precision | 93.1%，仅诊断，不是业务 precision |
| 端到端 accepted-correct recall | 19.9% |
| FP/photo | 3.684 |
| exact-set | 0.0% |
| count MAE | 16.873 |

### 5.4 E2 Phase C pilot

| 候选 | dev_v2 recall@FP3.0 | conf=0.25 FP/photo | 吞吐 | 结论 |
|---|---:|---:|---:|---|
| E0 v4 | 20.88% | 2.33 | 8.59/s | 基线 |
| P0 COCO 3ep | 13.51% | 2.90 | 7.47/s | 退化 |
| P1 v4 init 3ep | 24.23% | 5.28 | 7.88/s | 方向有改善但未过门 |

P1 相对 E0 只提升 `+3.35pp`，低于 `+10pp` 晋级门；FP/photo 也超过基线 1.2 倍。结论：

- Phase D 不晋级；
- 不跑单 seed 10 epoch；
- 不启动 classifier 阶段；
- 不发布新 bundle；
- 当时生产继续使用 `prod_20260804_v4_r2`；2026-08-05 后当前生产已经是 `prod_20260805_v5_r1`，见第 5.5 节。

不能为了让实验继续而事后降低门槛。若未来改变门槛，必须先写新假设和协议，再运行新实验。

### 5.5 当前生产与后续训练隔离

- 当前 `.models/bundles/CURRENT.json` 指向 `prod_20260805_v5_r1`，由 detector `sku_v5` + 原 classifier/registry/thresholds 组成。
- `.models/sku_v1` 至 `sku_v7_sam`、E2、classifier、archive 和 best 全部原样保留。
- 新训练族固定为 `fmcg_nextgen_v1`，不得从上述业务 checkpoint 续训、resume、继承 EMA/optimizer 或作为蒸馏 teacher。
- 当前生产 bundle 只允许继续识别、生成 assisted provisional proposal 和作为冻结基线。
- 后续四训练 lane：T1 detector、T2 classifier、T3 SAM segmenter、T4 `qwen3-vl:4b` QLoRA；统一风险/路由校准属于 Graph+Loop 治理，不是第五模型。

### 5.6 当前训练控制面的真实缺口

1. `web/src/pages/Training.tsx` 仍以单 YOLO snapshot/dry-run 为主，Qwen、classifier、SAM 没有同级 lane。
2. 现有 Worker 直接 `subprocess.Popen` 后等待退出，缺少结构化进度、资源互斥、安全停止、orphan 恢复和完整 artifact registry。
3. 训练页仍把 8092 标成旧监控，不能作为统一状态事实源。
4. assisted 项目 19 无 proposal，标注与当前生产识别能力未完成接线。
5. 当前测试在受限环境有 10 个 MPS 相关失败，暴露 host-dependent test 与错误优先级问题。
6. 4 个历史 dry-run 仍保存当前 CLI 不支持的 `--dataset/--budget-minutes`，必须追加标记 legacy/superseded，禁止批准或入队。
7. 8400 当前 degraded：Label Studio ML backend unavailable；8300 本体可用，proposal 正式写入口仍需收敛。

## 6. 切回 Bug 修复时的入口

### 6.1 不直接相信旧问题状态

`project-issue-register-and-remediation.md` 和 `project-reaudit-performance-training-optimization-2026-08-04.md` 是证据库，不是当前问题状态数据库。许多问题后来已经部分或全部修复，也有当前制品/在线服务未重新验证的情况。

下一轮必须建立 fresh issue matrix，状态只允许：

- CONFIRMED_OPEN
- PARTIALLY_CLOSED
- CLOSED_WITH_EVIDENCE
- NOT_REPRODUCED
- NOT_TESTED
- SUPERSEDED

### 6.2 优先复核清单

以下是必须重新审计的候选，不等于已经确认仍有 Bug：

1. 旧 `src/recognize/api.py` 是否仍可能与 v2 服务抢占 8091，是否仍保留 COCO fallback。
2. 低置信、`__unknown__`、margin 冲突是否在 recognize、ML backend、orchestrator 三入口完全统一。
3. 8300/8301/8304 是否能真实联调，而不是只看代码。
4. Label Studio ML backend health、model_version、SSRF、大小限制和失败语义。
5. orchestrator 认证、CORS、模型切换、危险操作和本地路径暴露。
6. Webhook HMAC、幂等、乱序、重复事件和业务写入是否原子。
7. exporter 路径、staging、内存、group split；importer O(N²) 与重跑幂等。
8. catalog 多文件发布是否已形成真正 bundle/manifest 原子切换。
9. warehouse SQLite/PostgreSQL 漂移与 compose 空库能否完整部署。
10. monitor 2 小时 RSS 是否稳定，mtime 未变时是否仍周期性 `torch.load`。
11. recognize、ML backend、orchestrator 是否重复加载 detector/classifier 并争抢 MPS。
12. 推理并发 1/2/4/8/16 的背压、p95、错误率和内存。
13. 当前 bundle 的 registry、thresholds、classifier classes、detector names 是否完全自包含并逐项校验。
14. 所有审计路径是否都有可靠 outbox/replay，失败任务是否可能被标成功。
15. 文档命令、服务入口和真实代码是否仍有漂移。

### 6.3 Bug 关闭的七层证据

任何 Bug 只有同时满足以下适用层，才能写 CLOSED：

1. **Reproduction**：有最小复现、失败输出和影响范围。
2. **Root cause**：解释具体失败链，不只描述症状。
3. **Regression test**：测试先失败，修复后通过；覆盖失败路径和旁路。
4. **Implementation**：最小修复，不扩大架构范围。
5. **Artifact/data**：若 Bug 影响数据/模型/导出，旧制品已明确隔离，新制品已重建核对。
6. **Runtime**：实际进程已加载新代码，health/smoke/长稳结果通过。
7. **Evidence**：commit、命令、结果、风险和回滚路径可追溯。

只做到第 4 层，最多写 PARTIALLY_CLOSED。

## 7. 切回模型训练时的入口

### 7.1 先解决实验可信度，不直接加 epoch

下一步不应直接把 P1 从 3 epoch 延长到 10 epoch。先回答：

1. synthetic box 对训练和 dev_v2 严格评估造成多大偏差？
2. P1 的新增 FP 来自重复框、背景、相邻商品合并、定位偏移还是低置信正确框？
3. P1 在尺寸、密度、场景、注册/未注册商品上的收益是否一致？
4. PR curve 中是否存在比 conf=0.25 更好的工作点，且仍满足固定 FP 预算？
5. pilot 数据的注册/未注册框比例、框质量和门店分布是否偏离 dev_v2？
6. 3 epoch 尚在 warmup 尾段是否能解释收益不足？若要验证，必须先定义小成本新门。

### 7.2 推荐的下一训练前工作包

按顺序执行：

1. 为 diagnostic 子集补真实矩形框，先做 200 张双人复核，再扩 500 张。
2. 用同一真实框对 E0/P0/P1 重新评估，确认合成框偏差。
3. 输出 detector 错误分类账：miss、duplicate、background、merge、split、localization、low-confidence-correct。
4. 做尺寸/密度/场景/门店/注册状态分桶。
5. 冻结新假设、成功线、停止线、最大 epoch 和最大 MPS 小时。
6. 只有证据支持“训练不足”时，才授权一个单变量延长实验；不自动进入三 seed。
7. detector 候选稳定后，classifier 才进入 true-box/predicted-box/unknown oracle。

### 7.3 训练实验方法论

每个实验必须具有：

~~~text
Hypothesis
  → DatasetSnapshot / protocol hash
  → one changed variable
  → G0 hardware gate
  → bounded pilot
  → strict offline evaluation
  → success/stop decision
  → immutable artifacts and report
  → no automatic production publish
~~~

必须分别报告：

- detector recall@固定 FP/image；
- business accepted precision，分母包含 accepted FP；
- accepted coverage 和 review rate；
- macro F1、unknown false accept；
- exact-set、count MAE；
- p50/p95、吞吐、峰值内存、MPS 使用和单位成本；
- 长尾、包装版本、场景、质量和门店分桶。

## 8. 项目实施方法论

### 8.1 架构方法：一底座，多 Domain Pack

先冻结平台契约，再实现业务模块。新增模块不能修改 Kernel 领域特例，也不能复制基础能力。

~~~text
业务需求
  → Domain Pack 边界
  → Manifest / contracts / schema owner
  → Capability / DomainCommand / events
  → tests and migration
  → module enable/disable isolation
  → performance/security/evidence gate
~~~

### 8.2 Stage 方法：Admission、Implementation、Acceptance

每个 Stage 分三步：

1. Admission：真实 HEAD、依赖门、契约、迁移、风险、测试矩阵。
2. Implementation：独立 worktree、TDD、小提交、追加式日志。
3. Acceptance：正确性、恢复、性能、安全、兼容、财务和证据门。

不允许用 UI demo 代替数据一致性，不允许用单元测试代替真实服务联调。

### 8.3 数据方法：事实、资源、派生、投影分离

- 业务事实进入模块自有 schema。
- 原始和派生文件进入 CAS，不可覆盖。
- 跨模块只传 ResourceRef/DataProduct。
- 统一工作台读取 WorkItemProjection，不直接写领域表。
- 事件和投影可重放；历史事实不可删除。

### 8.4 Agent 方法：权限、预算、证据、人工边界

Agent 不是万能管理员。Graph 节点必须声明 capability、数据域、预算、side effect、幂等键和人工边界。客户 Agent 可做数据分析、答疑和追踪，但不能接受任意数据库/SQL，也不能直接修改客户源数据。

### 8.5 计费方法：用量、成本、价格分层

1. UsageEvent 记录不可变原始单位。
2. CostEntry 记录内部真实成本。
3. PriceEntry 使用版本化 RateCard 计算客户价格。
4. 初期按模块成本汇总，后期折算 platform token。
5. 重算生成 correction，不覆盖原账。

## 9. 可复用流程模板

### 9.1 Bug 复查模板

~~~markdown
## BUG-XXX

- Current status:
- User impact:
- Reproduction:
- Evidence:
- Root cause:
- Failing test:
- Fix scope:
- Artifact rebuild required:
- Runtime reload required:
- Verification:
- Commit:
- Rollback:
- Residual risk:
~~~

### 9.2 训练实验模板

~~~markdown
## EXP-XXX

- Hypothesis:
- Baseline:
- DatasetSnapshot / manifest hash:
- Train/val/protocol leakage result:
- Initialization:
- One changed variable:
- Device / MPS gate:
- Maximum epoch / time / memory:
- Success line:
- Stop line:
- Metrics:
- Decision:
- Artifact paths and SHA:
- Production switch: false
~~~

### 9.3 Stage 验收模板

~~~markdown
## S<N> Acceptance

- Base commit:
- Final commit:
- Scope diff:
- Contracts:
- Migrations:
- Unit/contract/integration/E2E:
- Recovery:
- Performance:
- Security:
- Legacy regression:
- Data/evidence integrity:
- Billing reconciliation:
- Deleted files: false
- Production switch: false
- Result: ACCEPTED / NOT ACCEPTED
~~~

## 10. Git 与文件安全

1. 不运行 `git add .`、`git add -A`、`git clean`、`git reset --hard`。
2. 暂存明确文件名，提交前检查 `git diff --cached --name-only`。
3. 不自动 merge、push、deploy 或 force-push。
4. 实施复杂 Stage 使用 worktree；目录存在时不删除，换明确新目录。
5. 数据、模型、日志、SQLite、`.env`、原图和备份不进普通源码提交。
6. `.superpowers/` 是当前历史未跟踪目录，不属于 Codex 手册或项目代码，不碰。
7. 删除、清理、覆盖、迁移客户/业务数据必须获得独立明确授权。

## 11. 容易失忆或误判的事实

1. `handbook.md` 中“仍需关闭 G1–G6”已经过期。实际 G0–G6 已关闭，pilot 已完成，但 Phase D 不晋级。
2. `training-history-and-decisions.md` 的 46 tests 和本手册旧版的 74 tests 都已过期；当前必须以实时 full suite 为准。
3. final training gate 第 0 章保留了最初 NO-GO 背景，第 5、7 章才记录后续实际执行状态。
4. E2 的 dev_v2 GT 仍是锚点合成框，不是真实人工框。严格 IoU 算法正确不代表 GT 真实。
5. P1 在 pilot val 上 recall@FP3.0 为 39.0%，在 dev_v2 上只有 24.23%；不能混用两个分布。
6. MPS 可用不等于应该继续训练；当前停止原因是收益和 FP 门，不是硬件。
7. “Foundation 代码尚未实施”已经过期；当前已有 Platform/Graph+Loop/统一 Web 实现，但训练控制面没有完成四通道统一。
8. Stage 0–1 Task 16 只是 Graph Kernel 子门，Task 26 才是 Foundation 完成门。
9. 旧 Bug 文档的 Open/部分修复状态是历史快照，下一轮必须 fresh reproduce。
10. 当前生产 bundle 已在 2026-08-05 经授权切换为 `prod_20260805_v5_r1`；后续本轮不得再切换。
11. rq_v1 的 250 条是失效历史，rq_v2 的 250 条才是 active；不得把两者相加当成 500 个待审任务。
12. LS 19 assisted 当前无 proposal 不等于设计要盲标；它应接当前生产模型追加 provisional proposal。LS 20 blind 必须始终零 prediction。
13. `gold_region_v1=0` 阻止真实数据集/训练，不阻止机器侧 API、Graph、Worker 和 Web 框架建设。
14. 四训练通道是 detector/classifier/segmenter/VLM，不是客户四档；客户档位由 GraphPolicy 决定服务预算和最大阶段。
15. SAM 盒提示校准不是 SAM 权重微调；无真实 mask gold 时必须诚实显示 calibration-only。

## 12. 下一次工作的明确切换点

当前唯一机器侧实施入口：`docs/implementation/graph-loop-training-control-v1/AGENT-EXECUTION-PROMPT.md`。

### Track A：机器侧立即实施

1. 普通 Terminal 复核 10 个 MPS 测试失败，完成 hermetic/host 分层。
2. 旧模型不可变 inventory 与 nextgen parent 隔离。
3. assisted 项目 19 接当前生产 proposal，blind 20 零泄漏。
4. 四 Dataset Factory builder 与统一过滤投影。
5. 四 lane adapter、TrainingControlGraph、Hook、资源租约和可靠 Worker。
6. 统一 API/Web、浏览器 QA、故障恢复和机器验收。

### Track B：真人与真实训练并行等待

1. 两位真人完成 5 assisted + 5 blind 验收。
2. 通过后放量 rq_v2 250；分歧第三人仲裁。
3. 产生真实 gold 后分别构建 D1–D4，不能用一个数据集冒充四种任务。
4. 对具体 TrainingPlan 单独授权；一次只跑一个 Apple heavy job。
5. candidate 评估、shadow、发布仍保持独立门禁。

机器侧完成时只能标记 `FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION`，不能写训练完成。

## 13. 本手册维护规则

每次发生以下事件，都更新本文件：

- Bug 被确认、修复或重新打开；
- 测试基线变化；
- 训练实验完成或停止；
- production bundle 改变；
- L0/L1 架构或 Stage 门禁改变；
- 新 Domain Pack 决策确认；
- 用户改变删除、发布、训练或 Agent 权限；
- Git HEAD 成为新的稳定接续点。

更新方式：

1. 先实时验证事实。
2. 更新第 0.2 节当前锚点。
3. 更新对应专题章节。
4. 在第 14 章追加一条记录，不覆盖历史。
5. 若事实来自旧文档且未实时验证，明确标为 memory-derived/stale。
6. 不在本手册保存 secret、客户原始数据、完整个人信息或人脸模板。

## 14. 手册变更记录

| 日期 | HEAD | 变更 |
|---|---|---|
| 2026-08-04 | base `4dac8f8` | 创建 Codex 专用接续手册；整合训练门禁、E2 不晋级、统一架构、实施计划、Bug/训练恢复流程和长期方法论 |
| 2026-08-08 | base `c1d1d6f` | 更新到 logic-chain-v3：rq_v2/LS 19/20/gold=0、production v5_r1、现有 Platform 实现；加入四训练通道、旧模型隔离、机器/人工并行线、MPS 测试漂移和新执行目录 |
