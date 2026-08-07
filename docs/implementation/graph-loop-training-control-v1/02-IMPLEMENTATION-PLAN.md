# Graph+Loop Four-Lane Training Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` and `superpowers:test-driven-development`; use gstack `qa-only` before any mutation-heavy QA.

**Goal:** 在不切换当前生产 bundle、不启动全量真实训练、不删除历史制品的前提下，完成标注、过滤、四数据集、四训练通道和统一 Web 控制台的可运行闭环。

**Architecture:** 复用现有 PlatformStore、Graph+Loop Kernel、CapabilityRegistry、Job/Worker、Label Studio 和统一 Web。新增 TrainingControlGraph 与四个 lane adapter；当前生产模型只经 LegacyInferenceCapability 提供识别与 provisional proposal；未来权重使用独立 `fmcg_nextgen_v1` lineage。

**Tech Stack:** Python/FastAPI/Pydantic/SQLite（本机事实源）、React/TypeScript、PyTorch MPS、Ultralytics、SAM2.1、MLX/MLX-VLM、pytest。

---

## Task 0：运行事实、测试漂移与执行账本

1. 完整阅读本目录、`project-logic-chain-v3`、Qwen 级联规格、项目手册和相关源码。
2. 记录 branch、HEAD、工作树、服务、DB integrity、bundle、训练进程、磁盘/内存。
3. 在普通 Terminal 重跑全量测试；复现并分类当前 Codex 环境中的 10 个 MPS 失败。
4. 将 4 个含旧 `--dataset/--budget-minutes` 参数的 dry-run 追加式标记 legacy/superseded，禁止批准/入队；不删除历史行。
5. 复核 8400 degraded/ML backend unavailable：选择恢复受治理 backend，或明确让 assisted proposal 走当前平台 Recognition Capability；不能保留两条不一致的 proposal 写链。
6. 新建本轮 `STATUS/IMPLEMENTATION-LIST/DECISIONS/ISSUES/EXECUTION-LOG`，只追加不覆盖历史。
7. 测试并修复 HardwareGate 可注入性、host test marker 和错误优先级；不得降低真实 G0。

验收：默认测试 hermetic；真实 MPS host suite 独立执行；两类结果都在报告中。

## Task 1：冻结 V2 契约和追加式迁移

建议文件：

```text
src/modules/training_control/contracts.py
src/modules/training_control/vocabulary.py
src/platform/data/store.py
tests/platform/test_training_control_contracts.py
tests/platform/test_training_control_migrations.py
```

实现 TrainingLane、Plan、Run、Event、Artifact、ResourceLease、Readiness、Blocker 和 DatasetSnapshotV2。迁移只追加新表/列/投影，不改写旧 training_run、job、dataset_snapshot 历史。数据库触发器保护不可变事件和 artifact lineage。

## Task 2：旧模型隔离与 Legacy Model Adapter

1. 只读扫描现有模型与 bundle，生成 hash inventory；不移动文件。
2. 登记 `production_legacy/historical/experimental_ended/quarantined`。
3. 将 `prod_20260805_v5_r1` 作为当前 `LegacyInferenceCapability`。
4. 新 lineage builder 拒绝任何旧业务 checkpoint 作为 parent/resume/EMA/optimizer。
5. 允许旧生产 bundle 作为 `proposal_teacher`，输出必须是 provisional。
6. UI 同时显示生产 legacy 与 nextgen，禁止视觉混淆。

## Task 3：统一过滤投影和 Dataset Factory

建议文件：

```text
src/modules/dataset_factory/contracts.py
src/modules/dataset_factory/service.py
src/modules/dataset_factory/builders/{detector,classifier,segmenter,vlm}.py
src/modules/dataset_factory/split_guard.py
src/platform/api/datasets.py
tests/platform/test_dataset_factory_*.py
```

要求：

- builder 从 platform.sqlite/CAS/active review facts 读取；
- 四条 builder 共享身份、泄漏、原子发布和审计库，不共享错误标签语义；
- 输出目录存在拒绝覆盖；staging 完成后原子发布；
- 每条 snapshot 有 exclusion ledger、quality histogram、source hashes 和 disk verification；
- D3 无 mask gold 时只生成 calibration snapshot，不生成 trainable snapshot；
- frozen protocol 永不进入训练。

## Task 4：连接 assisted proposal，保持 blind 隔离

1. 对 LS 项目 19 做 dry-run：列出 200 任务、已有 prediction、可解析资产、预计 proposal 数和错误。
2. 使用当前生产 `prod_20260805_v5_r1`，可选 SAM 几何精修，生成 box + canonical SKU suggestion + evidence。
3. append-only、幂等写入项目 19；旧 prediction 不覆盖。
4. 项目 20 全量验证 prediction=0、模型 meta=0。
5. 模型零检出任务保留人工入口并显式标记 `no_proposal`。
6. 在统一 Web 展示 proposal coverage、no-proposal、错误和模型版本。

任何 proposal 都不得写入 `gold_region_v1`。

## Task 5：四训练 Lane Adapter

统一接口：

```text
validate_plan()
build_command_or_callable()
start()
stream_progress()
request_safe_stop()
collect_artifacts()
evaluate()
```

分别实现：

- DetectorAdapter：`src.training.train_v1` 的新 lineage 参数封装；
- ClassifierAdapter：分类训练入口的显式数据、类别、unknown、MPS 和输出目录封装；
- SegmenterAdapter：calibration 与 train 两种 mode；mask gold 未达标拒绝 train；
- VlmAdapter：复用 `src.training.vlm`，MLX 隔离环境、当前 CLI 探针、vision 独立授权。

adapter 必须返回结构化事件，不能只依赖 stdout 文本解析。

## Task 6：TrainingControlGraph 与特殊 Hook

建议文件：

```text
src/modules/training_control/graph.py
src/modules/training_control/service.py
src/modules/training_control/hooks.py
src/modules/training_control/policy.py
tests/platform/test_training_control_graph.py
tests/platform/test_training_control_hooks.py
```

实现 Admission→Dataset→Hardware→Approval→Queue→Execute/Monitor Loop→Evaluate→Candidate→Shadow→Publish Request。任何人工 gate 都写 checkpoint，可恢复、可回放。Agent 只能调用白名单 DomainCommand。

## Task 7：本地资源租约与可靠 Worker

1. heavy accelerator 默认并发 1；MPS 与 MLX 互斥。
2. 训练提交时冻结 env、command/callable、data/code/config hash。
3. Worker 保存 PID、进程组、heartbeat、attempt、日志 ResourceRef。
4. `safe-stop` 先走框架 checkpoint/终止信号，确认退出后再释放 lease。
5. Worker 崩溃后根据 heartbeat/进程证据恢复为 orphaned/failed，不伪称 running。
6. 服务健康、swap、memory、disk、thermal、NaN/Inf 触发 hook。
7. 启动重任务前阻止 Qwen/YOLO/SAM 并行争抢统一内存。

## Task 8：统一 API 与旧 API 兼容

实现 `01-ARCHITECTURE-AND-CONTRACTS.md` 第 10 章 API。旧 `/api/v1/training/*` 只作为兼容层读取或委托新服务，禁止新旧两套写状态。所有写端点使用 session+CSRF+IAM；批准计划、启动训练、发布审批三个动作分离。

## Task 9：统一 Web 训练与数据工作台

修改/新增：

```text
web/src/pages/Training.tsx
web/src/pages/Annotation.tsx
web/src/pages/Assets.tsx
web/src/pages/TrainingRunDetail.tsx
web/src/pages/Datasets.tsx
web/src/api.ts
web/src/App.tsx
web/src/styles.css
```

要求：

- 一屏看清当前生产、nextgen 四 lane、人工真值、数据集和资源；
- 每个按钮说明是否消耗算力、需要什么权限、为何被禁用；
- 真实 progress 来自 TrainingEvent/Run 投影；8092 只放入 Legacy 诊断折叠区；
- 失败不只显示 HTTP code，要显示 blocker code、原因、证据链接和下一动作；
- 浏览器刷新后状态不丢；多用户操作不重复提交；
- UI 不提供直接命令输入框。

## Task 10：通道评估和候选登记

| Lane | 最低评估 |
|---|---|
| detector | recall@FP1/3/5、IoU0.5/0.75、duplicate/background/localization、尺寸/密度/场景切片 |
| classifier | top1/macro-F1、unknown FAR、coverage-risk、包装版本/长尾/近邻 SKU |
| segmenter | mask IoU、boundary F、粘连/截断/边界触碰、下游分类增益与额外延迟 |
| vlm | candidate recall@k、accepted precision、coverage、abstain、registry escape、p95/token/内存 |

只有同口径冻结集和完整 error ledger 才能生成 Candidate。训练完成不得修改 CURRENT bundle。

## Task 11：测试、浏览器 QA 与故障演练

至少覆盖：

- 旧模型绝不成为 nextgen parent；
- assisted 有 proposal、blind 永远无 prediction；
- 四 builder 的 active/gold/泄漏/覆盖/原子发布；
- D3 无 mask gold fail-closed；
- 四 adapter 参数白名单与目标目录防覆盖；
- Graph gate/feedback/retry/人工审批；
- 资源租约互斥、orphan 恢复、安全停止；
- API IAM/CSRF/幂等/分页；
- UI 四 lane、blocker、刷新、进度、停止、失败；
- production bundle 未切换；
- SQLite integrity 和历史行不变。

先 `qa-only`，再在测试数据/测试项目做可逆 QA。不得用真实全量训练证明 UI 可用。

## Task 12：机器侧交付与下一 Gate

最终交付必须报告：

1. Git/工作树/提交链；
2. 旧模型 inventory 与隔离证据；
3. 四 lane readiness；
4. 四 builder smoke snapshot；
5. assisted/blind 对账；
6. Graph/Hook/API/Worker 状态；
7. UI 浏览器验收截图；
8. 测试、build、DB integrity；
9. 服务健康和资源租约；
10. 未关闭 blocker；
11. production bundle 未切换；
12. full training 未启动。

机器侧完成后 Gate 应为 `FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION`，不是“训练完成”。
