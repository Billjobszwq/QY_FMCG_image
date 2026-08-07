# Graph+Loop 一次性实施与训练计划

## 1. 唯一控制原则

四条 Lane 不是四个脚本入口。它们通过一个持久化 `TrainingCycleGraph` 编排，Lane 只以 Module Adapter 接入。

```text
Cycle
  -> AssetIngest
  -> ExactDedup
  -> NearDedup
  -> QualityAnalyze
  -> QualityHumanGate
  -> SamGenerate
  -> MaskAuditGate
  -> SnapshotBuild[D1,D2,D3,D4]
  -> ResourceBenchmark
  -> PlanApprove
  -> Train[M1,M2,M3]
  -> Train[M4 exclusive]
  -> Evaluate
  -> RegisterCandidates
  -> ShadowReady
  -> HumanPromotionDecision
```

Graph 状态、checkpoint、等待原因、事件序列和幂等键必须持久化在平台事实库；内存对象只能是执行投影，服务重启后必须从 DB 恢复。

## 2. 完成状态

### 2.1 Cycle 状态

```text
DRAFT
BASELINE_VERIFIED
ASSET_SCOPE_FROZEN
QUALITY_POLICY_CALIBRATED
SAM_DATASET_VERIFIED
SNAPSHOTS_READY
RESOURCE_PLAN_READY
TRAINING_AUTHORIZED
TRAINING_RUNNING
FOUR_EXPERIMENTAL_CANDIDATES_READY
HUMAN_EVALUATION_READY
SHADOW_READY
AWAITING_PROMOTION_DECISION
COMPLETED_NO_PROMOTION
FAILED
STOPPED
```

若缺 human frozen truth，允许以
`FOUR_EXPERIMENTAL_CANDIDATES_READY_AWAITING_HUMAN_EVALUATION`
结束本轮计算，但不得宣称模型达标或上线就绪。

### 2.2 本任务最终成功条件

以下全部完成才可写 `NEXTGEN_TRAINING_CYCLE_V2_COMPLETE`：

- 数据范围、过滤、SAM、四 snapshots 均有不可变 hash 和证据；
- 四个模型均有真实训练 artifact、曲线、环境和评估报告；
- Web/API/Agent 能查看同一状态并选择 recognition profile；
- 所有失败、停止、恢复和资源证据可回放；
- production 未自动切换；
- 若 human gold 不足，则完成状态必须带 `AWAITING_HUMAN_EVALUATION`，不能省略。

## 3. 实施 Task 0–15

### Task 0：基线和报告纠偏

- 记录 HEAD、工作树、服务、DB、bundle、进程、磁盘、MPS/MLX；
- 保护现有未跟踪证据，分类 3 个 backfill JSON 与 Web QA 截图，不删除；
- 用 TDD 修复默认 suite 的 8 个 MPS 环境耦合失败；
- 默认 hermetic、host MPS、TypeScript、Vite、SQLite integrity 分别留证据；
- 更新旧 GLTC 的 STATUS/ACCEPTANCE/ISSUES，禁止继续写“全部收口”。

### Task 1：持久化 Cycle/Plan/Run/Artifact

- 增加 append-only cycle、node checkpoint、plan approval、run attempt、artifact、evaluation、candidate、resource benchmark 表；
- Graph 的状态推进使用 DB 乐观版本/事务与 outbox；
- 服务重启、Worker orphan、重复 webhook、重复按钮均能幂等恢复；
- 旧 `training_run_v2` 有兼容投影，但只能有一个写事实源。

### Task 2：真实控制 API

最少提供：

```text
GET/POST /api/v1/training/cycles
GET      /api/v1/training/cycles/{id}
POST     /api/v1/training/cycles/{id}/resume
GET      /api/v1/training/data-scope
POST     /api/v1/training/data-scope/freeze
POST     /api/v1/training/quality/run
POST     /api/v1/training/sam/run
POST     /api/v1/training/snapshots/{lane}/build
POST     /api/v1/training/plans
POST     /api/v1/training/plans/{id}/approve
POST     /api/v1/training/runs/{id}/launch
POST     /api/v1/training/runs/{id}/safe-stop
GET      /api/v1/training/runs/{id}/{events,artifacts,evaluation}
POST     /api/v1/training/resource-benchmarks
```

所有写端点需 session + CSRF + RBAC + idempotency key；API 只接结构化参数白名单，禁止任意 shell/路径。

### Task 3：三批数据接入与去重

- 从三批原始源重建 asset reference；
- 复核 29,176 exact-unique 和 745,695 canonical points；计数不一致立即停止；
- 生成第一/二批 476 张坐标差异账本；
- 执行全量 near-dup，固定 group；
- UI 可查看每批、重复组、canonical 选择和原始证据。

### Task 4：严格质量 Pipeline

- 把现有 analyzers/qpol 输出统一为版本化 QualityDecision；
- 新增/接入斜拍、反光、翻拍/摩尔纹、大头照误导、遮挡/裁切、场景、价签等证据；
- 自动结果只能进入四级结论，不确定必须 manual_review；
- 建立校准/误拒绝抽检任务与 Label Studio/平台审核入口；
- 质量页显示分桶、阈值版本、证据图、误拒率和恢复入口。

### Task 5：SKU/unknown 治理

- 冻结 208 Registry 与 alias version；
- 对 5 个未映射名称逐类处置，不猜映射；
- unknown、新包装、沿用旧名/新名都用 canonical/package-version 状态机；
- 数据集和识别结果都存 ID，不用显示名做等值判断。

### Task 6：点提示 SAM 数据引擎

- 实现可断点续跑、批次化、幂等、缓存的 point+negative-point+ROI prompt；
- 记录 SAM 权重 SHA、prompt、候选 mask、选择分数和拒绝原因；
- 输出 mask、tight box、context crop、mask crop；
- 失败/不确定进入人工队列，不丢照片；
- 在训练前完成 ≥2,000 region 的 mask audit 门或如实停在等待状态。

### Task 7：四个 Snapshot Builder

- 按 D1–D4 独立 schema 构建，不复制共享身份/泄漏/原子发布基础库；
- 引入 label-source tier 与训练 sample weight；
- human gold 仅作 eval/calibration，pseudo 不能进入冻结 eval；
- SHA/store/session/near-dup/package-version 五键零泄漏；
- 产出 manifest、split、class/unknown/quality/source 分布和 exclusion ledger。

### Task 8：四个真实 Lane Adapter

- Detector、YOLO-seg、Classifier、Qwen QLoRA 分别连接实际 launcher；
- 每条支持 dry plan、validated command、start、structured progress、checkpoint、safe-stop、artifact、evaluation；
- 命令、环境、代码、配置、数据和 base revision 全冻结 hash；
- 输出目录存在即拒绝；失败 run 不覆盖重试，新 attempt 使用新目录。

### Task 9：算力 benchmark 与调度

默认 Apple heavy concurrency=1。数据 I/O/CPU 工作可与一个 MPS 任务并行。SAM 数据生成先完成并物化，再训练。

训练前分别对 M1/M2/M3 做 10–15 分钟单任务基线，再测试：

- detector + classifier；
- segmenter + classifier。

仅同时满足才允许 heavy 并发 2：

- 组合 normalized throughput 比顺序预估提升 ≥25%；
- 统一内存预留 ≥24GB，或组合峰值 ≤90GB；
- swap 绝对值 <8GB 且 benchmark 增量 ≤2GB；
- memory pressure 非 red，thermal 非 serious/critical；
- 8091/8400/8300 无错误，p95 不超过基线 1.2 倍；
- 无 MPS fallback、OOM、NaN/Inf。

不默认允许 3 个 heavy job。没有实证收益就保持 1。Qwen 永远持有独占 MLX/heavy lease，不与 SAM、YOLO、Classifier 重训练并行。

### Task 10：Web 图形化工作台

在统一 Web Shell 内完成并互链：

1. 数据准备：批次、去重、过滤、证据、人工队列、进度；
2. SAM 数据集：点覆盖、mask 产出、拒绝、审核、预览、snapshot；
3. 训练控制：四 Lane 卡、计划、预算、资源排程、启动/安全停止/恢复；
4. Run Detail：实时结构化进度、曲线、日志、checkpoint、资源、停止线；
5. Dataset Lineage：源、policy、builder、hash、split、exclusion、使用中的 runs；
6. Recognition：识别 Profile 选择、阻断原因、结果和比较；
7. Graph Run：cycle 节点、等待事项、人工 Hook、重放。

页面不能只有“已预留”空卡；每个操作必须调用正式 API 并有浏览器 E2E。

### Task 11：统一 Recognition Profile

不允许 UI 直接选择任意 `.pt` 路径。建立版本化 Profile：

- `production_legacy`；
- `nextgen_detector`；
- `nextgen_detector_segmenter_classifier`；
- `full_cascade_qwen`；
- `shadow_compare`。

提供 `GET /api/v1/recognition/profiles`。单文件、批量、URL、外部 API、内部 Agent 都传 `recognition_profile_id`，服务端校验 capability/状态/价格/资源。结果保存 profile version、各模型 artifact、policy、耗时、证据和计费单位。候选未训练/未发布时可见但禁用，并显示 blocker。

### Task 12：训练执行

在 Task 0–11 门通过后，本任务书视为对以下**有界实验训练**的统一授权：

1. M1/M2/M3 各先做 1 epoch smoke；
2. smoke 通过后做冻结预算的 pilot；
3. 只有 pilot 对同口径 baseline 有明确收益且无停止线，才各运行一个 candidate；
4. 是否并行遵循 Task 9 实测，不为追求“同步”牺牲吞吐和稳定性；
5. M4 Qwen 先 5k–20k、1 epoch、vision frozen pilot；通过后最多一个 1–3 epoch full candidate；
6. Qwen 独占，batch/grad accumulation 由实测决定；
7. 全部 candidate-only，不自动 publish。

具体 epoch、batch、imgsz、lr 必须先由 Agent 根据当前工具版本、数据分布和短 pilot 冻结在 TrainingPlan；不得照抄旧命令。

### Task 13：统一评估

- 每 Lane 使用独立冻结集和完整 error ledger；
- 旧生产/旧最好模型保留为同口径 baseline；
- 输出 overall + batch/SKU/包装/场景/质量/尺寸/密度/known-unknown 分桶；
- 生成端到端 profile 对比：准确、覆盖、复核率、p95、吞吐、内存、成本；
- 无 human gold 时明确 evidence level=`pseudo_or_coordinate_interim`。

### Task 14：故障、恢复与 QA

- 演练服务重启、Worker orphan、safe-stop、磁盘不足、输出已存在、MPS 不可用、LS 不可用、Qwen OOM；
- 默认/host/contract/integration/E2E/browser/performance 全部留证据；
- 训练期间每 30–60 秒 heartbeat，长任务每阶段更新文档/DB，不靠聊天文本作状态源；
- production services 必须受保护。

### Task 15：收口与版本

- 分阶段小 commit，建立新分支（建议 `feat/nextgen-training-cycle-v2`）；
- 不 `git add .`，不提交模型/原图/SQLite/secret；
- 更新本目录、`docs/README.md`、项目手册和旧 GLTC 状态；
- 最终按 `04-ACCEPTANCE-GATES-AND-REPORT.md` 汇报一次完整结果；
- 不 merge、不 push、不 deploy、不切生产，除非另获授权。

## 4. Loop 执行规则

每个节点统一：

```text
Observe current facts
  -> Validate input contract
  -> Plan one bounded action
  -> Acquire capability/resource lease
  -> Execute idempotently
  -> Verify artifact/runtime/business evidence
  -> Record event + checkpoint
  -> Decide next/retry/wait/stop
```

同一失败重试最多 2 次；第三次必须进入 `WAITING_FOR_*` 或 `FAILED` 并汇报根因，不能无限循环。恢复时从最后成功 checkpoint 继续，禁止全链重跑造成重复数据与重复训练。

