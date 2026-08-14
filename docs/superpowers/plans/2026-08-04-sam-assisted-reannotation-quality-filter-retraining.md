# SAM-Assisted SKU Reannotation, Quality Filtering and Retraining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不污染冻结协议集、不覆盖任何历史资产、不自动发布生产模型的前提下，建立“坐标点 + SAM 2.1 + 人工双审”的 SKU 真实框生产线，升级照片质量分流与证据链，并在真实框门禁通过后执行新的 class-agnostic product detector 小规模训练和严格评估。

**Architecture:** SAM 作为可替换的本地辅助标注 Worker，通过稳定契约接入现有 Label Studio/ML Backend，而不是写进训练脚本或成为事实库。坐标点负责实例提示，邻近坐标负责负提示，SAM mask 只作为 prediction；人工最终框、审核记录、质量判定、数据集版本、训练运行和评估结果全部追加保存并可追溯。照片质量采用 `accept / warn / manual_review / reject` 四级分流，原图永远保留，只有完成审核的真实框数据才能进入新训练集。

**Tech Stack:** Apple M3 Max、arm64 Python、PyTorch MPS、SAM 2.1 Hiera Small/Base+、Label Studio、OpenCV、Pydantic/dataclass 契约、Ultralytics YOLO、pytest、内容哈希与不可变实验目录。

---

## 可直接交给执行 Agent 的提示词

你现在负责 `<legacy-workspace>` 项目的“坐标点 + SAM 辅助真实框、照片质量过滤增强和 detector 重训”专项。你已获得在该专项范围内修改项目代码、测试、配置和文档，以及在门禁通过后执行小规模训练的授权。

你的职责不是尽快跑出一个新 `best.pt`，而是建立一条可信、可复核、可重复、适合 Apple Silicon 的标注—过滤—数据集—评估—训练闭环。任何人工审核、数据完整性或指标门禁没有通过时，都必须停止在对应 Gate，不得用自动结果冒充人工金标准，不得为了“完成训练”放宽预先约定的门槛。

### 一、全局硬约束

1. 不删除任何文件，包括原始照片、坏图、失败制品、旧数据集、旧 checkpoint、日志、缓存证据和归档目录。
2. 不覆盖任何现有 `.datasets/*`、`.models/*`、`.eval/*`、`.data_protocol/*` 或生产 bundle；全部使用新的唯一版本目录。
3. 不修改、切换或发布当前生产 bundle `prod_20260804_v4_r2`。新模型只允许处于 research/candidate 状态，生产切换必须另行取得用户明确批准。
4. 不恢复 sku_v6 lineage，不从任何 v6 checkpoint 续训。
5. `diagnostic_v1` 只允许诊断和评估，严禁用于训练、微调、阈值学习或 hard-negative mining。
6. SAM 输出只能作为 Label Studio prediction，不能直接写成最终 annotation；`diagnostic_v1` 的最终框必须由人工标注者确认并由第二人审核。
7. 不设置 `PYTORCH_ENABLE_MPS_FALLBACK=1`，不允许静默 CPU fallback。MPS 不可用或出现不支持算子时，立即停止大批量处理并记录证据。
8. 不污染项目主 Python 环境。SAM 依赖优先使用隔离环境或隔离 Worker；不得为了安装 SAM 无审计地升级/降级现有 torch、torchvision 或 Ultralytics。
9. 不提交模型 checkpoint、训练数据、原图、SAM mask 大制品和日志到 Git；只提交源代码、测试、配置、协议和 Markdown 报告。
10. 不 force-push、不 merge、不 deploy。使用独立 feature branch/worktree，提交保持小而可审查。
11. 所有原始输入和算法输出都要保留内容哈希。任何变换图只能作为 derived asset，必须能反向追溯原图。
12. “加强过滤”不等于只保留完美照片。可识别但困难的反光、斜拍、遮挡、小目标照片应保留为带标签的 hard-valid 样本；只有不可恢复数据才进入 `reject`。

### 二、开始前必须完整阅读

在修改任何代码前，逐个完整阅读以下文件，并把已读清单、关键约束和冲突写入专项状态文档：

- `AGENTS.md`（若存在）以及全局工作流路由文件；
- `docs/CODEX-PROJECT-HANDBOOK.md`；
- `docs/training-history-and-decisions.md`；
- `docs/experiments/E2-detector-pilot.md`；
- `docs/experiments/E0-strict-iou-baseline.md`；
- `docs/superpowers/plans/2026-08-04-final-training-execution-gate.md`；
- `docs/superpowers/plans/2026-08-04-model-training-next-phase.md`；
- `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md` 中数据质量、证据链、Label Studio、审核和模型治理章节；
- `.data_protocol/diagnostic_v1.json`、`.data_protocol/dev_v2.json`；
- `.datasets/e2_product_pilot_v1/build_audit.json`；
- `src/data/quality_gate.py`、`src/data/clean_batch3.py`；
- `src/data/protocol_guard.py`、`src/data/protocol_sets.py`；
- `src/training/build_dataset_v7.py`、`src/training/train_v1.py`；
- `src/eval/e2_detector_eval.py`、`src/eval/e0_strict_iou.py`；
- `src/ls_ml_backend/yolo_backend.py`；
- `src/ls_platform/importer.py`、`exporter.py`、`orchestrator.py`、`webhook.py`；
- `configs/label-studio/label_config.xml`；
- 现有全部 tests。

同时核对 Meta 官方 SAM 2 仓库和模型许可证，记录模型来源、版本、checkpoint URL、SHA256、许可证和依赖版本。SAM 3 当前官方要求 CUDA，不作为本机主实现。

### 三、先建立工作清单和日志

在专项目录中创建并持续更新以下文档；如果项目已有等价约定，沿用现有目录，但不得省略这些信息：

- `docs/implementation/sam-reannotation/STATUS.md`：当前阶段、Gate、完成比例、阻断项；
- `docs/implementation/sam-reannotation/PLAN.md`：按 TDD 拆分的文件级任务；
- `docs/implementation/sam-reannotation/DECISIONS.md`：模型、阈值、数据口径和架构决定；
- `docs/implementation/sam-reannotation/EXECUTION-LOG.md`：命令、开始/结束时间、退出码、耗时、MPS/内存和制品路径；
- `docs/implementation/sam-reannotation/ISSUES.md`：问题、严重性、证据、状态、修复 commit；
- `docs/implementation/sam-reannotation/RESULTS.md`：最终指标、结论和下一步。

先执行并记录：

```bash
git status --short
git rev-parse HEAD
git branch -vv
python3 -m pytest -p no:cacheprovider -q
python3 -m src.models.bundle verify --bundle-id prod_20260804_v4_r2
```

预期基线为 74 tests passed、生产 bundle 16 文件校验通过；如果不同，先调查并在 `ISSUES.md` 说明，不得把未知回归带入新实现。保留现有未跟踪的 `.superpowers/`，不得清理。

使用 Superpowers brainstorming/writing-plans 完成实现设计，使用 worktree 隔离，按 TDD 执行。每个任务必须遵循：写失败测试 → 运行确认失败 → 最小实现 → 测试通过 → 全量回归 → 小提交。

### 四、目标模块边界

先在 `PLAN.md` 锁定确切文件结构。推荐的责任边界如下，可根据现有项目风格微调文件名，但不得把所有逻辑塞进 `yolo_backend.py` 或 `quality_gate.py`：

```text
src/sam_assist/
  contracts.py       输入、候选、证据和审核状态契约
  runtime.py         SAM 2.1 隔离加载、设备门禁、embedding 缓存
  prompts.py         坐标、粗框、邻近负点和 ROI 构造
  candidates.py      multimask 候选生成和硬约束筛选
  scoring.py         候选质量评分与拒绝原因
  evidence.py        内容哈希、mask/overlay/JSON 证据追加保存
  service.py         本机 Worker API/CLI，不持有业务事实

src/data_quality/
  contracts.py       四级质量结果与指标契约
  analyzers.py       可插拔的清晰度、曝光、反光、翻拍、透视等分析器
  policy.py          版本化阈值与四级分流规则
  evidence.py        原图/派生图/指标/算法版本证据
  runner.py          批处理、断点续传、原子写和报告

src/ls_ml_backend/
  sam_backend.py     SAM prediction 与 Label Studio 的适配层

tests/unit/
  test_sam_prompts.py
  test_sam_candidates.py
  test_sam_evidence.py
  test_quality_policy.py

tests/contract/
  test_sam_prediction_contract.py
  test_annotation_provenance.py
  test_quality_evidence_contract.py
  test_truebox_dataset_guard.py
```

SAM Worker 必须可以将来替换为 CUDA/远程实现，主系统只依赖版本化 JSON 契约，不直接 import SAM 内部类型。

### 五、SAM 2.1 本机准入与性能 Gate S0

候选只比较：

- `sam2.1_hiera_small`；
- `sam2.1_hiera_base_plus`。

不得先下载或运行 Large；Small/Base+ 不能达到目标后，先报告原因和收益上限，再决定是否扩大模型。SAM 3/3.1 不进入本机实现，因为官方依赖 CUDA。

SAM 运行环境必须输出：

- Python、torch、torchvision、SAM commit/version；
- `platform.machine()`；
- `torch.backends.mps.is_built()`、`is_available()`；
- 模型 checkpoint 完整 SHA256；
- 实际 tensor/model device；
- 单图 image encoder 时间；
- 单 prompt decoder 时间；
- 每图总时间；
- peak RSS、MPS allocated memory、swap 前后；
- 是否出现不支持算子、CPU fallback、NaN/Inf。

先做 5 张 smoke，再做 50 张/约 1,000 坐标点 benchmark。每张图片只计算一次 image embedding，图片内所有坐标共享 embedding。若发现 MPS 不可用、静默 CPU、内存持续增长、结果非确定性严重或比 CPU 还慢，停止批量任务，保留报告，不得强行执行全量。

Gate S0：选择满足质量要求的最小模型，而不是默认选择最大模型。Small 达标就优先 Small；只有 Base+ 的质量收益达到实际标注效率门槛才选择 Base+。

### 六、坐标点 + SAM 候选生成规则

每个商品实例至少提供：`asset_id/photo_id`、原图 SHA256、宽高、`instance_id`、原始 `(x,y)`、SKU 原始名称、规范名称（可空）、邻近实例列表、质量版本。

对每个坐标点：

1. 当前点作为 positive prompt。
2. 同一 ROI 内最近的其他商品坐标自动作为 negative prompts。
3. 使用现有 `sku_box_frac` 仅生成扩大的粗 ROI/box prompt，不能再把它当最终框；默认扩张比例必须通过配置和测试管理。
4. 对没有注册 SKU 或新包装，使用通用 product ROI，不得丢弃。
5. 输出 multimask 候选，至少保留候选分数、mask、mask bbox、面积、质心、稳定性和拒绝原因。
6. 候选硬约束：必须包含当前 positive point；不得包含其他实例点；面积和长宽比不得越过经校准的物理范围；异常多连通域、触碰 ROI 边界、跨货架线和与已选实例大面积重叠必须降级人工。
7. 如果候选只包含 Logo、瓶盖、价签或局部标签，必须能够由人工追加正点/负点或改框，不得自动接受。
8. mask 转出的 `visible_tight_box` 与面向 classifier 的 `context_box` 分开保存；后者只是派生框，不得覆盖真实框。
9. 任何无合格候选的实例输出 `manual_required`，不能回退到固定比例框并伪装成真实框。
10. 坐标点不足以发现“原标注漏掉的可见商品”。必须把现有 P1 proposal、SAM automatic candidates 或人工巡检结果作为 completeness queue，所有可见注册商品、未注册商品和新包装商品都要成为 `product` 框；未锚定候选必须由人工决定 `missing_product / background / price_tag / shelf / poster / reflection`。

### 七、Label Studio 与审核工作流

SAM 结果只以 prediction 导入 Label Studio，不得自动创建最终 annotation。至少支持以下状态：

```text
auto_proposed
annotator_accepted
annotator_corrected
annotator_manual
reviewer_accepted
reviewer_rejected
adjudicated
```

必须保留：

- 原图 SHA和 source URI；
- 原始坐标点；
- positive/negative/box prompts；
- SAM 模型 ID、checkpoint SHA、代码 commit、参数；
- 全部候选 mask 与得分；
- 自动选择原因与规则版本；
- 自动框；
- 标注者修改前后 diff；
- 标注者、审核者、仲裁者、时间和理由；
- 最终框版本和导出 hash。

`diagnostic_v1` 前 200 张必须双人审核；500 张全部完成前不得做正式模型选择。随机抽取至少 50 张作为 blind-manual 对照：第一标注者在看不到 SAM 结果的情况下独立画框，用于估计 SAM anchoring bias 和真实提效，不能全部依赖“看着 SAM 改”。

人工未完成时，Agent 必须把任务链接、完成量、待审核量和阻断原因写入 `STATUS.md`，状态设为 `awaiting_human_review`，不得伪造审核结果并继续训练。

### 八、照片质量过滤增强

现有 `src/data/quality_gate.py` 只有全图 Laplacian、HSV 高光比例和 FFT 摩尔纹，且说明只用 40 张好图校准；不能直接作为新训练集的最终过滤事实。实现兼容旧入口的新版质量能力，至少覆盖：

1. 文件可读性、像素数、长宽比、EXIF 方向和解码一致性；
2. 全图与坐标 ROI 的多尺度模糊，区分“背景模糊但商品可读”和“商品主体不可读”；
3. 过曝、欠曝、动态范围、局部高光和商品 ROI 反光遮挡比例；
4. 严重斜拍/透视：货架线方向、消失点或矩形透视，输出 `recoverable` 与 `unrecoverable`，不因单一角度阈值直接删除；
5. 翻拍/屏幕：摩尔纹、屏幕边框、像素栅格、二次压缩和反射的组合证据；单项弱信号只能进入 warn/manual_review；
6. 大头照/无关场景：只检测构图和 face-dominant 比例，不做人脸身份比对、不保存人脸 embedding；模型不可用时输出 unknown，不得默认 reject；
7. 商品/货架覆盖、拍摄过近/过远、严重裁切、遮挡和重复/近重复照片；
8. 派生透视纠正图必须保留 homography 和坐标映射；映射未验证前，不得用派生图训练。

统一输出四级：

- `accept`：可直接进入标注候选池；
- `warn`：困难但有效，带质量标签进入训练抽样；
- `manual_review`：规则冲突或可恢复性不确定，由人工判断；
- `reject`：不可读、严重无关或无法恢复，只从训练 manifest 排除，原图仍保留。

禁止把 reject 图片移动成只有 JPEG 转码副本而丢失原始字节。原始 blob 必须内容寻址保存；overlay、缩略图、纠偏图都是 derived asset。质量结果必须包含算法版本、阈值版本、原始指标、触发规则、最终人工决定和 source SHA。

建立独立的质量校准/验证集，不得用 `diagnostic_v1` 调质量阈值。人工分层标记 accept/warn/manual/reject，输出每类混淆矩阵、reject precision、valid-photo false reject rate及按模糊/反光/翻拍/斜拍/大头照的召回。禁止继续只凭 40 张好图固定阈值。

质量 Gate Q0：不可恢复坏图的 reject precision 要优先，避免误删有效难例；任何照片只因单一弱指标触发时不得自动 reject。训练集必须报告各质量档比例，防止把真实业务难图全部清掉后得到虚高离线指标。

### 九、SAM 标注质量 Gate S1

先使用 50 张/约 1,000 个实例对 Small 与 Base+ 做人工对照，报告：

- Box IoU 分布和 IoU≥0.50/0.75/0.90比例；
- mask 只分割局部、跨多个商品、漏掉透明/反光区域、跨货架的比例；
- 无需修改、一次修改、完全重画比例；
- 纯手工与 SAM 辅助的每实例/每图时间；
- 按小目标、密集度、反光、遮挡、斜拍、新包装分桶；
- MPS吞吐和资源。

建议准入线：

- 标注总耗时下降至少 40%；
- IoU≥0.75候选比例至少 90%；
- 相邻商品错误合并率低于 5%；
- 人工审核后的严重错框/漏框率低于 0.5%；
- 无 MPS fallback、内存泄漏和不可复现实验。

未达到时，不得批量重标 2,300 张或训练。先根据错误账本调整 prompt/ROI/negative-point/候选选择；每次只改一个变量并重跑固定 50 张回归集。

### 十、真实框诊断，禁止训练

SAM pipeline 通过 S1 后：

1. 为 `diagnostic_v1` 前 200 张生成候选并完成人工双审；
2. 再完成全部 500 张；
3. 所有可见商品都要有 tight visible box，注册、未注册和新包装一视同仁；
4. 产出不可变真实框版本，例如 `diagnostic_v1_truebox_v1`，但不得修改原 `.data_protocol/diagnostic_v1.json`；通过引用或新伴随 manifest 连接；
5. 原始点框、SAM 候选、人工最终框并存。

使用同一真实框重新评估：

- E0 `prod_20260804_v4_r2` detector；
- P0 `.models/e2_p0_coco_s42/weights/best.pt`；
- P1 `.models/e2_p1_v4_s42/weights/best.pt`。

评估必须统一 one-to-one matching，报告 IoU=0.50/0.75、recall@FP/image=1/3/5、precision、proposal数、重复框、坏定位、背景误检、尺寸/密度/质量/场景分桶、p50/p95 latency和峰值内存。保存逐实例错误账本：

```text
missed_detection
duplicate_detection
bad_localization
merged_products
partial_product
background_shelf_edge
price_tag_or_poster
reflection_false_positive
annotation_error
taxonomy_conflict
```

不要把 E2 detector 的 confidence-greedy matching 与 E0 cascade 的 IoU-pair matching 混成同一指标。所有晋级比较必须用同一个 evaluator、同一 GT、同一配置。

### 十一、建立新的真实框训练数据集

只有 diagnostic 真实框评估和错误账本完成后，才建立训练数据。严禁把 diagnostic 的任何图片或框加入训练。

优先对 `.datasets/e2_product_pilot_v1` 的原 2,000 train + 300 val 同图同 split 进行 SAM 辅助重标，形成新的唯一数据集：

```text
.datasets/e3_product_truebox_pilot_v1/
```

如果目录已存在，必须换新的版本名，绝不覆盖。这样 E2 与 E3 只改变标签质量，最大限度保持 A/B 可解释性。

要求：

- 每张图所有可见 product 完整标注，不能只标已有坐标点；
- 注册、未注册、新包装统一为单类 `product`；
- train/val 保持原门店与 session 隔离，并再次执行五键 protocol guard；
- 每个框引用 final human annotation，不允许使用未审核 prediction；
- 质量 `accept/warn` 标签进入 manifest，`manual_review` 必须有最终人工裁决，`reject` 只排除且保留证据；
- 新 dataset build audit 记录源图片、旧点框、新真实框、审核完成率、质量分布、Git commit、builder hash、SAM checkpoint hash、label manifest hash和排除报告；
- staging + 原子发布 + fail-closed；
- 训练前逐文件内容哈希和 image/label 一一对应检查；
- 不得用符号链接目标缺失、空 val、损坏图、空标注或 class 越界数据训练。

Gate D0：2,300 张审核完成率 100%，严重错框/漏标抽检 <0.5%，五键泄漏为 0，train/val 门店与 session 交集为 0，manifest 可重复构建，质量档分布已披露。

### 十二、重训顺序和硬停止条件

训练前重新执行 G0：arm64、MPS built/available、1024²矩阵乘、AC 电源、高性能模式、磁盘、内存和 swap 记录。不得在 MPS 失败时自动改成 CPU。

第一轮只做 label-quality A/B，不同时改变模型、图像尺寸、增强、NMS和数据量。使用：

- 初始化：`best/sku_v4_best.pt`；
- 数据：`.datasets/e3_product_truebox_pilot_v1/data.yaml`；
- 单类 `product`；
- seed=42；
- epochs=3；
- imgsz=960；
- batch=4；
- device=mps；
- lr0=0.0005；
- cls=0.2；
- optimizer=AdamW；
- patience=3；
- close_mosaic=1；
- cos_lr；
- 唯一 run name，例如 `e3_p1_truebox_s42`，存在即拒绝运行。

训练命令必须通过当前 `src.training.train_v1` 的显式 data-dir、dataset hash和 run 防覆盖门禁。日志用 `caffeinate -dimsu` 包裹并保存。运行中记录每 epoch 耗时、MPS memory、RSS、swap、loss、NaN/Inf和是否 CPU fallback。

立即停止条件：

- 数据 guard 非零或审核不完整；
- MPS 不可用/CPU fallback；
- NaN/Inf；
- 内存持续增长或 swap 明显恶化；
- run 目录冲突、hash 不一致或数据文件改变；
- 前置 benchmark 不达标；
- 训练中发现 annotation completeness 系统性错误。

3 epoch 后，必须在真实框 diagnostic 和真实框 val 上用相同 evaluator 比较 E0、E2-P1和E3：

- 若 E3 在 diagnostic `recall@FP3` 相对 E0提升至少 10pp，FP/image不高于基线1.2倍，且小目标/密集货架同步改善，才允许进入单 seed 10 epoch D1；
- 若提升 3～10pp，停止长训，先按错误账本做 hard-negative、漏标补全或局部 prompt修复，不得直接堆 epoch；
- 若提升 <3pp，停止同数据续训，转向纯推理 960/1280/tiling/NMS 单变量消融；
- 如果 1280/tiling 的 recall增益 <2pp或延迟/内存劣化 >20%，停止该路线；
- classifier 训练仍不得开始，直到 detector 候选稳定且真实框 oracle完成。

即使 D1 达标，也只生成 research candidate 和不可变权重快照，不创建生产 bundle，不通知8091 reload，不切 production。

### 十三、hard-negative 与新包装处理

错误账本中以下内容必须形成可复用的负样本/审核类别：价签、货架边缘、促销牌、海报商品图、冰柜反射、屏幕翻拍、员工大头照、箱体图案、透明瓶反光、多个商品合并框。

但注意：未注册商品、新包装、客户未建档 SKU 仍然是 `product` 正样本，不能当背景 hard negative。SKU 名称变化属于 taxonomy/catalog 层，SAM/detector 只解决几何定位；最终框必须保存包装版本和 `known/unknown/new_package` 状态接口。

### 十四、测试与验收

至少覆盖：

- 点坐标缩放、EXIF旋转和百分比/像素转换；
- 正点必须落在 mask 内；
- 邻近负点不得被 mask 包含；
- 多候选确定性排序；
- 没有合格候选时 fail-closed；
- 原始 mask、自动框和人工框不可覆盖；
- source SHA、model SHA、run ID和review chain完整；
- quality四级策略和弱信号不得单项 reject；
- 原图保留，derived asset映射正确；
- diagnostic不能进入训练；
- active protocol五键泄漏检测；
- 未完成人工审核的数据集拒绝构建；
- 数据集/运行目录存在即拒绝覆盖；
- MPS门禁和禁止fallback；
- Label Studio prediction/annotation ID分离；
- 导入导出 round-trip；
- 原74项测试无回归。

每一阶段完成后运行目标测试和全量测试；记录命令和退出码。对于 Web/Label Studio 流程，先用 report-only/browser QA验证，不自动修改生产数据。

### 十五、Git 与提交顺序

建议小提交顺序：

1. `docs: add SAM reannotation execution records`
2. `test: define SAM prompt and evidence contracts`
3. `feat: add isolated SAM 2.1 assist worker`
4. `test: define four-tier photo quality policy`
5. `feat: add evidence-preserving quality pipeline`
6. `feat: connect SAM predictions to Label Studio review`
7. `feat: add true-box dataset builder and guards`
8. `feat(eval): add true-box detector evaluation and error ledger`
9. `docs: record SAM benchmark and annotation gate results`
10. 训练和评估制品不提交，只提交报告与哈希引用。

不得为了凑提交顺序制造空提交；每个 commit 必须测试通过且职责单一。

### 十六、最终交付格式

最终报告必须明确区分：

1. 已实现并通过测试的功能；
2. 已完成的 SAM benchmark；
3. 人工标注/审核的真实完成量；
4. 尚在等待人工的任务与链接；
5. 照片质量过滤各档数量和误杀率；
6. diagnostic 真实框上的 E0/P0/P1/E3 指标；
7. 训练是否实际启动、命令、耗时、MPS和制品路径；
8. 各 Gate 的 PASS/FAIL证据；
9. Git commit列表和工作树状态；
10. 为什么晋级或为什么停止；
11. 生产 bundle仍为 `prod_20260804_v4_r2` 的校验证据。

不要只报告 Ultralytics mAP；主判断必须是人工真实框上的 recall@固定FP、业务FP、错误账本、标注效率和系统性能。不要在没有人工完成量、内容哈希、真实框评估和MPS证据时声称“方案已完成”。

现在开始：先完整阅读、建立清单和日志、基线验证、设计评审；随后按 TDD 实现。只有 Gate S0 → S1 → Q0 → diagnostic人工双审 → D0依次通过后，才自动启动3 epoch E3 pilot；10 epoch D1必须满足预先约定的真实框指标，生产发布始终需要用户另行批准。
