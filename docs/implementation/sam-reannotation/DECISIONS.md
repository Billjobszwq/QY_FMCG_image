# SAM 辅助重标注专项 · 决策记录

每条格式：日期 | 决策 | 依据 | 影响。

## D-001 worktree vs 独立分支
- 日期：2026-08-01
- 决策：采用独立 feature branch `feat/sam-reannotation`（主工作区内），不另建 git worktree。
- 依据：手册允许"feature branch/worktree"；项目全部数据制品（`.batch3_clean/`、`.datasets/`、`.data_protocol/`、`.models/`）为未跟踪目录且脚本以 PROJECT_ROOT 寻址，worktree 内这些数据不可见，会导致 smoke/benchmark/构建全部断链。
- 影响：所有提交在 `feat/sam-reannotation`，不 merge 不 force-push；`.superpowers/` 未跟踪目录保留不清理。

## D-002 SAM 模型范围
- 日期：2026-08-01
- 决策：本机只评估 SAM 2.1 hiera_small 与 hiera_base_plus；SAM 3 因官方要求 CUDA 不作本机主实现。
- 依据：手册§五；Apple M3 Max 无 CUDA。
- 影响：checkpoint 只下载这两个；Gate S0 选"最小达标模型"。

## D-003 SAM 环境隔离
- 日期：2026-08-01
- 决策：SAM 依赖安装于独立 venv（`.venv_sam/`），Worker 以子进程方式调用隔离 python；主 conda 环境的 torch/torchvision/ultralytics 版本不变。
- 依据：手册§一.8。
- 影响：主环境 `pytest` 74 测试不受 SAM 依赖影响。

## D-004 提示协议
- 日期：2026-08-01
- 决策：坐标点=正提示；相邻 SKU 点=负提示；固定比例框（0.07×0.18）仅生成粗 ROI 并标 `coarse_only`，永远不得作为真实框或最终标签来源。
- 依据：手册§六；用户要求第 8 条。
- 影响：`prompts.py`/`candidates.py` 契约按此设计；无合格候选 → `manual_required`，不回退比例框。

## D-005 SAM 输出地位
- 日期：2026-08-01
- 决策：SAM 产物只能作为 Label Studio prediction（带 model_version/score），最终 annotation 必须由人工标注者确认 + 第二人审核产生。
- 依据：手册§一.6；用户要求第 9 条。

## D-006 质量四级分流
- 日期：2026-08-01
- 决策：accept/warn/manual_review/reject 四级；reject 需多信号组合支持，单项弱指标只能 warn/manual_review；原图永不删除；困难但可识别照片打 hard-valid 标签保留。
- 依据：手册§八；用户要求第 14/15/16 条。

## D-007 diagnostic_v1 用途隔离
- 日期：2026-08-01
- 决策：diagnostic_v1（500 张）仅诊断/评估；禁入训练、调参、阈值学习、hard-negative mining；质量阈值校准使用独立校准集。
- 依据：手册§一.5；用户要求第 11 条。

## D-008 E3 数据集口径
- 日期：2026-08-01
- 决策：`e3_product_truebox_pilot_v1` 沿用 e2_product_pilot_v1 相同 2000/300 照片与门店整组 split（seed=42 同一抽样），仅把合成比例框替换为人工审核真实框；新目录发布，绝不覆盖 e2。
- 依据：手册§十一；用户要求第 20 条。

## D-009 E3 训练单一变量
- 日期：2026-08-01
- 决策：E3 pilot 唯一变量是标签质量；模型（sku_v4_best.pt 初始化）、分辨率 960、batch 4、增强、NMS、数据量与 E2 一致；run-name `e3_p1_truebox_s42`。
- 依据：手册§十二；用户要求第 22 条。

## D-010 晋级判据
- 日期：2026-08-01
- 决策：真实框 diagnostic 上 recall@FP3 相对 E0 提升 ≥10pp 且 FP ≤1.2 倍 → 单 seed 10ep；3~10pp → 停止长训先修错误账本；<3pp → 转纯推理优化（960/1280/tiling/NMS 消融）。
- 依据：手册§十二；用户要求第 23 条。

## D-011 生产边界
- 日期：2026-08-01
- 决策：classifier 训练继续暂停；生产 bundle `prod_20260804_v4_r2` 不变；不切 8091；不恢复 v6；不自动发布。新模型一律 research/candidate 状态。
- 依据：手册§一.3；用户要求第 24/25 条。
