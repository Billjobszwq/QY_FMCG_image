# Micro-Gold 数据泄漏纠偏、项目 22 重建与 M4 独立评估继续执行指令


你需要继续完成当前工作，但上一轮项目 21 和 M4 评估存在新的独立性问题。本轮必须一次性修复，禁止把问题再次留给用户逐项处理。

本轮目标：

1. 保留但停止使用 Label Studio 项目 21；
2. 重建真正独立的 demo_micro_gold_v2；
3. 创建新的 Label Studio 盲审项目；
4. 重建 M4 来源组零泄漏评估集；
5. 重新进行真实 M4 三版本推理；
6. 修正 Gate、Taskboard、Blackboard、Web 和文档；
7. 最终只让用户进入新的有效项目进行人工审核。

本轮不是训练任务，不允许重新训练任何模型。

---

## 一、强制阅读

修改任何文件前，完整阅读：

1. `<ai-workflow-root>/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/CODEX-PROJECT-HANDBOOK.md`
3. `docs/README.md`
4. `docs/implementation/candidate-evidence-convergence-and-microgold-v1/` 全部文件
5. `docs/implementation/sku-long-tail-agent-foundation-v1/` 全部状态、决策和执行文件
6. `docs/implementation/project-logic-chain-v3/` 全部文件
7. `docs/implementation/nextgen-four-model-training-loop-v2/` 全部文件
8. `scripts/build_demo_micro_gold_v1.py`
9. `scripts/eval_m4_three_versions.py`
10. `scripts/eval_m4_evidence_v2.py`
11. `.micro_gold_v1/manifest.json`
12. `.micro_gold_v1/tasks.json`
13. `reports/nextgen_v2/m4_three_version_eval_v2.json`
14. `reports/nextgen_v2/m4_evidence_v2/` 全部逐样本账本
15. M3 TVT、QLoRA、Classifier、KB、SAM、Detector 的全部数据 manifest 和 split audit
16. Label Studio 项目 21、Profile、Cycle、Taskboard、Blackboard、Artifact Registry、Evaluation Registry 的源码、数据库和测试

建立新的执行文档目录：

`docs/implementation/micro-gold-v2-leakage-rebuild/`

至少包含：

- `AGENT-EXECUTION-PROMPT.md`
- `00-LEAKAGE-ROOT-CAUSE-AUDIT.md`
- `01-EXECUTION-PLAN.md`
- `DECISIONS.md`
- `ISSUES.md`
- `EXECUTION-LOG.md`
- `STATUS.md`
- `ACCEPTANCE.md`
- `FINAL-REPORT.md`

把本提示词原文保存为 `AGENT-EXECUTION-PROMPT.md`。

---

## 二、已经确认的事实

必须先用测试和现场数据复现，不得忽略。

### 2.1 M4 holdout 来源组泄漏

上一轮 M4 holdout：

- 122 个样本；
- 84 个唯一来源组；
- 其中 24 个来源组与 QLoRA 训练集重叠；
- 重叠比例约为 28.6%。

因此：

`M4 Top-1=0.828`

不能继续标记为独立评估成绩。

旧报告和原始证据必须保留，但状态必须改为：

`EXPERIMENTAL_GROUP_LEAKED_EVALUATION`

不得删除、覆盖或伪造为独立测试。

### 2.2 项目 21 没有完成五键零泄漏

`build_demo_micro_gold_v1.py` 实际只比较文件 SHA。

没有完整检查：

- photo_id
- original photo SHA
- normalized store
- store alias
- session
- leakage_group_id
- symlink target
- source image identity

而且使用完整原图 SHA 去对比训练裁剪图 SHA，同源图片裁剪后 SHA 必然不同，因此不能证明独立。

### 2.3 项目 21 的样本构成不可信

当前构建器：

- 将普通 product detector box 称为 canonical；
- 没有确认它属于 canonical38；
- 将框面积 `<0.005` 直接称为 hard；
- 没有验证反光、遮挡、低光、倾斜等真实质量证据；
- 随机裁剪生成 negative，却没有检查是否与商品框、point 或 SAM mask 重叠。

因此“120 canonical + 40 pending + 20 hard + 20 negative”只是构建器命名，不是真实样本组成。

### 2.4 关键证据没有进入版本链

以下文件当前未跟踪：

- `.micro_gold_v1/manifest.json`
- `.micro_gold_v1/tasks.json`
- `.micro_gold_v1/ls_project.json`
- `reports/nextgen_v2/m4_evidence_v2/` 逐样本证据

图片等大资产可以不进入 Git，但 manifest、ledger、hash audit 和评估摘要必须进入版本控制或不可变数据库登记。

### 2.5 Artifact 数量报告错误

上一报告写 16 artifacts，数据库和 API 实际为 15。

后续报告必须以实时 API/数据库对账值为准。

---

## 三、安全边界

本轮严禁：

1. 启动 M1、M2、M3、SAM、Classifier、Qwen 或 QLoRA 训练；
2. 切换 production bundle；
3. 删除 Label Studio 项目 21；
4. 删除旧 micro-gold 文件或旧 M4 报告；
5. 覆盖任何已有数据集和证据；
6. 恢复旧 250 张流程；
7. 把项目 21 继续列为有效人工任务；
8. 伪造 human_final、gold_verified 或人工审核结果；
9. 使用 GT、文件名 SKU、目录类别强制候选包含正确答案；
10. 降低泄漏门禁凑足 200 条；
11. merge、push、deploy；
12. `git add -A`；
13. 修改或清理 `.superpowers/` 等受保护目录。

生产必须保持：

`prod_20260805_v5_r1`

本轮起始 Gate 必须改为：

`MICRO_GOLD_REBUILD_REQUIRED_DUE_TO_LEAKAGE`

---

## 四、使用 Graph+Loop 执行

建立新的执行 Graph：

text
BaselineAudit
  → Project21Supersession
  → UnifiedForbiddenIdentityIndex
  → MicroGoldV2SamplingPolicy
  → MicroGoldV2BuilderTDD
  → MicroGoldV2LeakageAudit
  → MicroGoldV2ManifestFreeze
  → LabelStudioV2Import
  → M4HoldoutV3Builder
  → M4HoldoutV3LeakageAudit
  → M4ThreeVersionRealEvalV3
  → EvaluationRegistryCorrection
  → CycleTaskboardBlackboardConvergence
  → WebSupervisorAcceptance
  → FinalVerification
  → AwaitingHumanReview
  
要求：

- 每个节点有唯一 logical_node；
- 有幂等键；
- fail-closed；
- 不重复插入状态；
- 历史使用 append-only；
- 当前状态使用投影；
- 中间失败不能绕过；
- 8400 重启后能够恢复；
- Agent、API、Web、数据库使用相同 Domain Service。

---

## 五、处理项目 21

不得删除项目 21。

执行：

1. 将项目 21 标记为：
    
    `SUPERSEDED_INVALID_INDEPENDENCE_AUDIT`
    
2. 标题增加明确前缀：
    
    `[SUPERSEDED-DO-NOT-REVIEW] demo_micro_gold_v1_blind`
    
3. 在数据库追加 supersession 记录，原因：
    
    `five-key-and-source-group-leakage-gate-not-implemented`
    
4. 从以下当前态界面移除：
    
    - 首页待办
    - Taskboard 活动任务
    - Supervisor 今日待办
    - micro-gold 完成率
    - 有效 Label Studio 快捷入口
5. 保留：
    
    - 项目本身
    - 200 张图片
    - tasks
    - 截图
    - manifest
    - 审计证据
6. 项目 21 当前人工完成数仍应为 0，不得伪造。
    

---

## 六、建立统一 Forbidden Identity Index

新建版本化模块，例如：

`src/data_governance/forbidden_identity_index.py`

数据来源至少覆盖：

- M3 TVT train/val/test；
- M3 旧 classifier datasets；
- QLoRA train 数据；
- M4 旧 holdout；
- M4 v2 holdout；
- Detector/Segmenter/SAM 训练快照；
- KB 参考图片；
- active protocol sets；
- 旧 gold/diagnostic/test sets；
- 已登记 production evaluation sets。

每个样本尽可能解析：

- photo_id
- exact SHA256
- original photo SHA256
- symlink target SHA256
- source path identity
- normalized store ID/name
- store alias
- session ID
- leakage_group_id
- capture timestamp/group
- source batch
- SKU provisional identity
- dataset/split/role

规则：

1. 任意活动训练、验证或测试数据命中即排除；
2. 任意 source group 命中即排除；
3. store/session 信息缺失时不得默认通过；
4. 不能解析来源身份时进入 `identity_unresolved`，不得进入正式 micro-gold；
5. 同一照片不同裁剪必须识别为同源；
6. 不允许只比较输出 crop SHA；
7. 生成 append-only 排除账本。

冻结输出：

- `forbidden_identity_index_v2.jsonl`
- `forbidden_identity_index_v2.audit.json`
- index hash
- builder hash
- source manifests hash
- 各来源数量
- 各身份字段缺失率

---

## 七、Micro-Gold V2 样本设计

目标仍为 200 个 region，但只有满足独立性才允许导入。

### 7.1 目标构成

- 120 个 canonical38；
- 40 个 pending/new-packaging/unknown；
- 20 个真实 hard；
- 20 个真实 negative。

### 7.2 canonical38

要求：

- 38 类每类至少 3 个独立来源组，共至少 114；
- 剩余 6 个优先来自：
    - 已知混淆对；
    - worst-decile 类；
    - 数据量最少类；
- provisional SKU 必须来自可追踪的 legacy/SAM/人工标注证据；
- provisional SKU 只用于分层抽样；
- 不展示给审核员；
- 不能把 provisional 当 human_final。

### 7.3 pending/new packaging

要求：

- 来自 45 pending 类；
- 尽量覆盖更多 pending 类；
- 每个来源组最多一个 region；
- 不得和 QLoRA、M3、旧 holdout 同源；
- 人工可以选择：
    - 新包装沿用旧名称
    - 新包装使用新名称
    - unknown
    - unreadable
    - bad_crop
    - conflict

### 7.4 hard

hard 必须由真实质量证据确定，例如：

- reflection
- blur
- low_light
- over_exposure
- tilt
- occlusion
- truncation
- tiny_object
- reshoot/moire

禁止只用框面积决定 hard。

每个 hard 样本必须记录：

- quality policy version
- quality scores
- hard reason
- source evidence path
- crop/box/mask identity

### 7.5 negative

negative 必须满足：

- 与全部 YOLO box 零交集；
- 与 point annotation 安全距离大于阈值；
- 与 SAM mask 零交集；
- 不包含完整或可识别商品；
- 人工仍可将误判 negative 改为具体 SKU；
- 随机 crop 不能直接被视为 negative。

### 7.6 来源独立性

原则上每张来源照片最多一个 region。

只有为了已知混淆研究且有明确证据时，才允许最多两个 region。

目标：

- 至少 150 个唯一来源照片；
- canonical/hard/negative/pending 之间 source group 零重叠；
- 同一门店/session 不得跨分层大量重复；
- 所有跨类别重复都要 fail-closed。

---

## 八、Micro-Gold V2 Manifest

新 manifest 必须是逐任务可审计账本，不再只是数量摘要。

每条至少包含：

- micro_gold_task_id
- anonymous_image_name
- image SHA
- original photo ID
- original photo SHA
- source batch
- normalized store
- store alias
- session
- leakage_group_id
- provisional stratum
- provisional SKU ID（仅审计侧保存）
- quality conclusion
- quality reasons
- source box
- source point
- source mask SHA
- crop coordinates
- crop builder version
- forbidden-index result
- exclusion checks
- sampling seed
- evidence references

manifest 顶层至少包含：

- schema version
- dataset name/version
- builder hash
- source commit
- dirty diff hash
- manifest hash
- forbidden index hash
- seed
- target counts
- actual counts
- unique photo/store/session/group counts
- unresolved identity count
- exclusion reason distribution
- class distribution
- hard reason distribution
- negative verification statistics
- source files and hashes

要求：

- staging 构建；
- 原子发布；
- 已存在目标目录时拒绝覆盖；
- 同 seed 重跑结果一致；
- manifest 和 ledger 纳入 Git；
- 图片大资产可以保持未跟踪，但必须登记目录 Merkle/hash 和绝对路径。

如果不足 200：

- 不得重复、降门槛或复用项目 21；
- 停止导入；
- 报告各类别实际可用数及缺口；
- Gate 保持 `MICRO_GOLD_REBUILD_BLOCKED_INSUFFICIENT_INDEPENDENT_DATA`。

---

## 九、Label Studio 新项目

只有 Micro-Gold V2 全部门禁通过后才能创建新项目。

建议名称：

`demo_micro_gold_v2_blind`

项目 ID 不得硬编码为 22；创建后记录实际 ID。如果 22 可用可以使用 22。

### 9.1 标注模式

本轮是 M3/M4 classification/VLM 金标准，不用于证明 M1/M2 检测器性能。

因此使用 classification-region 模式：

- 系统展示已裁剪 region；
- 不展示模型 prediction；
- 不展示 provisional SKU；
- 不要求用户重新画已有 crop 的商品框；
- 用户选择 canonical SKU 或状态；
- 提供 `bad_crop/needs_recrop`；
- 提供 `background/no_product`；
- 提供 pending/new packaging；
- 提供 unknown/unreadable/conflict。

如果用户判断 crop 错误，必须能够标记需要重新裁剪。

### 9.2 人工流程

- 200 条主审；
- 确定性抽 40 条进行第二人盲审；
- 第二审核员必须不同；
- 只有分歧项进入第三人仲裁；
- 一致后成为 human_final；
- 仲裁后成为 gold_verified；
- 未审核时人工完成数必须为 0。

### 9.3 导入前 10 条验收

正式放量前先导入 10 条验收批：

- 3 canonical；
- 2 pending；
- 2 hard；
- 2 negative；
- 1 bad-crop 候选。

检查：

- 图片正常显示；
- 文件名匿名；
- taxonomy 可搜索；
- 无 prediction；
- provisional 信息不可见；
- 提交后刷新保持；
- unknown/new packaging 可提交；
- negative 可改判 SKU；
- bad_crop 可提交；
- API、数据库、Web 状态一致。

10 条通过后再幂等放量完整 200。

---

## 十、重建 M4 Holdout V3

旧 M4 v2 报告和 0.828 保留，但降级为：

`EXPERIMENTAL_GROUP_LEAKED_EVALUATION`

不得继续在 Web 上称为“独立评估准确率”。

新建：

`m4_eval_holdout_v3`

### 10.1 独立性范围

V3 holdout 必须与以下内容零来源组重叠：

- QLoRA train；
- old adapter train；
- M3 classifier train/val/test；
- candidate retriever 的训练数据；
- KB 参考图；
- M4 v1/v2 holdout；
- Micro-Gold V2；
- active protocol sets。

检查：

- exact SHA
- original SHA
- photo ID
- symlink target
- normalized store
- store alias
- session
- leakage group

候选生成器也是系统的一部分，因此如果 candidate retriever 训练时见过相同来源组，不能称为端到端独立测试。

### 10.2 Holdout 规模

目标至少：

- 100 个 canonical 样本；
- canonical38 每类至少 2 个；
- 20 个 pending/new-packaging/unknown；
- 20 个 hard/negative。

如果无法满足，诚实报告，不允许凑数。

### 10.3 数据冻结

不得继续使用：

`/tmp/m4_eval_samples.json`

作为事实源。

必须冻结：

- dataset manifest
- per-sample ledger
- candidates
- candidate scores
- model hash
- adapter hash
- prompt hash
- retriever hash
- KB hash
- ground-truth source
- leakage audit
- builder hash
- manifest hash

候选分数不得继续为 null。

候选构建器函数签名结构上禁止传入 GT。

---

## 十一、M4 三版本真实评估 V3

只推理，不训练。

比较：

1. base Qwen3-VL 4B；
2. old cropped adapter；
3. new real-candidate adapter。

要求：

- Apple MLX 独占运行；
- 先 bounded smoke；
- 三版本使用完全相同数据、candidates、prompt、解析器；
- 保存 raw output；
- 保存 generation tokens；
- 保存 wall time；
- 保存模型和 adapter 完整 SHA；
- 保存候选和候选分数；
- 保存 parsed canonical SKU；
- 保存 abstain/parse_error；
- 保存逐样本错误账本。

指标：

- candidate recall`@1/5/8`
- Top-1
- macro-F1
- accepted precision
- coverage
- abstain precision/recall
- false accept
- false reject
- pending false accept
- negative false accept
- registry escape
- p50/p95 latency
- tokens/region
- peak memory
- error categories

无论结果如何，都不得直接进入 production。

如果 v3 无法建立真正独立的 holdout：

- 不重跑；
- 保留旧结果为泄漏实验；
- 等待 Micro-Gold V2 人工完成后，以人工金标准作为真正独立评估集。

---

## 十二、状态和界面修正

### 修正前

当前 Gate：

`MICRO_GOLD_READY_AWAITING_HUMAN_REVIEW`

是不正确的。

### 修正后阶段

项目 21 失效后：

`MICRO_GOLD_REBUILD_REQUIRED_DUE_TO_LEAKAGE`

Micro-Gold V2 构建完成但未导入：

`MICRO_GOLD_V2_VALIDATED_AWAITING_IMPORT`

新项目导入并通过 10 条验收后：

`MICRO_GOLD_V2_READY_AWAITING_HUMAN_REVIEW`

### Web 必须显示

- 项目 21：历史、失效、禁止审核；
- 新项目：唯一有效人工入口；
- M4 0.828：来源组泄漏实验结果；
- M4 v3：若有效则显示新结果；
- 当前人工完成数；
- 当前唯一下一步；
- production 未切换；
- 当前没有训练进程。

### Supervisor 必须回答

1. 为什么项目 21 不能继续审核？
2. M4 0.828 为什么被降级？
3. 新 micro-gold 是否与训练集同源？
4. 新项目 ID 是多少？
5. 用户需要完成多少条？
6. 当前是否有训练运行？
7. 是否可以切生产？
8. 哪些数据仍然不足？

切 production 必须继续拒绝。

---

## 十三、测试要求

必须 TDD 覆盖：

### Forbidden Identity

- 同 photo ID、不同 SHA → 拒绝；
- 同 source group、不同 crop → 拒绝；
- 同 store alias/session → 拒绝；
- symlink target 命中 → 拒绝；
- identity 解析失败 → 拒绝；
- train/val/test 任一命中 → 拒绝；
- 跨类别同源 → 拒绝。

### Micro-Gold Builder

- 已有目录拒绝覆盖；
- 同 seed 结果确定；
- canonical 类分布满足要求；
- hard 必须有质量证据；
- negative 与 box/mask/point 零重叠；
- 每来源照片 region 数受限；
- 不足目标数 fail-closed；
- manifest 含完整字段和 hash；
- provisional label 不进入 LS 可见字段；
- blind project prediction=0。

### M4 Holdout

- QLoRA group overlap → 拒绝；
- Classifier/retriever group overlap → 拒绝；
- KB reference overlap → 拒绝；
- source group 无法解析 → 拒绝；
- GT 不得传入候选生成器；
- candidates score 不得为 null；
- `/tmp` 不得作为正式事实源；
- 三版本必须真实加载不同 adapter；
- report hash 与 Registry 一致。

最终执行：

```
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy \
python3 -m pytest \
-q -p no:cacheprovider -m "not host_mps"
```

以及：

```
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy \
python3 -m pytest \
-q -p no:cacheprovider -m host_mps
```

还要执行：

- TypeScript `tsc --noEmit`
- Vite build
- SQLite integrity check
- API/DB/Web 对账
- 8091/8092/8300/8400 健康检查
- 浏览器完整验收

---

## 十四、提交纪律

建议小步提交：

1. baseline/root-cause docs
2. project21 supersession
3. forbidden identity index TDD
4. micro-gold v2 builder TDD
5. micro-gold v2 freeze
6. Label Studio v2 import
7. M4 v2 leaked-status correction
8. M4 holdout v3 builder
9. M4 real eval v3
10. state/API/Web convergence
11. browser acceptance
12. final docs/handbook

要求：

- 禁止 `git add -A`；
- 只暂存本任务明确文件；
- 大图片不强制纳入 Git；
- manifest、ledger、audit 和报告必须可版本化；
- 不删除任何历史证据；
- 不 merge/push/deploy。

---

## 十五、完成门

只有以下全部满足，才允许写完成：

- 项目 21 已 supersede 且不再是活动入口
- 当前 Gate 已撤销错误的 READY 状态
- M4 0.828 已标记 group-leaked experimental
- Unified Forbidden Identity Index 已建立
- Micro-Gold V2 五键及 group 审计通过
- canonical38 分布真实满足要求
- hard 有质量证据
- negative 与 box/mask/point 零重叠
- 至少达到规定的唯一照片/来源组数量
- manifest 和 per-task ledger 完整
- manifest/builder/index hash 已登记
- 新 Label Studio 项目已创建
- 10 条验收批已通过
- 完整 200 条已导入，或诚实报告不足
- prediction=0
- provisional SKU 对人工不可见
- 当前人工完成数真实为 0
- M4 holdout v3 来源组零泄漏，或明确 blocked
- M4 v3 证据进入 Evaluation Registry
- Profile/Artifact/Cycle/Taskboard/Blackboard 一致
- Hermetic 测试通过
- Host MPS 测试通过
- SQLite integrity=ok
- 四服务健康
- production 未切换
- 没有启动训练
- 文档和手册更新完成

如果独立数据不足，不得写 COMPLETE，应写：

`BLOCKED_INSUFFICIENT_INDEPENDENT_DATA`

如果全部成功，最终 Gate：

`MICRO_GOLD_V2_READY_AWAITING_HUMAN_REVIEW`

---

## 十六、最终报告格式

最终至少报告以下 45 项：

1. HEAD、branch、worktree
2. commit 链
3. 阅读文件
4. 初始问题复现
5. 项目 21 supersession 状态
6. 项目 21 历史证据保留情况
7. M4 v2 泄漏复现
8. QLoRA 与旧 holdout 重叠组数量
9. M4 v2 状态修正
10. Forbidden Identity Index 来源
11. Forbidden Index 各字段覆盖率
12. identity unresolved 数量
13. Micro-Gold V2 候选池数量
14. 各排除原因数量
15. canonical38 类分布
16. pending 类分布
17. hard 原因分布
18. negative 验证结果
19. 唯一照片数量
20. 唯一门店数量
21. 唯一 session 数量
22. 唯一 leakage group 数量
23. 五键泄漏结果
24. symlink/source identity 结果
25. manifest hash
26. builder hash
27. forbidden index hash
28. 新 Label Studio 项目 ID
29. 10 条验收批结果
30. 完整导入数量
31. taxonomy 可见性
32. prediction/draft/annotation 初始数量
33. provisional SKU 隐藏证据
34. M4 holdout v3 数量
35. M4 v3 来源组泄漏结果
36. candidate recall
37. base 指标
38. old adapter 指标
39. new adapter 指标
40. Hermetic/Host MPS 测试
41. SQLite/API/Web/服务健康
42. production 未切换声明
43. 未启动训练声明
44. 当前 Gate
45. 用户下一步唯一操作

最终用户下一步必须只有一个：

进入新的有效 Label Studio 项目完成真实人工审核。

不要再让用户进入项目 21，不要再让用户承担机器侧的数据整理和状态收口工作。  
```
