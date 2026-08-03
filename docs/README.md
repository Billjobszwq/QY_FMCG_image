# 通用 SKU 图像识别系统

> 货架陈列巡检 · **知识库驱动的自动标注 + YOLO** · 人机协同 · **本机原生优先（不依赖 Docker）**

> **当前入口（2026-08-04）：** 本页前半部分保留早期系统说明；级联生产架构和整改状态以 [`handbook.md`](./handbook.md) 为准，严格复核以 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md) 为准。当前不能宣称所有 RA 项已关闭。

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
| [`setup.md`](./setup.md) | **环境+项目部署**：依赖、omlx、`.env`、校验、可选 Docker/镜像源、可选 Label Studio |
| [`structure.md`](./structure.md) | **结构**：三阶段数据流、`src/` 模块地图、运行时数据目录、数据仓库 schema、红线 |
| [`runbook.md`](./runbook.md) | **启动方式**：逐步命令、起服务、测试、闭环验证、故障排查、当前状态 |
| [`architecture.md`](./architecture.md) | **架构决策（为什么）**：7 条 ADR + 已知缺陷与缓解 + 规模化路径 |
| [`tuning-methodology.md`](./tuning-methodology.md) | **模型迭代调优方法论**：评估→诊断→定向调优闭环、各轮训练演进、调参规则 |
| [`handbook.md`](./handbook.md) | **项目手册（当前状态快照）**：架构/服务/数据/模型/命令/监控/已知坑，快速恢复上下文 |
| [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md) | **最新严格复核**：24 项整改证据、当前制品/运行状态、训练前阻断项 |
| [`superpowers/plans/2026-08-04-git-version-control.md`](./superpowers/plans/2026-08-04-git-version-control.md) | **Git 实施手册**：源码/数据分轨、初始提交、分支/标签、CI、DVC 和恢复演练 |
| [`superpowers/plans/2026-08-04-model-training-next-phase.md`](./superpowers/plans/2026-08-04-model-training-next-phase.md) | **下一阶段训练方案**：gold-v2、检测/分类 oracle、实验矩阵、性能与发布门禁 |
| [`project-issue-register-and-remediation.md`](./project-issue-register-and-remediation.md) | **项目问题清单与技术修复指南**：分级问题、代码证据、修复方案、验收标准、测试矩阵与实施顺序 |

**立项与治理背景（早于"原生优先"转向，作背景保留）**

| 文档 | 内容 |
|---|---|
| [`project-charter.md`](./project-charter.md) | 商业论证、目标、范围闸门、里程碑、治理、RACI |
| [`implementation-wbs.md`](./implementation-wbs.md) | 任务依赖图、关键路径、工期、交付物与验收 |
| [`risk-register.md`](./risk-register.md) | 风险等级、应对、触发条件、负责人 |
| [`data-and-annotation-plan.md`](./data-and-annotation-plan.md) | 数据盘点、金标准、标注一致性、防泄漏、多样性 |
| `../2026-07-31-general-sku-recognition-system.md` | 早期技术实施计划（13 Task；其中 docker 假设已被 `setup.md` 的原生路径取代） |

> 阅读建议：新读者先看本 README → `runbook.md` 跑通 → `structure.md` 理解结构 → `architecture.md` 理解取舍；治理/排期看背景四篇。

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

## 当前状态（2026-08-04 二次复核快照）

- ✅ recognize 当前能从 `prod_20260804_v4_r2` 加载 detector/classifier，bundle 的 16 个文件通过校验；8091 health 返回 200。
- ✅ monitor 新进程内存已从上一轮约 16.3 GiB 降到约 261 MiB，但仍需 2 小时长稳验证。
- ⏹️ 当前训练已停止；生产 classifier 为 208 类 ResNet18，记录 val_acc 83.67%，不含 `__unknown__`。
- ⚠️ 复核时实际监听 8091/8092；8300 Label Studio、8301 ML backend、8304 orchestrator 均未运行。
- 🟥 当前 977 张 holdout 全部被 v4 detector 见过，不能评价当前模型的未见泛化；`.datasets/sku_v6` 和 crop 数据仍是整改前旧制品。
- 🟥 完成本次文档纠偏后的 RA 状态为 5 项基本关闭/有主要证据、14 项部分修复、5 项未关闭；当前 22 项测试不覆盖本轮核心整改。
- ⏳ 下一步先冻结 fresh-store gold-v2 并做 detector/classifier oracle 实验，再决定是否重训；不要直接续跑现有训练命令。

## 维护约定

- 范围/门槛/治理变更走章程变更流程；技术决策更新 `architecture.md` 的 ADR。
- 文档与代码现状保持一致；状态变更同步本 README"当前状态"。
- 版本升级时更新各文档头部版本与日期。
