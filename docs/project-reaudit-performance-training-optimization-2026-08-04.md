# LLM-Image 项目复查、性能审计与训练优化建议

> 审查日期：2026-08-04  
> 审查角色：只读架构审查者、Bug 挑战者、算法与训练方法论评审者  
> 变更边界：本次未修改任何代码、配置、数据、数据库或模型，仅新增本报告  
> 重点参考：`docs/training-history-and-decisions.md`、上一版问题清单、当前源码、测试、训练日志、数据集、模型文件及运行进程快照

---

## 1. 结论先行

### 1.1 总体判断

当前项目相较上一轮有实质性改善，但“上一版 Bug 已全部修复”这一结论不能通过严格复查。

- 上一版 20 项问题中：**2 项可判定关闭、16 项部分修复、2 项仍未关闭**。
- 单元和契约测试为 **22 passed**，76 个 Python 文件 AST 解析通过；但测试没有覆盖级联推理、训练数据构建、模型切换、审计落库、并发、服务集成和端到端指标。
- 当前最需要停止的行为是继续无条件追加训练。现有证据显示，训练瓶颈首先是**评估协议失真、检测召回上限、训练/评估数据污染和目标定义不一致**，不是单纯的模型容量或训练轮数不足。
- 当前分类器 checkpoint 的验证准确率为 **83.67%**，但最新级联复测的端到端正确率只有 **24.4%**。两者不是同一个指标，不能相互替代。
- 当前检测召回为 **38.1%**。在该召回下，即使分类器达到 100%，端到端上限也约为 38.1%，因此无法支撑 95% 的端到端目标。
- 运行时发现一个新的 P0 性能问题：监控进程单独占用约 **16.3 GiB RSS**。代码证据表明它每 3 秒重复反序列化分类器 checkpoint，极可能造成持续内存滞留或增长。
- 当前在线模型并未由模型注册表完整治理。注册表仅有一个旧 detector 记录，当前 v4 detector 和 classifier bundle 未登记为一组可回滚的生产版本。

### 1.2 当前建议

**暂停 v6 Phase 2 和后续盲目续训。** 先完成以下四个门槛：

1. 建立与训练完全隔离、按门店/采集会话分组的金标准测试集。
2. 重写评估口径：一对一匹配，同时报告漏检、误检、错分、未知类、计数误差和置信区间。
3. 用真实人工框验证“点标注生成固定框”造成的检测上限，并对比 208 类检测器与单类商品提议检测器。
4. 将 detector、classifier、类别映射、预处理、阈值和数据版本作为一个不可变模型包进行注册、上线和回滚。

在这四项完成前，再训练更大的 backbone、增加 epoch 或继续微调，无法产生可信的优化结论。

---

## 2. 审查范围与证据边界

### 2.1 已检查内容

- 项目架构、服务入口、端口和服务间调用关系。
- 上一版 `docs/project-issue-register-and-remediation.md` 的 20 项问题。
- `docs/training-history-and-decisions.md` 中的训练数据、问题记录和架构演进结论。
- 检测、分类、级联推理、训练、数据导入导出、模型注册、Webhook、审核工作台和监控代码。
- 当前数据集目录、统计文件、训练结果 CSV、训练日志、SQLite 注册数据和模型 checkpoint。
- 单元/契约测试、Python 语法解析、当前本机服务和进程状态。
- 单张代表性图片的只读冷启动/热推理性能测量。

### 2.2 已执行的只读验证

| 验证项 | 结果 |
|---|---:|
| `tests/unit` + `tests/contract` | 22 passed，0 failed，0.23 s |
| Python AST 解析 | 76 个文件通过 |
| 当前 classifier 类别数 | 208 |
| classifier 类别 ID 与 registry 顺序 | 完全一致 |
| v4 YOLO 类别名称与 registry 顺序 | 完全一致 |
| 当前 classifier checkpoint | epoch 10，val_acc 83.672% |
| 代码/测试/脚本/迁移内容聚合哈希 | `ee749100...f1882063` |
| 根目录主要依赖/编排文件聚合哈希 | `9aa55c07...0c484b2` |

### 2.3 本次没有验证的内容

- 生产流量、真实并发、真实 SLA 和业务峰值吞吐。
- MPS/GPU 条件下的批量推理收益；本机基准运行时 MPS 不可用。
- 外部 Label Studio、PostgreSQL、Webhook 接收端的真实联调；审查时相关服务均未启动。
- 训练结果的统计显著性；现有实验没有三随机种子和置信区间。
- “95%”究竟指单框 SKU 准确率、端到端对象准确率、单照片全量正确率还是门店级计数准确率。这个定义必须由业务正式确认。

因此，报告中的问题分为：**已确认 Bug**、**高可信风险**和**待实验验证假设**，不把推断写成已证实事实。

---

## 3. 上一版 20 项问题复查

状态口径：

- **关闭**：主路径、失败路径和回归验证均有足够证据。
- **部分修复**：主问题有改善，但仍存在可执行旁路、失败路径或治理缺口。
- **未关闭**：核心风险仍存在，或缺少能证明关闭的实现与测试。

| 编号 | 原问题摘要 | 状态 | 复查结论 |
|---|---|---|---|
| 001 | 重训数据集选择错误 | 部分修复 | 任务执行器已显式传递 `data_yaml`；但底层训练函数仍允许隐式默认数据集。数据哈希只覆盖 YAML 字节和数量，不能证明图片、标签、切分和类别映射未变化。 |
| 002 | 在线链路未走级联 | 部分修复 | `/v2`、ML backend 和 orchestrator 已进入级联；但旧 `src/recognize/api.py` 仍可执行，并与新服务共享 8091 端口，部署误启动风险仍在。 |
| 003 | COCO 权重静默兜底 | 部分修复 | `/v2` 主路径已 fail-closed；旧 v1 入口仍保留 `yolo11n.pt` 兜底，仓库级闭环未完成。 |
| 004 | 人工审核门禁可绕过 | 部分修复 | 接受接口增加任务 ID、确认和 reviewer；但 ML backend 把所有结果统一标为 `matched`，且级联低置信分类仍回退到 YOLO SKU，未真正进入待审核。 |
| 005 | 模型选择、切换、缓存不一致 | 部分修复 | 主服务直接切换时会 reload；重训任务仍可直接修改数据库而不重载在线模型，回滚逻辑也不是基于明确的“前一生产 bundle”。 |
| 006 | 模型权重可变、不可追溯 | 部分修复 | detector 增加 snapshot；classifier 仍覆盖固定 `.models/classifier/best.pt`，v4-v6 和分类器组合未形成不可变 bundle。 |
| 007 | 审计链不完整 | 部分修复 | `/v2` 尝试写审计；写失败后仍返回 200 和 `audit_pending`，但没有 outbox/重试。批任务和 ML backend 也可绕过审计写入。 |
| 008 | asset ID 的 int/string 不一致 | 部分修复 | 多处主路径已规范化；工作台 assignment 仍接受原始 ID，旧入口也没有统一契约测试。 |
| 009 | VLM 候选边界和伪一致 | 关闭 | 候选边界已收紧，当前未发现原始绕过路径。仍建议把“硬过滤后为空”显式返回冲突，而不是回退未过滤结果。 |
| 010 | 工作台路径穿越和框校验 | 部分修复 | review submit 已增强；annotation save 仍缺少完整区域校验，Label Studio exporter 的 `out_name` 可影响输出路径，旧 review server 仍缺少坐标校验。 |
| 011 | 控制面无认证、宽 CORS、危险操作 | 部分修复 | orchestrator 增加本地/Token 门禁和 CORS allowlist；recognize 仍允许 `*` CORS，管理 token 未设置时认证直接通过，模型列表还暴露本地路径。 |
| 012 | ML backend SSRF 与失败静默 | 部分修复 | URL、大小和错误区分已有改善；health 即使预加载失败仍返回 UP，模型版本固定为 `sku_v1`，会产生虚假健康和错误版本观测。 |
| 013 | crop 数据集文件名冲突和脏重建 | 部分修复 | YOLO crop builder 已增加 staging 和唯一命名；其他数据集 builder/exporter 仍可能遗留旧文件。当前磁盘数据与 summary 仍不一致。 |
| 014 | jobs JSON 竞态、Webhook 缺签名/幂等 | 部分修复 | jobs 增加锁和原子写；Webhook seen 文件没有锁，事件去重与 DB 审计不是同一事务，HMAC 默认仍可不启用。 |
| 015 | 硬编码凭据、环境文件权限、注册开放 | 部分修复 | 主 `.env` 权限为 600，注册关闭；`.label-studio/.env` 仍为 644，`.gitignore` 的 `.env.*` 会连 `.env.example` 一起忽略，示例也缺新 Token。 |
| 016 | Compose/PostgreSQL/SQLite schema 不一致 | 部分修复 | PostgreSQL migration 已拆分并接入 compose；运行时 warehouse 仍硬编码 SQLite，没有 PostgreSQL adapter 和双后端契约测试。 |
| 017 | 审核页面 next 错误/XSS | 关闭 | 原问题页面已修复。其他 dashboard/workbench 仍存在未转义 `innerHTML`，应作为新的残余安全项处理。 |
| 018 | 文档和入口漂移 | 未关闭 | `architecture.md`、`structure.md`、setup 文档仍混杂旧 KB/VLM、旧迁移路径和旧服务入口，与当前 cascade 架构不一致。 |
| 019 | KB/评估资产非原子、版本不一致 | 未关闭 | catalog 四个文件逐个 `os.replace`，进程中断仍可产生混合版本；加载器没有验证 manifest 哈希。评估/status 文件也存在直接覆盖。 |
| 020 | 无锁定依赖、无 Git、无核心集成测试 | 部分修复 | 已有 `pyproject.toml`、lock 文件和 22 个测试；但 lock 包含大量本机 `file://` 依赖，不可移植，仓库仍无 Git，核心级联和系统测试缺失。 |

### 3.1 复查统计

| 状态 | 数量 |
|---|---:|
| 关闭 | 2 |
| 部分修复 | 16 |
| 未关闭 | 2 |

这不意味着修复工作无效；相反，多数主路径已经改善。问题在于上一版文档把“实现了一个修复点”直接等同于“风险已经闭环”，缺少失败路径、旁路入口、当前制品和回归测试四个维度的关闭证据。

---

## 4. 本轮确认的新问题与残余问题

### 4.1 P0：必须先处理，否则训练或发布结论不可信

#### RA-001：监控服务持续重复加载 checkpoint，实测 RSS 约 16.3 GiB

**类型：已确认性能 Bug；根因归属为高可信推断。**

审查快照中只有 monitor 服务运行：

- PID 9375；RSS 约 17,119,680 KB，即约 16.3 GiB。
- 监控页面每 3 秒同时请求 overview 和 models。
- 两个请求都会进入 `read_classifier()`。
- `read_classifier()` 每次执行 `torch.load(.models/classifier/best.pt)`。
- checkpoint 约 43 MB，但 PyTorch 反序列化、Tensor 分配和 allocator 缓存会造成远高于文件大小的驻留内存，持续高频加载极易导致内存滞留。

**影响：** 本机内存被单一监控进程大量占用，可能触发 swap、训练变慢、推理抖动或系统 OOM。监控本身反而成为最大资源消费者。

**建议：**

1. monitor 只读取轻量 metadata JSON/SQLite，不直接加载权重。
2. 如果必须读取 checkpoint，只在文件 mtime/hash 改变时加载一次并缓存结果。
3. overview 和 models 复用同一份缓存快照。
4. 降低轮询频率或改为服务端事件；监控接口增加耗时和内存自监控。
5. 修复后执行 2 小时稳定性测试，验收 RSS 无单调增长，p95 API 延迟稳定。

**证据：** `src/training/monitor.py:91-130`、`src/training/monitor.html:249-250,382`。

#### RA-002：现有级联评估集与分类器训练源重叠，不能作为泛化证据

**类型：已确认方法论缺陷。**

- `build_crop_dataset.py` 和 `build_yolo_crop_dataset.py` 都从 `.eval/batch2` 构建分类器数据。
- `integration_test()` 也在 `.eval/batch2` 上计算级联正确率。
- `.eval/batch2` 有 6,510 张照片；旧训练集与其 asset+SHA 重叠 2,945 张，几乎包含全部旧训练照片。
- 因此 92.95%、83.67%、20.8% 和 24.4% 都不能直接解释为未见门店/未见采集会话上的生产泛化能力。

**影响：** 模型选择、架构比较和“是否达到预期”均可能基于被污染的指标，继续训练会扩大沉没成本。

**建议：** 建立冻结 gold holdout；以门店+采集日期/会话+连拍簇为 group split；图片 SHA/感知哈希再做二次去重。holdout 永不参与 crop 生成、阈值搜索、hard-negative mining 或人工返修训练。

**证据：** `src/cascade/build_crop_dataset.py`、`src/cascade/build_yolo_crop_dataset.py`、`src/cascade/cascade_inference.py:127-196`。

#### RA-003：当前 `crop_dataset_yolo` 实体文件与统计清单不一致

**类型：已确认数据完整性 Bug。**

| 项目 | summary 声称 | 磁盘实际 | 差异 |
|---|---:|---:|---:|
| train crops | 52,623 | 51,397 | -1,226 |
| val crops | 13,025 | 12,690 | -335 |
| 合计 | 65,648 | 64,087 | -1,561 |

代码已加入 staging 并不能自动修复既有脏制品；当前模型仍是在该旧数据快照上训练。任何复现实验都必须先生成新版本目录并做 manifest 对账，不能复用当前目录。

**建议：** 每次构建产生不可变新目录；manifest 列出每个 crop 的 source photo、detector version、box、label、split 和 SHA256；发布前核对 manifest 行数、磁盘文件数、类别计数和内容哈希完全一致。

#### RA-004：低置信分类被强制回退为 YOLO SKU，审核门禁仍被语义绕过

**类型：已确认业务正确性 Bug。**

当 classifier 置信度低于阈值时，级联返回 detector 的类别和置信度，而不是 `unknown`/`needs_review`。同时 ML backend 将所有结果状态写成 `matched`。

**影响：** 系统会把“不确定”包装成“已匹配”，错分进入业务结果；表面审核率下降，真实错误率上升。对于细粒度包装 SKU，detector 的类别不能作为安全兜底。

**建议：**

- detector 只负责提出商品框时，不得拥有最终 SKU 决策权。
- 低置信、top1-top2 间隔过小、OOD 或硬属性冲突时返回 unknown/review。
- 所有下游状态由统一业务决策服务计算，ML backend 不得自行硬编码 `matched`。
- 离线评估必须同时报告自动接受准确率、审核率和 risk-coverage 曲线。

**证据：** `src/cascade/cascade_inference.py:109-123`、`src/ls_ml_backend/yolo_backend.py:168-171`。

#### RA-005：当前评估器缺少一对一匹配和误检指标

**类型：已确认指标 Bug。**

当前集成评估用“标注点是否落入预测框”判断命中，没有强制一个预测框只能匹配一个 GT，也不完整报告未匹配预测框、precision、每图假阳性、计数误差和照片全量正确率。

**影响：** 一个大框可能覆盖多个点；大量错误提议不会被充分惩罚。该指标无法回答盘点业务最关键的“漏了多少、错了多少、多算了多少”。

**建议：** 使用匈牙利匹配或按置信度的一对一 IoU/中心约束匹配；同时输出 TP/FP/FN、SKU correct、unknown、duplicate、count MAE、每照片 exact match 和门店 bootstrap CI。

**证据：** `src/cascade/cascade_inference.py:127-196`。

#### RA-006：在线模型不受完整版本注册和回滚治理

**类型：已确认架构 Bug。**

SQLite 中只有一个旧 `sku_v1...` detector 记录，且无 production 状态；当前在线默认使用 v4 detector 和固定路径 classifier，但 v4-v6、classifier、阈值和预处理没有登记为同一 bundle。classifier checkpoint 会覆盖 `best.pt`。

**影响：** 无法回答某次识别究竟使用哪一组 detector/classifier/threshold；回滚可能恢复错误组合；训练和线上观测无法闭环。

**建议：** 模型注册最小单位应为 immutable bundle：

`detector hash + classifier hash + registry hash + preprocessing version + thresholds + dataset manifest hash + code revision + metrics`。

上线只切 bundle ID；rollback 必须指向上一生产 bundle ID，不能猜测“最近 retired/trained”。

#### RA-007：批量识别吞掉推理异常并可能把失败任务标记为成功

**类型：已确认可靠性 Bug。**

批任务捕获单图推理异常后写入空 products，任务仍可继续完成。空识别与真正“图片中无商品”无法区分，也没有审计失败事件。

**影响：** 数据静默丢失，业务方看到的是正常空结果而不是需重试的失败。

**建议：** 明确 `success/empty/failed/retryable` 四态；错误记录包含 asset、模型 bundle、异常类别和重试次数；任务只有在失败率低于门槛且失败项可追踪时才能成功。

**证据：** `src/ls_platform/task_runners.py:48-51`。

### 4.2 P1：高风险架构、数据和安全问题

#### RA-008：v6 数据构建是随机 4,000 张抽样，不是覆盖驱动抽样

**类型：已确认训练数据设计问题。**

- batch3 有 22,664 张照片、571,404 个标注、213 个标签名称。
- 质量清单通过 22,659 张；v6 只随机选 4,000 张，使用约 100,227 个标注。
- 仍有 18,659 张“通过质量门”的照片、约 471,085 个标注未利用。
- v6 train 有 208 类，val 只有 197 类；11 类在 val 缺失，部分训练类仅 1-3 个实例。
- train/val 的门店代码重叠 146 个，约 37.7% 的 val 门店代码也出现在 train。

**影响：** 随机采样保留头部类冗余，却不能稳定提升稀有类、难例和跨门店泛化；随机照片切分还会高估相似场景表现。

**建议：** 改为约束抽样：先保证类覆盖与最小独立实例数，再覆盖新门店、设备、光照、遮挡和 hard confusion；按门店/会话 group split。

**证据：** `src/training/build_sku_v6_dataset.py:95-177`。

#### RA-009：40,591 个未注册标签被直接跳过，未知类信息被浪费

**类型：已确认数据处理问题。**

主要被跳过的标签包括：

| 标签 | 数量 |
|---|---:|
| `other` | 22,650 |
| `百事other` | 9,720 |
| `可乐other` | 8,216 |
| 其他未登记真实 SKU | 5 |

这些数据不能直接映射为 208 个正式 SKU，但非常适合构建 background/unknown、同品牌近邻负样本和 OOD 校准集。完全丢弃它们会让 classifier 成为强制闭集分类器，对任何框都输出某个正式 SKU。

**建议：** 先抽样人工审计标签质量；将稳定的 other 类转为层级 unknown/brand-other 负样本，不与正式 SKU 混为同一类；在发布指标中加入 unknown recall 和已接受结果错误率。

#### RA-010：点标注固定扩框与真实商品边界不一致，可能构成检测上限

**类型：高可信算法风险，需人工框实验确认。**

当前训练把点标注转换成固定比例框。不同包装大小、拍摄距离、透视、遮挡和密集堆叠都不满足固定框假设，模型学习到的是启发式框，而不是真实商品边界。

**建议实验：** 从新门店和高密度/遮挡场景中分层抽取一批照片，补真实框；分别训练/评估：

1. 固定点框；
2. 少量真实框；
3. 真实框 + 点标注半监督；
4. 单类商品提议检测。

只有真实框方案显著提高 recall@FP/image 时，才能确认这是主要瓶颈；否则再调查输入分辨率、密集 NMS、小目标和域偏移。

#### RA-011：预测 crop 只保留命中框，约 28% 未匹配提议没有进入分类器训练

**类型：已确认训练分布问题。**

当前记录为 91,104 个 detector boxes，65,648 个 matched boxes，约 28% 的未匹配提议被排除。线上 classifier 却会接收这些误检框。

**影响：** 训练分布只包含“可匹配正样本”，线上分布包含正样本、背景、半个商品、重复框和未知商品；closed-set softmax 必然对无效框给出一个 SKU。

**建议：** 将未匹配框按采样比例纳入 background/unknown；加入 detector box jitter、不同 context scale、不同 detector 版本产生的框；分别评估 oracle true-box 和 predicted-box 性能。

#### RA-012：classifier 续训可覆盖旧最佳模型，且没有验证类别映射一致性

**类型：已确认模型完整性 Bug。**

`finetune.py` 加载旧 checkpoint 后，如指定新 data_dir，会重新生成类别目录顺序，但没有验证与 checkpoint classes 完全一致；`best_acc` 又从 0 开始，并写回固定 `best.pt`。第一轮即可覆盖真正的旧最佳权重。

另有训练曲线代码读取不存在的 `train_loss`，日志中已出现 curve generation failed。

**建议：** 续训前强制校验 ordered class mapping hash；新训练永远写新版本；以旧模型在新 validation 上的基线作为 best；训练历史 schema 加版本并由测试验证。

**证据：** `src/cascade/finetune.py:44-51,72-122`。

#### RA-013：训练数据指纹不覆盖实际内容，best 权重与 last-row metrics 可能错配

**类型：已确认可追溯性 Bug。**

- dataset hash 只包含 YAML 和 train/val 数量，不含图片/标签内容、split 列表、类别映射和构建代码。
- snapshot 保存的是 `best.pt`，登记 metrics 却取 results CSV 最后一行；当最后一轮退化时，权重和指标不是同一 epoch。
- DB 中 seed 固定写 42，但训练调用没有显式传递 seed。

**影响：** 同一 dataset hash 可对应不同数据；模型注册指标可能不是该权重的指标；复现实验无法证明随机性一致。

**建议：** 内容 manifest hash；从 `best.pt`/best epoch 对应行读取指标；显式记录所有随机种子、依赖、硬件和训练参数。

**证据：** `src/training/train_v1.py:73-76,181-210`。

#### RA-014：数据导出存在路径、脏目录、内存和切分问题

**类型：已确认可靠性/安全/性能问题。**

- `out_name` 未限制为安全目录名，可影响输出位置。
- 输出目录未采用不可变新版本和完整 staging，旧文件可能残留。
- 导出器把所有图片 bytes 保存在 `written` 列表，大数据集可能产生 GB 级内存占用。
- validation 取确定性的前 N 项，没有 shuffle/group split。
- 框坐标没有完整 finite/range 校验。

**建议：** 固定输出根并验证规范化路径；流式写入；manifest 驱动分组切分；临时目录完成后原子发布；输出前后做计数和 hash 对账。

**证据：** `src/ls_platform/exporter.py:85-151`。

#### RA-015：Label Studio importer 为 O(N²) 且重跑不幂等

**类型：已确认性能/数据重复问题。**

每上传一个文件后都分页搜索任务，随着任务数增加总体趋近 O(N²)；重复执行没有稳定 external ID 去重，会产生重复资产和任务。

**建议：** 批量导入；以 asset_id/content hash 作为幂等键；一次建立远端索引；导入报告明确 created/skipped/failed。

**证据：** `src/ls_platform/importer.py:81-135`。

#### RA-016：模型被多个进程/入口重复加载，且缺少并发背压

**类型：高可信架构性能风险。**

recognize service、ML backend 和 orchestrator task runner 都可在进程内导入级联模型，可能各占一份 detector+classifier 内存并争用 MPS。`ThreadingHTTPServer` 还会为请求创建线程，而共享 YOLO/Torch 模型没有显式并发队列、信号量或微批处理器。

**影响：** 冷启动重复、内存倍增、MPS 上下文争用、并发下尾延迟和稳定性不可控。

**建议：** 只保留一个模型推理服务；其他组件通过内部 API/队列调用。按设备设置固定 worker 数和 bounded queue；过载返回 429/503；用真实并发 1/2/4/8/16 做吞吐、p95、RSS 和错误率曲线。

#### RA-017：审计失败没有可靠 outbox，部分路径完全不审计

**类型：已确认审计可靠性问题。**

`/v2` 审计写失败后仍返回成功，仅附 `audit_pending`；没有可恢复队列。batch 和 ML backend 可直接调用级联函数，不保证写 `recognition_run`。`extra` 字段也没有完整持久化。

**建议：** 识别结果和审计事件通过同一事务或 transactional outbox 绑定；没有审计 ID 的业务结果不得进入最终导出；后台重试具备幂等键和死信队列。

**证据：** `src/recognize/service.py:233-248,337-349`。

#### RA-018：Webhook 去重与业务写入不是原子操作

**类型：已确认并发风险。**

seen 文件无锁；解析损坏会当空集合；seen mark 与 DB 写入分离；弱事件键可能碰撞；HMAC 可不配置。

**建议：** 数据库唯一事件 ID + 单事务写业务数据和处理记录；HMAC 在非开发环境强制；保存原始 payload hash；重复事件返回幂等成功。

#### RA-019：catalog 多文件发布并非真正原子

**类型：已确认数据一致性问题。**

四个文件先 staging，再逐个 `os.replace`。如果进程在第二个文件后中断，读取端可能看到旧新混合版本；loader 只核对行数，没有验证 manifest 内 hash。

**建议：** 以版本目录为发布单元，目录写完并校验后原子切换一个 `CURRENT` 指针；loader 先校验 bundle manifest/hash，再打开内容。

**证据：** `src/catalog/store.py:67-93`。

#### RA-020：残余认证、CORS、XSS 和环境文件风险

**类型：已确认安全问题。**

- recognize CORS 为 `*`。
- 管理 Token 未配置时认证直接通过。
- 模型接口泄露本地文件路径。
- dashboard/workbench 将名称拼接进 `innerHTML`。
- `.label-studio/.env` 权限为 644。
- `.env.example` 被 `.env.*` ignore 规则覆盖，且缺少新增 Token 示例。

**建议：** 非开发环境启动时强制 Token；CORS allowlist；前端使用 textContent/DOM API；敏感路径只返回逻辑 ID；环境文件 600；在 ignore 中显式保留 `.env.example`。

### 4.3 P2：可维护性和观测问题

#### RA-021：监控端口和模型指标不可信

monitor 检查 recognize 的端口为 8302，而实际新服务使用 8091。分类器卡片把历史最高 92.95% 与当前 checkpoint epoch 10/83.67% 混合展示，无法代表一个确定模型。

#### RA-022：health 和 model_version 会报告虚假状态

ML backend 预加载失败被捕获后，health 仍返回 UP；`model_version` 固定为 `sku_v1`，与当前 v4+classifier 不一致。应区分 liveness/readiness，并从实际 bundle 读取版本。

#### RA-023：文档与真实架构继续漂移

`docs/structure.md` 和 `docs/architecture.md` 仍把旧 KB/VLM 或旧迁移路径描述为当前事实；旧新服务共享 8091 的风险也没有明确退役策略。文档应由 `services.json` 和模型 bundle registry 生成关键事实，减少手写漂移。

#### RA-024：依赖 lock 不可移植，测试通过不能证明系统可发布

当前 lock 有 328 行，其中约 36 行是本机 `@ file://` 路径；换机/CI 无法可靠安装。仓库没有 Git 版本，现有 22 个测试集中在命名、别名、只读和 SKU 对齐，未发现文档所称的 11 个可执行 smoke tests。

---

## 5. 系统性能审查

### 5.1 当前运行快照

| 服务 | 状态 |
|---|---|
| recognize 8091 | 未运行 |
| ML backend 8301 | 未运行 |
| orchestrator 8304 | 未运行 |
| Label Studio 8300/8080 | 未运行 |
| monitor 8092 | 运行中，API 单次约 192 ms |

由于核心服务未运行，本次不能声称已完成系统级吞吐或稳定性验收。

### 5.2 单图只读基准

环境：代表性 1500×2000 图片，27 个 GT、16 个 detector predictions；本次进程运行在 CPU，MPS 不可用。结果只用于定位热点，不代表生产 SLA。

| 指标 | 实测 |
|---|---:|
| 冷模型加载 | 12.766 s |
| detector 首次推理 | 0.208 s |
| sequential classifier 中位数 | 0.205 s |
| batch classifier 中位数 | 0.318 s |
| 热端到端中位数 | 0.395 s |
| 单请求理论吞吐 | 约 2.53 images/s |
| 进程最大 RSS | 约 1.576 GiB |

重要结论：在本次 CPU 样本上，batch classifier 比顺序执行更慢，不能把“批处理一定更快”当作结论。MPS 上需实测 batch size 1/2/4/8/16，并把 crop 数量分桶。

### 5.3 主要性能热点与优化顺序

| 优先级 | 热点 | 原因 | 建议验证 |
|---|---|---|---|
| P0 | monitor 内存 | 高频 `torch.load` | 2 小时 RSS 曲线、checkpoint 变更触发次数 |
| P1 | 多进程重复模型 | 三类入口可各加载 detector+classifier | 各服务 RSS、总内存、MPS contention |
| P1 | 无背压并发 | 无 bounded queue/semaphore | 并发 1-16 的 p50/p95、错误率、RSS |
| P1 | exporter 内存 | 保存全部图片 bytes | 1k/5k/20k 图片峰值 RSS |
| P1 | importer O(N²) | 每条导入后全量查找 | N=100/1k/10k 时间曲线 |
| P2 | classifier 冷启动 | inference 构建时仍初始化 ImageNet 默认权重，再覆盖 checkpoint | 冷启动 profile、禁用多余初始化对比 |
| P2 | 双重 checkpoint 读取 | cascade 加载后又 `torch.load` metadata | 冷启动 I/O 和 RSS 对比 |
| P2 | warehouse 每连接迁移 | 读请求也触发 schema 检查 | 高频读写锁等待和连接耗时 |

### 5.4 推荐的性能验收协议

测试不能只报平均值，应固定同一模型 bundle 和图片分层：空图、少框、中等框、密集框、超大图。

每个并发级别至少报告：

- 冷启动时间、首请求时间、热 p50/p95/p99。
- images/s、crops/s、每图预测框数量。
- 进程 RSS、系统总 RSS、swap、CPU/MPS 利用率。
- 超时率、OOM、429/503、推理异常率。
- 持续 2 小时后的内存斜率。
- 准确率是否因并发、resize 或 batch size 改变。

建议架构是单一 inference service + 有界队列 + 固定设备 worker，而不是让三类服务各自加载模型。

---

## 6. 为什么多轮训练仍未达到预期

### 6.1 训练指标混用了三种不同问题

当前文档把以下指标放在同一条进化线上：

1. YOLO 自身 mAP；
2. classifier 在 crop validation 上的 top-1 accuracy；
3. cascade 在完整照片上的点命中+SKU 正确率。

它们无法直接比较。最新可见结果为：

| 阶段 | 指标 |
|---|---:|
| v4 detector mAP50-95 | 0.6887 |
| classifier R1 GT heuristic crop val acc | 92.95% |
| classifier R2 predicted crop val acc | 83.67% |
| cascade detection recall | 38.1% |
| cascade conditional classification | 63.9% |
| cascade end-to-end | 24.4% |

端到端近似关系：

`0.381 × 0.639 = 0.2435 ≈ 24.4%`

这说明当前结果主要由 detector recall 和真实 predicted-crop 条件分类共同限制。R2 的 83.67% 不能代入端到端公式，因为它来自受污染且更容易的 crop validation。

### 6.2 95% 目标的数学约束

若 95% 指端到端对象正确率，则：

`End-to-end ≈ proposal recall × conditional SKU accuracy × association correctness`

忽略 association 损失，并假设前两阶段能力相同，每阶段至少需要：

`sqrt(0.95) ≈ 97.47%`

当前 detection recall 38.1%，所以无论 classifier 如何增强，端到端理论上限约 38.1%。如果文档中的“any box 可达约 60%”成立，60% 仍然不是 95% 的可行上限。

第一决策不应是换 ResNet50/EfficientNet，而应是确认：

- 95% 的业务分母是什么；
- detector 是否只做单类商品 proposal；
- 是否愿意用 unknown/review 换取自动接受结果的高准确率；
- 真实商品框是否是必须补齐的数据资产。

### 6.3 训练历史中的关键证据冲突

| 文档/记录 | 当前证据 | 影响 |
|---|---|---|
| v4 被描述为 batch1 续训 | v4 train meta 指向 `batch2_v4` | 实验谱系不准确 |
| v2 mAP 记录约 0.299 | CSV 最佳约 0.338 | 版本比较失真 |
| v3 mAP 记录约 0.4387 | CSV 最佳约 0.4514 | 版本比较失真 |
| R2 crop 65,648 | 当前磁盘 64,087 | 当前制品不完整/未重建 |
| “20 个问题已全部修复” | 严格复查仅 2 项关闭 | 缺少关闭门槛 |
| 22 tests + 11 smoke | 发现 22 tests，未发现 11 个可执行 smoke | 验证证据不可复现 |

训练决策文档应把“计划值、当时观测值、重新审计值”分列，禁止覆盖历史。

### 6.4 已投入计算量没有形成可比较实验

从可见训练时长估算，YOLO v1-v6、classifier R1/R2 共消耗约 **192,210 秒，即 53.39 小时**。但实验存在数据版本变化、评估集污染、指标错配、随机种子不完整和模型 bundle 不可追溯，因此这 53 小时不能组合成可靠的学习曲线。

v5 最佳 mAP 约 0.6898，几乎与 v4 的 0.6887 相同，且后续 epoch 退化；v6 Phase 1/2 也没有提供优于 v4 的明确冻结测试证据。继续续训的边际收益已经很低。

---

## 7. 训练数据与算法优化建议

### 7.1 先重建数据协议，而不是先换模型

建议把数据拆成四个互斥区：

| 数据区 | 用途 | 是否允许反复查看 |
|---|---|---|
| train | 参数训练、hard-negative mining | 是 |
| dev | 模型/损失/增强选择 | 是 |
| calibration | 温度缩放、阈值、unknown/review 策略 | 仅校准时 |
| gold test | 最终发布验收 | 否，发布候选才运行 |

切分规则优先级：门店 → 采集日期/会话 → 连拍簇 → 图片 SHA/感知哈希。不能只随机照片。

测试集要求：

- 208 类尽可能都有独立实例；稀有类单独报告，不能被 micro average 隐藏。
- 覆盖不同门店、设备、距离、光照、遮挡、密集度和包装版本。
- 标注真实 bounding box，而不是固定点框。
- 双人复核争议样本，保留 adjudication 记录。
- 冻结 manifest 和内容哈希；任何返修生成新版本。

### 7.2 检测器：重新定义为商品提议问题

当前 208 类 detector 同时承担定位和细粒度 SKU 分类，但最终又由 classifier 决策 SKU，目标重复且互相干扰。建议做严格 A/B：

### 方案 A：保留 208 类 detector

- 优点：可利用类别监督，detector 自身有 SKU 先验。
- 缺点：长尾和细粒度混淆会影响 proposal recall；NMS 可能因类别策略产生重复/漏检；低置信类别不应作为最终兜底。

### 方案 B：单类 `product` proposal detector

- 所有正式 SKU 和可确认的 other 商品都作为 product。
- 使用 class-agnostic NMS。
- 优化目标从 mAP 转为 `recall@FP/image`，优先保证每个商品被提出。
- classifier 独立负责 SKU/unknown。

### 必须控制的实验变量

同一 backbone、同一真实框训练集、同一输入尺寸、同一训练预算、三随机种子。比较：

- proposal recall；
- 每图 FP；
- 小/中/大目标 AR；
- 密集场景 recall；
- count MAE；
- cascade 最终准确率和延迟。

只有方案 B 在可接受 FP/image 下显著提高 recall，才切换架构。

### 7.3 分类器：从强制闭集改为细粒度识别 + 拒识

### 数据层

- 训练 crop 来自多个 detector 版本，避免只适配 v4 的框分布。
- 对真实框做 scale/jitter/context 扰动，模拟偏框、截断和邻接商品。
- 加入未匹配 detector proposal 作为 background/unknown。
- 审计 `other`、`百事other`、`可乐other`，构建品牌内 unknown hard negatives。
- 对高混淆 SKU 建 pair list，进行定向 hard-negative sampling。
- 先做增强消融；水平翻转、Hue 变化和随机裁剪可能破坏包装文字、色彩和关键属性。

### 目标函数与结构

建议按以下顺序实验，不能一次叠加：

1. 现有 cross-entropy 基线；
2. class-balanced batch 或 effective-number weighting，避免 inverse-frequency 过度放大脏稀有样本；
3. label smoothing/focal loss 单变量对比；
4. embedding/metric loss，用于同品牌细粒度近邻；
5. 层级或多任务 head：品牌、包装类型、容量、口味、含糖属性 + SKU；
6. 最后才比较 ResNet18、ResNet50、EfficientNet 等 backbone。

层级属性的价值在于把错误变得可解释，并能设置硬冲突：例如容量/包装明显冲突时拒绝该 SKU，而不是只相信 softmax。

### 置信度与拒识

- 用独立 calibration set 做 temperature scaling。
- 组合 top-1 confidence、top1-top2 margin、entropy、embedding distance 和属性冲突。
- 输出 `accepted / unknown / review`，不能低置信时回退 detector SKU。
- 报告 risk-coverage：自动处理覆盖率越高时，已接受结果错误率如何变化。
- 阈值按类别或混淆簇校准，不能只有一个全局 0.6。

### 7.4 数据选择：把随机 4,000 张改成覆盖和信息增益驱动

推荐优先级：

1. 当前 gold/dev 中漏检或错分最多的门店/场景。
2. 稀有类和验证缺失类。
3. top1-top2 小间隔、模型版本分歧样本。
4. 未匹配 detector proposals 和 unknown。
5. 新门店、新设备、新包装版本。
6. 头部类只保留去重后的代表样本。

每轮新增数据前生成 selection report：每类数量、独立门店数、独立采集会话数、场景分布、与已有图片的近重复率。这样才能知道新增 4,000 张增加了什么信息。

---

## 8. 推荐实验矩阵与止损门槛

### 8.1 Gate 0：证据重置

目标：先得到可信基线，不训练新模型。

- 冻结 gold test 和 calibration set。
- train/dev/calibration/test 的 SHA/感知哈希重叠必须为 0。
- 按门店/会话 group split，并输出 group overlap=0。
- 实现一对一匹配评估。
- 用当前 v4 + R2 checkpoint 重新跑完整基线。
- 保存逐图片明细，允许定位每个 FP/FN/错分。

**通过条件：** 同一 bundle 重跑两次结果一致；所有汇总指标可由逐图明细重新计算；评估集未被任何 builder 读取为训练源。

### 8.2 Gate 1：Proposal 检测能力

| 实验 | 单一变量 | 输出 |
|---|---|---|
| E1-A | 208 类 detector | recall@FP/image、AR、count MAE |
| E1-B | 单类 product detector | 同上 |
| E1-C | 固定点框 vs 真实框 | 定位噪声影响 |
| E1-D | imgsz/tiling/密集 NMS | 小目标和密集场景收益 |

为支持 95% 端到端目标，proposal recall 的暂定方向应接近或超过 97%，但必须同时定义可接受 FP/image 和延迟。若真实框+单类 detector 仍远低于该水平，应重新评估 95% 目标、拍摄规范或采用货架分区/多帧采集。

### 8.3 Gate 2：Classifier 与拒识

| 实验 | 数据/算法变量 | 关键指标 |
|---|---|---|
| E2-A | true boxes | oracle top-1/macro recall |
| E2-B | predicted boxes | 分布落差 |
| E2-C | predicted + jitter/context | 鲁棒性 |
| E2-D | 加 background/unknown | unknown FPR、risk-coverage |
| E2-E | hard-negative/metric loss | 混淆簇准确率 |
| E2-F | hierarchical attributes | 属性冲突率、可解释性 |
| E2-G | backbone 对比 | 同数据同预算下收益/延迟 |

每项至少三随机种子，报告均值、标准差和逐类变化。若某方案只提升 micro accuracy、却伤害稀有类或增加拒识错误，不应晋级。

### 8.4 Gate 3：完整级联

固定 Gate 1 detector、Gate 2 classifier，扫描 detector conf、NMS、classification threshold 和 reject threshold。

必须报告：

- detection precision/recall、FP/image、FN/image；
- accepted SKU micro/macro accuracy；
- unknown/review rate；
- end-to-end object accuracy；
- 每照片所有商品完全正确率；
- 每 SKU 和总量 count MAE；
- 门店级 bootstrap 置信区间；
- p50/p95 latency、吞吐、峰值 RSS。

任何阈值只允许在 calibration set 选择，gold test 只用于最终一次验收。

### 8.5 Gate 4：发布与回滚

- 发布对象是 immutable bundle，不是单独 best.pt。
- staging 与 production 用同一容器/依赖安装路径。
- readiness 必须实际加载并完成一次 smoke inference。
- shadow 流量先运行；错误可回放到具体 bundle 和输入。
- rollback 使用明确 previous production bundle。
- 审计写失败时业务结果不得静默完成。

---

## 9. 建议的执行顺序

### 第一优先级：立即止损

1. 暂停 v6 Phase 2 续训。
2. 处理 monitor 16.3 GiB 内存问题，并做稳定性验证。
3. 归档当前 v4、classifier、registry、阈值和日志为只读 bundle，避免 `best.pt` 被覆盖。
4. 明确 95% 的业务指标定义。

### 第二优先级：重建可信评估

1. 构建门店/会话隔离的 gold/dev/calibration。
2. 补真实框，至少覆盖密集、遮挡、远距和核心混淆类。
3. 替换当前 point-in-box 评估为一对一评估。
4. 重新评估当前 v4+R2，建立真正 baseline。

### 第三优先级：验证架构方向

1. 单类 product detector 对比 208 类 detector。
2. true-box 与 predicted-box classifier 差距分析。
3. 加入 background/unknown 和拒识校准。
4. 再做 hard-negative、层级 head 和 backbone 消融。

### 第四优先级：系统工程闭环

1. 单一模型推理服务和有界队列。
2. immutable model/data bundle registry。
3. transactional audit outbox。
4. 数据 builder 全部 manifest + staging + 原子发布。
5. CI 中加入端到端、并发、模型切换、故障注入和数据完整性测试。

---

## 10. 建议新增的自动化验证清单

### 数据测试

- train/dev/calibration/test 内容和 group 不重叠。
- YAML 类别、registry、YOLO names、classifier classes 顺序完全一致。
- summary、manifest 和磁盘文件数量/哈希一致。
- 所有 box 坐标 finite、范围合法、面积大于最小值。
- 每类训练/验证/测试数量和独立门店数有报告。
- 数据构建重复运行得到同一 hash，不遗留旧文件。

### 模型测试

- classifier 续训拒绝不一致 class mapping。
- checkpoint 不覆盖旧版本。
- model metrics 与 best checkpoint epoch 一致。
- 低置信、OOD、属性冲突返回 unknown/review。
- detector/classifier/threshold 必须由同一 bundle 加载。
- rollback 精确恢复上一生产 bundle。

### 服务测试

- 未配置生产 Token 时拒绝启动，而不是放行。
- 模型加载失败时 readiness=false。
- 审计失败时进入可靠 outbox，不返回不可追踪成功。
- 批任务区分 empty 和 failed。
- 并发过载有界并返回明确状态。
- 运行 2 小时无持续 RSS 增长。

### 指标测试

- 一对一匹配，单预测不可重复命中多个 GT。
- 错误提议计入 FP。
- micro、macro、per-class、per-store 均可从明细重算。
- 阈值只能在 calibration set 选择。
- gold test 运行被记录并限制频率。

---

## 11. 发布阻断条件

当前至少存在以下发布阻断项：

- [ ] monitor 内存异常未修复和验证。
- [ ] 没有无污染的冻结 gold test。
- [ ] 评估器没有一对一匹配和 FP/count 指标。
- [ ] 当前级联端到端只有约 24.4%，与目标有数量级差距。
- [ ] 低置信结果仍可被标记为 matched。
- [ ] 当前模型组合未形成不可变、可审计、可回滚 bundle。
- [ ] 批任务可把推理异常静默变为空结果。
- [ ] 核心服务未完成集成、并发和长稳测试。
- [ ] 数据集当前实体文件与 summary 不一致。
- [ ] 生产认证、CORS、health 和审计仍有残余风险。

在这些项关闭前，不建议把新的 mAP 或 classifier val_acc 作为可发布依据。

---

## 12. 最终挑战意见

这个项目当前最主要的矛盾不是“模型还不够大”，而是以下四点没有对齐：

1. **业务指标**：95% 的分母和失败代价尚未正式定义。
2. **学习任务**：点标注生成的 208 类检测、商品 proposal 和细粒度 SKU 分类混在一起。
3. **证据系统**：训练源与评估源重叠，指标不完整，实验谱系不准确。
4. **发布系统**：当前模型不是不可变 bundle，在线版本、审计和回滚没有形成闭环。

最有价值的下一步不是再跑一轮训练，而是用一套干净、可复算的实验回答三个问题：

- 用真实框训练的单类 proposal detector，能否把 recall 从 38.1% 提升到接近业务所需水平？
- classifier 在未见门店的真实预测框上，加入 background/unknown 后能否实现高准确率的可控拒识？
- 在相同冻结测试集上，这两个阶段组合后的端到端收益是否大于系统复杂度和推理成本？

只有这三个问题有了可信答案，继续训练、换 backbone 或扩数据才有明确方向。

---

## 13. 主要代码证据索引

| 主题 | 位置 |
|---|---|
| 在线级联、低置信回退 | `src/cascade/cascade_inference.py:84-123` |
| 当前集成评估逻辑 | `src/cascade/cascade_inference.py:127-196` |
| classifier 构建、增强、采样、保存 | `src/cascade/classifier.py:38-82,115-117,197-216` |
| classifier 续训映射/覆盖/曲线 | `src/cascade/finetune.py:44-51,72-122` |
| predicted crop 数据构建 | `src/cascade/build_yolo_crop_dataset.py` |
| GT crop 数据构建 | `src/cascade/build_crop_dataset.py` |
| v6 数据随机抽样和脏目录风险 | `src/training/build_sku_v6_dataset.py:95-177` |
| 数据 hash、模型指标登记 | `src/training/train_v1.py:73-76,181-210` |
| batch 错误静默、重训直接切 DB | `src/ls_platform/task_runners.py:48-51,138-156` |
| exporter 路径/内存/切分 | `src/ls_platform/exporter.py:85-151` |
| importer O(N²) | `src/ls_platform/importer.py:81-135` |
| ML backend 状态和 health | `src/ls_ml_backend/yolo_backend.py:36,168-171,193-197,239-245` |
| monitor 高频 checkpoint 加载 | `src/training/monitor.py:91-130` |
| monitor 3 秒双请求 | `src/training/monitor.html:249-250,382` |
| recognize CORS/认证/模型切换/审计 | `src/recognize/service.py:207-248,255-305,337-421` |
| catalog 多文件发布 | `src/catalog/store.py:67-93` |
| 训练历史与决策 | `docs/training-history-and-decisions.md` |

本报告中的数值均来自 2026-08-04 当前工作区快照；后续如数据、权重或进程状态变化，应生成新的审计快照，不应直接覆盖本报告。
