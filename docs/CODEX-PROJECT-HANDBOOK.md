# Codex 项目接续手册

> 用途：这是 Codex 自己使用的长期项目索引、进度快照和方法论手册，用于会话切换、上下文压缩和后续复盘。
>
> 权威边界：本文件不是产品 L0 架构、实施计划、训练启动授权或线上状态接口。它只负责把权威文件、已经发生的工作和下一步入口串起来。若本文件与权威文件或当前代码冲突，以权威文件和重新验证的当前事实为准，并立即修订本文件。
>
> 当前快照时间：2026-08-13，Asia/Shanghai。

## 2026-08-13 · Operational Scope V5.1 Correction 收口（当前接续入口）

- 现场：分支 `feat/nextgen-training-cycle-v2`；收尾 HEAD 见
  `git rev-parse HEAD`（基线 8e31708d → 本轮 18+ commits）；tracked
  工作树干净；未跟踪数据/训练资产未触碰。
- 本轮性质：**不增加新功能**，修复独立审计发现的安全边界/状态竞态/
  数据血缘/UI 连续性问题。入口目录
  `docs/implementation/operational-scope-v5-correction-v1/`
  （00-LIVE-AUDIT / 01-ROOT-CAUSES-AND-CONTRACTS / 02..05 设计契约 /
  STATUS / ISSUES / DECISIONS / LIST / EXECUTION-LOG / FINAL-REPORT）。
- 八项修复全部落地（细节见该目录 FINAL-REPORT 20 节）：
  1) P0-1 quarantine 写逃逸：服务层 `_assert_batch_writable` 唯一强制
     点（409 IMPORT_BATCH_WRITE_BLOCKED），14 模板参数化 + 并发/伪造/
     重启负例，Gate 检查 quarantine_execution_escape /
     quarantine_no_operational_writes（BLOCKED_BY_IMPORT_SECURITY）；
     imp-bf333d101db6 QA 重放以 QA_REPLAY_DETECTED 证据入账（不回写
     历史）。
  2) P0-2 首次密码零持久化：明文仅 commit 当次响应；落库/DTO/列表/
     errors.csv 递归 secret 扫描 [REDACTED]；熵 128bit；存量清洗脚本；
     Gate recursive_secret_scan。
  3) 隔离区裁决状态机：迁移 060 + CAS + 双人审批（申请人≠审批人）+
     新批次 revision（不原地改）+ UI 面板；三个现存批次
     retained_for_evidence，最终处置待用户业务裁决。
  4) 17 批客户血缘确定性回填（test_run→registry 唯一客户 +
     md_customer 交叉印证，零名称猜测；12→29 关联行）；quarantine
     显示“未绑定/待裁决”，禁“全局”误导；Gate 关联完整性检查。
  5) parallel 终态竞态：全部终态写改条件 UPDATE + rowcount，迟到
     回写被拒；100 轮压力（多种子）零漂移；test_branch_timeout 确定性化。
  6) Gate 证据新鲜度闭环：四份证据 binding 块（source_commit/
     code_tree_hash/migration_hash/database_fingerprint/
     suite_config_hash/command_hash/result_hash/时间戳）；去自比较；
     实时复核 HEAD+树+迁移+worktree+DB；test_report 机器生成器；
     浏览器四视图截图像素互异检查。评估器 3.2.0→3.3.0。
  7) 导航滚动连续性：ScrollManager（PUSH/REPLACE 归零聚焦 h1 +
     aria-live；POP 恢复），四视口浏览器断言 nav_scroll_continuity。
  8) 报告单一事实源：scripts/osv51_machine_facts.py；V5 历史报告
     42vs52/125vs126/namespace/“首次23/23”以更正附录修正。
- 负例账本 12→21（ALL_BLOCKED）；hermetic 全量 0 failed / 1581 passed
  （机器生成报告）；host_mps 6 passed；Registry 126 条零问题；
  SQLite integrity ok；production=prod_v4_best_r1 未切换；训练进程 0。
- 方法论新增（V5.1 教训）：
  (1) 证据文件的 recorded 绑定必须来自证据生成时刻，Gate 评估时把
      当前值同时当 recorded/current 是自比较缺陷——binding 块 +
      独立计算是唯一解；
  (2) “静态 READY、实时 STALE、报告 0 failed、实测 1 failed”可以
      并存——证据链每一环（测试报告、负例账本、浏览器证据）都必须
      机器生成且带绑定，手写摘要必漂移；
  (3) 守卫必须在 Domain Service 层单一强制点，UI/route 层只是体验；
      状态机写迁移一律条件 UPDATE/CAS，禁止 SELECT-then-UPDATE；
  (4) 隔离/历史数据的“全局”显示是血缘缺失的伪装——空关联必须有
      显式的“未绑定/待裁决”语义；
  (5) 多代理并行开发时，代理报告的 commit SHA/结果必须逐一 git 复核
      （本轮出现幻觉报告，实际工作以 git 内容为准）。
- 未关闭：OSV51-013（store.py set_business_run_status 残留
  SELECT-then-UPDATE，低风险）；三个隔离批次最终处置待用户裁决。
- 下一步：真实数据 UAT（Import Center 运营视图贯穿）+ 人工走查；
  UAT 通过前不得宣称 ACCEPTED/PRODUCTION_READY。

## 2026-08-12 · 当前接续入口（优先于下方历史快照）

- 现场 HEAD：`47c01c437a5ccae380e0bf80bc0ca016d4010325`；分支
  `feat/nextgen-training-cycle-v2`；tracked 工作树干净，历史未跟踪数据/训练资产
  继续受保护。
- SQLite：`integrity_check=ok`，107 张表，最新迁移
  `040_auth_credential_lock`；8091 当前仍加载
  `bundle:prod_20260805_v5_r1`。
- 当前唯一实施入口：
  `docs/implementation/agentic-business-os-operational-workbench-v3/`；
  直接执行文件为同目录 `AGENT-EXECUTION-PROMPT.md`。
- 当前 Gate：`OPERATIONAL_WORKBENCH_V3_NOT_STARTED`。旧
  `READY_FOR_USER_ACCEPTANCE` 已被用户真实体验和 Codex 独立复核撤销。
- 当前任务不是继续堆 Domain 页面，而是统一首页/任务/日历/日志/进度，建立真实
  Agent Runtime 和 React Flow 工作流，并使问卷、位置、识别训练、BI、IAM、
  主数据、Usage 都能由用户从空白创建和贯穿运行。
- 本轮用户授权：本机 `best/sku_v4_best.pt` 经 shadow/回归/回滚后成为默认
  standard profile；不授权长时间新训练、远程部署、merge/push 或删除历史资产。

## 2026-08-11 · 连续任务底座与 Domain Packs V2 接续

- 现场 HEAD：`e5c4236d`，分支 `feat/nextgen-training-cycle-v2`；tracked 工作树干净，用户未跟踪训练/数据资产继续受保护。
- 最新完整测试仍为 hermetic `1173 passed, 1 skipped, 6 deselected`，但浏览器和数据库/API 对账发现测试未覆盖的业务断链。
- 当前 Gate 已从交付报告中的 `READY_FOR_NEXT_DOMAIN_PACK` 纠正为 `FOUNDATION_CONTINUITY_REPAIR_REQUIRED`。
- 核心 P0：主页/主管读取旧 WorkItems 使 250 项历史审核复活；快速目标丢失输入；识别、Graph、Agent Command、Evidence、Usage 没有统一 work/run；服务档位只记录元数据。
- 核心 UI：1024/768 主管抽屉遮挡主内容；识别任务页面声称可查 trace，但无详情/证据/用量入口。
- 架构决定：ABOS 原生 Graph+Loop/Workflow Studio 是控制平面；n8n 只作可选 connector executor，Dify 只作可选 AI subflow provider，均不得成为第二事实源。
- 最新实施入口：`docs/implementation/agentic-business-os-domain-packs-v2/README.md`；完整 Agent 任务书：同目录 `AGENT-EXECUTION-PROMPT.md`。
- 实施顺序：P0 连续性/UI → Work/Event/Usage → Workflow Studio → IAM/主数据 → 问卷 → BI → Geo/Field → Finance。
- 本次 Codex 仅修改文档，未修改业务代码、DB、模型或运行配置；未启动训练、切 production、merge/push/deploy。

## 2026-08-11 · 平台定位与工作台纠偏接续

- 现场 HEAD 已前进到 `1a6f0aeebaaf48618bce4f34530bcec8fd496215`（后续仍须实时复核），分支 `feat/nextgen-training-cycle-v2`。
- 最新只读审计发现：平台文案仍绑定 SKU、Module/App/Agent 多事实源、多个假三级菜单、Recognition Profile 未进入请求、Agent UIIntent/command/evidence 未被 Web 消费、CSS 变量与关键组件类缺失。
- 2026-08-11 探测时 8091/8092/8300/8400 均未运行；这只是当时现场状态，不代表永久故障。
- 最新实施入口：`docs/implementation/agentic-business-os-workbench-v1/README.md`；完整 Agent 任务书：同目录 `AGENT-EXECUTION-PROMPT.md`。
- 本入口只授权工作台、模块/Agent/API 契约、识别首域、测试和文档实现；不授权训练、生产切换、删除、merge/push/deploy。

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
| Branch | `feat/nextgen-training-cycle-v2` |
| 当前代码基线 HEAD | `47c01c437a5ccae380e0bf80bc0ca016d4010325`；本轮 Codex 只新增/更新文档，后续以实时 `git rev-parse HEAD` 为准 |
| 最近独立测试 | 2026-08-12 Codex 在 `1c5cfe24` 后独立复核 hermetic `1260 passed, 1 skipped, 6 deselected`、host MPS `6 passed`；HEAD 后续前进到 47c01c43，实施前必须 fresh run |
| Python | `/Users/zhangweiqi/miniconda3/bin/python3`，3.13.2 |
| 工作树 | `.datasets_nextgen/`、`.micro_gold*`、`.quality/`、`.sam_*`、`cropped_images/`、`reports/nextgen_v2/` 等历史未跟踪资产不碰、不暂存、不删除 |
| 当前生产 bundle | `prod_20260805_v5_r1`；V3 获准在本机完成 V4 best 受控切换，必须可回滚 |
| 数据库 | `.platform/platform.sqlite` integrity ok；107 表；migration 040 |
| 训练 | 本轮不授权长训练，只允许 preflight/dry-run/smoke 和现有制品真实加载 |
| Foundation 实现 | 控制面和 Domain 纵向样板已有代码，但统一 current projection、真实 Agent、可视化 Workflow 和用户自定义工作台尚未闭合 |
| 当前工作主题 | `agentic-business-os-operational-workbench-v3`：从演示模块重建为可运营工作面，并为真实客户/地址/问卷 UAT 做准备 |

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

### 2.0 当前最高优先接续入口（2026-08-12）

| 文件 | 作用 |
|---|---|
| `docs/implementation/agentic-business-os-operational-workbench-v3/` | 当前唯一实施入口：首页/任务/日历/日志/进度、Agent/Workflow、各 Domain 用户工作台、V4 best 和真实 UAT |
| `docs/implementation/project-logic-chain-v3/` | 当前 22 层运行逻辑、事实源、rq_v2/LS/gold 状态和验收链 |
| `docs/implementation/nextgen-four-model-training-loop-v2/` | 历史训练专项入口：三批数据、SAM、四训练模型、Apple 调度和 Recognition Profile；不再是全平台当前入口 |
| `docs/implementation/graph-loop-training-control-v1/` | V1 契约与历史交付证据；已复核为执行链未闭合，不再是开工入口 |
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

下一阶段以 `docs/implementation/nextgen-four-model-training-loop-v2/` 为边界实施完整数据与训练闭环。必须继续使用 Adapter/Capability/Graph Hook，不能把四条训练逻辑塞回单体 `Training.tsx`、`service.py` 或 shell 分支。

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
16. Label Studio 的 208 个 SKU taxonomy 与 Registry 已三方核对一致；13 个 no-proposal 与 1 个低置信手工 SKU 不等于“标签缺失”，blind 20 必须继续零 prediction。
17. 三批数据 exact unique 为 29,176，canonical 坐标 745,695；第一/二批 476 张坐标不一致必须建账，第三批 40,591 个 unknown 点不得强映射。
18. 当前 V2 控制台只有只读卡片，Dataset API 固定空 rows，Graph 是内存态，Recognition 无 profile selector；不能因为契约测试通过就启动真实四模型训练。
19. 本轮四个训练候选定义为 detector、YOLO-seg student、classifier、Qwen QLoRA；SAM 先作冻结数据教师，禁止用自身伪 mask 证明 SAM 微调成功。

## 12. 下一次工作的明确切换点

当前唯一实施入口：`docs/implementation/agentic-business-os-operational-workbench-v3/AGENT-EXECUTION-PROMPT.md`。

以下旧 Track A/B 作为训练专项历史计划保留；不得覆盖 V3 的当前任务顺序。V3
先修统一状态，再连续完成首页、Import Center、Agent/Workflow、问卷、位置、
识别训练工作台、BI、Usage 和真实 UAT 预演。

### Track A：数据与真实控制链

1. 关闭 fresh suite 8 个宿主 MPS 耦合失败，重建可靠基线。
2. 三批照片从原始输入 exact/near dedupe、严格质量过滤和证据链。
3. 点提示 SAM 生成 mask/tight box/crops，并完成分层 mask audit。
4. 建 D1 detector、D2 YOLO-seg、D3 classifier、D4 VLM 四个 snapshot。
5. 将内存 Graph、空数据 API、只读 Web 补成持久化可恢复真实执行链。
6. Recognition Profile 在 Web/API/Agent 五入口同口径。

### Track B：有界实验训练与人工门

1. 质量/mask/gold 的人工审核与机器数据构建并行，人工结果不能由 Agent 伪造。
2. 本 V2 任务书已授权 Gate 后运行四个有界 experimental candidate；没有 human gold 时结果必须标 interim。
3. M1/M2/M3 先 benchmark；只有组合吞吐提升 ≥25% 且资源/服务安全才并发 2，不默认并发 3。
4. Qwen 永远独占 MLX/heavy lease，先 5k–20k、1 epoch、vision frozen pilot。
5. candidate 评估、shadow、发布仍保持独立门禁，production switch=false。

本轮完成状态由 V2 手册定义；没有 human frozen evaluation 时最多写
`FOUR_EXPERIMENTAL_CANDIDATES_READY_AWAITING_HUMAN_EVALUATION`，不能写上线就绪。

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
| 2026-08-08 | base `ce6f614` | 复核 V1 交付并重新打开执行链：确认 LS 208 标签完整、三批 29,176 照片/745,695 点、fresh 1002+8 失败；建立 V2 三批过滤+SAM+四模型+Profile 一次性执行手册与训练授权边界 |

## 2026-08-09 接续更新
- 当前实施入口：`docs/implementation/sku-long-tail-agent-foundation-v1/AGENT-EXECUTION-PROMPT.md`。
- 关键事实：grouped split 后分类器真实泛化 30–35%（随机切分 82.4% 为泄漏偏差）；
  KB 对百事系覆盖 0（recall 分母 0 → null）；四 snapshot v3 已冻结；
  Agent Kernel/黑板/记忆/黄色抽屉/任务板已上线；production 未切换。
- Gate：FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_EVALUATION。

## 2026-08-10 候选证据链收口 + micro-gold 更新
- 入口：docs/implementation/candidate-evidence-convergence-and-microgold-v1/。
- Gate=MICRO_GOLD_READY_AWAITING_HUMAN_REVIEW；Cycle 17/19。
- Profile 单源 DB（recognition_profile_def_v1，10 定义）；e1/e5→m3_tvt_*_v2；
  旧 ablation=EXPERIMENTAL_SUPERSEDED_BY_*。
- M4 三版本真实推理证据：reports/nextgen_v2/m4_evidence_v2/（逐样本 raw/tokens/latency）。
- demo_micro_gold_v1：LS 项目 21，200 blind 任务，0 prediction；待人工主审。
- 后续流程：人工完成 200 主审+40 二盲+分歧仲裁 → human_final/gold_verified。

## 2026-08-10 泄漏重建收口
- 入口 docs/implementation/micro-gold-v2-leakage-rebuild/。
- Gate=MICRO_GOLD_V2_READY_AWAITING_HUMAN_REVIEW（LS22 唯一有效人工入口）。
- M4 v2 0.828=EXPERIMENTAL_GROUP_LEAKED；v3 独立评估新 adapter 无收益。
- 用户下一步唯一操作：LS22 完成 200 条真实人工审核。

## 2026-08-12 · ABOSV2 Phase A–F + T9 收口接续

- 入口：`docs/implementation/agentic-business-os-domain-packs-v2/`（STATUS.md
  为唯一 Gate）。Gate=`PHASE_A–F_CLOSED_G1–G8_PASSED`，T9 Z-1/Z-2/Z-3 已收口。
- 关键事实：迁移至 039；统一控制平面（BusinessRun/WorkItem/Event/Usage/
  Evidence + Outbox + 可重建投影）；Workflow Studio（15 节点类型、生命周期、
  checkpoint/死信、n8n/Dify 诚实 blocked）；IAM+主数据（双 test fixture
  客户隔离实证）；问卷/BI/外勤/财务纵向切片全部实跑贯通。
- 集成契约：`GET /api/v1/platform/integration` 现场 ok=true（12 agents、
  34 UI 路由、190 OpenAPI 路径、33 命令）；前端 MODULE_ROUTES 与后端目录
  三方一致性由契约测试强制。
- 测试基线：hermetic 1260 passed（+1 skipped）；host_mps 6 passed 单独统计。
- 现场性能快检：workitems p50≈4.6ms/p95≈4.8ms；reconcile p95≈1.3ms。
- 安全快检：无 session 401；无 CSRF 403；identity 无敏感字段泄漏。
- 红线保持：未 merge/push/deploy；未启动训练；production 未切换；
  用户未跟踪资产零触碰。
- 下一步：用户验收（READY_FOR_USER_ACCEPTANCE 需用户确认）；剩余 P2 项
  （便签服务端化、event SSE、profile 信息架构）按 ISSUES.md 排期。

## 2026-08-12 · Operational Workbench V3 实施收口（当前接续入口）

- 实施 Agent：Lingma。入口仍为
  `docs/implementation/agentic-business-os-operational-workbench-v3/`。
- Gate：`READY_FOR_REAL_DATA_UAT`（T0–T12 全部 VERIFIED_LOCAL，
  G0–G8 通过，P0/P1 清零，UAT 机器预演 23/23）。
- 本轮 commit 链：a94cdc82（T1）→ 90eaa7e9/d9923cb5（T2）→ 419043d6
  （T3）→ T4 链 → e7b3361c（T5）→ 37a45c53（T6）→ 5c634489（T7）→
  1fd048b8（T8）→ d64a436a（T9）→ bbeaa643（T10）→ 7fd64b66（T11）
  → T12 收口。分支 `feat/nextgen-training-cycle-v2`；未 merge/push/deploy。
- 迁移 041–046 已应用；SQLite integrity ok；备份
  `.platform/backups/platform_pre_v3_*.sqlite`。
- **production bundle 已按用户授权切换为 `prod_v4_best_r1`**
  （shadow 对比 + 回滚验证完成；CURRENT.previous.json 备份在位；
  detector sha256 84bf9936…，classifier 与 v5 bundle 同 SHA 零变量）。
  实验 profile（exp_classifier_only / exp_v4_detector_smoke /
  exp_m3_grouped_classifier）诚实 disabled + blocker。
- 新增能力：统一 current-work 端点；首页总控八段；Import Center
  （14 模板）；真实 Agent Runtime（7 Agent 有界 health + 工具循环）；
  React Flow 工作流画布（wait 持久化 timer）；问卷 Builder（matrix/
  description）；地理编码 SPI + maplibre 地图（无 Key 诚实降级）；
  BI 受限公式 DSL + ECharts；客户 Usage 工作台；帮助/系统管理拆分。
- 测试基线：hermetic 1328 passed；host_mps 6 passed。
- 诚实残留：地理编码/瓦片未配 Key（degraded）；本轮未启动长训练；
  精细 rate limit 列入 P2。详见 STATUS.md。

## 2026-08-12 · 用户验收重新打开 + Operational Workbench V3

- 当前唯一实施入口改为：
  `docs/implementation/agentic-business-os-operational-workbench-v3/`。
- 用户实际体验证明 V2 的 `READY_FOR_USER_ACCEPTANCE` 过早：系统有大量页面和
  纵向 fixture，但首页/主管/任务/日历/进度、Agent Runtime、可视化 Workflow
  和各 Domain 自定义工作台尚未形成可运营闭环。
- Codex 独立复核重新打开四项事实 Bug：`workflow.succeeded` 未被 projection
  reducer 识别；首页 WorkItems 与 WorkItemV2/Taskboard 多事实源；成功 run
  残留旧 error；BI 版本列表重复 latest。
- 用户新增硬要求：真正首页 Dashboard；主管工作台重排；数据资产作为容量/资源/
  质量/血缘中心；问卷从空白搭建；地址导入/地理编码/规则/地图；V4 best 默认识别；
  其他模型本机真实 Profile；标注/数据集/自主训练中心；BI 指标/公式/Dashboard；
  Agent soul/prompt/Skill/知识库/记忆/工具配置；可视化 Workflow；自定义 IAM/
  主数据；客户级 Usage；帮助文档；全局 CSV/XLSX Import Center。
- Workflow 选型冻结：ABOS 原生 canonical graph/runtime + MIT React Flow 画布；
  Apache-2.0 Node-RED 只作未来可选 Adapter；因商业嵌入/多租户许可证限制，不把
  n8n 或 Dify 嵌入为产品核心。
- 人工与 Agent 是双通道：Agent 可以建议、规划和执行获批命令，但每项关键业务
  必须保留人工入口、失败接管和审计。
- 当前 Gate=`OPERATIONAL_WORKBENCH_V3_NOT_STARTED`；目标仅为
  `READY_FOR_REAL_DATA_UAT`。没有用户真实客户/地址/问卷贯穿验收，不得写
  ACCEPTED/PRODUCTION_READY。
- 编写任务书时现场 HEAD 为 `47c01c43`，较用户提供的 `1c5cfe24` 已前进；
  实施 Agent 必须以开工 fresh audit 为准，不能复用旧表数/迁移数。
- 本轮任务书授权本机 `best/sku_v4_best.pt` 经 shadow/回归/回滚后成为默认
  standard profile；不授权新增长时间训练、远程部署、merge/push 或把弱实验模型
  伪装成商业 production。

## 2026-08-13 · Scope Integrity V3：假阳性 Gate 收口与方法论（当前接续入口）

- 入口：`docs/implementation/agentic-business-os-scope-integrity-v3/`
  （STATUS/FINAL-REPORT 为准）。开工基线 HEAD `eb19425f`。
- **假阳性 Gate 教训**：SI2 的 READY_FOR_REAL_DATA_UAT 被独立审计
  证伪（media=24/work=8/recognition=5/BI=5/失败 Agent=5/Usage=89/
  节点漂移=39 全部漏检）。三个根因必须永久记取：
  1. **隔离只看行自身列**（COALESCE(data_scope)=operational）看不
     见父链泄漏 → 必须用 effective scope（自身列 ⊕ 父链 ⊕
     attribution）；
  2. **scanner except/continue 吞异常** → 扫描必须 fail-fast，异常
     即 BLOCKED；
  3. **静态 gate.json 无 freshness** → Gate 必须绑定 DB
     fingerprint（scope-graph 聚合/事件水位/投影 hash/关键表计数）
     并在读取时实时复评，数据变化即 STALE_GATE_EVIDENCE。
- **作用域传播方法**：唯一 ExecutionContext（tenant/customer/project/
  data_scope/test_run/correlation/parent_run/actor/source/定义版本）；
  解析顺序 Test Run registry（存在/current/客户匹配，fail-closed）
  → 父 Run → response/assignment 父链 → Customer → operational；
  六维父子校验；对象创建与 scope 写入同一事务（禁止先 commit 再
  bind）；namespace 不可覆盖（幂等仅内容一致否则 409）；失败路径
  先解析 scope 再查定义；客户端不得自证 operational。
- **不可变账本 effective_scope**：Usage/Evidence 绝不 UPDATE（DB
  触发器强制）；纠偏一律经 `scope_attribution_ledger_v1` 追加式
  绑定，运营查询/计费消费 effective 口径；每轮回填写
  `scope_backfill_audit_v1`（规则/父对象/数量/hash/actor/时间）。
- **全表 Scope Registry**：`src/platform/scope_registry.py` 登记全部
  123 表（七类），覆盖率 100% 是 Gate 前提；任何新业务表必须先
  登记再使用（否则 BLOCKED_BY_SCOPE_REGISTRY）。
- **防复发机制**：17 项契约红测试（test_si3_scope_integrity.py）+ 14
  项 Gate 负例（gate_negative_tests.json）+ UAT V5 内联泄漏注入
  负例（注入→STALE→修复→恢复）+ 浏览器真实文本断言（不再相信
  页面自报计数器）。任何新 Domain/表/创建路径接入时必须先过这四道。
- 当前机器 Gate：`.eval/scope_v3/gate.json`（Gate 3.0 全量评估）；
  production `prod_v4_best_r1` 未切换；未启动训练；真实数据 UAT
  与人工验收由用户执行，此前不得写 ACCEPTED/PRODUCTION_READY。

## 2026-08-13 · Operational Scope V4：IAM/BI/Finance 测试污染清零方法论（当前接续入口）

- 入口：`docs/implementation/agentic-business-os-operational-scope-v4/`
  （STATUS/FINAL-REPORT 为准）。开工基线 HEAD `63679be0`（含外部
  TaaS commits，已审计）。
- **SI3 READY 再次被证伪的教训（必须永久记取）**：
  1. **物理表覆盖率 ≠ 业务对象隔离覆盖率**：Scope Registry 登记了
     全部 123 表，但 IAM 身份/BI 注册表/前端默认值三个运营面仍被
     UAT 污染（85 active 账号、物理行数统计、硬编码客户）。每张表
     除分类外必须声明 UAT 生命周期（可创建性/provenance/归档/
     登录/计费/BI/浏览器暴露面）。
  2. **global configuration / reference registry 也会被 UAT 污染**：
     metric/dashboard/价目表/导入批次等“配置类”对象由 UAT 创建后
     会永久滞留运营平面；必须与业务对象同等的 provenance+归档。
  3. **测试账号必须有完整生命周期**：创建即登记 provenance（受
     信 test_run fail-closed）；Test Run 归档同事务收敛（禁用+
     membership 归档+会话失效）；登录拒绝带稳定错误码+审计；
     历史行永不物理删除。
  4. **BI 数据产品必须用 effective operational 口径**：禁止裸
     SELECT count(*) 物理行数；唯一计数函数与运营 Domain API 逐项
     对账并进 Gate。
  5. **Finance 默认上下文不得使用 demo/UAT 客户**：默认客户只能
     来自 operational customer 服务；无客户时空态+入口；永不回退。
  6. **Gate 浏览器覆盖必须与全部运营 Domain Pack 对齐**：12 个
     一级工作台语义断言强制；证据面必须等于报告表述（少一页即
     BLOCKED）。
  7. **READY 必须绑定最终 HEAD、DB fingerprint 与全应用语义证据**；
     外部 commits 会自然触发 STALE，必须先审计新 commits 再继续。
  8. **Agent 自动化必须保留人工备用入口**：IAM/BI/Finance 人工操作
     路径不依赖 Agent；Agent 失败不关闭人工入口。
  9. **后续所有 Domain Pack 必须声明 Test Run 创建、归档、计费和
     BI 影响**（module manifest 扩展项）。
- 当前机器 Gate：`.eval/scope_v4/gate.json`（Gate 3.1，34 检查）；
  production `prod_v4_best_r1` 未切换；未启动训练；真实数据 UAT 与
  人工验收由用户执行，此前不得写 ACCEPTED/PRODUCTION_READY。

## 14. 手册变更记录（追加）

| 日期 | HEAD | 变更 |
|---|---|---|
| 2026-08-13 | si3 收尾提交 | Scope Integrity V3 收口：假阳性 Gate 降级并修复；Scope Graph V3/effective scope/attribution ledger/全表 Registry/Gate 3.0 freshness/UAT V5 48 项；hermetic 1425 passed，host MPS 6 passed |
| 2026-08-13 | si4 收尾提交 | Operational Scope V4 收口：SI3 READY 再次证伪（IAM 85 active 账号/BI 物理计数/前端默认值）；IAM 身份生命周期（迁移 057）；BI/Finance effective 口径（迁移 058）；Registry 语义层；Gate 3.1 + 22 负例；UAT V6 57/57；12 页浏览器 30/30；hermetic 1447 passed，host MPS 6 passed |
| 2026-08-13 | osv5 收尾提交 | Operational Scope V5 收口：V4 READY 再次证伪（20 条历史 UAT 导入批次污染运营面/Import API 越权/Registry 假语义）；批次=冻结执行上下文（迁移 059 + 多客户关联表）；模板权限矩阵 + 逐客户整批 fail-closed + DTO 白名单；可执行 Registry（validator + scanner/archiver/filter/TestCenter/Gate 全部派生，平行清单废除）；历史 20 条纠偏 17 bind/3 quarantine；Gate 3.2.0（18 新检查 + 12 负例）；UAT V7 真实 multipart Import Center 23/23；浏览器对象级 29/29；hermetic 1479 passed，host MPS 6 passed |

## 2026-08-13 · Operational Scope V5：可执行 Registry 与导入链收口方法论

V5 再次证明：上一轮的 READY 只覆盖上一轮认识的失败面。新增
方法论（接续 V4 九条）：

  1. **表名进入 Registry 不等于作用域治理完成**。模块只有在创建、
     授权、运营查询、归档、测试中心、BI、Gate、浏览器和证据链
     全部由同一可执行策略驱动后，才算完成接入。
  2. **Registry 声明必须可机器验证**：pk/列/parent edge/handler
     对 schema 逐项校验；默认值不得臆造不存在的列（如全局
     tenant_id）；声明造假比漏登记更危险。
  3. **平行硬编码清单是泄漏温床**：scanner/archiver/过滤器/
     统计/Gate 必须从唯一事实源派生；新增表只改 Registry 一处。
  4. **导入批次是执行上下文载体**：必须冻结 tenant/scope/
     test_run/actor/客户关联与授权决定；多客户批次不得压成单
     customer_id；任何模板不得因“无客户列”绕过授权。
  5. **API 响应必须 DTO 白名单**：直接回数据库行 = 原始 payload
     泄漏；原始预览需独立权限 + 脱敏 + 行数上限。
  6. **历史纠偏必须结构化证据优先**：mapping/回执/时间窗 >
     文件名；不可唯一归属 → quarantine（fail-closed），不得删除
     或继续计入运营。
  7. **浏览器验收必须对象级对账**（DOM 行/具体 ID == API 口径）；
     “页面不含 token”是假阴性；同 URL hash 导航需强制重载防
     状态污染；CDP 值提取不得吞 falsy。
  8. **UAT 必须真实经过其声称的入口**：宣称“导入闭环”就必须
     multipart 走真实 Import API，否则无端到端证据。
  9. **Gate 版本必须单点定义全链引用**（代码/gate.json/API/Web/
     文档/validator/负例）；文档口径与代码版本漂移本身是缺陷。
