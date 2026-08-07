# Agent 一次性执行提示词

你现在负责 `/Users/zhangweiqi/Documents/QY/项目/LLM-Image` 的 NextGen 四模型数据与训练闭环 V2。你不是来再做一轮空框架，也不能把接口单测当成真实训练完成。你的目标是在现有 Graph+Loop Foundation 上，一次性打通三批照片 -> 严格过滤 -> 点提示 SAM -> 四类 DatasetSnapshot -> 四模型真实实验训练 -> 统一评估 -> Web/API/Profile，并保留完整证据和可恢复状态。

## 一、先完整阅读，禁止跳读

依次全文阅读：

1. `/Users/zhangweiqi/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md`
2. `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/docs/CODEX-PROJECT-HANDBOOK.md`
3. 本目录全部文件：
   - `README.md`
   - `01-CURRENT-STATE-AUDIT.md`
   - `02-DATA-SAM-FOUR-MODEL-DESIGN.md`
   - `03-GRAPH-LOOP-EXECUTION-PLAN.md`
   - `04-ACCEPTANCE-GATES-AND-REPORT.md`
4. `docs/implementation/project-logic-chain-v3/` 全部文件
5. `docs/implementation/graph-loop-training-control-v1/` 全部文件和 execution 日志
6. `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`
7. `docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md`
8. `docs/superpowers/plans/2026-08-06-qwen3-vl-4b-graph-loop-cascade-implementation-plan.md`
9. `docs/training-history-and-decisions.md`
10. 用户提供的上一轮最终交付报告；必须对照现场，不能把报告当事实源。

阅读后先建立并持续更新：

- `execution/STATUS.md`
- `execution/IMPLEMENTATION-LIST.md`
- `execution/EXECUTION-LOG.md`
- `execution/DECISIONS.md`
- `execution/ISSUES.md`
- `execution/ACCEPTANCE.md`

若目录不存在就创建在 `docs/implementation/nextgen-four-model-training-loop-v2/execution/`。日志追加式，不覆盖历史。

## 二、当前已知事实，必须现场重验

- 基线 HEAD 应为 `ce6f614`，分支 `feat/unified-workbench-training-readiness`；若不同，记录差异后按当前事实继续。
- 当前生产应为 `prod_20260805_v5_r1`，继续 serving，不得切换。
- 旧业务模型全部保留并隔离，不得作 nextgen parent/resume/EMA/optimizer。
- Label Studio Registry 与 taxonomy 均应为 208，双向差集 0；project 19 assisted，project 20 blind。
- project 19 预期：200 tasks，187 有 prediction，186 有可见 SKU taxonomy，13 `no_proposal`；project 20 prediction/model meta 必须为 0。
- 三批原始照片预期 2,947 / 6,510 / 22,664；exact unique 29,176；canonical points 745,695。
- 第一/二批 476 张重复照片坐标有差异，必须建账，不得静默覆盖。
- 第三批 5 个未映射名称共 40,591 点，禁止猜映射。
- 上一报告声称默认 1010 passed，但本次 fresh 实测是 `1002 passed, 8 failed, 1 skipped, 5 deselected`；先 TDD 关闭 hermetic/host MPS 分层残缺。
- 现有 NextGen API/Web/Graph 尚未形成真实可操作训练闭环：API 写端点不全，dataset build 固定空 rows，Graph 仍是内存态，Web V2 只有只读卡片，识别页没有 profile selector。

任何预期计数不一致立即停在对应 Gate，输出差异账本，不允许为了继续执行篡改预期。

## 三、授权范围

本提示词包含用户对以下工作的统一授权：

1. 在本项目内修改代码、测试、迁移和文档，补齐本手册 Task 0–15；
2. 从三批原始数据重新做去重、严格过滤、SAM 派生和四个 immutable snapshot；
3. 在所有数据、硬件、资源、评估门通过后启动四条有界实验训练；
4. 训练 M1 detector、M2 YOLO-seg、M3 classifier、M4 `qwen3-vl:4b` MLX QLoRA；
5. 根据 measured benchmark 决定 M1/M2/M3 是否最多并发 2；Qwen 必须独占；
6. 完成 candidate-only 评估与 shadow-ready 准备。

本授权不包括：删除/清理、merge、push、deploy、生产数据改写、production bundle 切换、candidate 发布。需要这些动作时停止并请求独立授权。

不要每完成一个 Task 就向用户重复请求相同授权。只在以下情况等待用户：必须真人完成的质量/mask/gold 审核、需要删除/发布/生产切换、关键计数无法对账、连续三次同一阻断无法自动恢复。

## 四、实施方式

使用 Superpowers 的 brainstorming/spec/planning/TDD/systematic-debugging/verification 流程和 gstack 的 plan-eng-review、qa-only、design-review、devex-review、security/release-readiness。先 report-only QA，再做有授权的修复。复杂实施使用新分支，建议 `feat/nextgen-training-cycle-v2`，小步 commit。

严格执行：

```text
Observe
-> Validate contract
-> Plan bounded action
-> Acquire capability/resource lease
-> Execute idempotently
-> Verify artifact/runtime/business evidence
-> Record event + checkpoint
-> Decide next/retry/wait/stop
```

每个节点最多自动重试 2 次。第三次进入明确 `WAITING_FOR_*`/`FAILED`，不无限循环。服务或 Agent 重启后从最后 checkpoint 恢复，不能从头重复造数据或重复训练。

## 五、按 Task 0–15 完整执行

以 `03-GRAPH-LOOP-EXECUTION-PLAN.md` 为唯一任务清单，逐项实施，不得跳过：

- Task 0 基线和报告纠偏；
- Task 1 持久化 Cycle/Plan/Run/Artifact；
- Task 2 真实控制 API；
- Task 3 三批数据接入、exact/near dedupe、坐标差异；
- Task 4 严格质量和误拒绝校准；
- Task 5 SKU/unknown/new packaging；
- Task 6 点提示 SAM 与 mask audit；
- Task 7 D1–D4 snapshots；
- Task 8 四个真实 adapter/launcher；
- Task 9 Apple 资源 benchmark；
- Task 10 Web 七个工作区；
- Task 11 Recognition Profile 与五入口 API 同步；
- Task 12 四模型真实训练；
- Task 13 同口径评估；
- Task 14 故障恢复与 QA；
- Task 15 文档、版本和最终收口。

## 六、算法与数据红线

1. SAM 本轮首先是冻结 teacher/在线精修能力。不得用 SAM 自己生成的 mask 训练 SAM 后宣称“真实 SAM 微调完成”。M2 是学习审核后 SAM mask 的轻量 YOLO-seg 学生；只有 human mask gold 足够时才能另开 SAM adapter 计划。
2. 建立 label source tiers：`human_gold`、`legacy_coordinate_verified`、`sam_verified_pseudo`、`model_proposal`、`unknown/new_packaging`。训练准入与评估准入必须不同。
3. 从三批原始输入重跑，不复用旧 `.batch3_clean` 的 5 张 reject 作为完整过滤结论。
4. 全量 near-dup 覆盖 29,176 张，group 不跨 split。
5. 第一/二批重复以第二批 canonical，第一批补 2 张独有；476 张差异写 ledger。
6. `other/百事other/可乐other` 不强映射；两个具体未映射名称进入 alias/new SKU 裁决。
7. Qwen 训练样本包含原图、bbox/point/mask、context crop、mask crop、OCR/属性、真实检索 CandidateSet；CandidateSet builder 禁止接收 GT。
8. Qwen 数据格式以当前锁定 `mlx-vlm` 版本的 CLI/help/smoke 为准，不照抄旧 `<|vision_start|>` 或假定参数。
9. 没有 human frozen truth 时可以训练 experimental candidate，但正式业务指标必须写 interim/not_evaluable，不能伪造 >95%。

## 七、算力调度红线

- M3 Max 128GB 统一内存，默认 heavy concurrency=1；CPU/I/O 可和一个 heavy task 并行。
- SAM 数据生成先物化，再进入训练。
- 分别测 M1/M2/M3 单任务，再只测试 detector+classifier、segmenter+classifier。
- 只有组合吞吐提升 ≥25%、峰值≤90GB或保留≥24GB、swap<8GB且增量≤2GB、无 thermal/memory/service/MPS 异常，才可并发 2。
- 不默认并发 3。
- Qwen MLX QLoRA 永远独占，禁止与 SAM/YOLO/Classifier 重训练并行。
- Qwen batch/grad accumulation 按实测，不预设 batch=16，不承诺固定时长。
- 任一停止线触发，执行 safe-stop、保存可恢复 checkpoint、记录证据、释放 lease。

## 八、UI/API 必须真能操作

统一 Web 至少完成并用浏览器真实验收：数据准备、SAM 数据、Dataset Lineage、四 Lane 训练、Run Detail、Recognition Profiles、Graph Run。

识别模型选择必须用 `recognition_profile_id`，禁止选择任意权重路径。至少提供：

- `production_legacy`
- `nextgen_detector`
- `nextgen_detector_segmenter_classifier`
- `full_cascade_qwen`
- `shadow_compare`

单文件、批量、URL、外部 API、内部 Agent 使用同一 Profile 契约，并保存 profile/model/policy/evidence/cost。未就绪 profile 可见但禁用并显示 blocker。修正 Recognition 页面过期 bundle 文案。

## 九、训练执行边界

数据/控制/Apple Gate 全绿后，无需再次询问即可：

1. M1/M2/M3 各做 1 epoch smoke；
2. smoke 通过后执行有界 pilot；
3. pilot 通过既定收益/安全门后，各执行一个 candidate；
4. Qwen 先 5k–20k、1 epoch、vision frozen pilot；通过后最多一个 1–3 epoch full candidate；
5. 所有 plan 先冻结 hypothesis、base revision、dataset hash、预算、stop line 和评估集；
6. 所有训练产物登记 hash，绝不覆盖旧 run；
7. 训练完成只登记 candidate，production switch=false。

如果人工审核阻断：继续完成所有不依赖人工的代码、数据、任务创建、UI/API 和可恢复 checkpoint；只在真正需要真人动作的唯一 Gate 停一次，提供具体链接、数量、操作和完成后的自动恢复方式。不得每个小环节都让用户重新决策。

## 十、Git 与文件安全

- 不运行 `git add .`、`git add -A`、`git clean`、`git reset --hard`；
- `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不删除、不清理、不整体暂存；
- 现有未跟踪 backfill JSON/Web QA 截图先分类，保留证据；
- 原图、模型、SQLite、secret、大数据集不进源码 commit；
- 只暂存明确文件；每阶段记录 diff、测试和 commit；
- 不自动 merge/push/deploy。

## 十一、验收和汇报

完整执行 `04-ACCEPTANCE-GATES-AND-REPORT.md` 的 G0–G9 和停止线。最终只汇报一次完整交付，严格按其中 1–34 项编号，不能用“框架已就绪”替代真实训练结果。

最终状态只能是：

- `NEXTGEN_TRAINING_CYCLE_V2_COMPLETE`
- `FOUR_EXPERIMENTAL_CANDIDATES_READY_AWAITING_HUMAN_EVALUATION`
- `WAITING_FOR_HUMAN_GATE`
- `BLOCKED`
- `FAILED`

如果某模型 pilot 不通过，保留真实失败结果和 artifact，说明停止原因与唯一下一假设；不要为了凑齐“四个成功模型”放宽门槛或伪造晋级。

现在开始：先读完全部文件，建立 execution 六件套，执行 Task 0 fresh audit。不要先启动训练，不要先改生产 bundle；但通过各 Gate 后按本授权连续推进到四模型候选与统一评估。

