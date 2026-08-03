# Model Training Next Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **2026-08-04 最终复核状态：** 本计划保留训练方法论和任务分解，但其中部分“待冻结”描述已被后续执行改变。当前准入结论、Apple M3 Max/MPS 规范、协议泄漏审计、E0 指标纠偏和最终实验顺序，以 [`2026-08-04-final-training-execution-gate.md`](./2026-08-04-final-training-execution-gate.md) 为唯一执行入口。当前禁止续跑旧 v6 checkpoint，也禁止立即开始全量训练。

**Goal:** 基于现有真实数据和失败证据，重建可信评估基线，定位级联系统的检测、裁剪、分类和拒识损失，并以最少、可证伪的实验决定后续数据建设、算法路线与模型发布。

**Architecture:** 保留“检测器提出商品框 + 分类器识别 SKU + 拒识/人工复核”的级联主线，但把训练流程拆成四个可独立测量的阶段：检测 oracle、分类 oracle、预测框分类、完整级联。数据按门店、采集会话、内容 SHA 和相似门店名称隔离；gold-v2 在任何后续训练前冻结；每个实验绑定 Git commit、数据哈希、registry 顺序、seed 和 bundle manifest。

**Tech Stack:** Ultralytics YOLO、PyTorch/torchvision、ResNet/EfficientNet、DVC/内容哈希数据版本、one-to-one IoU 评估、校准与 risk-coverage 分析、pytest、immutable model bundle。

---

## 0. 本手册的执行边界

本文件是后续训练实施方案。本次审查不执行数据重建、标注、训练、进程重启、模型发布或任何代码修改。

当前结论来自只读复核：

- 当前生产 bundle 为 `prod_20260804_v4_r2`。
- detector 使用 sku_v4，历史 mAP50=0.6887；最近真实级联日志中检测召回约 38.1%。
- classifier 当前 checkpoint 为 208 类，epoch 10，记录的 val_acc=83.67%，不含 `__unknown__`。
- 最近真实日志中“检测成功后的分类正确率”约 63.9%，端到端约 24.4%。
- 端到端近似满足 `0.381 × 0.639 ≈ 0.244`。检测召回不变时，即使分类器达到 100%，端到端召回上限也只有 38.1%。
- 若希望两个串联阶段对最终 95% 做近似等额贡献，每一阶段需要约 `sqrt(0.95)=97.47%`，所以“分类器 val_acc 继续涨”不足以单独实现 95%。
- 当前 `.data_protocol/gold_holdout.json` 的 977 张照片全部被当前 detector 见过，classifier 也见过其中绝大多数，不能作为当前模型未见 gold。
- 当前 `.datasets/sku_v6` 和 `crop_dataset_yolo` 都是新构建协议生效前的旧制品；现有 crop summary 比磁盘实际多 1,561 个文件。

## 1. 目标重新定义

### 1.1 不再用单个 accuracy 代表系统效果

项目目标应拆成五类指标：

1. **检测覆盖**：真实商品被至少一个 proposal 覆盖的比例。
2. **条件分类**：给定正确 GT box 时的 SKU 分类与拒识效果。
3. **预测框鲁棒性**：给定 detector box 时的分类效果及相对 oracle 的下降。
4. **端到端业务结果**：照片级完整识别率、SKU micro/macro F1、数量误差、人工复核率。
5. **生产成本**：p50/p95 延迟、吞吐、峰值 RSS、GPU/CPU 成本、误接受风险。

### 1.2 建议的发布门槛

95% 必须先明确业务口径。建议将“95%”定义为 gold-v2 上的 **已接受结果 precision ≥95%**，同时单独约束覆盖和人工量，而不是把拒识样本从分母中删除。

建议首轮门槛：

| 指标 | 候选门槛 | 说明 |
|---|---:|---|
| detector recall | ≥97% | 在事先约定的 FP/image 预算下；支持端到端高覆盖 |
| true-box classifier top-1 | ≥97% | 先证明分类器在干净裁剪上的能力 |
| accepted precision | ≥95% | unknown/低置信可进入 review，不能错误 accepted |
| accepted coverage | ≥90% | 防止通过大量拒识虚增 precision |
| macro F1 | ≥90% | 防止头部 SKU 掩盖尾部失败 |
| 照片 exact-set accuracy | 逐轮提升并报告 | 一张图所有 SKU/数量均正确，最接近业务体验 |
| count MAE | ≤基线的 50% | 先以 E0 基线为分母，不预设无证据绝对数 |
| p95 latency / peak RSS | 不劣于当前已验证基线 20% | 精度提升不能无限交换生产性能 |

这些是候选门槛。正式执行前，业务负责人必须确认“框级、SKU 件数级还是整图级”的 95% 口径和允许复核比例。

## 2. 当前数据机会与约束

### 2.1 可用的新数据池

只读统计显示：

| 项目 | 数量 |
|---|---:|
| batch3 清洗后照片 | 22,659 |
| 当前 v6 已选 batch3 照片 | 4,000 |
| 尚未选用的清洗照片 | 18,659 |
| 排除当前已选门店、batch2 同名门店和 SHA 重复后的候选照片 | 9,073 |
| 候选中的新门店 | 4,466 |
| 候选注册类标注 | 201,128 |
| 注册 SKU 覆盖 | 208/208 |
| 标注数 ≥10 的 SKU | 205 |
| 标注数 ≥30 的 SKU | 197 |
| 候选未注册标注 | 15,220 |
| 其中 `other` | 9,069 |
| 其中 `百事other` | 3,300 |
| 其中 `可乐other` | 2,848 |

这 9,073 张新门店候选是下一阶段最重要的泛化资源。不能全部直接投入训练；必须先在训练前冻结 gold-v2、校准集和诊断集。

### 2.2 低频类约束

至少存在只有 3、8、9 等极少标注的类别。对这些类：

- 不应仅依靠 inverse-frequency sampler 大倍数复制同一图片。
- 必须人工复核标签和 SKU taxonomy，确认不是命名合并/拆分错误。
- 应优先补不同门店、不同包装角度、遮挡和光照，而非同一照片增强。
- 无法获得足够样本时，应把“支持该 SKU 的生产识别”列为有条件能力，不能用总体 micro accuracy 掩盖。

## 3. Task 1：冻结可信数据协议

**Files:**
- Inspect: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.data_protocol/gold_holdout.json`
- Inspect: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.batch3_clean/clean_manifest.json`
- Inspect: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/data/sku_registry.json`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.data_protocol/legacy_regression_v1.json`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.data_protocol/gold_v2.json`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.data_protocol/calibration_v1.json`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.data_protocol/diagnostic_v1.json`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.data_protocol/dev_v1.json`

- [ ] **Step 1: 保留旧 gold，不删除、不覆盖**

把现有 977 张集合在元数据中重新分类为 `legacy_regression_v1`，记录它与 detector/classifier 训练数据的交集。旧文件可继续做回归稳定性测试，但所有报告必须标记 `seen_by_current_model=true`。

- [ ] **Step 2: 在任何新训练之前冻结四个互斥集合**

建议从 9,073 张新门店候选中建立：

| 集合 | 建议规模 | 用途 | 是否允许调参 |
|---|---:|---|---|
| `diagnostic_v1` | 500 张 | 全量高质量真框，测 detector/分类 oracle | 只做诊断，不做训练 |
| `gold_v2` | 约 1,200 张 | 最终一次性发布评估 | 禁止训练和日常调参 |
| `calibration_v1` | 400 张 | 温度缩放、阈值、risk-coverage | 允许校准，不训练 backbone |
| `dev_v1` | 800 张 | 实验迭代和错误分析 | 允许反复评估，不训练 |

剩余新门店候选以及原有合法训练数据进入训练池。规模不是机械目标；若类覆盖不足，应以“完整覆盖和门店隔离”优先。

- [ ] **Step 3: 使用四重隔离键**

任何 train/dev/calibration/gold 之间同时检查：

1. 图片内容 SHA256；
2. 精确门店 ID；
3. 归一化门店名称和模糊相似名称；
4. 采集会话/日期/连续拍摄组。

同一货架连续多张、同一原图不同压缩版本、同一门店别名必须进入同一分区。只按文件名或随机照片切分不合格。

- [ ] **Step 4: 完整标注 gold-v2**

每张 gold 照片必须标注所有可见商品框，包括 unknown/background hard negatives；不能只标目标 SKU。采用双人复核或“标注者 + 审核者”，记录争议、修订和审核人。

- [ ] **Step 5: 类别覆盖约束**

在数据允许时，gold-v2 对每个关键 SKU 至少 60 个实例，并覆盖多个门店；极低频类使用全部可用新门店实例并单独报告置信区间。不能为了满足 60 个而把训练门店复制进 gold。

- [ ] **Step 6: 生成不可变 manifest**

每个集合记录：照片相对路径、SHA256、门店规范名、采集组、全部 box/label、registry SHA256、构建 seed、选择理由、与其他集合的零交集证明。manifest 建立后只追加新版本，不原地改写 gold-v2。

- [ ] **Step 7: 先跑当前 bundle 基线**

在任何训练前用 `prod_20260804_v4_r2` 对 diagnostic/dev/gold-v2 各跑一次，保存逐框结果和性能数据。gold-v2 结果封存，不用于选择具体超参；日常选择用 dev。

## 4. Task 2：修正训练前的协议阻断项

**Files:**
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/src/training/build_sku_v6_dataset.py`
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/src/training/train_v1.py`
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/src/cascade/build_yolo_crop_dataset.py`
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/src/cascade/classifier.py`
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/src/cascade/finetune.py`
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/src/cascade/cascade_inference.py`
- Test later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/tests/`

本任务列出训练前必须完成的后续工程工作，但本次不修改这些文件。

- [ ] **Step 1: 数据构建全局 fail-closed**

最终合并后的 train/val 必须重新检查 gold-v2、dev、calibration 的照片/门店/会话/SHA 零交集；不能只检查 batch3 子集。构建输出使用 staging，成功校验后原子发布，旧版本归档保留。

- [ ] **Step 2: 数据哈希覆盖完整训练语义**

dataset hash 必须包含图片 bytes、label bytes、相对路径、split manifest、ordered registry、构建参数和 builder commit。当前只哈希 `images/train` 与 `images/val` 的做法不能识别 label 变更。

- [ ] **Step 3: 明确 unknown 契约**

两种方案只能选一种并保持训练/推理/评估一致：

1. **显式 209 类**：classifier 包含 `__unknown__`，只要 top1 是 unknown 就强制 `needs_review`，永远不得 accepted；需要新的分类头训练或显式扩展 208→209。
2. **208 类 + OOD 拒识**：unknown 不作为 softmax 正式类，使用背景/未匹配 proposal 训练能量、embedding 或校准拒识头。

短期建议先做 209 类作为可解释基线，但必须先补“高置信 unknown 仍拒识”的回归测试。若 unknown 内部分布极其多样，再对比 OOD/能量方案。

- [ ] **Step 4: 禁止可变 `best.pt` 覆盖**

每个 experiment 写入唯一目录；已有目录 fail-closed。训练完成后由发布步骤复制到 immutable bundle，训练脚本本身不能覆盖生产 best。

- [ ] **Step 5: 固定随机性与多 seed**

记录 Python、NumPy、PyTorch、DataLoader 和 Ultralytics seed；同一关键方案至少运行 3 个 seed：`42`、`20260804`、`3407`。报告均值、标准差和最差值，不能只挑最好一次。

- [ ] **Step 6: 评估改为真正 one-to-one IoU**

需要输出不同 IoU 阈值下的 TP/FP/FN、每类和每门店结果。当前 point-in-box 只能作为宽松诊断，不能在文档中称为 IoU 评估。

## 5. Task 3：E0 当前系统基线

**Experiment ID:** `E0-current-bundle-baseline`

- [ ] **Step 1: 固定 bundle、数据和阈值**

使用当前 `prod_20260804_v4_r2`，记录完整 MANIFEST SHA256、208 类有序 mapping、conf=0.6 和 margin=0.05 的实际来源。不要把代码默认 margin 误写成 bundle 参数。

- [ ] **Step 2: 输出四层指标**

1. detector-only：recall、precision、FP/image、AR small/medium/large、count MAE。
2. GT-box classifier：top-1/top-5、macro F1、per-class recall、ECE、混淆矩阵。
3. predicted-box classifier：相同指标，额外按 IoU/框大小/遮挡分桶。
4. cascade：accepted precision、coverage、review rate、端到端 micro/macro F1、整图 exact-set accuracy。

- [ ] **Step 3: 保存逐样本错误账本**

每个错误必须归为且仅归为一个主因：`missed_detection`、`duplicate_detection`、`bad_localization`、`classifier_confusion`、`unknown_false_accept`、`known_false_reject`、`annotation_error`、`taxonomy_conflict`。

## 6. Task 4：E1 真实框检测上限实验

**Experiment ID:** `E1-detector-oracle-boxes`

RA-010 的目标不是训练新模型，而是先回答“现有点框/弱框标注把 detector 上限压低了多少”。

- [ ] **Step 1: 在 diagnostic_v1 建立完整真实矩形框**

500 张中覆盖密集货架、反光、遮挡、小目标、不同拍摄距离和主要门店类型。审核标注完整性，统计每图物体数和尺寸分布。

- [ ] **Step 2: 同一架构、同一 seed、同一数据量做 A/B**

- E1-A：当前点框/自适应框协议。
- E1-B：人工真实矩形框。

除标签外，backbone、初始化、epoch、imgsz、增强和评估集全部一致。

- [ ] **Step 3: 决策规则**

- 如果 E1-B 的 recall 相对 E1-A 提升 ≥10 个百分点，优先投资真实框/高质量自动框修订，而不是继续堆模型规模。
- 如果提升 <3 个百分点，点框不是首要瓶颈，转向分辨率、切片、NMS 和数据域。
- 3～10 个百分点时，按标注成本与端到端收益做小规模扩展验证。

## 7. Task 5：E2/E3 detector 路线对比

### E2：208 类 detector 与 class-agnostic product detector

**Experiment ID:** `E2-detector-class-agnostic`

- [ ] **Step 1: 构建两套完全同图同框数据**

- E2-A：208 类检测标签。
- E2-B：完整标注中的注册与未注册商品都合并为单类 `product`；SKU/unknown 判定交给 classifier 和拒识模块。若只给注册商品画框，detector 会把未注册商品学成背景，破坏 unknown 覆盖。

- [ ] **Step 2: 解释假设**

当前架构已经由 classifier 负责细分类，detector 再学习 208 类可能浪费容量并降低稀有类召回。单类 detector 可能提升 proposal recall，但也可能增加背景 FP；必须以固定 FP/image 和最终级联结果判断。

- [ ] **Step 3: 主要指标**

优先比较 recall@固定 FP/image、平均每图 proposal 数、漏检尺寸分布、重复框、p95 latency；mAP50 只作辅助指标。

### E3：高分辨率与密集货架推理

**Experiment ID:** `E3-detector-resolution-tiling`

- [ ] **Step 1: 小规模 pilot**

在同一 checkpoint 上先对 `imgsz=640/960/1280` 和可控 overlap tiling 做纯推理消融，避免直接训练多个昂贵模型。

- [ ] **Step 2: 记录收益成本曲线**

输出小目标 recall、FP/image、重复框、GPU/CPU 延迟和峰值内存。如果 1280/tiling 只增加成本而召回提升 <2 个百分点，停止该路线。

- [ ] **Step 3: 检查 NMS/框合并**

对密集相邻商品测试 conf、IoU NMS、class-agnostic NMS 和跨 tile 合并；每次只改一个变量，不能同时改分辨率、增强和模型规模。

## 8. Task 6：E4 classifier oracle 与数据域实验

**Experiment ID:** `E4-classifier-oracle-domain`

- [ ] **Step 1: 建立四个输入层级**

同一 classifier 依次评估：

1. 精确 GT crop；
2. GT crop 加受控位置/尺寸 jitter；
3. detector matched crop；
4. detector unmatched proposal/background。

- [ ] **Step 2: 用差值定位瓶颈**

- GT crop 也低于 95%：taxonomy、标签、类间外观、分辨率或 classifier 表达能力有问题。
- GT crop 高、jitter 明显下降：训练 crop 太干净，需要边界扰动和上下文鲁棒性。
- jitter 高、预测框低：detector 定位或 proposal 分布有问题。
- known 高但 unknown 误接受高：拒识/校准问题，不是普通分类准确率问题。

- [ ] **Step 3: 重新审视增强**

对水平翻转、hue、随机裁剪、颜色抖动逐项消融。包装文字具有方向和品牌颜色语义，激进 flip/hue 可能制造不真实样本。每个增强只在 3-seed pilot 中保留对 macro F1 和校准有稳定正收益的项。

- [ ] **Step 4: 类别采样策略**

对比普通 shuffle、class-balanced batch 和 effective-number weighting。避免对 3～9 张样本的类进行极端逆频率重复；报告尾部类增益是否以头部类和校准恶化为代价。

## 9. Task 7：E5 unknown 与拒识校准

**Experiment ID:** `E5-unknown-rejection`

- [ ] **Step 1: unknown 数据来源分层**

至少分开记录：未注册 GT（15,220 个候选）、detector 未匹配 proposal、货架背景、相似包装但不在 registry 的饮料、严重遮挡/模糊 known。训练和评估报告不能把这些全部混成一个数字。

- [ ] **Step 2: 构建困难负样本**

优先使用当前模型高置信误识别的 unmatched proposal，不做纯随机背景堆积。每轮 hard-negative mining 必须只从 train/dev 产生，不能查看 gold-v2 后回灌。

- [ ] **Step 3: 比较拒识分数**

在 calibration_v1 上比较：

- max softmax probability；
- top1-top2 margin；
- temperature scaling 后概率；
- entropy；
- embedding 距离/原型距离；
- 若必要，energy-based OOD score。

- [ ] **Step 4: 以 risk-coverage 选阈值**

输出每个阈值下 accepted precision、accepted coverage、known false reject、unknown false accept、review rate。选择满足业务风险约束的点，而不是只优化 overall accuracy。

- [ ] **Step 5: 强制 unknown 推理契约测试**

测试至少覆盖：高置信 unknown、低置信 known、top1/top2 接近、mapping 缺失、阈值文件缺字段。任何 `sku_id=__unknown__` 且 `status=accepted` 都必须失败。

## 10. Task 8：E6 backbone/损失函数选择

**Experiment ID:** `E6-classifier-capacity`

只有 E4 证明干净 GT crop 下当前 ResNet18 仍是主要瓶颈时，才进入本任务。

- [ ] **Step 1: 公平对比模型**

建议顺序：ResNet18 基线、EfficientNet-B0、ResNet50；同一输入、数据、增强、优化器预算和 seed。先做短 pilot，再对最有希望的两种做完整训练。

- [ ] **Step 2: 比较层次/度量方案**

如果混淆集中在同品牌/同系列包装，可比较：

- 品牌/系列辅助头 + SKU 主头；
- supervised contrastive/metric loss；
- SKU prototype embedding；
- OCR/包装文字特征作为辅助信号。

这些方案必须在 oracle classifier 任务上证明收益，再进入级联；不能因为结构更复杂就直接上线。

- [ ] **Step 3: 停止规则**

若更大 backbone 的 macro F1 提升 <1.5 个百分点，而 p95 延迟或 RSS 增加 >20%，保留较小模型。若收益只来自头部类，视为无效提升。

## 11. Task 9：E7 完整级联与系统性能

**Experiment ID:** `E7-cascade-release-candidate`

- [ ] **Step 1: 只组合已经独立获胜的组件**

detector、classifier、unknown 策略和阈值都必须先在各自任务中胜出。不要一次组合多个未验证变化后将提升归因给某一项。

- [ ] **Step 2: 运行完整 gold-v2**

一对一 IoU 匹配，输出 micro/macro/per-class/per-store 结果、95% bootstrap CI、照片 exact-set accuracy、count MAE、review rate 和错误账本。

- [ ] **Step 3: 性能压测矩阵**

至少测试 batch=1 在线请求与批量任务两种模式：

| 维度 | 必报结果 |
|---|---|
| 延迟 | detector、crop、classifier、总链路 p50/p95/p99 |
| 吞吐 | 1/2/4 并发下 images/s，记录 429 与排队时间 |
| 内存 | 启动、首个请求、稳定 2 小时的 RSS/显存峰值 |
| 图片密度 | 低/中/高商品数分桶 |
| 失败 | OOM、超时、损坏图片、模型加载失败、审计失败 |

- [ ] **Step 4: monitor 长稳检查**

当前 monitor 已从约 16.3 GiB 降至约 261 MiB，但需至少 2 小时、每分钟 RSS 采样，确认 TTL 到期后的 checkpoint reload 不会阶梯式增长。

- [ ] **Step 5: 发布前 shadow**

候选 bundle 先对真实流量做只读 shadow，不改变用户结果和生产数据。比较当前 bundle 与候选 bundle 的 accepted/review、延迟、错误类型，确认无关键 SKU 回归。

## 12. 实验排期与资源控制

建议按下面顺序执行，不并行烧算力：

| 顺序 | 实验 | 目的 | 进入下一阶段条件 |
|---:|---|---|---|
| 0 | 数据协议 + E0 | 可信基线 | gold-v2 零泄漏、E0 报告完整 |
| 1 | E1 | 真实框上限 | 明确是否值得补框 |
| 2 | E2 | 单类 detector | recall@FP/image 有稳定收益 |
| 3 | E3 | 分辨率/tiling | 收益覆盖性能成本 |
| 4 | E4 | 分类 oracle/裁剪域 | 定位分类损失来源 |
| 5 | E5 | unknown/校准 | 风险-覆盖达到门槛 |
| 6 | E6 | 模型容量/结构 | 仅在分类器确为瓶颈时 |
| 7 | E7 | 级联候选 | gold-v2 + 系统性能同时过门 |

每个实验先运行约完整预算 10%～20% 的 pilot。pilot 明显劣于基线或违反停止规则就终止，不因已经投入时间继续堆 epoch。

## 13. 训练停止与转向规则

- [ ] true-box detector 相对点框大幅提升：停止模型扩容，转向框标注质量。
- [ ] detector 在真实框、1280/tiling、单类方案下仍无法达到目标 recall：重新评估拍摄距离、图像分辨率、货架分区拍摄和 95% 目标可达性。
- [ ] GT-box classifier <95%：先修 taxonomy、错标、低频类和裁剪分辨率；不要直接调 cascade 阈值。
- [ ] GT-box classifier 高而 predicted-box 低：优先修 detector box 和 crop distribution。
- [ ] accepted precision 达标但 coverage 很低：拒识过度，不能宣称系统达到 95%。
- [ ] micro 指标提升而 macro/per-store 下降：不接受，说明只优化头部门店/SKU。
- [ ] 3 个 seed 中只有一个提升：视为不稳定，不发布。
- [ ] gold-v2 被用于训练、阈值反复试探或 hard-negative mining：该 gold 版本立即失效，新建 gold-v3；旧版保留审计记录。

## 14. 每次实验必须提交的报告

实验报告保存到固定实验文件，例如 E1 使用 `docs/experiments/E1-detector-oracle-boxes.md`，至少包含：

```text
experiment_id
hypothesis
single_changed_variable
code_commit
dataset_id and full SHA256
registry SHA256 and ordered class count
train/dev/calibration/gold versions
seeds
hardware and software environment
exact command and config
training duration and compute cost
best checkpoint selection rule
all primary and guardrail metrics
confidence intervals
error taxonomy counts
latency/RSS/VRAM
decision: promote / iterate / stop
```

不能只保存 dashboard 截图、最高 accuracy 或可变日志路径。报告中的“best metric”必须与实际发布 checkpoint 对应，不能把最大 mAP50 行与 Ultralytics 按综合 fitness 选出的 `best.pt` 混为一谈。

## 15. 发布门禁

候选模型只有全部满足才允许创建 immutable bundle：

- [ ] 数据 manifest 与磁盘图片/label 数量、内容 hash 完全一致。
- [ ] train/dev/calibration/gold 按 SHA、门店、别名、会话零交集。
- [ ] ordered registry 与 detector names、classifier classes 完全一致。
- [ ] unknown 契约测试通过，不存在 unknown accepted。
- [ ] 3-seed dev 结果稳定，gold-v2 只执行正式发布评估。
- [ ] accepted precision、coverage、macro F1、count MAE 达到约定门槛。
- [ ] 关键 SKU、门店和小目标没有显著回归。
- [ ] p95 latency、吞吐和 2 小时 RSS 在预算内。
- [ ] bundle 包含 detector、classifier、registry、全部阈值/校准参数和完整 SHA256 manifest。
- [ ] bundle verify、冷启动、回滚和 shadow 均通过。
- [ ] 发布记录绑定 Git commit、DVC revision、gold 报告和 previous bundle。

## 16. 建议的第一周执行顺序

第一周不应立刻开大训练。建议：

1. 第 1～2 天：冻结四个集合，完成泄漏审计和 registry/taxonomy 复核。
2. 第 2～3 天：完成 diagnostic_v1 真实框双审，运行 E0 四层基线。
3. 第 3～4 天：完成 E1 点框 vs 真框；形成是否扩大真实框标注的决策。
4. 第 4～5 天：运行 E2 单类 detector 小规模 pilot，并做 E3 纯推理分辨率/tiling 消融。
5. 第 5 天：根据错误账本决定第二周资源，不预先承诺 ResNet50 或整轮重训。

这一顺序能最快回答三个关键问题：检测为什么只有约 38.1% 召回、真实框能提升多少、分类器的 83.67% 到底是模型问题还是预测框分布问题。
