# 数据、SAM 与四模型训练设计

## 1. 核心方法论

本轮把“标签来源”和“样本用途”分开治理。一个样本可以用于训练，但不等于可以作为评估真值。

| label source | 含义 | 可训练 | 可作为正式评估真值 |
|---|---|---:|---:|
| `human_gold` | `human_final/gold_verified` 的框、mask、SKU | 是 | 是 |
| `legacy_coordinate_verified` | 三批历史坐标与名称，通过身份、映射、抽检 | 是，带来源权重 | SKU/点命中可用；不能冒充真实 mask/box gold |
| `sam_verified_pseudo` | 点提示 SAM 通过几何门和人工抽检的 mask/box | 是，带伪标签权重 | 否 |
| `model_proposal` | 当前生产/实验模型建议 | 仅辅助和 hard-negative，默认不可当真值 | 否 |
| `unknown/new_packaging` | 未映射或新包装 | 可进入 unknown/拒答任务 | 只在人工确认后 |

这样既能利用 29,176 张照片和 745,695 个坐标，又不会把批量生成结果伪装成 gold。

## 2. 资产与坐标统一

### 2.1 不可变输入

- 第一、二、三批原始照片和 Excel 只读；
- 为每个原始引用记录 `source_batch/source_row/photo_id/path/sha256/width/height/decode_status`；
- 原图进入现有 CAS/ResourceRef 体系，任何派生结果只新增引用，不改源文件；
- 所有 builder 使用 staging + atomic publish + manifest hash，目标存在时拒绝覆盖。

### 2.2 精确去重与坐标冲突

精确重复按 SHA 聚合，canonical 规则：

1. 第一/二批重复照片优先采用第二批坐标版本；
2. 第一批仅补 2 张独有照片；
3. 第三批独立纳入；
4. 第一/二批 476 张坐标不一致照片写 `coordinate_discrepancy_ledger`，保留两份原始记录与差异摘要；
5. 不因选择 canonical 就删除非 canonical 引用。

### 2.3 全量近重复

旧 pHash 仅扫描 1,288 个本地目录资产，不覆盖三批 manifest。本轮对 29,176 张全量执行：

- EXIF 归一化后的 pHash/dHash；
- pHash LSH/BK-tree 候选，不做不可扩展的 O(N²) 全比较；
- 对临界候选可用视觉 embedding ANN 二次确认；
- near-dup group 整体落同一 split；
- 同一货架连拍不必全部删除：保留代表帧用于训练，其余可作为困难一致性/shadow 样本，规则写入 evidence ledger。

## 3. 严格照片质量过滤

### 3.1 必须覆盖的风险

- 解码失败、尺寸异常、重复/近重复；
- 严重模糊、运动模糊、主体过小；
- 过曝、欠曝、严重反光、局部高光遮字；
- 严重倾斜、透视变形、倒置；
- 翻拍屏幕/印刷品、摩尔纹；
- 大头照/单瓶近景对货架识别的误导；
- 大面积遮挡、裁切、空场景；
- 场景类型与价签有/无；
- 图片中坐标点是否越界、落在背景或落在同一目标冲突。

### 3.2 四级结论

| 结论 | 用途 |
|---|---|
| `accepted` | 正常训练候选 |
| `hard_valid` | 合法困难样本，单独分桶并控制采样权重 |
| `manual_review` | 自动规则不确定，进入人工质量队列 |
| `rejected` | 不进入主训练；原图与证据保留，可作负样本/鲁棒性评估 |

当前 `qpol_v2` 只有模糊/反光部分启发式，其他维度不能直接宣称全自动完成。新策略先用现有分析器产出所有可观测指标，再通过人工校准确定阈值。

### 3.3 质量校准门

- 全审 `rejected` 与 `manual_review`；
- 从 `accepted/hard_valid` 按批次、SKU、门店/session、场景、质量、密度、尺寸分层盲抽；
- 至少 1,000 张初始校准，且每个关键质量维度至少 50 个正/负案例；不足则扩样；
- 自动 reject precision 目标 ≥98%，重大分桶 ≥95%；误拒率单独报告；
- 任何阈值变化必须生成新 `quality_policy_version`，不能覆盖旧结论。

## 4. 点提示 SAM 生成 mask

### 4.1 Prompt 构造

对每个 canonical 点：

1. 当前点作为正点；
2. 局部 ROI 内其他 SKU 点作为负点，防止吞并相邻商品；
3. 由点密度、最近邻距离和图像尺寸生成局部 box prompt；
4. SAM 输出 multimask candidates；
5. 由几何、边界、稳定性与点关系打分，不能由目标 SKU 名称泄漏选择。

### 4.2 Fail-closed 几何门

拒绝或送人工：

- mask 不包含正点；
- mask 包含其他商品正点；
- 多个互不相连的主要连通域；
- 无合理原因触边/截断；
- 面积、长宽比、紧致度相对 SKU/场景分布异常；
- 与邻接 mask 大面积重叠或互相包含；
- tight box 小于最小可识别尺寸；
- SAM 多候选分差过小，无法稳定裁决。

每个接受实例输出：`mask_rle/polygon`、tight box、context box、mask crop、context crop、prompt、candidate scores、policy version、SAM model hash、source coordinate identity。

### 4.3 Mask 审核门

批量伪标签进入训练前，至少双审 2,000 个 region，覆盖：

- 每个已知 SKU 至少 5 个（数据不足时全部）；
- 三批来源、货架/冰柜/地堆/堆箱/小货架等场景；
- 大中小目标、稀疏/密集、正常/困难质量；
- unknown/new packaging。

自动接受 mask precision 目标：整体在 IoU≥0.75 下 ≥98%，主要分桶 ≥95%。未达标就调整 prompt/筛选策略并生成新版本，不允许直接扩大。

## 5. 四类 DatasetSnapshot

### D1 `detector_snapshot_v2`

- 输入：accepted/hard_valid 图像；human box 或 SAM tight box；
- 类别：第一阶段单类 `product`，unknown 商品同样是 product；
- 训练权重：human > verified coordinate/SAM pseudo；
- 输出：YOLO detect 格式、source weight、quality slice、完整 lineage；
- 评估：只使用独立 human truebox 冻结集。

### D2 `segmenter_snapshot_v2`

- 输入：经过 mask 审核门的 SAM mask；
- 输出：YOLO segmentation polygon/RLE 转换、tight box、mask quality；
- 训练对象：轻量 YOLO-seg 学生；
- SAM 保持冻结 teacher/在线精修能力；
- 若以后训练 SAM adapter，必须新建独立计划且只使用 human mask gold。

### D3 `classifier_snapshot_v2`

- 同一个 region 派生三种视图：tight crop、mask crop、带 10–30% context crop；
- canonical SKU 作为已知类；40,591 个未映射点按治理后进入 unknown/brand-unknown/category-unknown；
- 同包装新旧版使用 `package_version_id`，不只依赖显示名；
- near-dup group、门店/session、包装版本整体分组切分；
- 评估报告 top1/macro-F1/unknown FAR/coverage/package-version accuracy。

### D4 `vlm_snapshot_v2`

Qwen 样本不能只是 224×224 小 crop。每条记录包含：

- 原始图或受控缩放图；
- normalized bbox/point/mask 证据；
- context crop 与 mask crop；
- OCR/包装属性（有则给，无则空，不编造）；
- 由真实检索链产生的 CandidateSet，候选构建函数禁止接收 GT；
- canonical target，或 `unknown/new_packaging/abstain`；
- 标准 `images/messages` 聊天格式，实际格式以锁定版本的 `mlx-vlm --help` 和本地 smoke 为准，不手写过期特殊 token。

初始 QLoRA：冻结 vision tower，先做 5k–20k 分层 pilot、1 epoch；通过过拟合/收益门后才进入一个有界 full candidate（建议 1–3 epoch + early stop），不预设 batch=16，也不承诺 3–5 小时。

## 6. 四个实验模型

| Lane | 模型 | 公共初始化 | 本轮结果 |
|---|---|---|---|
| M1 detector | YOLO detector | 公共基础权重 | `candidate_detector_v2` |
| M2 segmenter | 轻量 YOLO-seg student | 公共分割基础权重 | `candidate_segmenter_v2` |
| M3 classifier | ResNet18/轻量分类器 | ImageNet 公共权重 | `candidate_classifier_v2` |
| M4 VLM | `qwen3-vl:4b` MLX QLoRA | 锁定 HF/MLX revision | `candidate_vlm_v2` |

旧 `sku_v4/sku_v7_sam/E2/classifier` 只作 baseline/proposal teacher，不作任何 parent/resume/EMA/optimizer。比较时使用相同冻结集和口径。

## 7. 评估与结果解释

### 7.1 必须分开报告

- 训练集/验证集损失：只用于看收敛；
- pseudo-label consistency：用于判断数据教师稳定性；
- human frozen evaluation：用于判断真实业务收益；
- end-to-end cascade：用于判断最终业务准确率、覆盖率、时延和成本。

没有 human frozen evaluation 时，可以产出 `EXPERIMENTAL_CANDIDATE`，但不得标 `PROMOTION_READY`。

### 7.2 最低业务指标

- Detector：recall@FP1/3/5、IoU50/75、duplicate/background/merge/localization ledger；
- Segmenter：mask IoU、boundary F、merge/truncation、下游分类收益、额外延迟；
- Classifier：top1、macro-F1、unknown FAR、coverage-risk、包装版本准确率；
- VLM：candidate recall@K、accepted precision、coverage、abstain、registry escape、p95、tokens/region；
- E2E：按照片 exact-set、count MAE、accepted precision/recall、人工复核率、p95/吞吐/内存/成本。

任何“>95%”必须说明是哪个分母、哪个冻结集、什么 coverage；不能用 top5、单类 mAP 或剔除 rejected 后的精度替代。

