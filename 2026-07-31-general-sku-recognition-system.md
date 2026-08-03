# 通用SKU图像识别系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一套由 Label Studio、本地视觉模型、多模态 SKU 知识库和 YOLO26 组成的可审计人机协同识别闭环，先在单一场景、30～50个高相似 SKU 上完成技术验证，再按发布门槛扩展。

**Architecture:** 系统采用“两阶段识别”：开放词汇模型或 YOLO 检测商品区域，随后结合条码、OCR、视觉向量检索、硬冲突规则和本地视觉大模型完成 SKU 裁决。Label Studio 仅承担预标注展示和人工审核；人工确认以追加事件进入数据版本，任何模型、提示词或知识库变更都必须通过固定金标准集和影子运行后才能发布。

**Tech Stack:** Python 3.11、FastAPI、PostgreSQL 16 + pgvector、Redis、MinIO、Label Studio Community、Label Studio ML Backend、Ultralytics YOLO26/YOLOE-26、Grounding DINO、SigLIP 2 或 DINOv2、PaddleOCR/条码解码、本地 Qwen2.5-VL、MLflow、Pytest、Docker Compose。

---

## 0. 计划基线

### 0.1 首期边界

- 单一业务场景，首选固定拍摄距离和相对稳定背景的货架或陈列照片。
- 30～50个高相似 SKU，必须包含同品牌不同规格、口味和新旧包装。
- 500张独立人工金标准照片，不参与训练、提示词调试或阈值选择。
- 训练与验证数据不少于1,500张现场图片；标准360度商品图仅作为知识库参考，不替代现场数据。
- 系统必须支持“未知 SKU”“图片不可判定”“候选冲突”，不得强制匹配。

### 0.2 MVP发布门槛

| 指标 | 技术验证门槛 | 试点门槛 |
|---|---:|---:|
| 商品框召回率 | ≥95% | ≥97% |
| SKU Top-5召回率 | ≥95% | ≥97% |
| SKU Top-1准确率 | ≥85% | ≥90% |
| 高置信自动通过错误率 | ≤2% | ≤1% |
| 未知SKU错误接纳率 | ≤3% | ≤1% |
| 人工平均审核时间下降 | ≥30% | ≥50% |
| 预测、审核、版本审计覆盖率 | 100% | 100% |

说明：如果高置信覆盖率较低但错误率达标，系统可以进入受控试点；如果错误自动通过率超标，无论整体准确率多高都不得发布。

## 1. 建议目录与职责

```text
.
├── compose.yaml                         # 本地与试点环境编排
├── .env.example                         # 非敏感配置说明
├── pyproject.toml                       # Python依赖与工具配置
├── configs/
│   ├── label-studio/label_config.xml    # 标注界面定义
│   ├── policies/decision_rules.yaml     # SKU硬冲突和自动通过策略
│   └── evaluation/gates.yaml            # 评测与发布门槛
├── src/
│   ├── common/                          # 配置、日志、ID和异常
│   ├── catalog/                         # SKU主数据、图片和知识版本
│   ├── detection/                       # YOLOE/Grounding DINO/YOLO26适配器
│   ├── retrieval/                       # 图像向量、Top-K召回和索引
│   ├── evidence/                        # 条码、OCR和证据融合
│   ├── adjudication/                    # 硬规则与本地VLM裁决
│   ├── labeling/                        # Label Studio ML Backend与Webhook
│   ├── feedback/                        # 追加式人工反馈事件
│   ├── datasets/                        # 数据集快照、切分和导出
│   ├── training/                        # YOLO训练与实验记录
│   ├── evaluation/                      # 金标准评测和分组指标
│   ├── release/                         # 影子运行、模型提升和回滚
│   └── api/                             # 识别与只读查询接口
├── migrations/                          # PostgreSQL迁移
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── regression/
├── scripts/
│   ├── seed_demo_catalog.py
│   ├── build_gold_set.py
│   ├── run_training.py
│   └── evaluate_release.py
└── docs/
    ├── architecture.md
    ├── data-contracts.md
    ├── annotation-guide.md
    ├── operations-runbook.md
    └── release-policy.md
```

## 2. 实施任务

### Task 1：冻结业务范围和评测协议

**Files:**
- Create: `docs/scope-and-success.md`
- Create: `docs/annotation-guide.md`
- Create: `configs/evaluation/gates.yaml`
- Test: `tests/contract/test_evaluation_gates.py`

- [ ] **Step 1：写入首期场景、SKU清单规则和排除项**

  `docs/scope-and-success.md`必须明确：拍摄设备、距离、光照、允许遮挡、单图最大商品数、首期SKU数量、未知SKU定义、不可判定定义、上线责任人。

- [ ] **Step 2：固化评测门槛**

```yaml
technical_validation:
  detection_recall_min: 0.95
  sku_top5_min: 0.95
  sku_top1_min: 0.85
  auto_accept_error_max: 0.02
  unknown_false_accept_max: 0.03
  audit_coverage_min: 1.0
pilot:
  detection_recall_min: 0.97
  sku_top5_min: 0.97
  sku_top1_min: 0.90
  auto_accept_error_max: 0.01
  unknown_false_accept_max: 0.01
  audit_coverage_min: 1.0
```

- [ ] **Step 3：写契约测试并验证配置可解析**

  Run: `pytest tests/contract/test_evaluation_gates.py -v`

  Expected: 两组门槛均通过范围检查，且试点门槛不低于技术验证门槛。

- [ ] **Step 4：提交**

```bash
git add docs/scope-and-success.md docs/annotation-guide.md configs/evaluation/gates.yaml tests/contract/test_evaluation_gates.py
git commit -m "docs: freeze SKU recognition scope and release gates"
```

### Task 2：建立本地基础环境

**Files:**
- Create: `compose.yaml`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `src/common/config.py`
- Test: `tests/integration/test_service_health.py`

- [ ] **Step 1：编排 PostgreSQL、pgvector、Redis、MinIO、Label Studio、API和Worker**
- [ ] **Step 2：确保所有密钥只由环境变量注入，`.env.example`只保留字段名和安全说明**
- [ ] **Step 3：加入健康检查**

  Run: `docker compose config`

  Expected: 配置解析成功，无未解析变量。

  Run: `docker compose up -d postgres redis minio label-studio`

  Expected: 四个服务均为 healthy，Label Studio登录页可访问。

- [ ] **Step 4：运行集成测试**

  Run: `pytest tests/integration/test_service_health.py -v`

  Expected: 数据库扩展、对象存储桶、Redis和Label Studio健康端点全部通过。

### Task 3：建立可追溯数据模型

**Files:**
- Create: `src/catalog/models.py`
- Create: `src/feedback/models.py`
- Create: `src/release/models.py`
- Create: `migrations/001_core_schema.sql`
- Test: `tests/unit/test_append_only_feedback.py`

- [ ] **Step 1：创建核心实体**

  必须包含：`sku`、`sku_alias`、`sku_image`、`asset`、`recognition_run`、`proposal`、`prediction`、`review_event`、`dataset_version`、`knowledge_version`、`prompt_version`、`model_version`、`release`。

- [ ] **Step 2：实现追加式反馈约束**

  `review_event`禁止更新和删除。纠错通过写入新的事件完成，事件包含审核前值、审核后值、审核人、时间、原因和所依据的证据。

- [ ] **Step 3：验证历史不可变**

  Run: `pytest tests/unit/test_append_only_feedback.py -v`

  Expected: 插入成功；更新和删除均被数据库拒绝；新纠错事件可追加。

### Task 4：建立SKU多模态知识库

**Files:**
- Create: `src/catalog/importer.py`
- Create: `src/catalog/validator.py`
- Create: `src/retrieval/embedder.py`
- Create: `scripts/seed_demo_catalog.py`
- Test: `tests/unit/test_catalog_validation.py`

- [ ] **Step 1：定义每个SKU的必需字段**

  SKU编码、标准名称、品牌、规格、口味、容量、包装版本、生效日期、条形码、别名、参考图、硬冲突字段均需显式存储。

- [ ] **Step 2：导入标准图和现场图**

  所有图片使用内容哈希去重，但原始文件不覆盖；重复文件记录来源关系。

- [ ] **Step 3：生成SigLIP 2或DINOv2向量并写入pgvector**
- [ ] **Step 4：验证缺失、冲突和历史包装**

  Run: `pytest tests/unit/test_catalog_validation.py -v`

  Expected: 条码冲突、规格缺失、包装版本重叠和孤立图片均被识别并阻止知识版本发布。

### Task 5：实现商品框候选层

**Files:**
- Create: `src/detection/base.py`
- Create: `src/detection/grounding_dino.py`
- Create: `src/detection/yoloe26.py`
- Create: `src/detection/yolo26.py`
- Test: `tests/contract/test_detector_contract.py`

- [ ] **Step 1：定义统一输出**

```python
@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    score: float
    model_version: str
```

- [ ] **Step 2：实现开放词汇检测器适配器**
- [ ] **Step 3：实现YOLO26检测器适配器**
- [ ] **Step 4：验证坐标范围、重复框和模型版本**

  Run: `pytest tests/contract/test_detector_contract.py -v`

  Expected: 三个适配器输出同一契约，坐标均限制在图片范围内。

### Task 6：实现条码、OCR和视觉检索

**Files:**
- Create: `src/evidence/barcode.py`
- Create: `src/evidence/ocr.py`
- Create: `src/retrieval/search.py`
- Create: `src/evidence/fusion.py`
- Test: `tests/unit/test_candidate_fusion.py`

- [ ] **Step 1：对每个商品裁剪独立运行条码和OCR**
- [ ] **Step 2：从知识库召回Top-20候选**
- [ ] **Step 3：用条码、品牌、规格、口味和容量执行硬过滤**
- [ ] **Step 4：验证硬冲突不可被视觉相似度覆盖**

  Run: `pytest tests/unit/test_candidate_fusion.py -v`

  Expected: 条码唯一命中优先；条码冲突进入人工审核；规格或口味冲突的候选不会自动通过。

### Task 7：实现本地视觉大模型裁决

**Files:**
- Create: `src/adjudication/prompt.py`
- Create: `src/adjudication/vlm.py`
- Create: `src/adjudication/schema.py`
- Create: `configs/policies/decision_rules.yaml`
- Test: `tests/contract/test_vlm_output_schema.py`

- [ ] **Step 1：限制大模型输入为商品裁剪、结构化证据和Top-K候选**
- [ ] **Step 2：要求输出结构化结论**

```json
{
  "decision": "matched|unknown|conflict|unreadable",
  "sku_id": "SKU-001",
  "confidence_band": "high|medium|low",
  "evidence": ["barcode", "ocr:500ml", "visual:front-packaging"],
  "conflicts": [],
  "prompt_version": "prompt-0001"
}
```

- [ ] **Step 3：禁止模型写入知识库或直接批准自身预测**
- [ ] **Step 4：验证非法SKU、缺少证据和非JSON输出均进入人工队列**

### Task 8：接入Label Studio预标注和审核

**Files:**
- Create: `configs/label-studio/label_config.xml`
- Create: `src/labeling/ml_backend.py`
- Create: `src/labeling/converter.py`
- Create: `src/labeling/webhook.py`
- Test: `tests/integration/test_label_studio_roundtrip.py`

- [ ] **Step 1：配置矩形框、SKU、未知、冲突和不可判定标签**
- [ ] **Step 2：把识别结果转换为Label Studio prediction格式**
- [ ] **Step 3：Webhook只做鉴权、验签、持久化和快速应答，后台Worker异步处理**
- [ ] **Step 4：验证预测→人工修改→反馈事件完整往返**

  Run: `pytest tests/integration/test_label_studio_roundtrip.py -v`

  Expected: prediction携带模型版本和分数；修改后产生一条新的review_event；原预测不被覆盖。

### Task 9：构建数据集版本

**Files:**
- Create: `src/datasets/builder.py`
- Create: `src/datasets/splitter.py`
- Create: `src/datasets/export_yolo.py`
- Create: `scripts/build_gold_set.py`
- Test: `tests/unit/test_dataset_leakage.py`

- [ ] **Step 1：仅使用人工确认或批准的标签**
- [ ] **Step 2：按拍摄批次、门店或来源分组切分，防止近重复图片跨训练和测试集**
- [ ] **Step 3：金标准集冻结并独立授权**
- [ ] **Step 4：验证零泄漏**

  Run: `pytest tests/unit/test_dataset_leakage.py -v`

  Expected: 相同原图、近重复图和同一连续拍摄批次不会跨数据集；金标准ID不出现在训练清单。

### Task 10：训练YOLO26并登记模型

**Files:**
- Create: `src/training/yolo_trainer.py`
- Create: `src/training/registry.py`
- Create: `scripts/run_training.py`
- Test: `tests/integration/test_training_smoke.py`

- [ ] **Step 1：从不可变dataset_version生成YOLO数据清单**
- [ ] **Step 2：记录代码版本、数据版本、参数、随机种子、指标和权重哈希**
- [ ] **Step 3：运行小数据冒烟训练**

  Run: `python scripts/run_training.py --dataset-version demo-v1 --epochs 1 --model yolo26n.pt`

  Expected: 生成MLflow实验和未发布model_version，不修改生产默认模型。

### Task 11：建立固定评测和发布门

**Files:**
- Create: `src/evaluation/metrics.py`
- Create: `src/evaluation/slices.py`
- Create: `src/release/gate.py`
- Create: `scripts/evaluate_release.py`
- Test: `tests/regression/test_release_gate.py`

- [ ] **Step 1：计算检测、SKU、未知拒识和人工效率指标**
- [ ] **Step 2：按SKU、包装版本、光照、遮挡和拍摄设备输出分组指标**
- [ ] **Step 3：只有全部硬门槛通过才允许进入影子运行**
- [ ] **Step 4：验证任何一项硬门槛失败都会阻止发布**

  Run: `pytest tests/regression/test_release_gate.py -v`

  Expected: 所有失败分支均返回可解释原因，当前生产模型保持不变。

### Task 12：影子运行、提升和回滚

**Files:**
- Create: `src/release/shadow.py`
- Create: `src/release/promote.py`
- Create: `src/release/rollback.py`
- Create: `docs/release-policy.md`
- Test: `tests/integration/test_model_rollback.py`

- [ ] **Step 1：新模型先在真实流量副本上运行，不影响业务结果**
- [ ] **Step 2：比较新旧模型分歧并抽样人工复核**
- [ ] **Step 3：提升操作记录审批人、时间、模型、数据、知识和提示词版本**
- [ ] **Step 4：验证一键回滚**

  Run: `pytest tests/integration/test_model_rollback.py -v`

  Expected: 回滚后生产路由恢复旧版本，历史预测和发布记录完整保留。

### Task 13：生产运行与安全审计

**Files:**
- Create: `src/api/main.py`
- Create: `src/api/auth.py`
- Create: `src/api/routes/recognize.py`
- Create: `src/api/routes/audit.py`
- Create: `docs/operations-runbook.md`
- Test: `tests/integration/test_api_permissions.py`

- [ ] **Step 1：识别接口只能创建新运行，不能覆盖历史**
- [ ] **Step 2：审计接口只读，禁止任意SQL和任意文件路径读取**
- [ ] **Step 3：记录图片哈希、模型版本、知识版本、提示词版本和决策证据**
- [ ] **Step 4：验证越权、重放、超时和模型不可用场景**

## 3. 里程碑和停止条件

### M0：范围冻结，1周

交付：场景定义、SKU清单、标注规范、金标准协议、许可证结论。

停止条件：无法取得至少30个高相似SKU及现场图片，或无法确定人工最终审核责任人。

### M1：技术验证，2～4周

交付：知识库、三条基线、500张金标准评测报告。

停止条件：Top-5低于95%，或未知SKU错误接纳率高于3%，应先修复数据和候选召回，不进入平台扩建。

### M2：MVP闭环，6～10周

交付：Label Studio预标注、追加式反馈、数据版本、YOLO训练、发布门。

停止条件：审计覆盖率低于100%，或错误自动通过率高于2%。

### M3：受控试点，3～6个月

交付：真实业务影子运行、人工效率报告、回滚演练、知识库更新流程。

停止条件：连续两轮评测未改善人工时间，或分组指标显示关键SKU持续退化。

### M4：生产扩展，6～12个月以上

进入条件：试点门槛全部通过，业务负责人接受剩余人工量，许可证和硬件成本已获批。

## 4. 角色分工

| 角色 | 核心责任 |
|---|---|
| 项目负责人/业务Owner | 冻结范围、确认验收门槛、批准上线 |
| 商品知识负责人 | SKU主数据、条码、规格、包装版本和冲突规则 |
| CV工程师 | 检测、检索、YOLO训练、指标分析 |
| 后端/MLOps工程师 | API、事件、数据版本、模型注册、发布和回滚 |
| 标注负责人 | 标注规范、审核一致性、金标准维护 |
| 安全/法务 | 数据权限、许可证、保留和审计要求 |

## 5. 首次执行顺序

1. 先完成Task 1并由业务负责人签字确认。
2. 完成Task 2～4，得到可查询的知识库和可复现环境。
3. 并行比较Task 5～7的三条识别路线，但统一使用同一金标准。
4. 只有技术验证门槛通过后，才实现Task 8～10的闭环训练。
5. Task 11～13作为任何生产试点的硬前置，不允许以演示版本替代。

## 6. 自审结论

- 需求覆盖：Label Studio、自动画框、本地视觉大模型、外挂知识库、人工审核、YOLO训练、YOLO反馈和持续学习均有明确任务。
- 边界覆盖：未知SKU、不可判定、硬冲突、审计、版本、回滚和许可证均纳入计划。
- 数据防污染：自动预测不能成为金标准；反馈追加保存；金标准与训练集强制隔离。
- 实施策略：先验证SKU候选召回和未知拒识，再扩建平台，避免把失败的识别方案包装成完整系统。
