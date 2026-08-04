# 通用 SKU 图像识别系统

> 货架陈列巡检 · **知识库驱动的自动标注 + YOLO** · 人机协同 · **本机原生优先（不依赖 Docker）**

> **平台最终架构入口（2026-08-04）：** 整个产品的唯一总纲是 [`Graph+Loop 智能业务操作系统最终统一架构设计`](./superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md)。它定义一套统一底座和可插拔 Domain Pack；位置外勤规格只是从属模块文档，不是第二套系统。
>
> **实施 Agent 当前开工入口：** 先读 [`统一框架持续可用执行手册 V2`](./superpowers/plans/2026-08-04-continuous-usable-framework-execution-manual.md)。它以当前可用的 8091 识别和 8092 监控为第一批 Capability，先交付统一 Web 和真实 Graph，再持续补齐 Foundation、Label Studio、训练治理和后续 Domain Pack。旧 [`全项目实施总纲`](./superpowers/plans/2026-08-04-full-project-execution-program.md) 保留 Stage 0–9 完整范围，但其串行门禁不再是当前开工顺序。
>
> **现有识别/训练运行入口：** 本页前半部分保留早期系统说明；级联生产架构以 [`handbook.md`](./handbook.md) 为准，最终训练准入、Apple M3 Max/MPS 规范和最新阻断项以 [`2026-08-04-final-training-execution-gate.md`](./superpowers/plans/2026-08-04-final-training-execution-gate.md) 为准。这些文档说明当前系统如何运行，不覆盖最终平台架构。较早严格复核保留在 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md) 作为历史证据。

用多模态大模型当"老师"自动打标签、人工把关，训出 YOLO 当"学生"上识别热路径。原始资产只读、标签追加式留痕、张张过人工才进训练。

---

## 30 秒看懂

- **三阶段**：① 标注（大模型+知识库出提案 → 人工 approved）② 训练（YOLO 微调）③ 识别（训好的 YOLO 检测 + 知识库/VLM 识别）。
- **形态**：默认全本机跑——SQLite 元数据、numpy 向量、本地 blob、自建审核页；Postgres/MinIO/Label Studio 为可选升级。
- **模型**：所有看/读/嵌入走本地 **omlx**（gemma-4 VLM / Qwen3 嵌入 / PaddleOCR-VL / DeepSeek-OCR）。

## 最短路径（完整 10 步见 [`runbook.md`](./runbook.md)）

```bash
cp .env.example .env                       # 填 OMLX_* （见 setup.md）
python -m src.catalog.build_kb             # 建知识库
python -m src.field.photos                 # 入库实景
python -m src.labeling.runner --mode B --max-photos 9   # 自动提案
python -m src.labeling.review_server --port 8090        # 人工审核（浏览器开 :8090，逐张 approved）
python -m src.training.dataset && python -m src.training.trainer   # 数据集 + smoke 训练
python -m src.recognize.api --port 8091    # 识别接口
```

---

## 文档地图

**操作向（怎么用 / 怎么跑）**

| 文档 | 内容 |
|---|---|
| [`superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`](./superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md) | **平台唯一架构总纲**：一套底座、Graph+Loop 内核、统一数据系统、Module SDK 和积木式 Domain Pack |
| [`superpowers/plans/2026-08-04-continuous-usable-framework-execution-manual.md`](./superpowers/plans/2026-08-04-continuous-usable-framework-execution-manual.md) | **当前唯一实施入口**：保留现有可用能力，按 M0–M7 持续交付统一 Web、真实 Graph、标注、训练治理和平台硬化 |
| [`superpowers/plans/2026-08-04-full-project-execution-program.md`](./superpowers/plans/2026-08-04-full-project-execution-program.md) | **全项目开工总纲**：Stage 0–9 依赖、交付物、门禁、需求映射、Agent 启动提示词和审查清单 |
| [`superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md`](./superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md) | **详细设计参考**：26 个 TDD 任务中的 Graph、Capability、IAM、CAS、Job、Billing 设计供新纵向计划按需复用，不再机械串行执行 |
| [`CODEX-PROJECT-HANDBOOK.md`](./CODEX-PROJECT-HANDBOOK.md) | **Codex 内部接续手册**：当前进度、上下文恢复、Bug/训练切换点和可复用方法论；只作索引，不覆盖 L0/L1 权威文件 |
| [`superpowers/specs/2026-08-04-location-field-operations-design.md`](./superpowers/specs/2026-08-04-location-field-operations-design.md) | **从属 Domain Pack 规格**：位置、路线、围栏、外勤、普查和现场证据；禁止自建平行底座 |
| [`setup.md`](./setup.md) | **环境+项目部署**：依赖、omlx、`.env`、校验、可选 Docker/镜像源、可选 Label Studio |
| [`structure.md`](./structure.md) | **结构**：三阶段数据流、`src/` 模块地图、运行时数据目录、数据仓库 schema、红线 |
| [`runbook.md`](./runbook.md) | **启动方式**：逐步命令、起服务、测试、闭环验证、故障排查、当前状态 |
| [`architecture.md`](./architecture.md) | **架构决策（为什么）**：7 条 ADR + 已知缺陷与缓解 + 规模化路径 |
| [`tuning-methodology.md`](./tuning-methodology.md) | **模型迭代调优方法论**：评估→诊断→定向调优闭环、各轮训练演进、调参规则 |
| [`handbook.md`](./handbook.md) | **项目手册（当前状态快照）**：架构/服务/数据/模型/命令/监控/已知坑，快速恢复上下文 |
| [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md) | **最新严格复核**：24 项整改证据、当前制品/运行状态、训练前阻断项 |
| [`superpowers/plans/2026-08-04-git-version-control.md`](./superpowers/plans/2026-08-04-git-version-control.md) | **Git 实施手册**：源码/数据分轨、初始提交、分支/标签、CI、DVC 和恢复演练 |
| [`superpowers/plans/2026-08-04-model-training-next-phase.md`](./superpowers/plans/2026-08-04-model-training-next-phase.md) | **下一阶段训练方案**：gold-v2、检测/分类 oracle、实验矩阵、性能与发布门禁 |
| [`superpowers/plans/2026-08-04-final-training-execution-gate.md`](./superpowers/plans/2026-08-04-final-training-execution-gate.md) | **最终训练执行手册**：Apple Silicon/MPS 核验、数据与评估阻断项、算力预算、pilot→全量→发布门禁 |
| [`project-issue-register-and-remediation.md`](./project-issue-register-and-remediation.md) | **项目问题清单与技术修复指南**：分级问题、代码证据、修复方案、验收标准、测试矩阵与实施顺序 |

**立项与治理背景（早于"原生优先"转向，作背景保留）**

| 文档 | 内容 |
|---|---|
| [`project-charter.md`](./project-charter.md) | 商业论证、目标、范围闸门、里程碑、治理、RACI |
| [`implementation-wbs.md`](./implementation-wbs.md) | 任务依赖图、关键路径、工期、交付物与验收 |
| [`risk-register.md`](./risk-register.md) | 风险等级、应对、触发条件、负责人 |
| [`data-and-annotation-plan.md`](./data-and-annotation-plan.md) | 数据盘点、金标准、标注一致性、防泄漏、多样性 |
| `../2026-07-31-general-sku-recognition-system.md` | 早期技术实施计划（13 Task；其中 docker 假设已被 `setup.md` 的原生路径取代） |

> 阅读建议：任何新 Agent 先读平台唯一架构总纲，再按任务读对应 Domain Pack 规格；需要操作当前识别系统时，再读 `runbook.md` → `structure.md` → `architecture.md`。当前运行文档与最终总纲冲突时，以总纲为目标架构，通过 Adapter 渐进迁移，不直接重写。

---

## 关键设计要点（详见 `architecture.md`）

- **大模型=老师，YOLO=学生**：大模型只自动标注，热路径只跑 YOLO。
- **人工门**：自动只提案；张张过人工才进 `approved/`；低置信不训练。
- **检索只召回，裁决=硬过滤+VLM 终审**：不取 embedding top1（同瓶型不同糖度/容量靠标签文字区分）。
- **追加式+只读原始资产**：DB 触发器禁改/删；`paths.assert_writable` 拦写原始数据。
- **native 优先**：Docker 仅可选；国内拉镜像坑已绕开。

## 红线

1. 原始资产（`搭建初期P1/`、`实景照片.xlsx`、`.field/blobs`）只读。
2. 训练只读 `.labels/approved/`；自动预测 ≠ 金标。
3. 人工动作只追加（`review_events.jsonl`）。
4. 密钥只经 `.env`。

## 测试

```bash
python -m pytest tests/unit tests/contract -q     # 不变性/对齐/命名/别名 契约
```

## 当前状态（2026-08-04 最终训练复核快照）

- ✅ recognize 当前能从 `prod_20260804_v4_r2` 加载 detector/classifier，bundle 的 16 个文件通过校验；8091 health 返回 200。
- ✅ monitor 新进程内存约 248 MiB，仍需 2 小时长稳验证。
- ✅ 本机为 Apple M3 Max / arm64 / 128 GB；真实终端中的 MPS 张量与当前级联 MPS 推理均已通过，硬件路线 GO。
- ⏹️ 当前训练已停止；生产 classifier 为 208 类 ResNet18，记录 val_acc 83.67%，不含 `__unknown__`。
- ⚠️ 复核时实际监听 8091/8092；8300 Label Studio、8301 ML backend、8304 orchestrator 均未运行。
- ✅ Git 已初始化；2026-08-04 统一架构交付前只读 fresh 测试为 74 passed。
- 🟥 新协议集虽已冻结，但 dev_v1 有 2 个规范化门店别名与 batch2 重叠，旧 v6 与四协议集也有大量门店重叠；不得续跑 v6 checkpoint。
- 🟥 `.datasets/sku_v6` 和两个 crop 数据仍是旧制品；默认 builder 会命中冻结集并失败，且门店/session 隔离未进入 fail-closed。
- 🟥 E0 的 89.0% 是 matched-conditional precision；纳入 accepted FP 后业务 precision 为 60.45%，且当前仍是 point-in-box 而非严格 IoU。
- ⏳ 下一步先关闭最终手册 G1～G6，再运行 MPS 小规模 detector pilot；不要立即执行正式全量训练。

## 维护约定

- 范围/门槛/治理变更走章程变更流程；技术决策更新 `architecture.md` 的 ADR。
- 文档与代码现状保持一致；状态变更同步本 README"当前状态"。
- 版本升级时更新各文档头部版本与日期。
