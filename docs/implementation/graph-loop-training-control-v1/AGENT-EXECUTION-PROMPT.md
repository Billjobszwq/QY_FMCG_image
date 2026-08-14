# 给实施 Agent 的完整提示词

你现在是 `<legacy-workspace>` 的主实施 Agent。不要只给我建议或再写一份空泛方案；请在严格门禁下完成“标注—过滤—四数据集—四训练通道—统一 Web 控制台”的真实机器侧框架建设，并保证系统在本机可启动、可查看、可 dry-run、可审计。真实全量训练和 production 切换不在本轮默认授权内。

## 一、先完整阅读，禁止只读摘要

按顺序完整阅读：

1. `<ai-workflow-root>/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/CODEX-PROJECT-HANDBOOK.md`
3. `docs/implementation/graph-loop-training-control-v1/00-READ-ME-FIRST.md`
4. `docs/implementation/graph-loop-training-control-v1/01-ARCHITECTURE-AND-CONTRACTS.md`
5. `docs/implementation/graph-loop-training-control-v1/02-IMPLEMENTATION-PLAN.md`
6. `docs/implementation/graph-loop-training-control-v1/03-ACCEPTANCE-GATES.md`
7. `docs/implementation/project-logic-chain-v3/` 下全部 Markdown
8. `docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md`
9. `docs/superpowers/plans/2026-08-06-qwen3-vl-4b-graph-loop-cascade-implementation-plan.md`
10. `docs/training-history-and-decisions.md`
11. 当前标注、过滤、training_gov、platform worker、Graph Kernel、FMCG cascade、VLM、SAM、Web Training/Annotation/API 源码和相关测试。

遵循全局工作流：方向/架构/QA 使用 gstack；规格、TDD、调试、执行与完成前验证使用 Superpowers。先 report-only 检查。若使用子 Agent，只能划分互不覆盖文件的独立任务，主 Agent 必须自己复核契约和最终 diff。

## 二、建立本轮账本后再改代码

在 `docs/implementation/graph-loop-training-control-v1/execution/` 新建：

- `STATUS.md`
- `IMPLEMENTATION-LIST.md`
- `DECISIONS.md`
- `ISSUES.md`
- `EXECUTION-LOG.md`
- `ACCEPTANCE.md`

只追加事实。每个任务记录 base commit、红测试、实现、验证、commit、遗留风险和下一 Gate。不得覆盖 project-logic-chain-v3 的历史文档。

## 三、先做现场复核

记录：Git branch/HEAD/status、`.platform/platform.sqlite` integrity/migrations/表统计、rq_v2/LS 19/20/gold、CURRENT bundle、模型与数据集 inventory、8091/8092/8400/8300、训练/MLX/MPS 进程、内存/swap/磁盘、电源。

当前已知基线是 `c1d1d6f`，但必须以你现场结果为准。受保护目录 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不得修改、暂存、清理或删除。

重新运行全量测试。上一轮在 Codex 受限环境得到 `904 passed, 10 failed, 1 skipped`，失败集中在 MPS host 探针和授权错误优先级。你必须在普通 Terminal 复现分类：

- 默认单元/契约测试必须 hermetic，通过依赖注入模拟 HardwareGate；
- 真 MPS 测试必须单独标为 host/integration；
- 修复授权、计划和硬件门禁错误优先级的契约；
- 不得降低真实训练前的 G0。

另外，实时 API 已确认 4 条历史 dry-run 仍包含当前 CLI 已禁用的 `--dataset/--budget-minutes`。不得删除历史行；请追加式标为 `legacy/superseded/non_executable`，确保它们不能被批准或入队。8400 当前 degraded，原因是 Label Studio ML backend unavailable；必须查清当前正式 proposal 应走 Platform Recognition Capability 还是受治理 ML backend，只保留一个正式写入口，另一条明确 legacy/disabled。

## 四、不可突破的红线

1. 不删除、移动、覆盖任何原图、SQLite、模型、数据集、审核、SAM、quality、eval、日志、备份或失败制品。
2. 不使用 `git add .`、`git add -A`、`git clean`、`git reset --hard`。
3. 不自动 merge、push、deploy、force-push。
4. 不切换 `.models/bundles/CURRENT.json`；当前继续使用 `prod_20260805_v5_r1`。
5. 不启动 YOLO/Classifier/SAM/Qwen 的真实全量训练；只允许不会消耗大算力的 parse-check、mock、synthetic/bounded smoke。
6. 不把任何旧业务模型作为 nextgen parent/resume/EMA/optimizer/distillation teacher。
7. 当前生产模型只允许作为识别能力和 assisted proposal teacher；proposal 永远不等于人工真值。
8. blind 项目 20 禁止 prediction、候选、模型 meta 和 proposal 回填。
9. rq_v1、invalidated、active protocol、frozen holdout、model-only 标签禁止进入训练。
10. Agent 不得直接执行任意 SQL/shell/文件写；只能通过批准的 Capability/DomainCommand/Hook。

## 五、必须完成的架构结果

系统仍然是一套 Graph+Loop 底座，不得新建第二套 Orchestrator、第二套标注事实库或四套训练系统。模块通过 API、Capability、DomainCommand、ResourceRef、事件和 Hook 接入。

实现四条独立训练 lane：

1. `detector`：YOLO 商品定位；新 lineage 从公开基础权重开始。
2. `classifier`：ResNet18/轻量 SKU 分类与表征；从 ImageNet/公开基础权重开始。
3. `segmenter`：SAM prompt/阈值/裁剪校准；只有真实 mask gold 足够时才允许 adapter/mask-decoder 微调。
4. `vlm`：`qwen3-vl:4b` 的 MLX QLoRA；闭集候选裁决，第一轮 vision frozen。

客户低/中/高/极高档是 GraphPolicy，不是这四个训练 lane。OCR、检索和风险校准是共享支撑，不另造训练系统。

## 六、旧模型隔离

只读 inventory 全部现有模型和 bundle，追加登记为 `production_legacy/historical/experimental_ended/quarantined`，不移动文件。把 `prod_20260805_v5_r1` 经 LegacyInferenceCapability 继续接入当前主线。

新增 `fmcg_nextgen_v1` lineage 契约。任何 nextgen plan 如果 parent/resume 指向 `.models/sku_*`、旧 classifier、E2 或 production bundle，必须 fail-closed。允许 `proposal_teacher_bundle=prod_20260805_v5_r1`，但此字段与 parent 字段结构上不可互换。

## 七、理顺标注和过滤

把质量四级结论、分析器覆盖、原始分数、阈值版本、证据、人工覆盖、误拒绝抽检和“对四个 lane 是否可用”投影接入统一 Web。

修复当前 assisted 项目 19 无 proposals：

1. 先 dry-run 和备份/对账；
2. 用当前生产 bundle 生成真实 box + canonical SKU suggestion；可用 SAM 做 provisional 几何精修；
3. append-only、幂等回填项目 19，不覆盖旧 prediction；
4. 零检出任务显示 `no_proposal`，仍要求人工检查漏标；
5. 全量证明项目 20 prediction/meta=0；
6. proposal 绝不写 gold_region。

## 八、完成四个 Dataset Factory builder

四个 snapshot 共享 canonical 身份、active/gold、split/leakage、staging/原子发布、hash 和 exclusion ledger 基础库，但各自有独立 schema：

- D1 Detector：原图 + 所有 product true boxes + 背景硬负样本；
- D2 Classifier：tight/mask/context crops + canonical SKU/package/unknown/难负样本；
- D3 Segmenter：prompt + real mask；无 mask gold 只能 calibration，不可 trainable；
- D4 VLM：原图/区域/context/OCR/CandidateSet/canonical target；候选构造禁止接收 GT。

派生 crop 继承原图 split；split 至少守 client/store/session/SHA/near-duplicate/time/package。四快照不可覆盖，必须输出 builder/hash/split/quality/exclusion/disk audit。

## 九、实现 TrainingControlGraph

复用现有 Graph+Loop Kernel，建立一套通用控制图：

```text
Admission -> Dataset Gate -> Hardware/Resource Gate
-> Human Approval Hook -> Queue/Lease -> Lane Adapter Execute
-> Monitor Loop -> Safe Stop/Fail/Complete -> Lane Evaluation
-> Promotion Gate -> Candidate Registry -> Shadow -> Publish Approval Hook
```

实现文档列出的全部 Hook。状态、checkpoint、重试、feedback、人工 gate 可恢复可回放。四 lane 仅以 adapter/policy 差异接入，不复制状态机。

## 十、可靠 Worker 和 Apple 资源管理

重构当前直接 `subprocess.Popen` 的薄执行器：

- heavy accelerator lease 默认并发 1；PyTorch MPS 与 MLX 互斥；
- 冻结 env/command/data/code/config hashes；
- 保存 PID、进程组、heartbeat、attempt、结构化 progress、日志 ResourceRef；
- 实现真实 `safe-stop`，确认 checkpoint/退出/lease 释放后才写终态；
- orphan/worker crash/服务重启可恢复；
- 真实 Worker 环境重新跑 G0；
- 保护 8091/8400/8300，并监控 swap/memory/disk/thermal/NaN/Inf。

任何 mock HardwareGate 只可用于测试，不能进入真实 launch 路径。

## 十一、统一 API 和 Web

实现文档中的 lane/readiness/dataset/plan/approve/launch/run/events/safe-stop/retry/evaluate/shadow/publish-request API。旧 API 只做代理或只读兼容，禁止两套状态同时可写。

统一 Web 必须让非开发人员一眼看懂：

- 当前生产 legacy 是什么、是否在服务；
- 四个 nextgen lane 分别缺什么、能否训练；
- 标注/过滤/gold/四数据集进度；
- 当前资源租约与服务健康；
- 生成计划、批准、启动、停止、发布分别意味着什么；
- 活动 run 的 epoch/step、loss、核心指标、速度、ETA、内存、swap、日志和 stop line；
- 历史 run、candidate、对比、shadow 和失败证据。

8092 旧监控只能放 Legacy 折叠区，不能继续作为统一训练进度事实源。前端不得提供任意 shell 输入。

## 十二、TDD、提交和验证

按 `02-IMPLEMENTATION-PLAN.md` Task 0–12 顺序，小步 TDD 和小 commit。每个 commit 只暂存明确源码、测试和本目录执行文档。不要提交模型、数据、SQLite、日志、截图中的敏感信息或受保护目录。

完成后执行：默认 pytest、host MPS suite、TypeScript typecheck、Vite build、SQLite integrity、API contract、服务 smoke、浏览器 QA、旧模型隔离测试、blind 零泄漏、四 builder smoke、资源冲突与 safe-stop 故障演练。

机器侧完成 Gate 必须是：

```text
FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION
```

不能写“训练完成”。5+5 真人验收、250 gold 放量、真实四数据集和具体 TrainingPlan 仍需后续人工与单独授权。

## 十三、最终报告格式

按以下编号逐项报告，不得省略：

1. Git HEAD/分支/工作树/commit 链；
2. 完整阅读文件；
3. 基线问题与根因；
4. 旧模型 inventory、状态与隔离证据；
5. 当前 production bundle 未切换证据；
6. assisted proposal 回填与 blind 零泄漏统计；
7. 过滤证据链和误拒绝机制；
8. D1–D4 builder/snapshot/hash/split/exclusion；
9. 四 lane adapter 状态；
10. TrainingControlGraph/Hook/状态机；
11. Worker/PID/heartbeat/progress/safe-stop/resource lease；
12. API 和统一 Web 页面；
13. 默认测试与 host MPS 测试分别结果；
14. tsc/Vite/DB integrity/API/浏览器 QA；
15. 服务健康和 Apple 资源证据；
16. 未关闭 blocker；
17. 删除文件=false；
18. production switch=false；
19. full training started=false；
20. 当前 Gate 与下一步人工操作。

现在开始执行。不要因为 gold=0 而停下机器侧框架建设；也不要因为框架完成而绕过 gold 和授权启动真实训练。
