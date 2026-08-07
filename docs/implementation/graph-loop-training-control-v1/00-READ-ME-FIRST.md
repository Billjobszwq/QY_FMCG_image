# Graph+Loop 四训练通道统一控制方案 V1

> 状态：设计与实施任务书已冻结，尚未实施代码，尚未授权真实训练。
>
> 快照：2026-08-08；基线分支 `feat/unified-workbench-training-readiness`；基线 HEAD `c1d1d6f`。
>
> 本目录是下一实施 Agent 的唯一新增任务入口。旧文档仍是历史与契约证据，不得删除或覆盖。

## 1. 本次要解决什么

当前项目已经具备 Graph+Loop、统一 Web、Label Studio V2、质量筛选、审核状态机、训练治理、FMCG 级联和 Qwen3-VL 试验代码，但仍存在五个系统性断点：

1. 训练页主要围绕单一 YOLO 快照，四类模型没有同级、独立、可插拔的训练通道。
2. 标注、照片过滤、数据集构建和训练之间缺少统一的资源引用与状态投影，用户需要跨页面理解内部实现。
3. 当前生产模型、历史实验模型与未来模型没有强制 lineage 隔离，容易误用旧 checkpoint。
4. 现有训练 Worker 可以直接起子进程，但缺少跨 PyTorch/MPS/MLX 的独占资源租约、结构化进度、停止语义、制品登记和失败恢复闭环。
5. 真人 5+5 验收尚未完成，不能让它阻塞机器侧控制框架建设；同时也不能绕过它启动真实训练。

## 2. 冻结后的四训练通道

| 通道 | 代码名 | 训练对象 | 第一阶段定位 |
|---|---|---|---|
| T1 | `detector` | YOLO 商品定位器 | 从公共基础权重建立全新 nextgen lineage，优化商品框召回与固定 FP |
| T2 | `classifier` | ResNet18/轻量 SKU 表征与闭集分类 | 从 ImageNet/公开基础权重开始，学习 canonical SKU、包装版本、unknown 和难负样本 |
| T3 | `segmenter` | SAM 几何精修能力 | 先做 prompt/阈值/裁剪策略校准；只有真实 mask gold 达标后才允许 adapter/mask-decoder 微调 |
| T4 | `vlm` | `qwen3-vl:4b` 的 MLX QLoRA adapter | 只做候选闭集裁决、unknown/new-package 判断；初期冻结 vision tower |

注意：

- 这四条是训练能力，不是四套系统，也不是客户低/中/高/极高四档。
- 客户档位是 GraphPolicy；它按预算、SLA 和风险决定能调用哪些已发布能力。
- OCR、向量检索、风险校准和路由策略属于共享支撑或非模型治理，不伪装成第五条模型训练。
- T3 在 mask gold 不足时必须显示 `CALIBRATION_ONLY` 或 `BLOCKED_BY_MASK_GOLD`，不得用盒标数据伪称完成 SAM 微调。

## 3. 两条并行工作线

### A. 机器侧框架建设，现在即可实施

- 旧模型逻辑隔离与不可变登记；
- 四数据集契约和 builder；
- 质量过滤、标注、审核、数据集和训练的统一状态投影；
- 四训练 adapter、TrainingControlGraph、资源租约、事件进度、统一 API；
- 统一训练控制台、数据集页、标注页和运行详情页；
- 当前生产模型为 assisted 项目生成可见 proposal；
- 单元、契约、集成、浏览器 QA 和无重训练的 bounded smoke。

### B. 真人真值与真实训练，继续受门禁约束

- 先完成项目 19/20 的 5+5 真人验收；
- 再放量 250 条审核；
- 四个 DatasetSnapshot 分别达到各自最低真值门；
- 用户对具体 `TrainingPlan` 单独授权后，才能提交真实训练 Job；
- 训练完成只登记 candidate，shadow 与发布仍要单独审批。

机器侧不能因为等待人工而停工；真实训练也不能因为页面已经完成而自动启动。

## 4. 当前现场结论

| 项目 | 结论 |
|---|---|
| 当前生产 | `.models/bundles/CURRENT.json` 指向 `prod_20260805_v5_r1`，继续使用，不切换 |
| 历史模型 | `.models/sku_v1` 至 `sku_v7_sam`、E2、classifier、archive 全部保留，不移动、不删除 |
| 人工链 | rq_v2 active 250，LS 项目 19/20，`gold_region_v1=0`，Gate=`AWAITING_HUMAN_ACCEPTANCE` |
| assisted proposal | 项目 19 当前没有 proposals；应接当前生产 bundle 追加生成，blind 项目 20 必须保持零 prediction |
| 训练表 | 当前只有 1 个不可训练的 E2 snapshot 和 4 个历史 dry-run；没有活动 training job |
| 训练授权 | `training_authorized=false` |
| 训练页 | 已有 dry-run/批准/enqueue/history，但仍是单 YOLO 语义，8092 监控仍标为旧链路 |
| 历史计划漂移 | 4 个旧 dry-run 的 command 仍含当前 CLI 已禁用的 `--dataset/--budget-minutes`；必须追加式标为 legacy/superseded，禁止批准或提交 |
| 服务状态 | 8091/8092/8400/8300 可访问；8400 为 degraded，原因是 Label Studio ML backend unavailable，必须在新工作台如实显示并决定 proposal 走平台能力还是恢复 backend |
| 新训练 | 不继承任何当前业务 checkpoint；默认只允许公开基础模型作为 parent |

## 5. 本轮 fresh 测试发现

在 Codex 受限运行环境执行全量测试，结果为 `904 passed, 10 failed, 1 skipped`。10 个失败全部汇聚到 MPS 主机探针：当前受限进程中 `torch.backends.mps.is_available()==False` 且 `sysctl hw.memsize` 不可读；测试却把“macOS”直接等同于“MPS 必须可用”。同时，部分授权语义测试因为 `_require_g0()` 先于授权校验而收到 `TrainingGovError`，不是预期的 `AuthorizationRequired`。

实施 Agent 必须在普通 Terminal 重跑以区分环境限制和产品缺陷，但无论 Terminal 是否全绿，都要完成：

1. 单元/接口测试使用可注入的 `HardwareGateProvider`，不依赖运行测试的宿主权限；
2. 真实 MPS 测试单独标记为 host/integration，不混进默认 hermetic suite；
3. 授权、计划有效性和硬件门禁的错误优先级冻结并有契约测试；
4. 真实训练提交前仍必须重新执行真实 G0，禁止用 mock 报告启动训练。

## 6. 目录文件

- `01-ARCHITECTURE-AND-CONTRACTS.md`：目标架构、数据链、模型隔离、Graph+Loop 和 UI。
- `02-IMPLEMENTATION-PLAN.md`：可逐项执行的实现顺序与文件范围。
- `03-ACCEPTANCE-GATES.md`：功能、数据、资源、测试和发布验收门。
- `AGENT-EXECUTION-PROMPT.md`：可以直接交给实施 Agent 的完整提示词。

## 7. 权威边界

本目录补充并更新训练控制面，不替代：

- `docs/implementation/project-logic-chain-v3/` 的当前事实源与人工审核链；
- `docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md` 的识别级联契约；
- `docs/CODEX-PROJECT-HANDBOOK.md` 的接续索引；
- `.platform/platform.sqlite` 的当前运行事实。

若冲突：实时代码/数据库/制品 > project-logic-chain-v3 > 本目录实施设计 > 历史训练文档。
