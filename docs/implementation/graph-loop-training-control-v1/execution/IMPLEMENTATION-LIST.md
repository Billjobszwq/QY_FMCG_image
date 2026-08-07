# Graph+Loop Training Control V1 · IMPLEMENTATION-LIST

> 每项：ID / 问题 / 当前事实 / 目标状态 / 前置依赖 / 涉及文件 / 红测试 / 验收证据 / 状态 / commit / 阻断原因。

## GLTC-000（Task 0）运行事实、测试漂移与执行账本
- 问题：Codex 受限环境 10 个 MPS 测试失败；4 个历史 dry-run 含禁用 CLI 参数；8400 degraded；HardwareGate 不可注入。
- 当前事实：普通 Terminal 914 passed 全绿（环境限制而非产品缺陷，需 hermetic 分层固化）；training_run 4 行 dry_run（`--dataset/--budget-minutes`）；8400 health 因 ml_backend 8301 不可用 degraded。
- 目标状态：默认 suite hermetic（HardwareGateProvider 可注入）；真 MPS 测试标 host marker 独立执行；授权>硬件错误优先级契约冻结；4 dry-run 追加式 legacy/superseded；ml_backend 明确 disabled，proposal 唯一正式写入口=平台识别能力。
- 前置依赖：无。涉及文件：`src/modules/training_gov/{mps_gate,service}.py`、`src/platform/api/health.py`、`src/platform/data/store.py`、`tests/platform/test_umt005_mps_g0.py` 等。
- 红测试：错误优先级契约（未授权先于 G0 报 AuthorizationRequired）、legacy dry-run 禁批准/入队、disabled 服务不影响聚合。
- 状态：IN_PROGRESS。commit：—。阻断：无。

## GLTC-001（Task 1）冻结 V2 契约和追加式迁移
- 问题：无 TrainingLane/PlanV2/RunV2/Event/Artifact/ResourceLease/DatasetSnapshotV2 契约。
- 目标状态：`src/modules/training_control/contracts.py`+vocabulary；migration 追加新表（不改旧 training_run/job/dataset_snapshot）；触发器保护不可变事件与 artifact lineage。
- 红测试：tests/platform/test_training_control_contracts.py、test_training_control_migrations.py。
- 状态：PENDING。

## GLTC-002（Task 2）旧模型隔离与 Legacy Model Adapter
- 问题：旧模型无状态登记；nextgen parent 无隔离。
- 目标状态：hash inventory（只读）；production_legacy/historical/experimental_ended/quarantined 登记；`prod_20260805_v5_r1`=LegacyInferenceCapability；lineage builder 拒旧 checkpoint 作 parent/resume/EMA/optimizer；proposal_teacher 与 parent 字段结构分离。
- 状态：PENDING。

## GLTC-003（Task 3）统一过滤投影和 Dataset Factory
- 问题：四数据集 builder 缺失；过滤无统一投影。
- 目标状态：`src/modules/dataset_factory/`（contracts/service/builders×4/split_guard）+`src/platform/api/datasets.py`；active/gold-only 准入、frozen 拒入、staging 原子发布、exclusion ledger、D3 无 mask gold 只 calibration、D4 候选构造禁 GT。
- 状态：PENDING。

## GLTC-004（Task 4）assisted proposal 接线，blind 保持隔离
- 问题：LS 19 无 proposal；19 需补、20 必须恒零。
- 目标状态：dry-run→用 prod_20260805_v5_r1 生成 box+canonical SKU suggestion+evidence，append-only 幂等写 19；零检出标 no_proposal；20 全量验证 prediction/meta=0；proposal 永不入 gold_region。
- 状态：PENDING。

## GLTC-005（Task 5）四训练 Lane Adapter
- 问题：无统一 validate/build/start/progress/safe-stop/collect/evaluate 接口。
- 目标状态：Detector/Classifier/Segmenter/Vlm adapter；结构化事件；参数白名单；目标目录防覆盖；Segmenter 无 mask gold 拒 train；VLM 隔离环境+vision 独立授权。
- 状态：PENDING。

## GLTC-006（Task 6）TrainingControlGraph 与 Hook
- 问题：无四 lane 共享控制图与 13 个 Hook。
- 目标状态：`src/modules/training_control/{graph,service,hooks,policy}.py`；复用 Graph Kernel；人工 gate checkpoint 可恢复回放；Agent 白名单 DomainCommand。
- 状态：PENDING。

## GLTC-007（Task 7）本地资源租约与可靠 Worker
- 问题：Worker 直接 Popen；无租约/heartbeat/orphan 恢复/真 safe-stop。
- 目标状态：ResourceLeaseV1（heavy=1、MPS/MLX 互斥）；env/command/hash 冻结；PID/heartbeat/attempt/日志 ResourceRef；safe-stop 证据链；orphan 恢复；服务健康/swap/内存/磁盘/thermal/NaN 停止线。
- 状态：PENDING。

## GLTC-008（Task 8）统一 API 与旧 API 兼容
- 问题：旧 /api/v1/training/* 单 YOLO 语义；无 lanes/readiness/safe-stop 等。
- 目标状态：01 文档第 10 章 API；旧 API 只读/委托兼容；session+CSRF+IAM；批准/启动/发布分离。
- 状态：PENDING。

## GLTC-009（Task 9）统一 Web 训练与数据工作台
- 问题：Training.tsx 单 YOLO；无四 lane/数据集/运行详情页。
- 目标状态：Training/Annotation/Assets/Datasets/TrainingRunDetail 页 + api.ts；production legacy 与 nextgen 视觉隔离；按钮算力/权限语义；8092 进 Legacy 折叠区；无 shell 输入框。
- 状态：PENDING。

## GLTC-010（Task 10）通道评估和候选登记
- 问题：四 lane 评估口径未冻结。
- 目标状态：按 02 计划 Task 10 表冻结各 lane 最低评估；同口径冻结集+error ledger 才可生成 Candidate；训练完成不改 CURRENT bundle。
- 状态：PENDING。

## GLTC-011（Task 11）测试、浏览器 QA 与故障演练
- 问题：隔离/盲审/原子/租约/safe-stop/幂等回归未覆盖新框架。
- 目标状态：02 计划 Task 11 全矩阵绿；qa-only 先行；故障演练（崩溃/重启/MPS 不可用/磁盘不足/目录已存在/LS 不可用）。
- 状态：PENDING。

## GLTC-012（Task 12）机器侧交付与下一 Gate
- 目标状态：12 项交付报告；Gate=`FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION`。
- 状态：PENDING。
