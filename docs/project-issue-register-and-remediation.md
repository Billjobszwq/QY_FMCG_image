# 项目问题清单与技术修复指南

> 文档状态：待评审  
> 审查基线：2026-08-03  
> 适用项目：LLM-Image 通用 SKU 图像识别系统  
> 审查方式：只读架构审查、静态代码检查、数据资产一致性检查、无副作用测试  
> 变更说明：本文只记录问题与修复方案，尚未实施任何代码、配置、数据库或模型修改。

## 1. 文档目的

本文是项目当前问题的统一登记表，也是后续修复工作的技术实施依据。目标是让研发、算法、数据和运维人员能够回答以下问题：

1. 当前系统哪里存在确定缺陷。
2. 缺陷会影响哪些用户、数据、模型或服务。
3. 缺陷的根因是什么，而不只是表面症状。
4. 应按什么技术方案修复。
5. 如何证明修复已经生效，并且没有引入新的数据污染或回归。

本文不替代 [`architecture.md`](./architecture.md)、[`runbook.md`](./runbook.md) 和 [`handbook.md`](./handbook.md)。这些文件解释系统设计和运行方式，本文专门记录实现与设计之间的偏差、已确认 Bug 以及治理缺口。

## 2. 严重等级

| 等级 | 定义 | 处理要求 |
|---|---|---|
| P0 | 会直接产生错误业务结果、训练错误模型、绕过人工门，或在共享环境中造成不可接受的数据与安全风险 | 阻断正式发布；修复后必须完成专项回归和上线前验收 |
| P1 | 会导致模型发布不一致、审计缺失、数据损坏、服务被滥用或并发状态丢失 | 在下一次功能扩展前完成；不得继续扩大受影响入口 |
| P2 | 当前主要影响可维护性、可复现性、操作体验或文档可信度 | 纳入工程治理迭代，避免继续积累技术债 |

本文的安全等级按“服务可能被浏览器、局域网或其他进程访问”评估。如果所有服务永久限制在单用户本机回环地址，部分安全问题可降低一级，但仍需修复，因为恶意网页也可能访问本机 HTTP 服务。

## 3. 审查范围与验证结果

### 3.1 覆盖范围

- 数据与知识库：`src/common`、`src/catalog`、`src/field`、`src/data`
- 自动标注与人工审核：`src/labeling`、`src/ls_platform`、`src/ls_ml_backend`
- 训练与模型：`src/training`、`src/cascade`、`.models`、`.datasets`
- 在线识别：`src/recognize`、`src/pipeline`
- 评测与监控：`src/eval`、`src/training/monitor.py`
- 基础设施：`compose.yaml`、`migrations`、`.env.example`
- 文档与测试：`docs`、`tests/unit`、`tests/contract`

### 3.2 已完成的无副作用验证

- 76 个 Python 文件均能完成 AST 语法解析，未发现语法错误。
- `pytest -p no:cacheprovider tests/unit tests/contract -q` 执行结果为 `22 passed`。
- 测试前后源码、测试、脚本、配置和迁移文件的元数据哈希一致。
- 当前主要 YOLO 数据集未发现 train/val 文件名或目标文件交叉。
- `crop_dataset_yolo` 汇总记录为 65,648 张裁剪图，但磁盘实际为 64,087 张，相差 1,561 张。
- 当前 SQLite 中只有一个 `model_version`，状态为 `trained`，权重指向 sku_v1；sku_v4 和分类器虽然存在于磁盘，但不在当前在线模型选择链路中。

现有 22 个测试主要覆盖命名、别名、SKU 对齐和原始资产只读契约。它们没有覆盖复训闭环、在线模型加载、模型切换、安全接口、审计完整性、并发和数据库迁移，因此测试通过不能证明当前平台闭环可用于正式业务。

## 4. 当前架构与主要断点

项目同时存在三代实现：

1. KB/VLM + 自建审核页 + 旧识别 API。
2. Label Studio + 编排 API + 单阶段 YOLO。
3. 文档规定的 sku_v4 YOLO 画框器 + 分类器精识别级联架构。

目前三个关键闭环没有真正连通：

```mermaid
flowchart LR
    A["Label Studio 人工审核"] --> B["export_yolo 导出数据集"]
    B -. "dataset_yaml 未传给 train" .-> C["train_v1 默认训练数据"]
    C --> D["model_version 登记"]
    D -. "编排层只改数据库状态" .-> E["进程内已缓存的在线模型"]
    E -. "dashboard 入口不写审计" .-> F["recognition_run"]
```

这意味着“人工修正进入训练”“新模型立即上线”“每次识别完整留痕”三个核心承诺目前都不能成立。

## 5. 问题总表

| ID | 等级 | 模块 | 问题 | 主要后果 | 状态 |
|---|---|---|---|---|---|
| ISSUE-001 | P0 | 复训闭环 | 导出的 Label Studio 数据集没有传给训练函数 | 训练并上线错误数据集产生的模型 | Open |
| ISSUE-002 | P0 | 在线识别 | 在线入口没有使用文档规定的级联识别器 | sku_v4 与分类器资产没有进入热路径 | Open |
| ISSUE-003 | P0 | 模型加载 | 业务权重缺失时回退 COCO 模型并映射为业务 SKU | 输出确定性错误的 SKU | Open |
| ISSUE-004 | P0 | 人工审核 | 模型预测可被批量转成人工 annotation | 自动结果绕过人工门进入训练 | Open |
| ISSUE-005 | P1 | 模型发布 | production/trained 混选，切换不下线旧版本且不刷新缓存 | 数据库状态与实际在线模型不一致 | Open |
| ISSUE-006 | P1 | 模型版本 | 固定 run_name 和可覆盖权重破坏版本不可变性 | 历史版本无法可靠回滚和审计 | Open |
| ISSUE-007 | P1 | 识别审计 | 部分入口不写审计，写入失败被静默忽略 | 无法达到全量识别留痕 | Open |
| ISSUE-008 | P1 | 数据契约 | 照片 ID 在整数和字符串之间不一致 | 旧审核页、图片加载和数据集构建失败 | Open |
| ISSUE-009 | P1 | AI 裁决 | VLM 可选择候选集以外 SKU，置信度绑定错误候选 | 硬过滤失效，高置信自动误判 | Open |
| ISSUE-010 | P1 | 审核工作台 | photo_id 可目录穿越，框坐标未校验 | 越界写文件或生成非法训练标签 | Open |
| ISSUE-011 | P1 | 平台安全 | 编排层无认证、通配 CORS，并提供删除和模型切换 | 浏览器或网络调用可修改关键状态 | Open |
| ISSUE-012 | P1 | ML 后端 | 任意 URL 图片下载形成 SSRF，错误又返回空成功 | 内网资源被访问，失败难以发现 | Open |
| ISSUE-013 | P1 | 分类数据集 | 裁剪文件名碰撞且输出目录非全新构建 | 样本被覆盖、统计错误、重复运行残留旧数据 | Open |
| ISSUE-014 | P1 | 任务与 Webhook | jobs.json 非原子并发写；Webhook 无验签和幂等 | 任务丢失、重复审计、伪造审核事件 | Open |
| ISSUE-015 | P1 | 凭据 | 管理员密码硬编码并打印，`.env` 权限过宽 | 凭据泄漏和未授权登录 | Open |
| ISSUE-016 | P1 | 数据库基础设施 | Compose 未创建业务表，迁移文件是 SQLite 方言 | PostgreSQL 方案无法按文档部署 | Open |
| ISSUE-017 | P2 | 审核前端 | “下一张”按钮引用未初始化变量；动态内容未转义 | 页面报错并存在存储型 XSS 风险 | Open |
| ISSUE-018 | P2 | 文档与入口 | 8090/8091 旧链路与 830x/级联链路同时被描述为当前方案 | 操作者可能启动错误服务 | Open |
| ISSUE-019 | P2 | 资产版本 | KB、评测和状态文件直接覆盖，缺少原子版本发布 | 中断后文件组合不一致、历史结果丢失 | Open |
| ISSUE-020 | P2 | 工程治理 | 无依赖锁、无项目级构建定义、当前目录非 Git 仓库、集成测试缺失 | 环境难复现，缺陷难回归，变更不可追踪 | Open |

## 6. P0 问题详细说明

### ISSUE-001：复训使用了错误的数据集

**代码证据**

- [`src/ls_platform/task_runners.py:97-107`](../src/ls_platform/task_runners.py#L97-L107) 计算了 `yaml`，调用 `train()` 时没有传入 `data_yaml`。
- [`src/ls_platform/task_runners.py:110-148`](../src/ls_platform/task_runners.py#L110-L148) 导出 Label Studio 审核数据后再次遗漏 `data_yaml`，随后可能把本次模型设置为 production。
- [`src/training/train_v1.py:34-43`](../src/training/train_v1.py#L34-L43) 在没有参数时回退到 `.training_data/data.yaml`。

**影响**

用户认为模型吸收了本轮人工修正，实际训练数据仍是旧默认数据。训练任务表面成功、模型也可能被自动上线，因此该问题比普通参数遗漏更危险：系统会给出一个看似完成、实际上数据来源错误的闭环结果。

**根因**

任务层只把数据集路径写入返回摘要，没有把它作为训练函数的强制输入；训练函数又允许隐式默认数据集，使调用错误没有立即失败。

**修复方案**

1. `train_job()` 和 `retrain_job()` 必须显式传入 `data_yaml=yaml`。
2. 复训任务禁止使用隐式默认数据集。可以在训练函数增加 `require_explicit_data=True`，或者单独提供复训入口。
3. 训练前读取 `data.yaml`，检查 train/val 路径、类别数、类别表和样本数量。
4. 计算数据集 manifest 哈希，写入 `dataset_version` 和 `model_version.data_version`。
5. 训练元信息中的 `dataset`、`data_yaml`、样本数量和哈希必须与任务返回值一致。
6. 自动切换前重新读取模型登记记录，确认本次 `mv_id` 绑定的 `data_version` 就是本次导出的版本。

**建议接口形态**

```python
mv_id = train(
    data_yaml=yaml,
    run_name=unique_run_name,
    dataset_desc=f"label-studio:{project_id}:{dataset_hash}",
    epochs=epochs,
    imgsz=imgsz,
    batch=batch,
    device="mps",
    model_name=model,
)
```

**验收标准**

- 修改一条 Label Studio 人工标注并发起复训，训练日志和 `train_meta.json` 必须指向本次导出的目录。
- `model_version.data_version` 能反查到该数据集 manifest。
- 将默认数据集临时设置为不可用时，复训仍能使用显式数据集完成；反之，缺少显式数据集时任务必须失败。
- 自动切换只发生在上述校验全部通过之后。

### ISSUE-002：在线识别没有使用级联模型

**代码证据**

- [`docs/architecture.md:53-62`](./architecture.md#L53-L62) 规定 sku_v4 YOLO 只负责画框，分类器负责精识别。
- [`src/cascade/cascade_inference.py:40-124`](../src/cascade/cascade_inference.py#L40-L124) 实现了 `CascadeRecognizer`。
- [`src/recognize/service.py:92-126`](../src/recognize/service.py#L92-L126) 仍直接使用单个 YOLO 类别作为最终 SKU。
- `src/ls_ml_backend`、`src/ls_platform/task_runners.py` 和 dashboard 编排入口都继续调用 `detect_and_recognize()`。

**影响**

文档、监控和磁盘资产显示项目已经演进到级联方案，但线上结果仍来自旧单阶段 YOLO。分类器的精识别能力和低置信兜底没有进入业务接口，离线指标与线上指标不可直接比较。

**修复方案**

1. 建立唯一的 `RecognitionEngine` 业务接口，内部加载一个完整模型包。
2. 模型包至少包含检测权重、分类权重、分类器 `classes`、SKU registry 哈希和阈值配置。
3. `/v2/recognize`、`/recognize/run`、ML backend 和批量识别任务全部调用同一实例。
4. 低置信结果必须显式返回 `needs_review=true`，不能只通过 `source` 字符串暗示。
5. 健康接口返回检测器版本、分类器版本、registry 版本、模型包哈希和加载时间。
6. 在迁移期间保留旧引擎只能作为明确命名的 `legacy` 模式，不得自动回退。

**验收标准**

- 启动日志和健康接口同时报告 sku_v4 检测器及分类器版本。
- 对固定回归图片运行服务接口和 `CascadeRecognizer`，结果在相同配置下完全一致。
- 删除分类器权重后服务启动失败，不允许自动退回单阶段业务输出。
- 所有在线入口的模型版本字段都来自同一个模型包。

### ISSUE-003：通用 COCO 模型被错误映射为业务 SKU

**代码证据**

- [`src/recognize/service.py:78-88`](../src/recognize/service.py#L78-L88) 在业务权重缺失时加载 `yolo11n.pt`。
- [`src/recognize/service.py:101-122`](../src/recognize/service.py#L101-L122) 按业务 registry 的 `class_id` 解释模型输出。

**影响**

COCO 的 class 0、1、2 等代表通用物体，业务 registry 的相同数字代表饮料 SKU。服务会把通用物体稳定映射成错误商品，这不是低置信问题，而是类别语义完全不同。

**修复方案**

1. 删除业务服务中的通用模型自动回退。
2. 模型加载时验证 `model.names`、类别数量和模型包中的 registry 哈希。
3. 任何校验不一致都进入 `MODEL_UNAVAILABLE`，健康检查返回非健康状态。
4. 如确实需要通用瓶身检测器，必须使用独立检测任务和独立类别解释器，再进入后续 SKU 分类器，不能直接复用业务 class ID。

**验收标准**

- 权重文件不存在、损坏或类别不匹配时，不返回任何业务 SKU。
- 自动测试构造一个 COCO 模型结果，确认业务映射函数拒绝处理。
- 只有模型包内声明的类别映射可以进入结果生成阶段。

### ISSUE-004：模型预测可绕过人工门

**代码证据**

- [`src/ls_platform/orchestrator.py:277-300`](../src/ls_platform/orchestrator.py#L277-L300) 未指定任务时可把项目全部 prediction 转为 annotation。
- [`src/ls_platform/exporter.py:81-105`](../src/ls_platform/exporter.py#L81-L105) 对缺少状态的区域默认使用 `matched`。
- [`src/ls_platform/importer.py:118-129`](../src/ls_platform/importer.py#L118-L129) 将外部种子预测标记为 `ground_truth_xlsx` 且 score 为 1.0。

**影响**

系统无法证明训练标签经过真实人工确认。错误预测可能先被批量转成 annotation，再被 exporter 视为 matched，最终进入下一轮训练并形成错误自强化。

**修复方案**

1. prediction、annotation、review decision 使用不同的数据类型和状态机。
2. 移除“未提供 task_ids 就全量接受”的行为。
3. 接受预测必须记录真实用户 ID、原 prediction ID、接受时间、修改内容和审核动作。
4. exporter 采用拒绝式默认值：缺状态、缺审核人、缺完成时间时一律跳过。
5. 训练集准入条件建议固定为：`annotation.completed_by != null`、`review_status == approved`、所有区域显式 `matched`、SKU 属于当前 registry、框合法。
6. 外部 Excel 种子使用 `external_seed` 或 `weak_label`，不得命名为 ground truth。

**验收标准**

- 只有 prediction 的任务导出 0 个训练标签。
- 缺审核人或缺状态的 annotation 导出 0 个训练标签，并在报告中给出跳过原因。
- 批量接受接口必须要求明确任务列表、授权用户和确认参数。
- 训练集 manifest 能追溯每个标签对应的人工审核事件。

## 7. P1 问题详细说明

### ISSUE-005：模型选择、切换和实际加载状态不一致

**证据与根因**

- [`src/recognize/service.py:52-64`](../src/recognize/service.py#L52-L64) 将 `production` 和 `trained` 混合后按时间取最新。
- [`src/recognize/service.py:212-230`](../src/recognize/service.py#L212-L230) 设置新 production 时没有下线其他版本。
- [`src/ls_platform/orchestrator.py:80-89`](../src/ls_platform/orchestrator.py#L80-L89) 只更新数据库，不刷新识别进程已缓存的模型。

数据库中的“当前模型”和进程内真正执行推理的模型可能不同，健康接口也可能只报告数据库最新记录而不是实际加载状态。

**修复方案**

1. 只允许 `status='production'` 的模型进入线上加载。
2. 模型切换使用单事务：验证目标模型、将旧 production 改为 retired、将目标设为 production、写发布事件。
3. 增加“一任务一个 production”数据库约束或受控发布表。
4. 编排层通过识别服务的受保护管理接口执行加载，并等待健康检查确认新哈希。
5. 切换失败时回滚数据库状态和进程模型，保留明确的发布失败事件。

**验收标准**

- 任意时刻每个任务只有一个 production。
- 切换响应返回的模型哈希与随后健康检查、下一次识别审计完全一致。
- 目标权重缺失或加载失败时，旧模型继续服务且数据库保持旧 production。

### ISSUE-006：模型权重不是不可变版本

[`src/training/train_v1.py:67-75`](../src/training/train_v1.py#L67-L75) 使用固定 `run_name` 和 `exist_ok=True`；[`src/training/train_v1.py:118-128`](../src/training/train_v1.py#L118-L128) 把相同可变路径登记到不同模型版本。

**修复方案**

- 每次训练使用 `task + UTC 时间 + 数据哈希 + 短 UUID` 的唯一目录。
- 训练完成后将最佳权重复制或移动到按 SHA-256 命名的只读模型仓库。
- `model_version` 保存完整 SHA-256、数据版本、代码版本、配置版本、类别表哈希和父模型。
- 发布前重新计算权重哈希，发现变化立即拒绝发布。
- 回滚只选择历史不可变模型包，不使用 mutable `best.pt` 别名。

**验收标准**：连续训练两次产生不同目录；旧权重哈希不变；任一历史版本可独立加载并复现其健康信息。

### ISSUE-007：识别审计不完整且会静默丢失

[`src/ls_platform/orchestrator.py:208-224`](../src/ls_platform/orchestrator.py#L208-L224) 的 dashboard 入口不写审计；[`src/recognize/service.py:191-204`](../src/recognize/service.py#L191-L204) 捕获审计异常后直接继续返回 200。毫秒时间戳 `run_id` 在并发时也可能冲突。

**修复方案**

- 生成 UUIDv4 或 UUIDv7 作为 run ID。
- 将“推理 + 审计”封装为唯一业务函数，禁止入口自行拼装结果。
- 审计至少保存输入来源、图片哈希、模型包、阈值、结果、耗时和错误。
- 采用可靠 outbox：识别结果和待写审计先在本地事务中落盘，再异步送入最终审计表。
- 如果业务要求 100% 留痕，审计无法持久化时返回明确失败或 `audit_pending`，不能伪装成普通成功。
- SQLite 开启 WAL、busy timeout，并对锁冲突做有限重试。

**验收标准**：并发运行 1,000 次识别，run ID 无重复；成功识别数与审计记录数一致；模拟数据库锁冲突后无静默丢失。

### ISSUE-008：照片 ID 类型不统一

[`src/labeling/review_server.py:30-36`](../src/labeling/review_server.py#L30-L36) 使用 manifest 原始整数作字典键，HTTP 路由返回字符串；[`src/training/dataset.py:19-39`](../src/training/dataset.py#L19-L39) 使用整数索引查找字符串文件 stem。

当前只读验证已经确认：manifest 首个 ID 为整数，路由 ID 和 approved 文件 stem 为字符串，查找均失败。

**修复方案**

- 定义 `AssetId = str`，所有输入边界立即执行 `str(value)`。
- manifest 加载器统一规范化 ID，不允许业务模块各自解析。
- 文件名、数据库、API 和 Label Studio meta 均保存同一个规范字符串。
- 增加历史 manifest 兼容层，但写出时只允许新格式。

**验收标准**：同一个 ID 能贯通照片列表、图片获取、审核提交、approved 文件和数据集构建；整数历史数据通过兼容层正常读取。

### ISSUE-009：VLM 裁决越过候选边界

[`src/labeling/assign.py:56-69`](../src/labeling/assign.py#L56-L69) 会解析任何已知 SKU，却没有验证结果属于 `option_ids`；[`src/labeling/assign.py:91-104`](../src/labeling/assign.py#L91-L104) 使用 top1 分数评估另一个被选候选，并把“种子在 top3”当作高置信验证。

**修复方案**

- VLM 响应使用 JSON schema，并校验 `pick in option_ids | {unknown, conflict}`。
- 任何越界结果转换为 `conflict` 并强制人工复核。
- 置信度使用所选候选的检索分数、OCR 属性一致性和 VLM 选择共同计算。
- Mode B 只有 `pick == prior_canon` 才能标记 validated；进入 top3 只能作为候选证据。
- 将决策规则写成纯函数并建立表驱动测试。

**验收标准**：构造 VLM 返回候选外 SKU 时无法进入训练提案；VLM 与种子不一致时始终 `needs_review=true`。

### ISSUE-010：审核工作台目录穿越与非法坐标

[`src/labeling/workbench.py:256-290`](../src/labeling/workbench.py#L256-L290) 的审核接口没有确认 `photo_id` 存在；[`src/labeling/workbench.py:295-318`](../src/labeling/workbench.py#L295-L318) 直接把 ID 拼接成路径，并且没有验证框坐标。

**修复方案**

```python
pid = str(body.get("photo_id", ""))
if pid not in state["photos"]:
    raise NotFound(pid)

approved_root = APPROVED_DIR.resolve()
target = (approved_root / f"{pid}.txt").resolve()
if target.parent != approved_root:
    raise ValueError("invalid photo_id")
```

同时对每个框执行：四个值均为有限数字、`0 <= x1 < x2 <= W`、`0 <= y1 < y2 <= H`、最小尺寸达到阈值。审核 JSON、事件和 approved 标签应先写临时文件，再作为一个受控提交单元发布。

**验收标准**：`../`、绝对路径、空 ID、NaN、Infinity、负坐标、反向框、越界框全部被 400 拒绝；项目目录外没有任何文件变化。

### ISSUE-011：平台控制面无认证

[`src/ls_platform/orchestrator.py:96-114`](../src/ls_platform/orchestrator.py#L96-L114) 返回通配 CORS；同一服务允许导入、训练、复训、批量接受预测、模型切换和删除项目，删除逻辑位于 [`src/ls_platform/orchestrator.py:315-325`](../src/ls_platform/orchestrator.py#L315-L325)。

**修复方案**

- 所有管理接口要求 Bearer token 或受信反向代理身份。
- 权限至少拆分为 viewer、reviewer、trainer、model-admin、dataset-admin。
- CORS 使用明确前端 Origin 白名单；带凭据写操作校验 Origin 和 CSRF token。
- 删除、全量接受、production 切换要求二次确认参数和操作审计。
- 默认只监听 `127.0.0.1`；对外部署必须通过 TLS 反向代理。
- 设置请求体上限、速率限制和操作超时。

**验收标准**：无 token 的所有写接口返回 401；普通 reviewer 无法训练、切换模型或删除项目；恶意 Origin 预检失败。

### ISSUE-012：ML 后端 SSRF 与静默失败

[`src/ls_ml_backend/yolo_backend.py:42-64`](../src/ls_ml_backend/yolo_backend.py#L42-L64) 接受任意 HTTP URL，可能让服务端访问本机或内网地址；[`src/ls_ml_backend/yolo_backend.py:136-155`](../src/ls_ml_backend/yolo_backend.py#L136-L155) 将下载和推理异常转换为空结果成功响应。

**修复方案**

- 只允许已配置的 Label Studio 域名、受控对象存储域名或合法 `data:` URI。
- 解析 DNS 后拒绝回环、链路本地、私有网段和云元数据地址，并在重定向后重复校验。
- 限制下载字节数、Content-Type、图片像素和解码时间。
- 区分“真实无检测结果”和“下载/解码/推理失败”，失败必须进入错误字段和日志。

**验收标准**：访问 `127.0.0.1`、私网、重定向私网和超大响应均被拒绝；模型真实返回空框与异常响应可被监控区分。

### ISSUE-013：分类裁剪文件覆盖和残留

[`src/cascade/build_yolo_crop_dataset.py:70-72`](../src/cascade/build_yolo_crop_dataset.py#L70-L72) 只创建已有输出目录，不构建全新版本；[`src/cascade/build_yolo_crop_dataset.py:126-129`](../src/cascade/build_yolo_crop_dataset.py#L126-L129) 仅用照片 ID 和取整后的左上角坐标命名文件。

当前 `dataset_summary.json` 与实际文件数相差 1,561，说明计数次数不等于最终文件数。可能原因包括同名覆盖以及重复构建残留。

**修复方案**

- 文件名加入原始框序号或完整框坐标哈希，例如 `{photo_id}_{box_index}_{box_hash}.jpg`。
- 每次在 `.datasets/staging/<dataset_id>` 全新构建，禁止写入旧版本目录。
- 完成后重新扫描实际图片与标签，核对总数、每类数量和 train/val 照片隔离。
- 校验通过后原子更新 current 指针，不覆盖历史数据集。

**验收标准**：汇总数、磁盘文件数和 manifest 数完全一致；使用相同输入重复构建得到相同哈希；改变 seed 后不会留下旧文件。

### ISSUE-014：任务持久化与 Webhook 不可靠

[`src/ls_platform/jobs.py:28-50`](../src/ls_platform/jobs.py#L28-L50) 直接读写整个 `jobs.json`，`create_job()` 没有使用锁；解析错误会返回空字典，下一次保存可能覆盖全部历史。Webhook 处理见 [`src/ls_platform/webhook.py:42-79`](../src/ls_platform/webhook.py#L42-L79)，目前没有签名校验、事件唯一键和真实审核人。

**修复方案**

- 将任务状态迁入 SQLite，使用事务和唯一 job ID；任务结果使用临时文件加原子替换。
- 如果暂时保留 JSON，所有读改写必须共用进程锁和跨进程文件锁，解析失败时停止写入而不是返回空对象。
- Webhook 使用共享密钥或签名头验签。
- 保存 Label Studio event ID，并添加唯一约束实现幂等，即同一事件重复到达只处理一次。
- 从 payload 中提取真实用户信息，不能使用 `ls_webhook:动作` 代替审核人。

**验收标准**：并发创建 100 个任务无丢失；中途模拟进程退出后 jobs 状态仍可解析；重复发送同一 Webhook 只新增一条审计；伪造签名被拒绝。

### ISSUE-015：凭据硬编码和文件权限过宽

[`src/ls_platform/bootstrap.py:16-18`](../src/ls_platform/bootstrap.py#L16-L18) 硬编码管理员密码；[`src/ls_platform/bootstrap.py:100-132`](../src/ls_platform/bootstrap.py#L100-L132) 将 token 和密码写入 `.env` 并打印登录信息。当前 `.env` 权限为 `0644`，且包含已设置的敏感值。Compose 和启动脚本还开启了无需邀请注册。

**修复方案**

- 删除代码中的固定密码，由环境变量或首次启动安全输入提供。
- 首次初始化生成随机高强度密码，输出一次后要求立即更换。
- `.env` 写入后执行 `chmod 600`，日志不得输出 token 片段或密码。
- 关闭公开注册，限制管理员创建流程。
- 立即轮换当前 Label Studio、OMLX、Postgres 和对象存储凭据。

**验收标准**：仓库文本中没有固定凭据；启动日志不出现秘密；权限测试确认 `.env` 只有当前用户可读写；默认注册关闭。

### ISSUE-016：PostgreSQL 部署链路不成立

[`compose.yaml:3-15`](../compose.yaml#L3-L15) 只加载 `000_init.sql`，不会创建业务表；[`migrations/001_schema.sql`](../migrations/001_schema.sql) 使用 `AUTOINCREMENT` 和 `RAISE()` 等 SQLite 语法，却被文档描述为 PostgreSQL 同构迁移。

**修复方案**

- 拆分 `migrations/sqlite` 与 `migrations/postgres`。
- 用正式迁移工具维护版本，不让应用每次连接都执行整份 schema。
- PostgreSQL 迁移使用 identity/bigserial、标准触发器函数、JSONB、外键、NOT NULL、CHECK 和必要索引。
- Compose 初始化必须执行完整迁移，应用启动前运行 schema version 检查。
- CI 分别从空 SQLite 和空 PostgreSQL 验证迁移及核心 CRUD 契约。

**验收标准**：全新 Compose 环境启动后八张业务表和约束存在；应用能完成模型登记、审核事件和识别审计；SQLite 与 PostgreSQL 契约测试结果一致。

## 8. P2 问题详细说明

### ISSUE-017：审核前端按钮错误与 XSS

[`src/labeling/review.html:78`](../src/labeling/review.html#L78) 使用 `let k=(k+1)%v.length`，初始化时引用自身会触发 `ReferenceError`。同文件多处把 SKU、种子名称和状态直接拼入 `innerHTML`。

**修复方案**：先通过 `v.indexOf(ptr)` 初始化索引；空列表时禁止翻页；所有文本使用 `textContent`，选项通过 DOM API 创建；如必须使用 HTML 模板，统一转义并设置内容安全策略。

**验收标准**：首张、末张、仅待审为空、切换过滤条件均能正常翻页；包含 HTML 标签的 SKU 名称只能按普通文本显示。

### ISSUE-018：文档与入口漂移

[`docs/runbook.md`](./runbook.md) 仍把 8090/8091 旧链路放在完整流程和常驻服务部分，后文又声明系统已演进到级联架构。`docs/README.md`、`handbook.md`、运行脚本和真实在线服务并未共享同一个服务清单。

**修复方案**

- 确认一个受支持的当前架构和唯一入口。
- 将旧入口移动到 `legacy` 命名空间或明确标注“只用于历史回归，禁止生产”。
- 维护机器可读的服务清单，包括端口、启动命令、健康地址、模型类型和是否可写。
- README、runbook、handbook 从该清单生成或由文档测试检查一致性。

**验收标准**：新成员只按 README 能启动正确服务；所有文档中的端口、命令、模型链路一致；旧服务不会被默认脚本启动。

### ISSUE-019：KB、评测和状态资产缺少版本与原子发布

[`src/catalog/store.py:30-37`](../src/catalog/store.py#L30-L37) 分三次覆盖 SKU、向量和 ID；进程在中间退出会产生不匹配组合。[`src/pipeline/autolabel.py:65-68`](../src/pipeline/autolabel.py#L65-L68) 每次运行删除旧进度，最终报告也固定覆盖。

**修复方案**

- 所有复合资产写入唯一 staging 目录。
- manifest 保存文件名、大小、哈希、schema version、输入版本和生成参数。
- 加载前验证 manifest 与所有文件哈希。
- 发布时原子替换 current 指针，历史版本只读保留。
- 评测使用 run ID 输出，另生成 `latest.json` 指针，不删除历史进度。

**验收标准**：模拟任意写入阶段中断时，旧 current 版本仍可加载；任一历史评测可按 run ID 查询；向量行数与 ID 数不一致时加载器明确拒绝。

### ISSUE-020：工程复现与测试覆盖不足

项目根目录没有 `pyproject.toml`、正式 requirements 或依赖锁文件；当前目录也不是 Git 仓库。现有测试没有覆盖系统最关键的跨模块闭环。

**修复方案**

1. 建立 `pyproject.toml`，区分 runtime、training、dev 和 optional infrastructure 依赖。
2. 锁定 Python 与核心依赖版本，记录 Torch、Torchvision、Ultralytics 和模型格式兼容性。
3. 初始化或恢复版本控制，明确忽略本地密钥、大模型、缓存和运行时数据；历史业务资产是否纳入版本控制需要单独决定。
4. 增加格式检查、静态检查、单元测试、契约测试、集成测试和迁移测试。
5. 大模型和大数据测试使用小型固定 fixture，不依赖当前本地完整资产。

**验收标准**：新环境可从锁文件安装；一条命令运行基础质量门；提交记录可追踪文档和源码变更；核心闭环测试在不访问真实业务数据的情况下稳定执行。

## 9. 建议修复路线

### 阶段 A：风险收口

目标是在正式修复前阻止继续产生错误数据或未授权变更。

1. 暂停或限制 `/accept-predictions`、`/models/switch`、数据集 DELETE 和自动切换。
2. 禁止通用 COCO 模型产生业务 SKU。
3. 关闭公开注册，轮换现有凭据并收紧 `.env` 权限。
4. 对当前模型、数据库和关键数据集生成只读哈希清单，作为修复前基线。

完成条件：未经授权无法修改数据或模型；权重缺失时服务失败关闭；现有状态有可核对基线。

### 阶段 B：恢复业务闭环正确性

按以下依赖顺序处理：

1. ISSUE-001：复训显式使用导出数据。
2. ISSUE-004：恢复严格人工准入门。
3. ISSUE-002、ISSUE-003：统一级联在线引擎并失败关闭。
4. ISSUE-008、ISSUE-009、ISSUE-010：统一 ID、裁决和标签合法性。
5. 增加端到端闭环测试后才允许重新开启自动复训。

完成条件：人工修改能确定进入本轮数据集；模型包正确加载；错误输入不会产生训练标签或业务 SKU。

### 阶段 C：模型发布与审计

1. ISSUE-005、ISSUE-006：建立不可变模型包和原子发布事务。
2. ISSUE-007：所有识别入口统一写可靠审计。
3. ISSUE-013、ISSUE-019：数据集、KB 和评测产物版本化。

完成条件：数据库 current、进程模型和识别审计中的版本完全一致；任一发布可以可靠回滚。

### 阶段 D：平台安全与可靠性

处理 ISSUE-011、ISSUE-012、ISSUE-014、ISSUE-015、ISSUE-016，完成鉴权、SSRF 防护、任务持久化、Webhook 幂等和数据库迁移验证。

完成条件：安全测试通过；并发和异常恢复不丢状态；可选 PostgreSQL 环境从空库部署成功。

### 阶段 E：工程治理

处理 ISSUE-017、ISSUE-018、ISSUE-020，统一文档入口、依赖锁和自动化质量门。

## 10. 必须补充的测试矩阵

| 测试层级 | 测试目标 | 最低场景 |
|---|---|---|
| 单元测试 | ID 规范化、框校验、候选裁决、模型映射 | 正常值、空值、字符串/整数、NaN、越界框、候选外 VLM 返回 |
| 数据契约 | 人工审核准入、数据集 manifest、类别表 | prediction-only、缺状态、缺审核人、SKU 不存在、类别数不一致 |
| 集成测试 | LS 导出到训练 | 修改一条人工标注后确认训练输入和数据哈希发生预期变化 |
| 模型发布测试 | 模型切换和回滚 | 正常切换、权重缺失、加载失败、健康检查不一致、旧模型回滚 |
| 识别审计测试 | 全入口留痕 | 单次、并发、数据库锁、审计写失败、重复 run ID 防护 |
| 安全测试 | 鉴权、CORS、CSRF、目录穿越、SSRF | 无 token、低权限 token、恶意 Origin、`../`、私网 URL、重定向私网 |
| 并发测试 | jobs、Webhook、SQLite | 并发建任务、重复事件、进程中断、database locked |
| 数据集测试 | 防泄漏与文件一致性 | 照片级 train/val 隔离、图片标签配对、汇总与磁盘数量一致、重复构建确定性 |
| 迁移测试 | SQLite/PostgreSQL schema | 空库升级、重复迁移、约束生效、核心 CRUD、版本检查 |
| 浏览器测试 | 审核工作台 | 翻页、空列表、过滤、非法数据、HTML 文本转义、提交错误提示 |

## 11. 发布与回滚要求

### 11.1 发布前门槛

- 所有 P0 问题关闭。
- ISSUE-005、ISSUE-006、ISSUE-007 关闭，确保模型与审计可追踪。
- 固定回归集通过，服务结果与离线级联结果一致。
- 未经人工审核的数据无法进入训练集。
- 当前 production 模型包、registry、数据版本和阈值均有哈希。
- 安全写接口完成鉴权和权限测试。

### 11.2 灰度验证

1. 新旧引擎对同一批固定图片并行推理，只让旧链路继续对外返回。
2. 比较检测框、SKU、低置信率、耗时和审计完整率。
3. 人工检查所有不一致和低置信样本。
4. 通过门槛后再切换 production 指针。

### 11.3 回滚条件

出现以下任一情况立即回滚：

- 实际加载模型哈希与 production 记录不一致。
- 审计完整率低于 100%。
- 未审核 prediction 出现在训练数据 manifest。
- 类别表或 registry 哈希不匹配。
- 固定回归集准确率或召回率低于发布门槛。

回滚必须切换到上一个不可变模型包，而不是依赖被覆盖的 `best.pt`。

## 12. 问题关闭模板

每个问题关闭时应在任务系统或后续修复记录中填写：

```markdown
### ISSUE-XXX 关闭记录

- 修复提交或变更编号：
- 修改文件：
- 数据或模型迁移：
- 新增测试：
- 测试结果：
- 安全检查：
- 发布版本：
- 回滚版本：
- 验收人：
- 验收时间：
- 遗留风险：
```

只有“代码修改完成”不能关闭问题。问题必须同时满足对应验收标准、自动测试和实际运行验证。

## 13. 下一步建议

建议先把 ISSUE-001 至 ISSUE-004 拆成四个独立修复任务，再建立一个“级联在线引擎与模型发布”技术设计任务承接 ISSUE-002、ISSUE-003、ISSUE-005、ISSUE-006、ISSUE-007。安全问题应独立建工作流，不与模型功能开发混在同一个发布批次中。

在任何新的模型训练、数据导入或平台功能扩展开始前，应先完成阶段 A 的风险收口，避免继续累积来源不明的训练数据和不可验证的模型版本。
