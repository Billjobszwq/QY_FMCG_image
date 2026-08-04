# SAM 辅助重标注专项 · 实施计划（TDD）

> 锁定目标模块边界（手册§四，可按项目风格微调文件名，禁止把逻辑塞进 yolo_backend.py / quality_gate.py）。
> 每个任务：写失败测试 → 确认失败 → 最小实现 → 通过 → 全量回归 → 小提交。

## 模块边界（锁定）

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

## 任务分解（按提交顺序）

### T1 文档基线（本提交）
- [x] 六份专项文档 + baseline 记录 → commit `docs: add SAM reannotation execution records`

### T2 SAM 契约与纯逻辑（不依赖 SAM 权重）
- [ ] `tests/unit/test_sam_prompts.py`：点提示构造（正点=商品中心、负点=相邻 SKU 点）、粗 ROI 由固定比例框生成且标记 `coarse_only=True`、负点不得落在正点实例内
- [ ] `tests/unit/test_sam_candidates.py`：候选硬约束（含正点、不含他实例点、面积/长宽比在物理校准范围、多连通域/触边界/跨货架线/大重叠→降级、无合格候选→manual_required 且不回退固定比例框）
- [ ] `tests/unit/test_sam_evidence.py`：证据记录字段完整性（原图 SHA、模型 SHA、提示点、mask SHA、算法版本、时间戳）、追加式不可覆盖
- [ ] `tests/contract/test_sam_prediction_contract.py`：SAM 输出只能生成 LS prediction 结构（score/model_version/result），绝不产生 annotation
- [ ] `tests/contract/test_annotation_provenance.py`：审核状态机 auto_proposed→annotator_accepted/corrected/manual→reviewer_accepted/rejected→adjudicated；每次状态变更追加记录且保留前版
- [ ] 实现 `src/sam_assist/{contracts,prompts,candidates,scoring,evidence}.py`（纯 CPU 可测，SAM 权重不参与）
- [ ] 全量回归 74+N passed → commit `test: define SAM prompt and evidence contracts`（若实现与测试同批，则拆两个提交）

### T3 SAM 隔离 Worker
- [ ] 隔离 venv（`.venv_sam/`，独立 torch/torchvision + SAM2），主环境不装 SAM 依赖
- [ ] checkpoint 下载 sam2.1_hiera_small / sam2.1_hiera_base_plus，SHA256 + URL + 许可证记录
- [ ] `src/sam_assist/runtime.py`：设备门禁（MPS 必须可用、无 fallback 环境变量）、embedding 缓存、不支持算子即中止
- [ ] `src/sam_assist/service.py`：CLI/Worker（进程隔离调用隔离 venv 的 python）
- [ ] commit `feat: add isolated SAM 2.1 assist worker`

### T4 四级质量策略
- [ ] `tests/unit/test_quality_policy.py`：accept/warn/manual_review/reject 四级；reject 必须多信号支持（单项弱指标不得自动 reject）；原图保留标记；hard-valid 标签
- [ ] `tests/contract/test_quality_evidence_contract.py`：每张图证据（原图哈希、指标、规则版本、结论、原因码）
- [ ] 实现 `src/data_quality/{contracts,analyzers,policy,evidence,runner}.py`（8 类分析器：模糊/局部模糊/曝光/反光/翻拍/斜拍透视/大头照无关场景/遮挡裁切/近重复）
- [ ] 独立校准集（禁用 diagnostic_v1 调阈值）
- [ ] commit `test: define four-tier photo quality policy` + `feat: add evidence-preserving quality pipeline`

### T5 Gate S0（SAM 准入）
- [ ] 5 张 smoke（MPS 实跑，记录设备/内存/耗时）
- [ ] 50 张 / 约 1000 点 benchmark：encoder/decoder 时间、RSS、MPS 内存、swap；hiera_small vs base_plus 比较，选最小达标模型
- [ ] 未过门禁禁止批量 → 结果写 RESULTS.md / EXECUTION-LOG.md

### T6 LS 接入
- [ ] `src/ls_ml_backend/sam_backend.py`（仿 yolo_backend.py 结构，prediction only）
- [ ] 契约测试：prediction schema 兼容 label_config.xml（product box + taxonomy + status）
- [ ] 50 张盲人工框对照任务建立 → commit `feat: connect SAM predictions to Label Studio review`

### T7 真实框数据集构建器
- [ ] `tests/contract/test_truebox_dataset_guard.py`：e3_product_truebox_pilot_v1 沿用 e2 的 2000/300 同 split；仅标签来源=人工审核真实框；五键 0 泄漏；拒绝覆盖；仅接受 reviewer_accepted 框
- [ ] commit `feat: add true-box dataset builder and guards`

### T8 真实框评估器
- [ ] IoU 0.50/0.75、recall@FP1/3/5、逐实例 10 类错误账本；统一评估 E0/P0/P1
- [ ] commit `feat(eval): add true-box detector evaluation and error ledger`

### T9 benchmark/门禁报告
- [ ] commit `docs: record SAM benchmark and annotation gate results`

### T10 Gate D0 检查 + E3 pilot（全门禁通过后）
- [ ] D0 五项全过 → e3_product_truebox_pilot_v1 发布 → 3ep pilot（best/sku_v4_best.pt、seed=42、imgsz=960、batch=4、mps、lr0=0.0005、cls=0.2、AdamW、patience=3、close_mosaic=1、cos_lr、run-name e3_p1_truebox_s42）
- [ ] 决策规则：≥+10pp 且 FP≤1.2x → D1 单 seed 10ep；3~10pp → 修错误账本；<3pp → 转推理侧优化

## 人工环节（机器侧完成后置 awaiting_human_review）

1. 前 200 张 diagnostic_v1 双审（标注员 + 独立审核者）
2. 50 张盲人工框对照（随机抽样，隐藏 SAM 预标注）
3. 500 张 diagnostic 完成前不得做正式模型选择
