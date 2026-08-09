你现在负责 LLM-Image 项目的“状态一致性收口与候选模型独立评估”。

本轮目标不是继续堆功能，也不是立即扩大训练，而是修复以下核心问题：

1. Training Cycle同一逻辑节点同时存在pending和done；
2. Supervisor、Taskboard、Overview和Web仍显示过期状态；
3. 旧250人工审核仍被当作活动任务；
4. Recognition Profile仍引用旧smoke模型；
5. M1/M2不是候选，但总Gate错误地写成“四候选就绪”；
6. M3 E1/E5没有独立测试集，不能宣布E5全面胜出；
7. M4只有训练loss和检索recall，没有VLM实际裁决准确率；
8. hermetic测试仍有3个MPS环境耦合失败；
9. Web任务板和训练面板文字对比度不足；
10. 当前工作树存在未提交的`.gitignore`修改。

本提示词授权：

- 修改代码、测试、数据库迁移和文档；
- 对现有数据库状态做追加式修正；
- 创建新的状态投影表；
- 构建新的独立grouped test snapshot；
- 在平台状态收口后，重新训练M3 E1/E5两个有界实验；
- 对M4执行有界的独立推理评估；
- 重启8400加载新代码；
- 分阶段Git commit。

本提示词不授权：

- 删除或覆盖历史Cycle节点、Task、模型、SQLite或证据；
- 恢复旧250张人工审核流程；
- 启动新的M1/M2训练；
- 再次训练M4；
- 自动切换production；
- merge、push、deploy；
- 自动裁决45个pending SKU；
- 伪造micro-gold或人工真值；
- 修改客户输入型业务数据。

# 一、必须先完整阅读

完整阅读：

1. `/Users/zhangweiqi/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/CODEX-PROJECT-HANDBOOK.md`
3. `docs/README.md`
4. `docs/implementation/sku-long-tail-agent-foundation-v1/` 全部文件
5. `docs/implementation/nextgen-four-model-training-loop-v2/` 全部文件
6. `docs/implementation/project-logic-chain-v3/` 全部文件
7. 当前Cycle、Taskboard、Blackboard、Agent Runtime、Recognition Profile、Training Registry、Web、M3/M4训练与评估源码和测试
8. 当前数据库schema和001～027迁移
9. 当前分支最近30个commit
10. 当前Git diff、服务、进程、模型和报告

继续更新现有目录：

`docs/implementation/sku-long-tail-agent-foundation-v1/`

新增或更新：

- `08-STATE-CONVERGENCE-AND-CANDIDATE-EVALUATION.md`
- `execution/STATE-CORRECTION-LIST.md`
- `execution/STATE-CORRECTION-STATUS.md`
- `execution/STATE-CORRECTION-DECISIONS.md`
- `execution/STATE-CORRECTION-ISSUES.md`
- `execution/STATE-CORRECTION-LOG.md`
- `execution/STATE-CORRECTION-ACCEPTANCE.md`
- `AGENT-STATE-CORRECTION-PROMPT.md`

将本提示词原样保存到最后一个文件。

# 二、现场已知事实——必须重验

只读复核时发现：

- HEAD曾为`69451495`；
- 分支为`feat/nextgen-training-cycle-v2`；
- `.gitignore`当前存在未提交修改，新增`.gstack/`；
- production仍为`prod_20260805_v5_r1`；
- 四个Snapshot和12个Artifact已经注册；
- `blackboard_event_v1`约23条，不是报告中的28条；
- `memory_entry_v1`约4条；
- Cycle存在1个；
- 同一Cycle逻辑节点同时有pending和done行；
- Cycle API仍显示`TRAINING_CYCLE_ACTIVE`；
- Supervisor仍回答14/19；
- Taskboard仍把M1、M3、KB显示为running/todo；
- 旧250人工任务仍在Overview占据主要位置；
- Profile仍引用旧smoke模型；
- M1/M2 Artifact Registry为`PILOT_NOT_CANDIDATE_YET`；
- M3 E5和M4为`CANDIDATE_PENDING_EVAL`；
- M1/M2训练报告内部却写`candidate=true`；
- hermetic复跑为`1101 passed, 3 failed, 1 skipped, 6 deselected`；
- host MPS正确命令实跑为`6 passed, 1105 deselected`；
- M3 canonical38未发现source prefix或symlink target跨train/val重叠；
- M3 E1与E5各有优劣，不能简单宣布E5全面胜出；
- M4尚未有模型裁决准确率。

先记录新的基线，禁止直接沿用报告数字。

# 三、Task 0：Git和现场保护

1. 记录HEAD、branch、status、diff。
2. 不得擅自丢弃`.gitignore`修改。
3. 判断`.gstack/`忽略规则是否是本轮有意修改：
   - 若合理，单独提交；
   - 若不是本任务产生，保留并在报告披露；
   - 禁止使用checkout/reset覆盖。
4. 记录8091/8092/8300/8400健康状态。
5. 确认没有训练进程。
6. 记录SQLite integrity和表行数。
7. 记录production bundle。
8. 不触碰受保护未跟踪资产。

# 四、Task 1：修复Cycle逻辑节点重复

当前`training_cycle_node_v1`同时保存事件和状态，却允许同一`cycle_id + node`出现多个不同状态。

不得删除历史记录。

推荐方案：

## 1. 保留历史表

`training_cycle_node_v1`继续作为历史证据，不删除pending/done旧行。

## 2. 新增唯一状态投影

增加：

`training_cycle_node_state_v2`

至少包含：

- cycle_id
- logical_node
- current_status
- latest_event_id
- evidence_json
- version
- updated_at

唯一约束：

`UNIQUE(cycle_id, logical_node)`

## 3. 状态更新

采用事务和乐观版本更新：

pending
→ running
→ done/waiting/failed/stopped

禁止done回退到pending，除非通过显式reopen事件。

## 4. 历史事件

每次状态变化仍追加事件，状态投影只保存当前状态。

## 5. 旧数据回填

对已有重复节点：

- 按合法状态优先级和时间重建投影；
- 已有done证据的节点投影为done；
- 保留所有历史行；
- 生成backfill audit；
- 幂等重跑不新增重复投影。

## 6. Cycle状态

基于19个distinct logical nodes计算：

- 当前应为16/19 done；
- pending应只剩：
  - DemoEvaluation
  - AwaitingIndependentEvaluation
  - AwaitingProductionDecision

Cycle总状态改为：

`MODEL_PILOTS_READY_AWAITING_CANDIDATE_EVALUATION`

不能继续写`TRAINING_CYCLE_ACTIVE`或`FOUR_CANDIDATES_READY`。

# 五、Task 2：修复Taskboard和Blackboard投影

Taskboard当前读取历史Task事件，没有正确收敛状态。

新增或完善：

`task_state_projection_v1`

唯一逻辑键至少包含：

- project/tenant
- cycle_id
- logical_task_key

当前任务必须修正为：

## Done

- 平台事实对账
- Canonical38 Dataset Build
- M1 5 epoch pilot
- M2 5 epoch pilot
- M3长尾E1～E5实验
- KB canonical38建设
- M4 real-candidate QLoRA pilot

## Waiting/Review

- M3 E1/E5独立测试
- M4独立裁决评估
- DemoEvaluation
- micro-gold
- 45 pending SKU裁决
- production决定

不得继续显示：

- 已完成的M1为running；
- 已完成的M3为todo；
- 已完成的KB为running。

Blackboard要追加：

- Cycle重复节点问题；
- 状态投影修复决定；
- E1/E5不能提前判胜；
- M4缺裁决评估；
- 四候选Gate撤销；
- 正确Gate。

旧黑板记录不删除，通过supersedes或Resolution追加修正。

# 六、Task 3：彻底关闭旧250活动投影

旧250任务保留历史证据，但必须：

- 标记`SUPERSEDED_FOR_DEMO_TRAINING`；
- 从active workitems排除；
- 从Overview待办排除；
- 从Supervisor下一步建议排除；
- 从Taskboard活动任务排除；
- 不再显示“待人工审核250”；
- 不再建议“先完成250项审核”。

历史页面仍可查询：

- 原队列；
- superseded原因；
- 时间；
- 替代流程；
- 证据。

当前Overview应显示真正的：

- 当前Cycle；
- M3独立评估；
- M4独立评估；
- M1/M2数据不足；
- pending SKU裁决；
- micro-gold尚未启动。

# 七、Task 4：统一候选状态

建立明确状态定义：

- `SMOKE_ONLY_NOT_CANDIDATE`
- `PILOT_NOT_CANDIDATE`
- `PILOT_PENDING_EVALUATION`
- `CANDIDATE_PENDING_EVALUATION`
- `CANDIDATE_REJECTED`
- `CANDIDATE_ACCEPTED_FOR_SHADOW`
- `PRODUCTION_APPROVED`

修正：

## M1

统一为：

`PILOT_NOT_CANDIDATE`

原因：

- mAP50约7.7%；
- 数据仅894张全场景图；
- 尚无独立业务评估。

训练报告中的`candidate=true`必须纠正为pilot语义，不能与Registry冲突。

## M2

统一为：

`PILOT_NOT_CANDIDATE`

原因：

- mAP50约7.1%；
- pseudo mask interim；
- 无人工mask评估。

## M3 E1

状态：

`PILOT_PENDING_EVALUATION`

## M3 E5

状态：

`PILOT_PENDING_EVALUATION`

在独立测试完成前，两者都不能写最终candidate。

## M4

状态：

`PILOT_PENDING_EVALUATION`

KB recall通过只证明检索器通过，不证明VLM通过。

磁盘报告、Registry、API、Web、Profile必须完全一致。

# 八、Task 5：修复Recognition Profile

Profile必须引用最新Artifact，而不是旧smoke。

至少改为：

## production_legacy

- enabled
- 继续使用当前production

## nextgen_m1_pilot

- 引用`nextgen_detector_pilot_v1`
- disabled
- blocker：`PILOT_NOT_CANDIDATE`

## nextgen_m1_m2_pilot

- 引用：
  - `nextgen_detector_pilot_v1`
  - `nextgen_segmenter_pilot_v1`
- disabled

## canonical38_classifier_e1

- 引用`m3_ablation_e1_v1`
- disabled
- blocker：等待独立测试

## canonical38_classifier_e5

- 引用`m3_ablation_e5_v1`
- disabled
- blocker：等待独立测试

## canonical38_vlm_real_candidate

- 引用`nextgen_vlm_real_candidate_v1`
- disabled
- blocker：等待VLM裁决评估

## canonical38_cascade

引用最新M1/M2/M3/M4，但因M1/M2未成为候选保持disabled。

## research83

继续标记：

`实验，不可商业输出`

## shadow_compare

不得引用未注册的`legacy_detector`占位符。

应引用真实production bundle/artifact；若生产artifact尚未注册，先追加式注册再派生状态。

Profile blocker必须动态来源于Artifact Registry，禁止硬编码旧文本。

# 九、Task 6：M3独立评估设计

当前canonical38的train/val已经被用于训练、调参、选epoch和选择E1/E5，不能再把同一个val当最终独立测试集。

构建：

`canonical38_train_val_test_v2`

要求：

- source photo分组；
- store分组；
- session分组；
- burst分组；
- near-duplicate group分组；
- train/val/test零交叉；
- exact SHA零交叉；
- symlink target零交叉；
- 测试集在训练开始后不可变化；
- builder hash；
- manifest hash；
- split audit；
- 每类测试样本统计。

推荐比例：

- train 70%；
- val 15%；
- test 15%；

以group为单位分配，优先保证每类test有足够样本。

若某类不足，报告真实数量，不通过复制或增强补测试集。

只重新训练：

- E1 CrossEntropy
- E5 hierarchical

不重复E2/E3/E4。

共同条件：

- 同一公开初始化；
- 同一seed；
- 同一训练预算；
- 同一train/val/test；
- 10～15 epoch；
- early stop只看val；
- test只在训练完成后运行一次；
- MPS heavy=1。

独立测试必须报告：

- top1；
- macro precision；
- macro recall；
- macro F1；
- balanced accuracy；
- worst-decile recall；
- head-tail gap；
- per-class precision/recall/F1；
- confusion matrix；
- ECE/calibration；
- coverage@accepted precision；
- latency；
- error ledger。

选择规则：

不能仅按top1选择。

建议综合优先级：

1. accepted precision；
2. macro F1；
3. worst-decile recall；
4. top1；
5. calibration；
6. latency。

若E1和E5各有优劣，保留两个候选并明确适用档位，不强行选一个。

# 十、Task 7：M4真实裁决评估

本轮禁止重新训练M4。

评估以下三个版本：

1. base Qwen3-VL 4B；
2. 旧`nextgen_vlm_cropped_v1` adapter；
3. 新`nextgen_vlm_real_candidate_v1` adapter。

使用独立grouped holdout，禁止使用QLoRA训练样本。

CandidateSet来自真实检索链，函数签名不得接收GT。

评估至少覆盖：

- 38个canonical SKU；
- 每类至少一个样本；
- hard negatives；
- 相似包装；
- 候选中无GT；
- abstain；
- OCR错误；
- 反光/模糊；
- 新包装或unknown。

若数据不足，诚实报告实际覆盖。

必须报告：

- candidate recall@1/5/8；
- VLM top1；
- accepted precision；
- coverage；
- abstain precision；
- false accept；
- false reject；
- registry escape；
- base→旧adapter→新adapter的差值；
- p50/p95；
- tokens/region；
- MPS/MLX内存；
- 错误账本。

至少增加合理数量的abstain/unknown样本。当前2条abstain不能用于结论。

M4只有在新adapter相对base和旧adapter有明确收益时，才能升级为：

`CANDIDATE_PENDING_MICRO_GOLD`

否则保持pilot或标记rejected。

# 十一、Task 8：M1/M2本轮不继续训练

本轮不增加M1/M2 epoch。

只完成：

- 状态统一；
- Profile更新；
- 错误账本整理；
- 数据缺口统计；
- 按场景/尺寸/密度/反光/遮挡统计缺口；
- 建议需要补采的全场景图数量和类型；
- 生成数据采集优先级。

不得因为“需要四候选”而把低mAP pilot强行标成candidate。

# 十二、Task 9：修复测试分层

当前普通suite仍有3个测试依赖真实MPS。

修复原则：

- 业务单元测试使用确定性mock/fake G0 evidence；
- 测试approve、enqueue和idempotency时，不调用真实MPS；
- 不降低生产G0门；
- 不删除G0校验；
- 不用环境变量偷偷绕过生产逻辑。

目标：

## Hermetic

```text
pytest -m "not host_mps"
```

在无MPS沙箱中全绿。

## Host MPS

```text
pytest -m host_mps
```

必须真实显示：

`6 passed`

报告不能再把“6 deselected”写成host测试结果。

# 十三、Task 10：修复Web界面

当前任务板和训练对账面板存在严重低对比度。

修复：

- 浅色卡片使用深色文字；
- 深色背景使用浅色文字；
- 满足基本WCAG AA对比度；
- 表格状态、blocker、证据可读；
- 长blocker支持换行/展开；
- Profile表格不截断关键内容；
- 手机和桌面宽度可使用；
- Drawer不能遮挡全部主界面；
- 当前状态与数据库一致。

Supervisor必须正确回答：

- “目前训练到哪里？”
  → 16/19，剩余3个评估/决策节点；
- “M1是否可以上线？”
  → 不可以，pilot mAP低；
- “M3哪个最好？”
  → E1/E5待独立测试，不提前判定；
- “Qwen是否已经达标？”
  → KB通过，VLM裁决尚未评估；
- “还要做250张吗？”
  → 不需要，旧流程已superseded；
- “可以切换生产模型吗？”
  → 拒绝，需人工且候选门未通过。

# 十四、当前正确Gate

任务开始时Gate：

`MODEL_PILOTS_READY_AWAITING_CANDIDATE_EVALUATION`

如果状态收口、M3独立测试和M4独立评估全部完成，但micro-gold未完成：

`EVALUATED_CANDIDATES_READY_AWAITING_MICRO_GOLD`

只有以下条件全部满足，才允许第二个Gate：

- Cycle只有19个逻辑状态投影；
- 16个done、3个pending/waiting；
- Taskboard无过期状态；
- 旧250不再active；
- M1/M2正确标为非候选；
- M3 E1/E5独立测试完成；
- M4三个版本独立对比完成；
- Profile引用最新Artifact；
- hermetic全绿；
- host MPS 6 passed；
- Web状态一致；
- production未切换。

仍然禁止写：

- FOUR_CANDIDATES_READY
- PROMOTION_READY
- PRODUCTION_READY

除非M1/M2未来真正通过候选门。

# 十五、Loop规则

每个节点执行：

Observe
→ Reproduce
→ Root Cause
→ Red Test
→ Implement
→ Verify
→ Update Projection
→ Record Evidence
→ Checkpoint
→ Decide Next

同一失败最多重试两次。

第三次进入WAITING或FAILED并登记Issue。

不得通过重复插入新状态行掩盖旧状态问题。

# 十六、Git规则

- 继续当前分支；
- 小步TDD commit；
- 不使用`git add .`；
- 不提交模型、原图、SQLite、secret和大型数据；
- 不删除历史证据；
- 不清理受保护未跟踪目录；
- 不merge、push、deploy；
- 不切production；
- 有意的`.gitignore`修改单独提交；
- 最终工作树必须说明所有未提交内容来源。

# 十七、最终报告格式

最终报告必须包含：

1. HEAD、branch、worktree；
2. commit链；
3. 阅读文件；
4. 初始复现；
5. `.gitignore`处理；
6. Cycle重复节点根因；
7. 新状态投影schema；
8. 历史节点保留证据；
9. 19个逻辑节点最终状态；
10. Cycle最终状态；
11. Taskboard修复前后；
12. Blackboard修正事件；
13. 旧250 supersession；
14. Overview当前数字；
15. M1统一状态；
16. M2统一状态；
17. M3 E1统一状态；
18. M3 E5统一状态；
19. M4统一状态；
20. Artifact/DB/API/Web一致性；
21. Profile更新结果；
22. shadow profile修复；
23. canonical38新train/val/test统计；
24. 五键零泄漏证据；
25. M3 E1独立测试；
26. M3 E5独立测试；
27. M3选择结论；
28. M4 base结果；
29. M4旧adapter结果；
30. M4新adapter结果；
31. M4微调收益；
32. M1/M2数据缺口；
33. hermetic测试；
4. host MPS测试；
35. TypeScript/Vite；
36. SQLite integrity；
37. 浏览器验收截图；
38. Supervisor真实问答；
39. 服务健康；
40. production未切换声明；
41. 未关闭问题；
42. 当前Gate；
43. 用户下一步真正需要决定的事项。

完成本轮前，不要求用户执行micro-gold，不要求用户处理旧250，不要求用户立即裁决45个pending SKU。

立即从Task 0开始，先修状态事实源，再做M3/M4独立评估。
