你现在负责 LLM-Image 项目的“平台真实接通 + 长尾模型正式实验”纠偏任务。

本轮不是重新搭一套架构，也不是继续增加静态页面。你必须在现有成果上完成最后一公里：

1. 将已经生成的数据集、模型、评估和 blocker 纳入统一事实库；
2. 让 Graph+Loop 真正接管训练；
3. 让主管 Agent 成为可对话、可调用领域能力、可控制界面的真实 Agent；
4. 让任务板、黑板、训练页面和识别 Profile 显示真实状态；
5. 按 canonical 38 类和 research 83 类拆分训练范围；
6. 完成 M1/M2/M3 正式 pilot；
7. 修复 KB 后，再决定是否重新训练 M4；
8. 不再使用旧 250 张照片流程阻塞演示模型。

本提示词授权：

- 修改代码、测试、数据库迁移和项目文档；
- 对现有制品做追加式注册和对账；
- 运行有界的 M1/M2/M3 实验训练；
- KB 达标后运行一次 M4 QLoRA pilot；
- 重启本地开发服务以加载新代码；
- 小步 Git commit。

本提示词不授权：

- 删除、移动、覆盖历史模型、数据、SQLite、审核队列和证据；
- 自动切换 production；
- merge、push、deploy、force-push；
- 把 pending SKU 自动写成正式 canonical SKU；
- 修改客户输入型业务数据；
- 让 Agent 执行任意 Shell、任意 SQL或任意文件路径；
- 将旧生产模型作为新模型 parent/resume/optimizer/EMA；
- 伪造人工真值、训练结果或任务板数据。

# 一、必须先读完

完整阅读：

1. `<ai-workflow-root>/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/CODEX-PROJECT-HANDBOOK.md`
3. `docs/README.md`
4. `docs/implementation/sku-long-tail-agent-foundation-v1/` 全部文件
5. `docs/implementation/nextgen-four-model-training-loop-v2/` 全部文件
6. `docs/implementation/project-logic-chain-v3/` 全部文件
7. `docs/implementation/platform-v2/` 全部文件
8. `docs/implementation/graph-loop-training-control-v1/` 全部文件
9. Agent、blackboard、memory、training cycle、training governance、Recognition Profile、Web、Label Studio、Dataset Snapshot 相关源码和测试
10. 当前分支最近至少30个 commit
11. 当前数据库 schema、服务状态、训练制品和未跟踪资产

继续使用：

`docs/implementation/sku-long-tail-agent-foundation-v1/`

不得新建另一套平行手册。

新增或更新：

- `07-PLATFORM-RECONCILIATION-AND-TRAINING-CORRECTION.md`
- `execution/CORRECTION-IMPLEMENTATION-LIST.md`
- `execution/CORRECTION-STATUS.md`
- `execution/CORRECTION-DECISIONS.md`
- `execution/CORRECTION-ISSUES.md`
- `execution/CORRECTION-LOG.md`
- `execution/CORRECTION-ACCEPTANCE.md`

将本提示词原样追加保存为：

`AGENT-CORRECTION-PROMPT.md`

# 二、开始时必须重新核验

已知只读复核结果如下，但你必须现场重验：

- HEAD 曾为 `633b4abd`；
- 分支为 `feat/nextgen-training-cycle-v2`；
- 受保护未跟踪目录不得触碰或清理；
- 8091/8092/8300/8400 曾健康；
- production 为 `prod_20260805_v5_r1`；
- 四个 v3 snapshot 文件存在；
- `/api/v1/agents` 返回4个 Agent Manifest；
- `/api/v1/taskboard` 五列为空；
- `/api/v1/training/cycles` 返回0；
- `/api/v1/training/data-scope` 为空；
- `blackboard_event_v1=0`；
- `memory_entry_v1=0`；
- `training_cycle_v1=0`；
- `training_plan_v2=0`；
- `training_artifact_v1/v2=0`；
- `/api/agent/v1/chat`、Agent command、UIIntent 接口不存在；
- Recognition Profile 中仍有过期 blocker；
- Web 训练页面仍显示旧的 gold=0、training_authorized=false、T1～T4 全部受阻；
- M1/M2 是1 epoch smoke，`candidate=false`；
- grouped M3 top1约30.7%，`candidate=false`；
- M4真实 candidate recall 为 null，因为 KB 对测试 GT 覆盖为0；
- 默认沙箱测试曾出现1092 passed、3 failed；主机环境重跑3项通过。

将当前项目 Gate 从错误的：

`FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_EVALUATION`

纠正为：

`PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED`

不得仅改文档，必须让数据库、API、Web和运行状态一致。

# 三、Task 0：建立纠偏基线

记录：

- HEAD、分支、工作树；
- 未跟踪资产；
- 服务 PID、端口、健康状态；
- SQLite integrity和迁移版本；
- production bundle；
- 数据集和模型 artifact hash；
- 当前 Agent、Cycle、Plan、Run、Artifact、Blackboard、Memory 行数；
- Recognition Profile；
- Label Studio项目与taxonomy状态；
- 当前测试结果。

分别运行：

1. hermetic suite；
2. host MPS suite；
3. TypeScript；
4. Vite build；
5. SQLite integrity；
6. API contract；
7. 浏览器 smoke。

Hermetic suite 必须在看不到主机 MPS 时仍可重复运行。

主机 MPS 门只能存在于独立 host suite，不得让普通业务单元测试依赖真实 MPS。

# 四、Task 1：纠正完成状态与事实源

修正所有错误状态：

- M1：`SMOKE_ONLY_NOT_CANDIDATE`
- M2：`SMOKE_ONLY_NOT_CANDIDATE`
- M3 random split：`INVALID_FOR_BUSINESS_EVAL_LEAKED_SPLIT`
- M3 grouped：`GROUPED_BASELINE_NOT_CANDIDATE`
- M4旧 QLoRA：`PILOT_NOT_EVALUABLE_KB_COVERAGE_ZERO`
- SAM decoder v1/v2：
  `EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE`

不得删除这些制品。

所有报告、数据库、API、Profile、Web必须从同一状态投影生成，禁止再出现数据库说未训练、磁盘已有模型、页面又显示另一种状态。

# 五、Task 2：将现有制品追加注册进统一平台

实现一个正式、幂等、追加式的 reconciliation/backfill 命令。

该命令不得覆盖历史行，必须记录：

- source artifact；
- artifact SHA；
- dataset manifest SHA；
- source commit；
- dirty diff hash；
- model base；
- label source；
- evidence level；
- candidate状态；
- blocker；
- created_at；
- reconciliation actor；
- reconciliation run id。

注册：

## Dataset Snapshot

- `detector_snapshot_v3`
- `segmenter_snapshot_v3`
- `classifier_snapshot_v3`
- `vlm_snapshot_v3`

## Model Artifact

- `nextgen_detector_smoke_v1`
- `nextgen_segmenter_smoke_v1`
- `nextgen_classifier_cropped_v1`
- `nextgen_classifier_grouped_v1`
- `nextgen_vlm_cropped_v1`
- `nextgen_sam_decoder_v1`
- `nextgen_sam_decoder_v2`

## Evaluation

- grouped split comparison；
- SKU readiness policy；
- Qwen candidate recall report；
- SAM segmentation report；
- M1/M2 smoke；
- M3 random/grouped；
- M4 QLoRA pilot。

注册后必须实现三方对账：

磁盘 Artifact
= 数据库 Artifact
= API Artifact
= Web 展示状态

若任何 hash 不一致，fail-closed。

# 六、Task 3：创建真实 Training Cycle

基于现有历史证据建立一个追加式 Cycle：

`sku_long_tail_nextgen_cycle_v1`

节点至少包括：

1. BaselineReconciled
2. SamPseudoMasksGenerated
3. SamDecoderExperimentRecorded
4. SnapshotsV3Frozen
5. M1SmokeRecorded
6. M2SmokeRecorded
7. M3LeakageDetected
8. M3GroupedBaselineRecorded
9. M4PilotRecorded
10. PlatformFactsReconciled
11. Canonical38DatasetBuild
12. M1Pilot
13. M2Pilot
14. M3LongTailExperiments
15. KBCoverageBuild
16. M4RealCandidatePilot
17. DemoEvaluation
18. AwaitingIndependentEvaluation
19. AwaitingProductionDecision

历史已完成节点通过 reconciliation event 标记，不伪造重新执行。

Cycle 必须：

- 持久化；
- 可恢复；
- 有节点 checkpoint；
- 有 blocker；
- 有证据引用；
- 有资源租约；
- 有幂等键；
- 重启8400后仍可恢复；
- 能生成 taskboard卡片。

# 七、Task 4：真正实现主管 Agent

现在的4个 Agent只有 Manifest，不算 Agent 已经可用。

必须实现正式接口：

```text
POST /api/agent/v1/sessions
GET  /api/agent/v1/sessions/{session_id}
GET  /api/agent/v1/sessions/{session_id}/messages
POST /api/agent/v1/chat
POST /api/agent/v1/commands/{command_id}/approve
POST /api/agent/v1/commands/{command_id}/reject
GET  /api/v1/agents/{agent_id}
POST /api/v1/agents/{agent_id}/invoke
GET  /api/v1/agents/{agent_id}/health
GET  /api/v1/blackboard
POST /api/v1/blackboard/events
GET  /api/v1/taskboard
GET  /api/v1/events/stream
```

## Supervisor Agent必须完成的真实能力

用户输入：

- “目前训练到哪里？”
- “打开分类器训练结果”
- “哪些SKU数据最少？”
- “显示当前阻塞”
- “创建M3训练计划”
- “比较random和grouped结果”
- “打开Label Studio”
- “为什么Qwen不能继续训练？”
- “停止当前训练”
- “切换生产模型”

Supervisor必须：

1. 解析意图；
2. 查询正式事实源；
3. 调用对应 Domain Agent；
4. 返回证据引用；
5. 必要时生成命令预览；
6. 通过白名单 UIIntent 打开界面；
7. 高风险操作要求审批；
8. 不能自行切生产。

支持的 UIIntent：

- navigate
- open_panel
- filter
- highlight
- compare
- pin_card
- show_evidence

禁止：

- inject_html
- eval_js
- arbitrary_url
- arbitrary_sql
- arbitrary_shell
- arbitrary_path

模型 Provider 必须可替换。

本地开发默认使用已有本地模型服务；若模型不可用，提供结构化规则 fallback，但不得伪装成大模型推理成功。

# 八、Task 5：让黑板、记忆和任务板产生真实数据

当前黑板和记忆表为空，不得再以“表已经建好”作为验收。

由 reconciliation和Cycle自动写入真实黑板事件：

- 发现47.7pp数据泄漏；
- SAM decoder不可作为候选；
- M1/M2仅smoke；
- M3 grouped为30.7%；
- M4 KB覆盖为0；
- 45个pending SKU；
- D1/D2只含894张原图；
- production未切换；
- 下一步训练计划。

至少形成：

- Findings；
- Decisions；
- Tasks；
- Blockers；
- EvidenceRefs；
- ModelRunRefs；
- PendingCommands；
- Resolutions。

Taskboard必须真实出现：

- Todo；
- Running；
- Waiting；
- Review；
- Done。

不得插入假任务或伪造训练运行。

Memory写入：

- L1：Cycle checkpoint；
- L2：项目决策、指标和制品；
- L3：只保存权限允许的租户级摘要；
- L4：只保存通用平台方法论，不含客户原始照片和业务数据。

# 九、Task 6：修复 Web 工作台

当前黄色抽屉文字对比度不足，任务板为空，也没有对话输入。

必须完成：

## 主管抽屉

- 对话输入框；
- 会话历史；
- Agent状态；
- 当前Graph；
- 今日待办；
- Running；
- Waiting/Blocked；
- Needs Review；
- Resolved；
- 命令预览；
- 批准/拒绝；
- Evidence；
- 资源状态；
- 抽屉折叠/展开；
- 跨页面保持；
- 可读颜色对比度；
- 响应式布局。

## 任务板

真实读取平台事实源，不得使用静态数组。

每张卡至少显示：

- 标题；
- owner Agent；
- status；
- blocker；
- evidence；
- graph_run_id；
- linked model/dataset；
- updated_at；
- acceptance状态。

## 训练页面

必须显示：

- 当前production；
- 四个snapshot；
- M1/M2 smoke；
- M3 random无效；
- M3 grouped baseline；
- M4 KB阻断；
- SAM实验状态；
- 当前Cycle；
- 当前资源租约；
- 可创建的训练计划；
- 可启动的有界实验；
- 日志、曲线、指标；
- safe-stop；
- blocker说明。

不得继续显示已经过期的 T1～T4 固定卡片状态。

# 十、Task 7：修复 Recognition Profile

Profile状态必须从 Artifact Registry、Evaluation和Blocker动态派生，不能保存过期文本。

至少提供：

- `production_legacy`
- `nextgen_m1_pilot`
- `nextgen_m1_m2_pilot`
- `canonical38_classifier`
- `canonical38_cascade`
- `research83_classifier`
- `research83_full_cascade`
- `shadow_compare`

规则：

- production只有当前legacy enabled；
- smoke制品不能成为可选识别模型；
- candidate=false必须disabled；
- KB覆盖0时M4 Profile必须disabled；
- pending 45类不得混入商业 canonical Profile；
- research83必须明显标记“实验，不可商业输出”。

识别页面、外部API、内部Agent均使用同一个：

`recognition_profile_id`

# 十一、Task 8：把训练范围拆成两条

## Scope A：canonical38

包含38个已经映射到Registry的SKU。

用途：

- 正式 grouped训练；
- 长尾算法实验；
- KB建设；
- Qwen候选检索；
- 演示识别；
- 后续业务评估。

## Scope B：research83

包含38个canonical加45个pending类。

用途：

- 研究新包装；
- few-shot/prototype；
- pending类混淆分析；
- 包装版本建议；
- 业务裁决材料。

不得把 research83 的 pending名称当作稳定商业SKU ID。

为45个pending类自动生成裁决材料，但不自动裁决：

- class_id；
- display name；
- 代表图；
- raw count；
- effective groups；
- store/session；
- 最近canonical候选；
- embedding距离；
- OCR相似度；
- 包装差异；
- 建议：新SKU/新包装/别名/合并/保留未知；
- 置信度；
- 证据路径。

输出：

- `pending_sku_decision_pack.json`
- `pending_sku_decision_pack.md`
- Web可视化裁决入口。

# 十二、Task 9：M3长尾算法实验

不要直接重复当前10 epoch普通CrossEntropy。

在 canonical38 grouped split 上运行受控消融：

## E1

普通CrossEntropy grouped baseline。

## E2

Balanced sampler + CrossEntropy。

## E3

Effective-number class-balanced loss。

## E4

Logit adjustment或focal loss，只选一种进入首轮。

## E5

层级分类：

品牌/商品族/容器/容量
→ canonical SKU/package version。

## E6

基于混淆矩阵的 specialist head。

E6只有在混淆证据明确后运行，不按主观猜测建立。

共同要求：

- 相同 grouped split；
- 相同公开初始化；
- 相同训练预算；
- 10～15 epoch；
- early stop；
- MPS；
- 不继承旧classifier；
- 记录每类指标。

必须报告：

- top1；
- macro recall；
- macro F1；
- balanced accuracy；
- Tier B/C表现；
- worst-decile recall；
- head-tail gap；
- confusion matrix；
- calibration；
- coverage@accepted precision；
- unknown/abstain表现。

只有相对 grouped baseline 有明确收益的方案才能登记为candidate。

random split 82.4%只能保留为泄漏证据，禁止再参与方案排名。

# 十三、Task 10：M1/M2正式pilot

## M1 Detector

D1是全场景商品检测器。

只能使用原始货架/冰柜等全场景图片及其region，不得把20,338张单商品crop伪装成全场景检测数据。

当前：

- 894张原图；
- 5,981个区域；
- M1只有1 epoch smoke；
- mAP50约0.0035。

执行：

1. 数据可视化抽检；
2. 校验box是否来自正确mask；
3. 5 epoch pilot；
4. 检查学习曲线；
5. 若指标持续上升且无异常，允许一个最多30 epoch、带early stop的candidate；
6. 与当前legacy detector在相同数据和口径比较。

## M2 Segmenter

区分：

- 894张全场景图、5,981个polygon；
- 20,338张单商品crop mask。

建立两个明确子集：

- `scene_segmenter_snapshot`
- `product_crop_mask_snapshot`

不得混淆两个评估口径。

执行：

1. polygon质量门；
2. 5 epoch pilot；
3. 若收敛正常，允许一个最多30 epoch candidate；
4. 报告pseudo-mask一致性；
5. 报告边界质量；
6. 报告下游分类收益；
7. 无人工mask时仍标记 `pseudo_mask_interim`。

SAM decoder不再继续使用自生成伪mask反复自训练。

SAM继续作为teacher和困难样本精修器。

# 十四、Task 11：KB与M4

当前Qwen真实候选评估：

- KB size=27；
- 抽样GT在KB覆盖=0；
- candidate recall@K=null；
- p95约75.3秒。

在此状态下禁止再次训练Qwen。

先完成 canonical38 KB：

每个SKU至少包括：

- canonical SKU ID；
- package version；
- 标准名称；
- alias；
- 品牌；
- 容量；
- 容器；
- 口味；
- OCR关键词；
- 多张参考图；
- image embedding；
- text embedding；
- provenance；
- version。

真实候选链：

crop/context
→ OCR
→ image embedding
→ text/attribute retrieval
→ rerank
→ top-K CandidateSet

Candidate builder函数签名禁止接收GT。

先评估：

- KB coverage；
- recall@1；
- recall@5；
- recall@8；
- latency；
- registry escape。

Gate：

- canonical38 KB coverage必须100%；
- candidate recall@8建议≥90%；
- 若未达到，继续修检索，不启动Qwen训练。

通过后：

1. 重新构建真实candidate数据集；
2. 不沿用保证包含GT的旧数据集；
3. Qwen3-VL 4B、MLX、vision frozen；
4. 先1 epoch QLoRA pilot；
5. MLX独占；
6. 报告accepted precision、coverage、abstain和p95；
7. 只有评估有效才登记candidate。

# 十五、资源调度

默认：

- `apple_mps_heavy=1`
- `apple_mlx_exclusive=1`
- Qwen独占；
- CPU/IO可与一个heavy任务并行；
- 不默认并行两个训练；
- 不允许三个heavy job。

只有完成真实组合benchmark，并满足以下全部条件，才允许并发2：

- 总吞吐提高≥25%；
- swap增量≤2GB；
- swap绝对值<8GB；
- memory pressure不是red；
- thermal不是serious/critical；
- 8091/8300/8400健康；
- 服务p95不超过基线1.2倍；
- 无MPS fallback/OOM/NaN/Inf。

# 十六、旧250流程和micro-gold

继续保持：

`5+5+250 = SUPERSEDED_FOR_DEMO_TRAINING`

不得恢复旧250张门，不得删除历史队列。

`demo_micro_gold_v1`：

- 不阻塞本轮M1/M2/M3实验训练；
- 不阻塞主管Agent和平台建设；
- 只阻塞准确率声明、shadow晋级和production发布；
- 待机器侧闭环后再让用户决定是否执行。

无独立人工真值时，只能写：

`DEMO_CANDIDATE_AWAITING_INDEPENDENT_EVALUATION`

# 十七、测试与浏览器验收

必须新增和通过：

## 平台

- reconciliation幂等；
- Artifact hash冲突拒绝；
- Cycle恢复；
- taskboard真实投影；
- Profile动态blocker；
- 服务重启恢复；
-空数据库和历史数据库迁移。

## Agent

- session；
- chat；
- invoke；
- capability scope；
- command preview；
- approve/reject；
- UIIntent白名单；
- arbitrary SQL/Shell/path拒绝；
- production切换拒绝；
-黑板跨Agent覆盖拒绝；
- memory ACL。

## Web

真实浏览器完成：

1. 打开主管抽屉；
2. 输入“目前训练到哪里”；
3. 返回当前Cycle和证据；
4. 输入“显示SKU长尾”；
5. 自动打开长尾面板；
6. 输入“打开M3 grouped结果”；
7. 自动跳转并展示30.7%；
8. 输入“创建M3训练计划”；
9. 生成命令预览；
10. 用户批准后创建Plan，不直接启动；
11. 打开任务板；
12. 任务真实存在；
13. 打开Recognition；
14. smoke Profile禁用；
15. production legacy可用；
16. 黄色抽屉文字清晰；
17. 控制台无error；
18. 刷新后会话、任务和Graph保持。

# 十八、Git规则

- 继续当前分支；
- 小步TDD commit；
- 不使用`git add .`；
- 不提交模型、图片、SQLite、secret、大型数据集；
- 不清理受保护未跟踪目录；
- 不覆盖run；
- 不删除历史证据；
- 不merge、push、deploy；
- 每个阶段更新纠偏手册。

# 十九、Loop状态

使用以下状态：

- `CORRECTION_BASELINE_VERIFIED`
- `CURRENT_GATE_CORRECTED`
- `PLATFORM_FACTS_RECONCILED`
- `TRAINING_CYCLE_ACTIVE`
- `BLACKBOARD_POPULATED`
- `SUPERVISOR_RUNTIME_READY`
- `WORKBENCH_OPERATIONAL`
- `PROFILES_RECONCILED`
- `CANONICAL38_SNAPSHOT_READY`
- `RESEARCH83_SNAPSHOT_READY`
- `M3_LONGTAIL_EXPERIMENTS_COMPLETE`
- `M1_PILOT_COMPLETE`
- `M2_PILOT_COMPLETE`
- `KB_CANONICAL38_READY`
- `M4_REAL_CANDIDATE_EVALUABLE`
- `FOUR_CANDIDATES_READY_AWAITING_MICRO_GOLD`
- `AWAITING_PRODUCTION_DECISION`
- `COMPLETED_NO_PROMOTION`
- `FAILED`

每个节点：

Observe
→ Validate
→ Plan
→ Acquire Lease
→ Execute
→ Verify
→ Record Event
→ Checkpoint
→ Decide Next/Retry/Wait/Stop

同一错误最多重试两次。第三次进入WAITING或FAILED，禁止无限循环。

# 二十、最终完成门

只有以下全部成立，才能写：

`FOUR_CANDIDATES_READY_AWAITING_MICRO_GOLD`

- 四个snapshot正式注册；
- 磁盘/DB/API/Web四方一致；
- 一个真实Training Cycle存在；
- taskboard非空并反映真实状态；
- blackboard有真实事件；
- memory有真实、有证据的项目记忆；
- Supervisor可以对话；
- Domain Agent可以被调用；
- UIIntent真实工作；
- M1不是1 epoch smoke，而是完成正式pilot/candidate；
- M2不是1 epoch smoke，而是完成正式pilot/candidate；
- M3在grouped split上有正式长尾实验结果；
- M4的KB coverage和candidate recall可计算；
- M4使用真实CandidateSet完成pilot；
- Recognition Profile状态正确；
- hermetic和host测试分离且通过；
- Web浏览器验收通过；
- production未切换。

任一条件不成立，不得再次写“四候选就绪”。

# 二十一、最终报告格式

最终一次性提交以下报告：

1. HEAD、分支、工作树；
2. commit链；
3. 阅读文件；
4. 初始纠偏状态；
5. 修正前后Gate；
6. DB迁移；
7. SQLite integrity；
8. reconciliation结果；
9. 四snapshot数据库/API对账；
10. 模型Artifact数据库/API对账；
11. Training Cycle ID和节点；
12. taskboard真实卡片统计；
13. blackboard事件统计；
14. memory分层统计；
15. Supervisor对话验收；
16. ModelOps调用验收；
17. Data Steward调用验收；
18. Workbench/UIIntent验收；
19. Recognition Profile状态；
20. canonical38数据；
21. research83数据；
22. pending SKU裁决包；
23. M1 pilot/candidate结果；
24. M2 pilot/candidate结果；
25. M3各长尾实验对比；
26. KB coverage和candidate recall；
27. M4真实候选QLoRA结果；
28. 资源benchmark；
29. 实际并发策略；
30. Label Studio标签状态；
31. Web截图；
32. hermetic测试；
33. host MPS测试；
34. TypeScript/Vite；
35. 服务健康；
36. production未切换声明；
37. 未关闭问题；
38. 当前Gate；
39. 下一步只需要用户决定的事项。

最终不要向用户重复询问已经可以由机器验证的问题。

只有以下情况暂停请求用户：

- 删除或覆盖数据；
- pending SKU最终canonical裁决；
- production切换；
- merge/push/deploy；
- 客户输入数据修改；
- 购买外部资源；
- 不可逆业务口径选择。

立即从Task 0开始执行。先接通平台事实链和主管Agent，再开展M1/M2/M3训练；KB不达标时不得浪费算力训练Qwen。