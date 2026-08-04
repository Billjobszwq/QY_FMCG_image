# Graph+Loop 智能业务操作系统全项目实施总纲

> **For agentic workers:** 这是全项目唯一实施编排入口。任何 Agent 开工前必须先读本总纲与 L0 架构；Stage 0–1 按配套代码级计划逐任务执行。后续 Stage 必须满足前置门禁，不得跨阶段抢跑。实现使用 `superpowers:executing-plans`、`superpowers:test-driven-development` 和 `superpowers:verification-before-completion`。

**Program Goal:** 以一个统一数据与智能底座承载 Graph+Loop、FMCG 识别、标注审核、数据集训练、位置外勤、问卷和 BI。平台先在单机稳定运行，模块像积木一样独立开发、测试、升级、启停和维护；成熟后可在不推翻契约的前提下拆分服务、迁移云端和支持多客户。

**Current Authorization:** 本文件只完成实施设计与 Agent 交接，不修改实现代码、不启动服务、不启动训练、不切换生产入口。后续实施 Agent 获得的权限仅限其被批准的 Stage 和隔离 worktree。

**Authoritative Baseline:** 文档编制基线为 Git `94a6e718ed26faeb78237c8d19fe34eb2410ff52`；只读回归为 `74 passed`；Python 为 `3.13.2`。实施开始时必须重新记录真实基线，不能把这里的快照当作永远有效的现状。

---

## 1. 唯一事实源与阅读顺序

| 等级 | 文档 | 用途 |
|---|---|---|
| L0 | `docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md` | 唯一总体架构、模块边界、数据底座、Graph+Loop、商业规则和 Stage 定义 |
| L1 | 本文件 | 全项目依赖、交付物、门禁、Agent 分工和开工顺序 |
| L1 | `docs/superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md` | Stage 0–1 的代码级 TDD 实施计划 |
| L1 | `docs/superpowers/specs/2026-08-04-location-field-operations-design.md` | Geo & Field Operations Domain Pack 完整规格 |
| L1 | `docs/superpowers/plans/2026-08-04-final-training-execution-gate.md` | 当前训练唯一执行门禁和 Apple MPS 规范 |
| L2 | `docs/training-history-and-decisions.md` | 训练事实、失败、数据问题与已确认决策 |
| L2 | `docs/handbook.md`、`docs/runbook.md`、`docs/structure.md` | 现有系统行为和兼容接入点 |
| L2 | `docs/superpowers/plans/2026-08-04-git-version-control.md` | Git、数据/模型分轨、分支、标签和恢复规则 |

冲突优先级固定为：L0 总体架构 → 当前 Stage 验收契约 → Domain Pack 规格 → 现有运行文档。现有代码与目标架构冲突时，通过 Adapter 渐进承接，不把旧实现直接复制成第二套底座。

## 2. 项目不是九套系统

全项目只有一个 Foundation：

~~~text
Unified Foundation
├── Graph+Loop Runtime / Policy / Capability
├── IAM / Tenant / Project / Data Domain
├── PostgreSQL facts / CAS evidence / ResourceRef / DataProduct
├── Job / Attempt / Worker / Outbox / Inbox
├── Usage / Cost / Price / Audit
└── Web Shell / API / Module SDK
    ├── FMCG Vision
    ├── Annotation & Review
    ├── Dataset, Training & Model
    ├── Geo & Field Operations
    ├── Questionnaire
    └── BI & Analytics
~~~

识别是第一个业务能力，不是产品中心。产品中心是受权限、预算、证据和人工节点约束的 Graph+Loop。业务模块禁止自建用户、租户、文件、任务、计费、审计或 Agent 底座。

## 3. 全项目硬性实施规则

1. 不删除、不覆盖原图、历史 SQLite、模型、训练制品、人工审核、失败证据、备份和临时产物；清理只生成候选清单，等待用户明确批准。
2. Foundation 不依赖 Domain Pack；Domain Pack 不互相 import。跨域只使用 API、Capability、DomainCommand、事件、DataProduct、ResourceRef 和 WorkItemProjection。
3. 每个模块拥有独立 schema、migration、Manifest、契约、测试和 feature flag；禁止万能业务表与跨模块直接写表。
4. PostgreSQL 是新平台事实库；CAS 是不可变文件与证据存储；旧 SQLite 是受保护的历史/兼容源，不被静默迁移或覆盖。
5. Graph/Agent 默认只读；任何领域写入必须是声明式 DomainCommand，经过权限、预算、幂等和审计。不得开放任意 SQL、文件系统、shell 或 Python import。
6. 每个 Loop 有步骤、迭代、时间、token、费用和人工停止边界。预算耗尽、策略拒绝和等待人工是正式终态/暂停态。
7. 先写失败测试，再写最小实现；每个 Stage 有契约、单元、集成、E2E、恢复、性能、安全和回归证据。
8. 实施使用独立 worktree；不得 `git add .`；不得合并、部署、切换生产、导入生产 cookie、force-push 或启动下一 Stage，除非用户明确批准。
9. 本机是当前唯一交付目标，但接口不能绑定单一绝对路径、单进程内存状态或 Apple 私有行为。硬件适配通过 execution backend 契约完成。
10. 不以“能跑”为完成。正确性、吞吐、P95、资源占用、失败恢复、证据完整、计费对账和模块隔离都必须过门。

## 4. Stage 依赖图与唯一开工顺序

~~~text
Stage 0–1 Unified Foundation
  └── Stage 2 FMCG Reference Graph / Ingestion / Quality
       ├── Stage 3 Annotation & Review
       └── Stage 4 Production Recognition
            ├── Stage 5 Dataset / Training / Model Governance  ← also depends on Stage 3
            │    └── Stage 6 FMCG Enhancement / Packaging / VLM / SAM
            └── Stage 7 Commercialization / Graph Studio       ← also depends on Stage 6 pricing evidence
                 └── Stage 8 Geo & Field Operations
                      └── Stage 9 Questionnaire / BI / Hybrid Deployment
~~~

Stage 是验收顺序，不是要求一个大分支连续开发。前一 Stage 的 Acceptance 文档为 `ACCEPTED` 且经用户批准后，下一 Stage 才建立 worktree。Stage 3 和 Stage 4 可在 Stage 2 通过后分别制定精确计划，但正式集成必须在共享契约上串行验收。

## 5. 每个 Stage 的标准准入包

任何 Stage Agent 收到任务后，第一项工作不是写代码，而是生成并评审 Admission Package：

- `docs/experiments/S<stage>0-admission.md`：真实 HEAD、基线测试、依赖门、服务/数据现状、磁盘和硬件；
- `docs/superpowers/plans/<date>-stage<stage>-<name>.md`：基于已落地代码写出的精确文件级 TDD 计划；
- Contract Diff：新增/变更的 JSON Schema、OpenAPI、events、DomainCommand、meters；
- Migration Plan：schema owner、forward-only 步骤、失败隔离、恢复验证；
- Test Matrix：unit/contract/integration/E2E/recovery/performance/security；
- Rollback Plan：禁用/降级/前向修复，不删除事实；
- Scope Diff：说明不做什么，防止把下一 Stage 偷带进来。

计划通过评审后才实施。Stage 0–1 的 Admission Package 已由配套计划直接定义，因此可以立即开工。

## 6. Stage 0–1：Unified Foundation Milestone

### 6.1 范围

建立 Module SDK、Graph+Loop、IAM、PostgreSQL 平台 schema、CAS/Evidence、Job/Worker、Outbox/Inbox、DataProduct/ResourceRef、WorkItemProjection、Usage/Cost/Price、Audit 和 Web Shell。用 Reference Echo Pack 与 FMCG Vision Bridge 证明模块化和旧识别适配。

### 6.2 实施入口

严格执行 `docs/superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md` 的 Task 1–26。Task 16 只是 Graph Kernel 子关卡；只有 Task 26 的 `UF1-foundation-acceptance.md = ACCEPTED` 才代表底座完成。

### 6.3 完成门

- Foundation 无 `src.modules` import，模块间无互相 import；
- 两模块可独立启停、升级失败隔离，历史数据仍可读；
- tenant/project/module/data-domain fail-closed；
- Graph、Job、Evidence、Usage、Audit 可跨重启恢复且无重复成功/计费；
- Web Shell、统一工作项和模块管理可用；
- 备份恢复、性能、安全和原有 74 项回归全部通过；
- 8091/8304 未切换，未启动训练，未删除任何文件。

### 6.4 分支与证据

- Branch: `feat/unified-foundation`
- Worktree: `../LLM-Image-unified-foundation`，若存在则使用新明确目录，绝不删除旧目录。
- Evidence: `GK0`、`GK1`、`UF0`、`UF1`。
- Stop: 提交 `UF1` 后停止，等待用户验收。

## 7. Stage 2：FMCG Reference Graph、照片接入与质量证据

### 7.1 模块与目标路径

- Owner: `src/modules/fmcg_vision`
- Schema: `mod_fmcg_vision`
- Target packages: `ingestion/`、`quality/`、`scene/`、`catalog/`、`graphs/`、`api/`、`web/`
- Reuse: Asset/CAS、EvidenceBundle、Job、Graph、Usage、Audit；不得自建文件仓库和任务表。

### 7.2 必须交付

1. 两种输入统一为同一 `AssetIngestCommand`：直接上传照片，或提交 URL 由受控下载 Worker 获取。
2. URL 下载防 SSRF、限制 redirect/size/time/MIME，记录原 URL、最终 URL、headers 摘要、时间、哈希和失败证据。
3. 原件写 CAS；EXIF、方向、尺寸、拍摄时间和来源作为不可变 metadata；所有预处理只生成派生 Asset。
4. 质量检测至少输出：模糊、严重斜拍/透视、严重反光、翻拍/屏摄、曝光、遮挡、分辨率、重复/近重复、大头照或非业务主体误导风险。
5. 质量结论不是简单删除：`accepted/rejected/review_required`，每个分数、阈值、模型版本、可视化热区和人工推翻动作进入 EvidenceBundle。
6. 场景识别覆盖货架、冰柜、冷风柜、地堆、堆箱、小货架、其他/未知，并分别判断有无价签；未知必须可拒识。
7. 建立第一条真实 FMCG Graph：接入 → 质量 → 场景 → 路由 → 人工检查点 → DataProduct。
8. Web Shell 增加照片接入、质量证据、场景、失败重试和人工处理，不复制新的登录/导航。

### 7.3 门禁

- 上传和 URL 对同一字节生成同一 Asset、不同 source event；
- 原件零覆盖，预处理 lineage 100%；
- 质量回归集按问题类型报告 recall/precision/误杀率，不能只报平均 accuracy；
- “大头照误导”有独立负样本和人工复核门，不允许无证据自动进入识别；
- 1,000 张混合输入可恢复处理，丢失 0、重复事实 0、证据完整率 100%；
- Stage 2 只完成参考 Graph，不宣称生产级识别或每日十万张 SLA。

### 7.4 分支、证据和停止

- Branch: `feat/stage2-fmcg-reference`
- Evidence: `S20-admission.md`、`S21-fmcg-reference-acceptance.md`
- Stop: 禁止实施 Label Studio 全闭环、正式多模型路由或训练。

## 8. Stage 3：Annotation & Review 100% 闭环

### 8.1 模块边界

- Owner: `src/modules/annotation_review`
- Schema: `mod_annotation_review`
- Label Studio 是独立标注引擎；平台拥有任务、分配、证据、审核、仲裁、计量和数据版本。
- 不 fork Label Studio 核心，不把其数据库当业务事实库，不把 webhook 当唯一可靠同步。

### 8.2 必须交付

1. Label Studio 项目/任务/标注/预测/用户/导入导出完整适配；平台 ID 与第三方 ID 分离。
2. Webhook → Inbox 去重，同时用 API 周期对账，修复漏事件、乱序和重复事件。
3. 多模态外挂数据库保存图像、框、mask、OCR、SKU 候选、知识库命中、模型版本、prompt、人工动作与证据引用。
4. Extension Provider 接口允许将来新增模式，不修改核心表；配置由 versioned contract 驱动。
5. 预标注使用现有模型自动画框；SAM 可选细化；低置信/冲突/无结果明确进入人工任务，不把预测当金标。
6. 审核覆盖已标注数据集和已识别数据集；动作包含正确、错标、漏标、框错误、SKU 错误、质量错误、不可判定、升级仲裁。
7. 任务可按链接分配；链接有到期、scope、领取/退回/转派、并发冲突和审计，不泄露原始文件路径。
8. 抽检、双人复核、仲裁和一致性指标；关键集可要求 maker-checker。
9. 人工结果只追加；最终 approved 数据由确定性导出生成 DatasetSnapshot 候选。

### 8.3 100% 验收定义

- 支持平台创建、导入、同步、预标注、人工编辑、提交、复核、仲裁、导出和重放；
- webhook 丢失/重复/乱序后，API 对账恢复一致；
- 错标与漏标都可表达、统计和回溯到人/模型/证据；
- 自动框、人工框、最终框各自保留，不能覆盖；
- Label Studio 停机时平台任务保留并明确 degraded；恢复后不重复计费或任务；
- 插件兼容性、租户隔离、签名媒体代理、性能和升级副本回归全部通过。

### 8.4 分支、证据和停止

- Branch: `feat/stage3-annotation-review`
- Evidence: `S30-admission.md`、`S31-label-studio-contract.md`、`S32-annotation-acceptance.md`
- Stop: 不自动将任何新审核数据投入训练。

## 9. Stage 4：Production Recognition Domain Pack

### 9.1 必须交付

1. 统一识别 Pipeline：Asset → Quality → Scene → Detector → 可选 SAM → Retrieval → Classifier/OCR → 可选 VLM Challenger → Rule/Fusion → Reject/Review/Publish。
2. 四个客户档位：低、中、高、极高。每档固定模型集合、阈值、最大延迟、资源预算、人工升级策略、准确率口径和价格版本；不得把档位硬编码到路由。
3. 同一 `RecognitionCommand/RecognitionResult` 支持 API、Web 和内部 Agent；三入口权限、计量、幂等和证据相同。
4. Agent API 只能使用受控 Capability，不能任意 SQL、写库或访问文件；领域写入走 DomainCommand。
5. 识别输出含商品身份/包装版本候选、框/mask/OCR、模型与知识版本、各分支置信、冲突、拒识原因、EvidenceBundle 和 UsageEvent。
6. 模型不可用、SAM 不可用、VLM 超时、OCR 失败和资源不足有显式降级，不能静默返回高档结果。
7. 任务级计费记录实际资源；客户价格按档位 RateCard，失败、重试、人工复核的计价规则可对账。
8. 建立批量/微批调度，禁止多个服务各自加载重复大模型争抢 MPS；模型服务声明 backend、内存、并发和 warmup。

### 9.2 性能与正确性门

- 按低/中/高/极高分别报告端到端 p50/p95/p99、吞吐、峰值内存、MPS 利用率、队列等待和单位照片成本；
- 与当前 bundle 做冻结回归，接受/拒识/错识分开统计，严格 one-to-one IoU，不使用 matched-conditional 指标冒充业务 precision；
- MPS batch 1/2/4/8/16 实测后选择，不假设 batch 一定更快；
- 每日十万张是容量目标：先证明单机持续吞吐、队列背压和 8TB 增长模型，再给横向 Worker 方案；
- 所有档位结果可追溯，降档、升档和人工升级都产生决策证据。

### 9.3 分支、证据和停止

- Branch: `feat/stage4-production-recognition`
- Evidence: `S40-admission.md`、`S41-tier-benchmark.md`、`S42-recognition-acceptance.md`
- Stop: 不能因为识别通过就直接发布新模型或启动训练。

## 10. Stage 5：Dataset、Training 与 Model Governance

### 10.1 当前不可绕过的训练事实

本阶段必须先读 `docs/training-history-and-decisions.md` 和 `docs/superpowers/plans/2026-08-04-final-training-execution-gate.md`。当前已确认：Apple M3 Max/arm64/MPS 硬件路线可用；旧 v6 lineage 和协议集存在门店泄漏风险；旧 checkpoint 禁止续跑；正式训练仍需关闭数据与评估门禁。

### 10.2 必须交付

1. `DatasetSnapshot`：输入 Evidence/Annotation 引用、样本哈希、SKU/包装版本、门店/session/customer/time/source、split、过滤原因、生成代码 commit 和 contract version。
2. Split Planner 对精确门店、规范化别名、session、近重复图、包装版本、客户和时间进行 fail-closed 泄漏检查。
3. 训练集只读 approved/仲裁完成事实；预测、未审核、质量拒绝和冻结评估集不能混入。
4. `TrainingRun` 记录配置、seed、设备、依赖、数据快照、初始化权重、指标、日志、checkpoint hash、峰值内存、功耗/温度证据和停止原因。
5. `ModelVersion/ModelBundle` 不可变，发布与训练分离；发布门要求数据、性能、回归、安全和回滚证据。
6. 评估同时包含 detector oracle、classifier oracle、end-to-end strict IoU、accepted FP、unknown/reject、长尾、新包装、场景、质量和各档位成本。
7. 实验注册表防止重复试错：每轮只改变有限变量，写假设、成功阈值、停止条件和结论。
8. Apple execution backend 明确支持 MPS/Core ML/MLX/ONNX；CUDA 是另一套验证结果，不能外推。

### 10.3 第一轮训练顺序

1. 关闭最终训练手册 G1–G6 数据和评估门；
2. 重建不可变 gold snapshot，不恢复旧 v6；
3. detector pilot：2,000 train + 300 val、3 epoch、MPS、batch 4；
4. pilot 通过才做单 seed 10 epoch；有明确收益才做 seed `42/20260804/3407`；
5. classifier 先跑 oracle；oracle 不达标先修 crop/标签/unknown，不盲目加大 backbone；
6. 任何正式模型先 shadow，不能自动替换当前 production bundle。

### 10.4 Apple 资源门

- 真实终端确认 arm64、`mps.is_built/is_available`、MPS tensor、剩余磁盘、电源/高性能模式；
- 禁止静默 CPU fallback；不主动设置 `PYTORCH_ENABLE_MPS_FALLBACK=1`；
- 按设备关闭无效 `pin_memory`，记录 workers/batch/imgsz 和峰值统一内存；
- MPS 统计可复现以多 seed 区间定义，不承诺 checkpoint bitwise 相同；
- 温度、swap、内存增长、吞吐低于历史 2 倍等停止条件来自最终训练手册。

### 10.5 分支、证据和停止

- Branch: `feat/stage5-training-governance`
- Training experiment branches/tags follow Git manual; dataset/model artifacts不进入普通 Git。
- Evidence: `S50-admission.md`、现有 `G0`、新 DatasetSnapshot 报告、每轮 TrainingRun、`S51-model-governance-acceptance.md`。
- Stop: 没有单独的训练启动授权时，Stage Agent 只搭治理与 dry-run，不执行正式训练。

## 11. Stage 6：FMCG Enhancement、包装演进、VLM 与 SAM

### 11.1 商品与新包装

1. 主数据分 ProductFamily、SellableSKU、PackageVersion；包装具有 `valid_from/valid_to/status`。
2. 新包装可沿用旧商品名称，也可按客户策略更名；名称不是身份主键，客户别名与全球/内部身份分层。
3. 发现流程：高频未知/冲突聚类 → 候选包装 → 人工确认 → 主数据命令 → 新数据收集 → shadow → 发布。
4. 识别结果明确返回“当前包装”“兼容旧包装”“候选新包装”“身份不确定”，禁止强行映射。

### 11.2 7B 内本地多模态模型

- 目标是 OCR/属性/包装 challenger 与拒识辅助，不替代高吞吐 detector/classifier；
- 首选从 2B/4B 级模型做 frozen baseline，再决定 LoRA；7B 是上限，不是目标；
- 模型选择必须比较许可证、中文/OCR、结构化输出、Apple MLX/MPS 可行性、内存、tokens/s、准确收益和单位成本；
- 训练样本由 EvidenceBundle 构造，包含 crop、上下文、OCR、SKU/包装、错误类型和人工理由；
- 使用 held-out 包装/门店/时间评估，防止 VLM 记忆背景。

### 11.3 SAM 与更优 FMCG 方案

- SAM 2.x tiny/small 先测吞吐和裁切收益；只在遮挡、粘连、复杂轮廓或高档位触发；
- SAM 不提供 SKU 身份，收益以严格 end-to-end 指标和增量成本判断；
- 更优体系是 detector + retrieval + classifier/OCR + temporal package master + VLM challenger + selective review，不以单一大模型替代全部；
- 任何新模型先离线 → shadow → 小流量可逆路由，旧模型保留。

### 11.4 验收

- 新包装发现的 precision、发现延迟、人工工作量和错合并率；
- 2B/4B/≤7B 在 Apple 上的峰值内存、tokens/s、每图延迟和增量准确率；
- SAM 触发率、裁切/遮挡收益、额外延迟和失败降级；
- 四档服务的新路由重新通过正确性、性能、计费和证据门。

### 11.5 分支与证据

- Branch: `feat/stage6-fmcg-enhancement`
- Evidence: `S60-admission.md`、`S61-package-evolution.md`、`S62-vlm-sam-benchmark.md`、`S63-enhancement-acceptance.md`

## 12. Stage 7：商业化、Graph Studio 与客户定制智能服务

### 12.1 商业底座

1. Tenant/Project、套餐、Entitlement、RateCard、额度、账期、账单预览、用量查询和 correction ledger。
2. 初期按模块成本计算总费用；后台成本拆分稳定后，将客户消费折算为 platform tokens。原始用量永久保留，token 是可重算的商业层。
3. 低/中/高/极高识别档位与 Graph+Loop 高级服务分别定价，不能混为同一个“识别次数”。
4. 7 年、2 年、半年保留策略进入 policy 和成本模拟；本地开发先实现契约与测试，不立即执行历史删除。

### 12.2 Graph+Loop 高级服务

Graph Studio 允许基于已注册模块/Capability 组合客户 Graph，定义节点、条件、Loop、人工审批、预算、SLA、版本和发布。客户 Agent 可在权限范围内读取客户 DataProduct 做分析、答疑、追踪和建议，但：

- 不接受任意“输入一个数据库连接/SQL”的模式；
- 不直接改客户源表；写入只生成待审批 DomainCommand；
- 不把客户数据用于其他客户或通用训练；
- 每个 node、token、工具、数据域和决策可审计、可计费、可停止。

### 12.3 验收

- 同一原始用量按不同 RateCard 重放，原事实不变；
- 账单预览到 UsageEvent、CostEntry、PriceEntry、Graph Run 可逐项追溯；
- 超预算、越 scope、模块禁用、数据域撤权实时 fail-closed；
- Graph 发布版本不可变，回滚是切换版本；
- 模块套餐启停不影响历史账单和证据；
- 模拟用户量暴增时，队列、数据库分区、对象存储和 Worker 可独立扩展，无需改业务契约。

### 12.4 分支与证据

- Branch: `feat/stage7-commercial-graph-studio`
- Evidence: `S70-admission.md`、`S71-billing-reconciliation.md`、`S72-agent-security.md`、`S73-commercial-acceptance.md`

## 13. Stage 8：Geo & Field Operations Domain Pack

### 13.1 唯一边界

位置外勤是 `src/modules/geo_field` Domain Pack，不是第二个平台。复用 IAM、Asset/Evidence、Job、Graph、Usage、Audit、Web Shell 和 WorkItemProjection。完整语义以位置外勤 L1 规格为准。

### 13.2 分层交付顺序

- L0 契约：LocationSample、Place、Address、RoutePlan、Geofence、Visit、FieldTask、SurveyArea、StorefrontEvidence；
- L1 地址主数据、地理编码、纠错、去重和置信度；
- L2 定位采集、权限、后台限制、异常轨迹与证据；
- L3 路径规划、员工/车辆/时窗/容量约束、不可达解释；
- L4 电子围栏、到离店事件、漂移/批量/离线处理；
- L5 门店核验、任务执行、导航辅助与地理推荐；
- L6 无门店清单的区域普查、地图区块、管理人员协调与 Agent 派发。

### 13.3 已确认业务要求

1. 每次门店任务门头照必选；采用多轮识别、地址/名称/历史/位置综合匹配，保留每轮候选和证据。
2. 员工自拍照接口预留；初期不自动人脸对比，但可按授权随时触发并示警。生物特征必须独立同意、最小保留、严权限和审计。
3. 现场证据包含时间、位置精度、设备、门头照、可选自拍、任务动作和异常理由；GPS 不是唯一真相。
4. 有明确门店清单时按任务/路线/员工位置推荐；类似 EDS 普查没有清单时，由管理人员设约束，Agent 将地图切分为可审计区块并派发。
5. 路线必须考虑自有车辆续航、时窗、服务时长、返回要求和不可达工作，不能输出理论直线最优。
6. 辅助导航通过 provider adapter；不把第三方地图 ID 当平台主键；外部调用计量并留供应商证据。

### 13.4 性能与验收

- 目标设计规模：单客户 1,000 外勤、100,000 地点、50,000 任务/日；本机阶段先以分层基准证明索引、队列和分区策略；
- 定位延迟、批量、缺失、漂移和离线必须可恢复，不假定后台实时；
- 门头匹配输出 precision/recall/人工确认率/错店率，不把地理距离单独当身份；
- 路线报告可行率、总里程/时长、超时、不可达、重排稳定性和供应商成本；
- 地理围栏事件、现场证据、任务结论和识别结果可通过 ResourceRef 关联，但互不越权写表。

### 13.5 分支与证据

- Branch: `feat/stage8-geo-field`
- Evidence: `S80-admission.md`，L0–L6 每层独立 acceptance，最终 `S87-geo-field-acceptance.md`
- Stop: 未通过一层不得把下一层的模拟结果包装为真实功能。

## 14. Stage 9：Questionnaire、BI、跨域 Graph 与混合部署准备

### 14.1 Questionnaire Domain Pack

- versioned 问卷、题型、逻辑跳转、配额、任务、回答、附件、离线同步、复核和导出；
- 回答与门店/人员/任务/识别结果通过 ResourceRef 关联，不直接写 Geo/FMCG 表；
- 变更问卷生成新版本，历史回答保持原 schema 语义。

### 14.2 BI & Analytics Domain Pack

- 只消费授权 DataProduct/事件，生成指标语义层、数据集、报表、Dashboard 和导出；
- 指标定义版本化，包含粒度、过滤、去重、时间和来源；
- Agent 做数据答疑时引用 DataProduct、指标版本和查询证据，不运行任意客户 SQL；
- 识别、问卷、位置、任务和费用可在权限范围内组合分析。

### 14.3 多端与部署准备

- 管理端、客户端复用 Web Shell 与 API；小程序/App 使用同一契约和短期授权，不另建后门 API；
- 建立 offline command/inbox、同步冲突和设备注册契约；
- 保持单机默认部署，同时完成 PostgreSQL、CAS、Worker、模型服务和 Web 的可拆分边界；
- 开源只包含 Foundation SDK、公开 contracts、示例模块和明确许可依赖；客户逻辑、商业计价、私有模型/数据、密钥和运营策略保留私有。

### 14.4 最终系统验收

- 统一 IAM/数据/证据/任务/计费/审计贯穿所有模块；
- 任一 Domain Pack 禁用或故障不会拖垮其他模块；
- 至少一条跨域 Graph 完成“外勤任务 → 门店证据 → FMCG 识别 → 问卷 → 审核 → BI DataProduct”，且每个写动作是受审计 DomainCommand；
- 备份、恢复、升级、容量、安全、账务和保留策略完成全系统演练；
- 单机形态达到已批准容量门，扩展方案有可验证拆分点，不做无证据微服务化。

### 14.5 分支与证据

- Branches: `feat/stage9-questionnaire`、`feat/stage9-bi-analytics`、`feat/stage9-cross-domain`
- Evidence: 每模块独立 admission/acceptance，最终 `S99-system-acceptance.md`

## 15. 需求到 Stage 的完整映射

| 原始要求 | 主要 Stage | 最终验收证据 |
|---|---:|---|
| 统一 Web：标注、训练监控、识别、数据 | 0–1, 3–5 | Web Shell + 模块 E2E |
| Label Studio 全功能、外挂数据库、扩展口 | 3 | LS contract/reconciliation/plugin matrix |
| 标注/识别人工审核、链接分配、错标漏标 | 3 | review/assignment/arbitration E2E |
| 模型辅助和自动画框 | 3–4 | prediction lineage + human override |
| 斜拍、反光、翻拍、大头照过滤及证据链 | 2 | quality per-type report + EvidenceBundle |
| 场景与价签有无 | 2 | scene/price-tag confusion matrix |
| 统一输入输出和多客户准备 | 0–2 | contracts + IAM isolation |
| 照片与 URL 输入 | 2 | ingest equivalence + SSRF tests |
| 7B 内 VLM 微调，越小越好 | 5–6 | 2B/4B/≤7B Apple benchmark |
| SAM 与 FMCG 多模型 | 4, 6 | routing/SAM incremental-value report |
| API、Web、Agent 三种识别 | 4 | three-entry contract E2E |
| 每次识别计费 | 0–1, 4, 7 | usage/rate/reconciliation |
| SaaS 数据、问卷、BI、多端准备 | 0–1, 9 | domain packs + final cross-domain E2E |
| 模块化、避免升级推倒重来 | 0–1, all | Module SDK + isolation/upgrade tests |
| 可变 Graph+Loop 智能核心 | 0–1, 7, 9 | Runtime + Graph Studio + cross-domain Graph |
| 地址、路线、围栏、导航、位置派单 | 8 | Geo L0–L6 evidence |
| 门头照多轮匹配、可选自拍/人脸示警 | 8 | storefront/selfie consent and review E2E |
| 无清单区域普查 Agent 派发 | 8 | SurveyArea/coverage/audit acceptance |
| 新包装与名称沿用/更换 | 6 | temporal package master acceptance |
| 8TB 本地盘、十万张/日增长 | 4, 7 | capacity, retention and cost evidence |
| Graph+Loop token 商品化 | 7 | immutable usage + token rerating |

## 16. 跨 Stage 契约、迁移和版本规则

### 16.1 契约版本

- JSON Schema/OpenAPI/Event/DomainCommand 使用 semver；breaking change 发布新 major，旧版本有明确兼容期；
- 发布 GraphVersion、Manifest、RateCard、DatasetSnapshot、ModelBundle 和指标定义均不可原地修改；
- Contract CI 执行生成稳定性、consumer fixture、breaking diff 和未知字段策略。

### 16.2 数据迁移

- 只 forward-only；先 expand、双读/适配、回填验证、切换、最后在另一次明确审批中 contract；
- 每模块只迁自有 schema；历史导入是独立 Job，源只读，生成行级核对和差异报告；
- 不自动 DROP、TRUNCATE、purge 或 downgrade；失败保留证据并前向修复。

### 16.3 模块发布

每个 Domain Pack 发布物包含：Manifest、contract SHA、migration head、backend package、web chunk、Graph、meters、feature flags、health checks、SBOM/许可证、测试报告和 rollback/disable 说明。缺少任一项不得标记 installable。

### 16.4 模型发布

代码版本、DatasetSnapshot、TrainingRun、ModelVersion、ModelBundle、RoutingPolicy 分开版本化。模型进入 production route 必须经过离线评估、Apple/目标后端性能、shadow、回滚演练和用户批准。

## 17. Git 与 Agent 协作方式

1. 每个 Stage 新建独立 worktree 和 `feat/stage...` 分支；发现目录存在时停止或换新名字，不删除。
2. 每个 Task 一个小提交，格式 `test|feat|fix|docs(scope): outcome`；计划、实现、验收证据分别提交。
3. 不暂存 `.env`、数据、模型、数据库、日志、原图、备份或 `.superpowers/`；提交前跑 `git diff --check` 和 name-only 审计。
4. 多 Agent 只在文件所有权不重叠时并行；migration、contracts、composition root、OpenAPI、共享 repository 和 Web Shell 由单一 owner 串行修改。
5. Reviewer 只报告证据和门禁；未经用户批准不 merge、不 deploy、不切生产、不执行清理。

## 18. 第一位实施 Agent 的完整启动提示词

将下面整段原样交给负责开工的 Agent：

~~~text
你现在负责 LLM-Image 项目的 Stage 0–1 Unified Foundation，只实施这一阶段，不要开始 Stage 2，不要启动任何模型训练。

仓库：/Users/zhangweiqi/Documents/QY/项目/LLM-Image

开工前必须按顺序完整阅读：
1. docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md
2. docs/superpowers/plans/2026-08-04-full-project-execution-program.md
3. docs/superpowers/plans/2026-08-04-stage0-1-graph-loop-kernel.md
4. docs/handbook.md
5. docs/runbook.md
6. docs/structure.md
7. docs/training-history-and-decisions.md
8. docs/superpowers/plans/2026-08-04-git-version-control.md

使用 superpowers:executing-plans 执行详细计划 Task 1–26；每个行为变更使用 superpowers:test-driven-development；宣布任何门禁完成前使用 superpowers:verification-before-completion。

执行要求：
- 先检查 git status 和真实 HEAD，记录基线；不要暂存或覆盖用户未提交文件。
- 使用独立 worktree 和分支 feat/unified-foundation；目录存在时不要删除，换一个清晰的新目录。
- 先跑只读基线测试。基线红色先诊断，不要把旧失败混入新实现。
- 按 Task 顺序执行，先写失败测试，再写最小实现，再验证，再只提交该 Task 文件。
- 不能 git add .；不能删除任何原图、SQLite、模型、训练制品、审核、失败证据、备份或临时文件。
- 不允许 Foundation import src.modules；不允许模块互相 import；不允许跨 schema 直接写表。
- 不允许任意 SQL、shell、文件访问、数据库 Python import path 或无界 Loop。
- PostgreSQL 是新平台事实库，CAS 是文件/证据层；旧 SQLite 只读兼容，不做大爆炸迁移。
- 保持旧 8091 和 8304 入口不变。不要切生产 feature flag，不要启动训练，不要修改生产模型。
- Graph Kernel Task 16 通过不代表底座完成；必须继续 Task 17–26。
- 每个失败、恢复、性能和安全结果写入 GK0/GK1/UF0/UF1 证据文档，未知结果写 FAIL，不得写“基本通过”。
- Task 26 后停止，不 merge、不 deploy、不清理、不进入 Stage 2。

最终只向用户报告：
1. UF1 是否 ACCEPTED；
2. 每个门禁及证据路径；
3. commit 列表和 diff 范围；
4. 测试、性能、恢复、安全结果；
5. 未解决风险；
6. production_switch、training_started、deleted_files 是否均为 false。
~~~

## 19. 后续 Stage Agent 的固定启动模板

后续 Stage 只能在前一 Stage 被用户接受后使用：

~~~text
你负责 LLM-Image 的 Stage <N>：<NAME>，只实施该 Stage。

先读 L0 总架构、全项目实施总纲、Stage <N-1> Acceptance、相关 Domain Pack 规格、当前仓库与运行手册。先创建 S<N>0-admission.md，再基于真实代码写精确文件级 TDD 计划；计划通过评审后实施。

强制复用 Unified Foundation 的 IAM、Asset/Evidence、Job/Event、Graph、Usage/Audit、Web Shell 和 Module SDK。禁止自建平行底座、跨模块直接写表、任意 SQL/shell/file capability、覆盖历史事实或自动清理文件。

使用独立 worktree/branch；每 Task 测试先行和小提交；完成 contract/integration/E2E/recovery/performance/security/legacy regression。提交 Acceptance 后停止，不 merge、不 deploy、不切生产、不启动下一 Stage，等待用户批准。
~~~

## 20. 审查 Agent 的固定挑战清单

每个 Stage 实施完成后，独立 Reviewer 必须回答：

1. 是否真的复用 Foundation，还是暗中建了第二套用户/文件/任务/账本/Agent？
2. 模块能否独立禁用、失败、升级和恢复？历史是否仍可读？
3. 数据所有权是否明确？是否存在跨 schema 写、通用 JSON 大表或路径型资源身份？
4. 幂等、崩溃、乱序、重复、超时、预算耗尽、人工等待是否有真实测试？
5. 权限是否对 tenant/project/module/data domain/field fail-closed？
6. 证据链是否从输入到派生、模型、人工、输出、计费完整可验？
7. 指标是否使用真实业务分母？是否用条件精度、模拟结果或平均值掩盖问题？
8. 性能是否在目标硬件和实际并发下测 p95/p99、内存、队列和成本？
9. Apple MPS 是否明确且无静默 CPU fallback？跨硬件结论是否被错误外推？
10. 是否误改/删除/覆盖历史数据、模型、证据、备份或用户文件？
11. 是否引入下一 Stage 范围、生产切换或未经批准的训练？
12. Acceptance 的每个 PASS 是否能指向命令输出、测试、数据库不变量或证据文件？

任何答案不确定，门禁为 FAIL。Reviewer 不替实施 Agent 修代码，只出问题清单和证据。

## 21. 项目经理最终判定

现在可以立即开工的只有 Stage 0–1。总体架构、底座代码级计划、Stage 0–9 顺序、业务覆盖、训练边界、Apple 路线、地理外勤承接、Agent 提示词和验收方式已经统一。

“一次性完成整个项目”的正确执行方式不是让一个 Agent 在一个分支里同时造完所有模块，而是一次性冻结完整路线与接口，然后用严格门禁逐 Stage 交付。这样既能立即开工，也能防止前一个模块尚未稳定，后面的识别、训练、外勤和 BI 同时依赖未定底座，最终再次推倒重来。

本总纲发布后，架构层不再等待补充讨论。只有业务阈值、第三方账号/许可证、真实数据授权、训练启动、生产切换、删除和发布等需要新增用户授权；技术实施按本文与对应 Stage 计划继续。
