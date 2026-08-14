你现在是 LLM-Image 项目的首席实施 Agent。请在现有项目上一次性完成“SKU 长尾治理、SAM 数据链修正、四模型训练闭环、主管 Agent 与共享黑板底座、统一 Web 工作台”的建设。

本任务不是传统 SaaS 页面堆叠。系统核心必须继续保持：

Graph+Loop 智能化内核
    + 独立领域模块
    + 统一事实源
    + 标准能力接口
    + 特殊 Hook
    + Agent 编排
    + 完整证据链

FMCG 识别只是第一个 Domain Pack，不得继续把平台内核写成只适用于 SKU 识别的专用系统。

本提示词授权你：

1. 修改项目代码、测试和项目文档；
2. 创建新的数据库迁移，但不得破坏、覆盖或删除历史数据；
3. 修复本任务发现的 Bug；
4. 构建新数据集快照；
5. 启动有边界的实验训练和资源 benchmark；
6. 完成 Web、API、Agent、Graph+Loop 的正式接口；
7. 分阶段提交 Git commit。

本提示词不授权你：

- 删除任何原始照片、模型、SQLite、审核记录、旧队列或历史证据；
- 强制停止当前训练/分割进程；
- merge、push、deploy、force-push；
- 自动切换 production bundle；
- 自动发布新模型；
- 把伪标签或训练集指标伪装成人工金标准；
- 让任何 Agent 直接执行任意 Shell、任意 SQL或任意文件路径；
- 修改客户输入型业务数据库；
- 将旧模型作为新模型的 parent、resume、EMA 或 optimizer 继承来源。

所有高风险发布和生产切换仍然必须由真人批准。

# 一、开始前必须完整阅读

先完整阅读以下文件，不得只读摘要：

1. `<ai-workflow-root>/routing/GLOBAL_AGENT_ROUTING.md`
2. `docs/GLOBAL_AGENT_ROUTING.md`（如存在）
3. `docs/CODEX-PROJECT-HANDBOOK.md`
4. `docs/README.md`
5. `docs/implementation/nextgen-four-model-training-loop-v2/` 全部文件
6. `docs/implementation/project-logic-chain-v3/` 全部文件
7. `docs/implementation/platform-v2/` 全部文件
8. `docs/implementation/graph-loop-training-control-v1/` 全部文件
9. `docs/implementation/sam-reannotation/` 全部文件
10. 当前训练、SAM、数据集、Label Studio、SKU Registry、平台 API、Web、Graph、Agent Command Gate 的源码与测试
11. 当前分支最近至少 30 个 commit
12. 当前 Git diff、未跟踪资产、运行进程、服务、数据库迁移、模型和报告

阅读完成后，先创建并持续更新：

`docs/implementation/sku-long-tail-agent-foundation-v1/`

至少包含：

- `README.md`
- `01-CURRENT-STATE-AND-BUG-AUDIT.md`
- `02-SKU-LONG-TAIL-DATA-POLICY.md`
- `03-SAM-AND-FOUR-MODEL-DESIGN.md`
- `04-MULTI-AGENT-BLACKBOARD-MEMORY.md`
- `05-WEB-WORKBENCH-AND-API-CONTRACTS.md`
- `06-EXECUTION-PLAN-AND-GATES.md`
- `AGENT-EXECUTION-PROMPT.md`
- `execution/IMPLEMENTATION-LIST.md`
- `execution/STATUS.md`
- `execution/DECISIONS.md`
- `execution/ISSUES.md`
- `execution/EXECUTION-LOG.md`
- `execution/ACCEPTANCE.md`

将本提示词原样保存为 `AGENT-EXECUTION-PROMPT.md`。

# 二、已知现场信息——必须重新验证，不能直接当成事实

只读检查时观察到：

- 分支：`feat/nextgen-training-cycle-v2`
- HEAD 曾为：`2b5f32603fad4fe9dcda1c84c82f4742addfb0de`
- 工作树存在未提交修改：
  `scripts/train_sam_decoder_nextgen.py`
- 受保护未跟踪资产包括：
  `.datasets_nextgen/`
  `.quality/`
  `.sam_checkpoints/`
  `.sam_runs/`
  `.superpowers/`
  `cropped_images/`
  `adapter_config.json`
  `reports/nextgen_v2/sam_crop_masks.jsonl`
- 观察到两个 SAM 相关进程：
  - `scripts/run_sam_crop_segmentation.py`
  - `scripts/train_sam_decoder_nextgen.py --samples 2000 --epochs 1 --run-name nextgen_sam_decoder_v2`
- `sam_crop_masks.jsonl` 当时已增长到约 17,832 条。
- 当前 83 个 SKU 类约有 20,338 张裁剪图；单类数量约 7～866。
- 约 38 类已映射 Registry，45 类仍处于 `new_class_pending_adjudication`。
- 当前分类器报告 top1 约 83.3%，但切分可能以裁剪图随机切分，没有严格按原始照片、门店、session、近重复组隔离，因此指标可能偏乐观。
- 当前 Qwen pilot 有 loss 下降，但缺独立业务评估，且候选构造可能总是包含 GT，不能证明真实检索链有效。
- 旧模型必须保留并隔离；当前最好生产模型继续作为默认识别模型和 baseline，新训练不得继承旧模型。

重新检查并记录：

- 实际 HEAD、分支、工作树；
- 当前进程 PID、开始时间、命令、CPU、内存、MPS、swap；
- 当前脚本 SHA、Git diff SHA、数据 manifest SHA；
- 运行目录和日志；
- 8091、8092、8300、8400 健康状态；
- SQLite integrity；
- production bundle；
- 当前输出记录数量。

特别注意：运行中的 Python 进程可能是在脚本修改前启动的。若运行目录没有保存启动时源码快照，必须将该次实验标记为 `SOURCE_SNAPSHOT_UNPROVABLE`，不能用最终工作树脚本解释运行结果。

以后每次训练必须把启动时以下内容复制或记录到 run artifact：

- source commit；
- dirty diff hash；
- launcher source hash；
- resolved command；
- environment lock；
- data manifest；
- base model hash；
- config；
-随机种子。

# 三、先保护当前进程，再开始工作

1. 不强制停止当前两个 SAM 进程。
2. 不修改它们正在写入的 run 目录、JSONL 和 checkpoint。
3. 当前进程运行期间，不再启动新的 MPS/MLX heavy job。
4. 可以并行开展只读审计、测试设计、数据库/API/Web 设计和 CPU 轻任务。
5. 当前进程自然完成后，立即验证：
   - exit code；
   - 日志完整性；
   - artifact hash；
   - NaN/Inf；
   - train/val loss；
   - MPS fallback；
   - 内存、swap、服务影响；
   - source snapshot 能否证明。
6. 若触发 OOM、swap 持续恶化、磁盘危险、服务不可用、NaN/Inf，按现有 safe-stop 机制停止；不得直接 kill，除非 safe-stop 失效且有证据。

# 四、必须优先关闭的训练 Bug

所有修复必须红测试先行。

## P0-1：SAM Dice loss 不可导

当前实现使用：

`pred_bin = (p > 0.5).float()`

再以 `pred_bin` 计算 Dice。阈值操作切断梯度，Dice 项不能训练 mask decoder。

必须改成可导 soft Dice，例如基于概率 `p` 和 `gt_t` 计算；二值 Dice 只允许作为 metric。

新增测试至少覆盖：

- 完全一致时 soft Dice 接近 0；
- 完全不相交时接近 1；
- loss 非负；
- 对 logits 反向传播后梯度非零；
- 空 mask 的数值稳定；
- BCE 与 Dice 权重进入 manifest；
- train/val 使用一致几何变换。

当前 `nextgen_sam_decoder_v1/v2` 一律标记为：

`EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE`

不得删除制品，不得发布。

## P0-2：SAM 自蒸馏不等于真实提升

SAM 用自己的伪 mask 训练自己的 decoder，只能证明自一致性，不能证明边界更准确。

必须将 SAM 角色拆开：

- `SAM Teacher`：生成 mask、tight box、context crop 和证据；
- `YOLO-seg Student`：学习 SAM 通过质量门后的伪 mask；
- `SAM Adapter/Decoder Experiment`：只有使用人工 mask gold，或至少独立人工 mask 评估后，才允许成为候选。

演示训练可以继续使用伪 mask，但 evidence level 必须为：

`pseudo_mask_interim`

## P0-3：数据切分泄漏

不得继续用同类裁剪图随机 9:1 切分。

建立统一 `leakage_group_id`，至少综合：

- 原始照片；
- SHA；
- near-duplicate group；
- 门店；
- session；
- 连拍组；
- package version。

同一 group 必须进入同一 split。

若裁剪图无法恢复原始来源，必须：

- fail-closed 排除出正式验证集；
- 或仅用于训练；
- 不能进入独立评估。

重新评估旧分类器，并分别报告：

- 旧随机切分结果；
- 严格 grouped split 结果；
- 差值；
- 泄漏数量。

## P0-4：Qwen 候选泄漏

CandidateSet 构建函数不得接收 GT，也不能保证把 target 塞入候选。

候选必须来自真实链路：

图片/crop
→ OCR/视觉 embedding/属性
→ SKU KB 检索
→ 候选排序
→ Qwen 裁决或 abstain

分别报告：

- candidate recall@1/5/8；
- 候选不含 GT 时的模型行为；
- accepted precision；
- coverage；
- abstain；
- registry escape；
- p95；
- 每次调用成本。

## P0-5：并发训练缺少资源租约

当前两个 SAM 任务同时使用 MPS，必须实测判断是否有收益，不能默认并行越多越好。

实现统一 `ResourceLease`：

- `apple_mps_heavy`
- `apple_mlx_exclusive`
- `cpu_io`
- `service_reserved_memory`

默认规则：

- MPS heavy 并发数 1；
- benchmark 证明组合吞吐提高至少 25%，且资源停止线全部通过后，才允许并发 2；
- 不默认允许 3 个 heavy job；
- Qwen/MLX 永远独占；
- 8091、8300、8400 保留服务资源。

# 五、SKU 长尾治理：不是按数量拆四套孤立模型

生成不可变 `sku_data_readiness_policy_v1`。

不能只统计图片数量，必须同时统计：

- raw crops；
- unique source photos；
- unique SHA；
- unique near-dup groups；
- unique stores；
- unique sessions；
- package versions；
- scene diversity；
- quality diversity；
- target-size diversity；
- occlusion/reflection diversity；
- Registry 状态；
- Label Studio taxonomy 状态。

以有效独立组数量为主要依据，默认分层：

- Tier A / Mature：有效独立组 ≥300，且来源、session、场景和包装版本覆盖达标；
- Tier B / Growing：100～299；
- Tier C / Tail：30～99；
- Tier D / Prototype：<30，或 Registry/包装身份未裁决。

如果一类有 300 张近重复图，不得进入 Tier A。

每个 Tier 的默认策略：

### Tier A

- 正常进入闭集分类；
- 每 epoch 做上限或平方根采样，避免头部类垄断；
- 重点挖掘 hard negative 和新包装漂移。

### Tier B

- 适度过采样；
- 强化但合理的数据增强；
- 按混淆矩阵补 hard negative；
- 建议补数据到 Tier A。

### Tier C

- 优先使用 metric/prototype/retrieval；
- 可进入分类训练，但默认不能高置信自动接受；
- 检索、VLM 或人工兜底；
- 输出明确补数建议。

### Tier D

- 不承诺闭集自动识别；
- 进入新包装/未知商品工作流；
- 可以做 few-shot prototype；
- 不得通过重复增强伪造样本规模；
- 需要业务决定补数、合并、保留或舍弃。

输出：

- 83 类完整统计；
- Tier 分布；
- 每类有效样本量；
- 每类建议：加强、保留观察、专家头、合并候选、舍弃候选；
- 头尾差距；
- 最差十类；
- 混淆商品族；
- 数据采集优先级。

# 六、四种模型的正确拆分

四个正式 Lane 保持：

## M1 Detector

- 目标：单类 `product` 检测；
- 不按 SKU 数量拆模型；
- 重点按目标尺寸、密度、遮挡、反光、场景、拍摄角度分桶；
- 从公开基础权重初始化；
- 旧生产模型只作为同口径 baseline/proposal teacher。

## M2 Segmenter

- 目标：轻量 YOLO-seg student；
- 训练数据来自通过质量门的 SAM mask；
- 不按 SKU 数量拆模型；
- 重点按形状、边界、遮挡、密集相邻、截断、透明/反光包装分桶；
- SAM 保持 teacher/在线精修角色。

## M3 Classifier

采用：

共享视觉主干
→ 商品族/品牌/容器/容量等粗粒度头
→ canonical SKU/package version 细粒度头
→ 混淆商品族 specialist head
→ unknown/abstain

先完成以下对比 pilot：

1. 普通 CrossEntropy baseline；
2. class-balanced/effective-number loss；
3. balanced sampler；
4. logit adjustment 或 focal loss；
5. metric/prototype 辅助目标。

不得一次叠加全部方法。使用相同 split 和预算做消融，按 macro-F1、尾部 recall、校准和 accepted precision 选方案。

只有混淆证据明确的商品族才建立 specialist，例如：

- 同品牌不同口味；
- 同瓶型不同容量；
- 新旧包装；
- 瓶盖颜色差异；
- 高度相似的无糖/含糖版本。

## M4 Qwen3-VL 4B

- 使用本地 Apple MLX/`mlx-vlm`；
- 具体模型 revision、量化格式和训练参数以当前已安装版本真实能力为准；
- 不照抄过期 `--use-mps` 等命令；
- vision tower 初期冻结；
- 使用原图/context crop/mask crop/坐标/候选/OCR；
- CandidateSet 必须来自真实检索；
- 按 SKU Tier 平衡训练 episode；
- 加入真实 hard negatives；
- 支持 unknown/new packaging/abstain；
- 先小 pilot，再决定 full candidate；
- Qwen 训练时独占 heavy resource lease。

# 七、取消旧 250 照片门，但不能取消评估

将旧 `5+5+250` 人工流程标记为：

`SUPERSEDED_FOR_DEMO_TRAINING`

不得删除队列、项目、SQLite 行或历史证据。

旧 250 张照片不再阻塞演示候选训练。

替代方案：

1. 建立小规模 `demo_micro_gold_v1`；
2. 以 region/mask 为单位，而不是任意照片数量；
3. 按 SKU Tier、混淆族、目标尺寸、场景、质量和新包装分层；
4. 建议 120～300 个 region；
5. 可以和训练并行补充，不阻塞 M1～M4 实验训练；
6. 只有需要宣称真实准确率、晋级 shadow 或 production 时，它才成为硬门；
7. 没有完成时，候选状态只能是：
   `DEMO_EXPERIMENTAL_AWAITING_INDEPENDENT_EVALUATION`。

不得宣称“演示可用”等于“生产达标”。

# 八、Label Studio 必须完成可用性复核

全面检查 Label Studio：

- 83 个当前训练类是否全部有 canonical label；
- Registry 中的 208 个 SKU 是否与 taxonomy 双向可追踪；
- 45 个 pending 类是否明确显示 pending/new packaging 状态；
- 自动框是否显示；
- 建议 SKU 名称是否对人工可见；
- assisted 与 blind 是否严格隔离；
- blind 中不得出现 prediction、模型字段或隐藏泄漏；
- 人工修改后能保存；
- 刷新后保持；
- 导出不能把 prediction 当 human truth；
- 新训练 snapshot 能从正式导出入口消费；
- 标签新增/改名/沿用旧名均需 package version 和 alias 版本。

若发现标签未自动生成，必须：

1. 红测试复现；
2. 找到 taxonomy/Registry/LS config/import/export 的断链；
3. 修复自动生成及幂等回填；
4. 不覆盖历史 annotation；
5. 完成真实浏览器 QA；
6. 输出“可见标签数、缺失数、pending 数、越界数”。

# 九、四个 DatasetSnapshot

构建并冻结：

- `detector_snapshot_v3`
- `segmenter_snapshot_v3`
- `classifier_snapshot_v3`
- `vlm_snapshot_v3`

共同要求：

- staging + atomic publish；
- 输出目录存在则拒绝覆盖；
- manifest hash；
- builder hash；
- source lineage；
- quality policy；
- Registry/taxonomy version；
- leakage groups；
- exclusion ledger；
- SKU Tier；
- label source；
- sample weight；
- train/val/test group 零泄漏；
- 任何伪标签不能进入 human frozen eval。

# 十、训练与算力排程

先让当前 SAM 任务自然完成，再做 benchmark。

M1/M2/M3：

1. 每个 Lane 单独运行短 benchmark；
2. 每个 Lane 先做 1 epoch smoke；
3. smoke 通过后做有界 pilot；
4. 使用相同冻结预算比较；
5. 只有 pilot 收敛、无资源停止线、指标有意义时再运行 candidate；
6. 允许测试：
   - Detector + Classifier；
   - Segmenter + Classifier；
7. 只有组合吞吐较顺序预估提升 ≥25% 才保留双并发；
8. 不默认三并发。

M4：

- 等 M1/M2/M3 heavy 任务完成；
- 独占运行；
- 先做 5k～20k 样本、1 epoch pilot；
- 检查过拟合、candidate recall、accepted precision、coverage；
- 再决定是否运行 1～3 epoch candidate；
- 不承诺固定 batch=16 或固定耗时。

停止线：

- MPS/MLX fallback；
- OOM；
- NaN/Inf；
- swap ≥8GB 或持续恶化；
- memory pressure red；
- thermal serious/critical；
- 服务错误；
- 磁盘低于安全余量；
- loss/metric 明显异常；
- 输出目录冲突；
- manifest 漂移。

所有新模型只登记为 candidate，production bundle 不自动切换。

# 十一、主管 Agent 与三个独立 Agent

建立通用 Agent Kernel，不得把名称和数据结构绑定 FMCG。

## 1. Supervisor Agent

职责：

- 接收自然语言目标；
- 查询全局状态；
- 将目标拆成 Graph；
- 调用领域 Agent；
- 汇总证据；
- 展示待办、阻塞、已解决问题；
- 生成命令预览；
- 通过 UIIntent 弹出页面、筛选数据、比较模型、固定卡片。

权限：

- 可自动执行只读及低风险、可逆动作；
- 本提示词明确授权的实验训练可按资源门执行；
- 发布、生产切换、删除、客户数据写入必须人工批准；
- 不得绕过 Domain Service 直接写库。

## 2. ModelOps Agent

管理：

- Label Studio；
- Registry/taxonomy；
- 数据过滤；
- SAM；
- Snapshot；
- 训练计划；
- 资源租约；
- Run；
- 评估；
- Candidate；
- 发布提案。

它可以发起有边界实验训练，但不能自行切 production。

## 3. Data Steward Agent

管理：

- 数据质量；
- 血缘；
- 查询；
- 审计；
- 项目纵向打通；
- 实体横向关联；
- 指标口径；
- 数据保留策略。

默认只读客户业务数据。

数据更正必须通过正式 DataCorrection command、审批和审计，不得任意 SQL。

## 4. Workbench Agent

管理：

- 任务板；
- 黄色笔记抽屉；
- 页面导航；
- 待办；
- 阻塞；
- 已解决；
- 运行状态；
- 命令预览；
- UIIntent。

WorkBench Agent 只能发送前端可验证的结构化 UIIntent：

- `navigate`
- `open_panel`
- `filter`
- `highlight`
- `compare`
- `pin_card`
- `show_evidence`

不得生成和注入任意 HTML/JS。

## 5. 扩展接口

每个未来 Agent 使用 `AgentManifest` 注册：

- agent_id；
- version；
- domain；
- capability scopes；
- command schemas；
- allowed data scopes；
- memory policy；
- UI slots；
- Graph templates；
- risk level；
- approval rules；
- billing unit；
- health endpoint。

# 十二、共享黑板、分级记忆和上下文索引

## Shared Blackboard

黑板不是自由文本垃圾箱，也不是第二套业务数据库。

采用 typed、append-only 事件：

- Question
- Finding
- Decision
- Task
- Blocker
- EvidenceRef
- DataQueryResultRef
- ModelRunRef
- PendingCommand
- Approval
- Resolution
- Note

卡片投影包含：

- tenant/project；
- owner/watchers；
- priority；
- status；
- due date；
- version；
- correlation_id；
- graph_run_id；
- linked entity/resource；
- evidence refs；
- created_by agent/human；
- resolved_by；
- acceptance status。

Agent 只能追加自己的结论、证据和命令提案，不能静默覆盖别的 Agent 或人工结论。

## Memory Hierarchy

- L0：当前推理 scratchpad，不持久化；
- L1：Graph Run checkpoint；
- L2：Project memory；
- L3：Tenant/customer memory，权限过滤；
- L4：Global product/system memory，不包含客户原始业务数据；
- Archive：不可变审计。

每条持久化记忆必须有：

- source；
- evidence；
- scope；
- ACL；
- confidence；
- valid_from/valid_to；
- retention；
- version；
- supersedes；
- entity links。

## Context Index

使用混合检索：

metadata filter
+ entity graph
+ full-text
+ vector retrieval

向量索引只是可重建派生物，不是事实源。

所有上下文必须能追溯到原始实体、数据库查询、文档、模型 run 或人工决定。

# 十三、统一 Web 工作台

在现有 Web Shell 内实现，不新建另一套系统。

所有页面右侧保留一个可展开的黄色“主管笔记”抽屉，跨页面保持上下文。

至少包含：

1. 对话区；
2. 今日待办；
3. Running；
4. Waiting/Blocked；
5. Needs Review；
6. Resolved；
7. 命令预览与批准；
8. 证据引用；
9. 资源状态；
10. 当前 Graph；
11. Agent 健康状态。

任务板采用：

`Todo → Running → Waiting → Review → Done`

只有用户明确验收或满足自动验收契约，才可进入 Done。

借鉴 `dashi-taskboard` 的：

- UI/CLI/Agent 共用 API；
- 乐观版本；
- 实时事件更新；
- 任务关联 thread/branch/run；
- 用户验收后完成。

不得复制：

- 本地无认证模式到商业环境；
- CDP 浏览器注入；
- 绕过正式 API 的自动化。

已有页面继续保留：

- Overview；
- Recognition；
- Annotation；
- Assets；
- Training；
- Cascade；
- Model Runtime；
- New Packaging；
- Status；
- Graph Runs。

但要改造成真实可操作页面，不得只放“预留”卡片。

# 十四、识别 Profile 和 API 一致性

识别页面、批量识别、URL 输入、外部 API、内部 Agent 必须统一使用：

`recognition_profile_id`

Profile 至少包括：

- `production_legacy`
- `nextgen_detector`
- `nextgen_detector_segmenter`
- `nextgen_detector_classifier`
- `nextgen_full_cascade`
- `shadow_compare`

未完成训练的 Profile：

- 可以展示；
- 必须 disabled；
- 显示 blocker；
- 不能退化为任意模型路径选择。

识别结果保存：

- profile/version；
- detector artifact；
- segmenter artifact；
- classifier artifact；
- VLM adapter；
- policy；
- confidence；
- abstain；
- evidence；
- latency；
- resource usage；
- billable units。

Web、API、Agent 必须调用同一 Domain Service，禁止各自复制业务逻辑。

# 十五、测试、QA 和安全

至少完成：

- unit；
- contract；
- integration；
- SQLite migration/integrity；
- Graph resume/idempotency；
- Agent capability/RBAC；
- blackboard append-only；
- memory ACL；
- Label Studio真实 payload；
- grouped split leakage；
- SAM loss gradient；
- Snapshot builder；
- resource lease；
- safe-stop；
- recovery；
- recognition profile；
- TypeScript；
- Vite build；
- browser E2E；
- Apple MPS/MLX host test；
- API/Web/Agent 三方一致性。

浏览器验收至少覆盖：

- 和主管 Agent 对话；
- 主管 Agent 打开训练页面；
- 展示当前运行；
- 展示 SKU 长尾卡片；
- 打开某个尾部 SKU 证据；
- 创建训练提案；
- 显示资源阻塞；
- 审批低风险命令；
- 拒绝未授权发布；
- 模型选择；
- Label Studio标签可见；
- 任务从 Running 到 Review；
- 用户验收后进入 Done。

# 十六、Git 与制品规则

- 使用当前功能分支，不擅自切换或合并；
- 小步 commit；
- 红测试 commit 和修复 commit 可追踪；
- 不使用 `git add .`；
- 不提交模型、原图、SQLite、secret、大型生成数据；
- 不触碰、删除、清理 `.superpowers/`；
- 不覆盖已有 run；
- 每次重试创建新 attempt/run 目录；
- 旧模型登记为 `legacy_baseline`；
- 当前最好生产模型保持默认；
- 新模型不得继承旧模型训练状态。

# 十七、Graph+Loop 状态

本任务使用持久化状态：

- `AUDIT_VERIFIED`
- `ACTIVE_RUNS_PROTECTED`
- `CRITICAL_TRAINING_BUGS_FIXED`
- `SKU_DATA_TIERED`
- `LABEL_STUDIO_VERIFIED`
- `SAM_DATA_PIPELINE_READY`
- `FOUR_SNAPSHOTS_READY`
- `RESOURCE_PLAN_READY`
- `M1_M2_M3_EXPERIMENTS_RUNNING`
- `M1_M2_M3_CANDIDATES_READY`
- `M4_EXCLUSIVE_RUNNING`
- `FOUR_DEMO_CANDIDATES_READY`
- `AGENT_KERNEL_READY`
- `BLACKBOARD_MEMORY_READY`
- `WEB_WORKBENCH_READY`
- `DEMO_ACCEPTANCE_READY`
- `AWAITING_INDEPENDENT_EVALUATION`
- `AWAITING_PRODUCTION_DECISION`
- `COMPLETED_NO_PROMOTION`
- `FAILED`

每个节点必须执行：

Observe
→ Validate Contract
→ Plan
→ Acquire Lease
→ Execute
→ Verify
→ Record Event
→ Checkpoint
→ Decide Next/Retry/Wait/Stop

同一错误最多重试两次。第三次必须登记 Issue 并进入 WAITING 或 FAILED，不得无限循环。

训练、测试、Web 和文档可在无资源冲突时并行推进，但状态事实源必须唯一。

# 十八、完成定义

只有以下全部成立，才可以写：

`SKU_LONG_TAIL_AGENT_FOUNDATION_V1_COMPLETE`

- 当前 SAM 进程已安全对账；
- SAM loss Bug 有回归测试；
- 83 类长尾分层完成；
- grouped split 完成；
- Label Studio标签真实可见；
- 四个 Snapshot 有 hash；
- M1～M4 均至少产生真实实验 artifact，或明确报告某 Lane 的客观阻断；
- 所有模型证据等级诚实；
- 主管、ModelOps、Data Steward、Workbench Agent 可独立注册和调用；
- Shared Blackboard 可用；
- 分级记忆和 Context Index 可用；
- 黄色主管抽屉可用；
- Recognition Profile 可选；
- Web/API/Agent 三方一致；
- 全量测试和浏览器 QA 有证据；
- production 未自动切换；
- 项目手册已更新。

如果缺少独立人工真值，最终状态必须是：

`FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_EVALUATION`

不能写 `PROMOTION_READY`。

# 十九、最终报告格式

最终一次性汇报，必须包含：

1. Git HEAD、分支、工作树；
2. commit 链；
3. 完整阅读文件清单；
4. 初始进程和服务状态；
5. 当前 SAM 两个进程最终对账；
6. 发现的 P0/P1/P2 Bug；
7. 每个 Bug 的复现、根因、修复、测试和证据；
8. 83 类 raw count/effective count/Tier 分布；
9. 最强类、最弱类、最差十类；
10. 建议加强、专家头、检索兜底、舍弃候选清单；
11. grouped split 泄漏修复前后结果；
12. Label Studio可见标签统计；
13. Registry/pending/new packaging 统计；
14. 四个 DatasetSnapshot 名称、数量、hash；
15. SAM mask 数量、接受/拒绝/不确定分布；
16. SAM decoder v1/v2 的有效性判断；
17. M1训练命令、耗时、曲线、指标、artifact；
18. M2训练命令、耗时、曲线、指标、artifact；
19. M3训练命令、耗时、曲线、宏平均和分 Tier 指标；
20. M4训练命令、耗时、曲线、真实 candidate 指标；
21. 单任务和组合资源 benchmark；
22. 最终并发策略；
23. Supervisor Agent 状态；
24. ModelOps Agent 状态；
25. Data Steward Agent 状态；
26. Workbench Agent 状态；
27. Shared Blackboard 和 Memory 状态；
28. Web页面和浏览器截图路径；
29. API/Web/Agent 一致性结果；
30. 测试总数；
31. SQLite integrity；
32. 服务健康；
33. production bundle 未切换声明；
34. 未关闭问题；
35. 当前 Gate；
36. 用户下一步只需做的决定。

不要只报告“完成”。每项必须给文件、API、数据库行、artifact、截图、hash 或测试证据。

# 二十、执行要求

立即开始，但先完成 Task 0 现场保护和事实核对。

不要因为旧 250 照片流程而停止整个项目，也不要因此取消所有评估。

不要重复以前已经正确完成的代码；先核验证据，只修断链和缺口。

不要每完成一点就向用户索要下一次提示词。使用持久化 Loop、IMPLEMENTATION-LIST、STATUS、DECISIONS、ISSUES、EXECUTION-LOG 自主推进。

只有遇到以下情况才暂停询问用户：

- 需要删除或覆盖数据；
- 需要切换 production；
- 需要 merge/push/deploy；
- 需要修改客户输入数据；
- 需要额外购买或下载重大外部资源；
- 两种业务口径会造成不可逆分叉。

任务结束时更新：

- 本任务新文档目录；
- `docs/README.md`；
- `docs/CODEX-PROJECT-HANDBOOK.md`；
- 相关旧执行手册的状态和 superseded 关系。

最终只提交一份完整交付报告，不把未经验证的训练 loss、伪标签自一致性或演示效果写成生产准确率。