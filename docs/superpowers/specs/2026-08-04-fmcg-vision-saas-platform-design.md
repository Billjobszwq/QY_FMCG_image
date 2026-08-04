# Graph+Loop 智能业务操作系统最终统一架构设计

> 文档日期：2026-08-04
>
> 文档性质：整个产品的唯一权威架构总纲（Single Architecture Source of Truth）
>
> 路径说明：为保留已确认引用和 Git 历史，文件名暂保留 `fmcg-vision-saas-platform-design`；文件名不代表另建 FMCG 独立系统
>
> 当前阶段：本机优先、文档先行、尚未授权修改实现代码
>
> 适用对象：产品负责人、架构师、开发 Agent、训练 Agent、测试与运营人员

## 0. 唯一系统声明与文档权威关系

本项目只建设一套系统，不建设“识别系统”与“位置外勤系统”两个独立平台。所有业务共用：

- 一套身份、租户、客户、项目和权限体系；
- 一个 Graph+Loop Kernel 与能力注册表；
- 一套统一数据系统底座和全局 ID/版本/时间语义；
- 一个内容寻址对象与证据存储；
- 一套事件、任务、Outbox/Inbox 和 Worker 管理；
- 一套策略、审批、审计、用量和计费账本；
- 一个 Web 应用壳、API Gateway 与 Agent 入口。

FMCG 识别、标注训练、Geo/Field Operations、问卷、BI 和未来客户模块都是这套系统内的 Domain Pack。它们可以独立开发、测试、发布、启停和维护，但不得复制平台底座，不得自建身份、账本、证据库、Agent Runtime 或第二个业务事实源。

文档权威层级：

| 级别 | 文档 | 权威语义 |
|---|---|---|
| L0 | 本文档 | 唯一总架构、边界、底座、依赖和实施顺序 |
| L1 | 位置外勤、识别训练等领域规格 | 只定义 Domain Pack 内部业务语义，必须从属 L0 |
| L2 | Stage/L0–L6 实施计划 | 将已批准规格映射到文件、测试、迁移和提交 |
| L3 | Runbook、测试报告、ADR 和验收证据 | 记录如何运行、决策变更和是否达标 |

任何从属文档与本文冲突时，默认以本文为准；确需改变总架构时，必须先新建 ADR，再同步修订所有受影响文档。

## 1. 执行摘要

本项目的核心不是识别，也不是传统 SaaS。它要建设的是一个以 Graph+Loop 为运行内核的智能业务操作系统：系统能够围绕客户目标动态编排能力、持续观察结果、判断下一步、调用工具、请求人工介入，并在预算、权限和审计约束下完成业务闭环。

FMCG 视觉识别是第一个落地领域和第一套行业能力包，用来验证这套智能内核能否在高数据量、强证据、模型不确定性、人工审核和计费约束下可靠运行。第二个已确认的领域包是“Geo Foundation + Field Operations”，用于地址主数据、工作时定位、电子围栏、多点路线、任务派发、EDS 类无清单普查和现场证据闭环。未来的问卷、数据库分析、BI、追踪和客户专属业务也应作为新的领域能力包接入同一内核，而不是继续扩展一个以识别为中心的系统。

已经确认的总体方案是：

1. 第一阶段 100% 在本机运行，降低早期成本；成熟后可演进为“云端智能控制面 + 客户现场或本地能力执行面”。
2. 系统第一层核心是 Graph Runtime、Loop Engine、能力注册表、策略与权限、状态/记忆、人工检查点、评估和审计，不是识别模块或 CRUD 页面。
3. 本机阶段采用“Graph+Loop 内核 + 模块化领域能力 + 隔离 Worker”的架构。业务事务保持一致性，训练、推理、下载和分析等重任务通过队列隔离。
4. PostgreSQL 是系统事实库；文件系统采用内容寻址存储，并预留 S3 兼容适配器。SQLite 只允许作为历史迁移源、离线缓存或测试工具。
5. Web、API、Agent、小程序和 App 共用同一套能力、Graph、Run 和领域 API，不允许每个入口重新实现业务规则。
6. 客户不只购买“某个功能页面”，而是购买能力额度、预构建工作流和可定制 Graph+Loop 服务。用量按节点、模型、token、人工和存储进入不可变账本。
7. 基础客户可以使用平台预置、版本冻结的固定 Graph；高级客户购买可定制 Graph、持续 Loop、专属工具和更高预算。智能内核是系统架构核心，不等于所有高级能力免费开放。
8. Label Studio、视觉模型、问卷、BI 和数据库分析都是 Capability Provider。它们通过统一能力契约接入，不反向控制平台。
9. Agent 只能读取授权的客户数据和调用获批能力；可自动写系统自己的 Run、Checkpoint、用量、审计和衍生产物，不能直接写客户源数据或绕过领域服务。
10. FMCG 识别首域仍采用多模型流水线，并保留商品版本、照片证据、人工审核和分档服务，但这些属于首个 Domain Pack，不是平台中心。
11. 位置与外勤领域必须使用版本化地点、路线、围栏、任务和证据；Agent 只生成候选和建议，正式事实由领域服务与人工/策略门执行。

本设计覆盖 Graph+Loop 智能内核、能力市场与工具治理、智能工作台、FMCG 识别首域、位置与外勤第二领域、Label Studio、审核、训练、数据、计费、8TB 本地容量和每日十万张照片的增长目标。位置与外勤的完整语义以 `docs/superpowers/specs/2026-08-04-location-field-operations-design.md` 为准。

### 1.1 与传统 SaaS 的第一性区别

| 维度 | 传统 SaaS 思路 | 本系统 |
|---|---|---|
| 用户入口 | 找菜单、开页面、填表单 | 提交目标或直接调用能力 |
| 业务流程 | 固定在页面和服务代码中 | 版本化 Graph 编排能力 |
| 智能作用 | 页面旁增加聊天助手 | Loop 持续观察、判断、执行和求助 |
| 模块关系 | 每个模块拥有一套流程 | 模块提供可复用 Capability |
| 状态 | 页面状态、任务表、聊天上下文分散 | Run、Node、Checkpoint 和领域事实分离 |
| 客户差异 | 复制页面、字段和分支代码 | Graph、Policy、工具和数据产品组合 |
| 风险控制 | 给用户/Agent 一个大角色 | 每节点最小权限、预算和人工检查点 |
| 计费 | 按账号、模块或固定套餐 | 账号/套餐 + Run/Node/token/算力/人工用量 |
| 进化 | 发布新页面和功能 | 反馈 → 评估 → 新 Graph/能力版本 → 影子验证 |

保留直接模块页面是为了专业操作、人工接管和审计，不代表系统退回以 CRUD 页面为中心。

## 2. 设计边界

### 2.1 本期目标

- 首先交付完整 Foundation Milestone：统一身份与数据底座、Module SDK、Graph+Loop Kernel、证据、事件任务、账本、审计、Web 壳和运维基线。
- 建立 Graph+Loop 最小内核：Graph 定义、版本、执行、循环、检查点、工具调用、预算、人工介入、终态和审计。
- 建立统一能力契约，使识别、标注、审核、训练、问卷、BI、数据查询和未来客户能力都能成为可编排节点。
- 建立目标驱动的智能工作台，同时保留确定性模块页面作为直接操作、审计和人工接管入口。
- 以 FMCG 识别作为第一条端到端参考 Graph，完成照片或 URL 到质量、识别、审核、发布、计费和反馈学习的闭环。
- 将 Geo Foundation 和 Field Operations 作为第二个可插拔 Domain Pack，冻结地址、工作会话、轨迹、围栏、路线、普查区块、任务和现场证据的统一契约。
- 形成原始数据、标注、审核、数据集快照、训练运行、模型版本、Graph 版本和结果之间可追溯的生命周期。
- 支持 API、Web 和 Agent 三种入口启动同一 Graph 或直接调用获批领域能力。
- 从第一版开始具备租户、客户、项目、权限、保留策略、客户商品映射和用量账本的数据边界。
- 在 8TB 本地磁盘条件下，为每日十万张照片的稳态吞吐设计背压、分层存储和容量预警。
- 明确开源内核、商业能力和客户定制 Graph 的边界，避免未来从传统 SaaS 菜单重新改造成智能系统。

### 2.2 本期明确不做

- 当前不进行公有云部署、自动扩缩容或跨地域容灾。
- 当前 Stage 0–7 不完整实现问卷、BI、小程序和员工 App；员工 App 与地理外勤能力按第二 Domain Pack 的 L0–L6 单独计划实施。
- 当前不承诺对任意客户、任意照片都成立的统一准确率；准确性承诺只针对客户确认的冻结验收集。
- 当前不自动删除任何业务数据。保留策略、到期状态和预警先实现，真实删除必须经过明确审批与可恢复流程。
- 当前不允许 Graph 节点或 Agent 直接更新客户源数据、模型发布状态、价格或结算结果；高风险变更只能生成待审批命令。
- 本文不修改任何现有代码，也不替代后续逐阶段实施计划。

## 3. 成功标准

### 3.1 业务成功标准

- 客户能够用目标而不是页面路径启动工作，例如“分析本周门店缺货并追踪异常”，系统将其落为可解释、可暂停、可继续的 Graph Run。
- 同一业务目标可根据客户权限、数据、预算和服务档位选择不同 Graph，而不复制整套应用。
- 每次 Run 能解释经过哪些节点、读了哪些授权数据、为何循环、何时请求人工、花费多少以及为何结束。
- FMCG 识别、标注和审核可以作为一条参考 Graph 完成闭环，同时也能被其他 Graph 作为能力复用。
- 明确门店任务与 EDS 类无清单普查可以在同一内核中分别通过点任务 Graph 和区域普查 Graph 闭环。
- 新增问卷或 BI 时只需注册领域能力和数据产品，不需要重新建设身份、计费、Agent、审计和任务底座。
- 开源版能运行最小 Graph+Loop 内核和示例能力包；商业能力通过注册接入，不污染开放内核。

### 3.2 技术成功标准

- 所有写业务数据的操作只能经过领域服务，禁止 Graph 节点、前端、Worker、插件和 Agent 绕过服务直接写表。
- 每个 GraphDefinition、GraphVersion、LoopRun、NodeExecution、Checkpoint 和 PolicyDecision 都可追溯。
- 任何节点和异步任务可安全重试，使用幂等键避免重复动作、重复识别、重复账单和重复发布。
- Graph 在进程重启后能够从持久检查点恢复，不依赖模型上下文窗口记住运行状态。
- Loop 具有最大轮数、时间、token、费用、数据范围和人工检查点，不允许无界自治。
- 每个模型结果保存输入版本、模型版本、路由策略版本、阈值版本和运行环境。
- 主业务请求不等待训练或批量识别完成；重任务进入队列并可被暂停、取消、限速和恢复。
- 单模块故障不会阻断整个系统；Label Studio、训练、VLM 或 SAM 不可用时，平台能降级并明确标记结果质量。
- 容量、队列积压、失败率、P95 延迟、GPU/MPS 利用率、单位照片成本和人工复核率可观测。

## 4. 架构选择与理由

### 4.1 采用方案

采用修订后的方案 B：本机 Graph+Loop 内核 + 模块化能力单体 + 隔离 Worker。

Graph+Loop 是业务运行主干，能力模块是可注册节点，PostgreSQL、存储、身份和计费是可信执行基础。第一阶段仍保持一个可部署控制单元，降低本机运维成本；模型、训练、下载、报表和长循环通过独立 Worker 隔离。

### 4.2 未采用方案

| 方案 | 当前不采用的原因 | 未来触发条件 |
|---|---|---|
| 传统模块化 SaaS + 外挂聊天 Agent | Agent 只能导航 CRUD，无法成为业务运行内核；流程、记忆、预算和反馈仍散落在模块中 | 不作为目标架构 |
| 单进程“大一统”智能应用 | 长 Loop、训练与推理容易耗尽资源；故障域太大；无法独立限速 | 不考虑作为正式目标 |
| 从第一天拆微服务 | 本机运维复杂、事务和调试成本高、能力契约尚未稳定 | 能力需独立团队、独立扩缩或有明确故障隔离收益 |
| 纯云智能平台 | 当前成本高，客户数据和大文件传输不经济 | 本机内核与能力契约成熟后 |

### 4.3 总体逻辑图

~~~mermaid
flowchart TB
    subgraph EXPERIENCE["One Experience Plane"]
        WEB["Web 应用壳 / 智能工作台"]
        ENTRY["API / App / 小程序 / 外部 Agent"]
        GW["Unified API Gateway"]
        WEB --> GW
        ENTRY --> GW
    end

    subgraph KERNEL["One Graph+Loop Intelligence Kernel"]
        RUNTIME["Graph Registry / Loop Runtime / Checkpoint"]
        POLICY["Policy / Permission / Budget / Human Gate"]
        CAPREG["Module / Capability / Tool Registry"]
        EVAL["Evaluation / Memory / Audit"]
    end

    subgraph MODULES["Pluggable Domain Packs"]
        FMCG["FMCG Vision"]
        LABEL["Annotation / Review"]
        TRAIN["Dataset / Training / Model"]
        GEOFIELD["Geo Foundation / Field Operations"]
        QB["Questionnaire / BI"]
        CUSTOM["Customer-specific Future Packs"]
    end

    subgraph FOUNDATION["One Trusted Platform and Data Foundation"]
        IAM["Identity / Tenant / Project"]
        PG[("PostgreSQL Unified Fact Store")]
        OBJECTS[("CAS / Evidence / Artifact Storage")]
        BUS["Outbox / Inbox / Job / Worker Control"]
        MONEY["Usage / Billing / RateCard"]
        OPS["Config / Feature Flag / Observability"]
    end

    GW --> RUNTIME
    GW --> CAPREG
    RUNTIME --> POLICY
    RUNTIME --> CAPREG
    RUNTIME --> EVAL
    CAPREG --> FMCG
    CAPREG --> LABEL
    CAPREG --> TRAIN
    CAPREG --> GEOFIELD
    CAPREG --> QB
    CAPREG --> CUSTOM
    RUNTIME --> IAM
    FMCG --> PG
    LABEL --> PG
    TRAIN --> PG
    GEOFIELD --> PG
    QB --> PG
    CUSTOM --> PG
    FMCG --> OBJECTS
    LABEL --> OBJECTS
    TRAIN --> OBJECTS
    GEOFIELD --> OBJECTS
    FMCG --> BUS
    LABEL --> BUS
    TRAIN --> BUS
    GEOFIELD --> BUS
    RUNTIME --> MONEY
    RUNTIME --> OPS
~~~

这张图的核心不是“每个模块都连一个数据库”，而是所有 Domain Pack 进入同一平台后，在统一身份、数据、事件、证据、计费和运行规则下拥有自己的领域边界。本机阶段它们可在一个模块化单体中运行；未来只拆需要独立扩容或故障隔离的 Worker/数据面，不重写平台契约。

## 5. 技术基线

| 层级 | 选型 | 约束 |
|---|---|---|
| 后端与 AI | Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic | 领域服务和 API 类型统一；现有逻辑通过适配器迁移 |
| 前端 | TypeScript、React、PWA | 同一代码基线支持管理端和客户 Web；移动端先响应式 |
| 外勤移动端 | React Native/TypeScript + Swift/Kotlin 原生适配 | 可共享业务层；定位、相机、加密存储和设备信任不由 PWA 承担 |
| 智能内核 | 版本化 Graph DSL + 持久状态机 + Capability SDK | 不把运行状态放在 LLM 上下文；运行时实现可替换 |
| 事实库 | PostgreSQL | 第一版即包含 tenant_id、customer_id 和审计字段 |
| 异步执行 | 可替换队列接口；本机可用 Redis 队列实现 | 领域层不绑定具体队列；支持优先级、重试、取消、死信 |
| 文件存储 | 本机 CAS + S3 Compatible StorageAdapter | 数据库保存对象引用、哈希、大小、媒体类型，不存大图二进制 |
| 标注 | 上游 Label Studio + ML Backend + 平台网关 | 不 fork 核心；Webhook 只作为事件通知，不作为唯一可靠传输 |
| 推理 | PyTorch / ONNX Runtime / Core ML / MLX 适配层 | 按 Apple Silicon、NVIDIA、CPU 能力选择执行后端 |
| 可观测性 | OpenTelemetry 语义、结构化日志、Prometheus 指标接口 | 本机可先用轻量存储，但字段与接口不缩减 |
| 部署 | 本机进程编排或 Docker Compose 二选一配置 | 业务接口不依赖部署方式 |

所有外部组件必须通过版本锁定、许可证清单和安全扫描进入系统。正式开源前对模型权重许可证、数据集许可证、商标使用和第三方服务条款做专项法律复核。

## 6. 内核与能力边界

系统分为五个边界，领域能力不得反向接管内核或复制底座：

1. Experience：智能工作台、直接模块页面、API 和客户入口。
2. Intelligence Kernel：Graph、Loop、策略、记忆、评估、检查点、人工介入和预算。
3. Module Integration Plane：Module SDK、Manifest、注册表、UI 插槽、Capability/DataProduct/DomainCommand 契约和版本兼容性。
4. Domain Pack：识别、标注、审核、训练、地理、外勤、问卷、BI 和客户专属模块。
5. Trusted Foundation：身份、租户、PostgreSQL、对象存储、事件任务、审计、计费、配置和可观测性。

模块化单体只是当前部署形态，不是产品中心。真正稳定的边界是 Graph Contract、Capability Contract、Domain Command 和 Data Product Contract。

八条强制架构规则：

1. 任何识别专属功能必须通过 Capability 或 Domain Pack 接入，禁止在 Graph Runtime 中写 FMCG 特例。
2. 任何通用内核能力除用 FMCG 参考 Graph 验证外，还要用一个极小的非识别 Graph 验证，防止所谓通用内核实际被识别流程绑死。
3. 不先空造一个庞大通用平台再接识别；最小内核与 FMCG 识别纵向切片共同迭代，每增加一个内核能力都必须解决当前参考 Graph 的真实问题。
4. Platform 代码不得 import 任何具体 Domain Pack；模块只能通过 Module Contract 反向注册。
5. Domain Pack 不得直接写其他模块的 schema；跨域交互只能通过领域 API、DomainCommand、事件或经授权 DataProduct。
6. 身份、租户、证据存储、事件任务、审计、计费和可观测性只由平台底座提供，模块禁止自建平行版本。
7. 本机首版不接受上传任意代码的运行时插件；所有模块必须随代码审查、版本锁定和签名 Manifest 进入系统。
8. 停用、升级或故障的模块不能删除历史事实、证据、Run 和账本，也不能阻断其他模块。

| 模块 | 核心职责 | 禁止行为 |
|---|---|---|
| Graph Registry | Graph 定义、版本、输入输出 schema、发布和兼容性 | 运行时修改已发布版本 |
| Loop Runtime | 节点调度、循环条件、检查点、恢复、终止和补偿 | 依赖模型对话上下文保存真实状态 |
| Capability Registry | 能力、工具、数据产品、成本、权限和健康声明 | 注册任意代码后无沙箱执行 |
| Policy & Budget | 数据范围、工具白名单、模型档位、token/费用/时间预算 | 让节点自行扩大权限或预算 |
| Memory & Evaluation | 短期状态、客户授权记忆、运行评估、反馈和回归 | 把未审核模型输出写成长期事实 |
| Human Interaction | 人工任务、审批、询问、仲裁和接管 | 用“等待人工”隐藏无终态运行 |
| Identity & Tenant | 用户、服务身份、角色、租户、客户、项目、授权范围 | 业务模块自建权限逻辑 |
| Ingestion | 文件和 URL 接入、下载、去重、病毒与媒体校验、批次 | 直接触发未审计的模型调用 |
| Asset & Evidence | 原图、衍生图、哈希、证据链、保留策略 | 覆盖原图或复用路径冒充新版本 |
| Quality | 斜拍、反光、翻拍、大头照、模糊、遮挡、可恢复性 | 仅凭单一模型分数删除照片 |
| Scene | 货架、冰柜、冷风柜、地堆、堆箱、小货架、其他场景和价签有无 | 把场景结论冒充 SKU 结论 |
| Annotation | 标注项目、任务、预标注、Label Studio 映射、导入导出 | 把第三方内部 ID 暴露为平台主键 |
| Review | 任务分配、链接、盲审、仲裁、错误类型、金标准 | 审核者修改原始提交记录 |
| Recognition | 识别作业、多模型路由、融合、置信度、拒识 | 直接发布未经规则检查的单模型结果 |
| Catalog | 商品主档、包装版本、客户映射、新包装候选 | 用客户别名覆盖平台商品历史 |
| Dataset | 数据集定义、快照、切分、血缘、污染检查 | 训练时动态读取“最新数据”导致不可复现 |
| Training | 训练方案、运行、资源门禁、评估、产物 | 训练完成即自动成为生产模型 |
| Model Registry | 模型、版本、权重、指标、兼容性、审批、部署状态 | 覆盖已有模型文件或指标 |
| Routing | 服务档位、路由策略、阈值、降级、A/B 和影子运行 | 在代码里硬编码客户价格和模型组合 |
| Usage & Billing | 原始用量事件、聚合、套餐、价格版本、账单对账 | 修改或删除已入账事件 |
| Agent Interface | 将自然语言目标编译为已授权 Graph 输入，解释进度和结果 | 自行创建未注册工具或直接业务写入 |
| Admin & Audit | 配置、健康、审计、导出、容量和合规 | 使用日志替代审计事实 |
| Geo Foundation | 位置版本、地图适配、工作时位置、围栏、空间事件和路线矩阵 | 在领域对象中泄漏供应商字段或覆盖历史坐标 |
| Field Operations | 工作会话、活动、候选/正式任务、派单、路线、普查区块、现场执行和重排 | Agent 直接写正式任务、派单或员工处置结论 |
| Mobile Field Evidence | 工作会话定位、离线补传、门头必拍、可选自拍和证据链 | 非工作时跟踪或用单信号自动处罚 |
| Questionnaire / BI | 当前只提供模块契约、导航和数据产品接口 | 本阶段扩张为完整业务实现 |

### 6.1 必须先完成的统一底座

“底座先行”不是先建大量空表和空页面，而是先建立所有模块无法各自正确重做的共享语义。底座最小完整集为：

| 底座单元 | 必须统一的事实 | 完成标志 |
|---|---|---|
| Identity & Scope | Platform/Tenant/Customer/Project、用户、服务身份、RBAC + ABAC | 同一身份从 Web/API/Agent 访问任意模块时语义一致 |
| Module Platform | ModuleManifest、注册、依赖、版本、启停、健康和租户功能开关 | 新模块只通过插槽接入，无需修改 Kernel |
| Graph+Loop Kernel | Graph/Run/Node/Checkpoint、预算、停滞、人工门和恢复 | 两个不同领域的最薄 Graph 都能注册和恢复 |
| Unified Data | 全局 ID、租户范围、UTC、版本、幂等、迁移、事务和数据所有权 | 模块拥有独立 schema，但共用一套治理和备份恢复 |
| Asset & Evidence | CAS、哈希、血缘、签名访问、保留、legal hold | 识别照、门头照、问卷附件和报表不重做存储 |
| Event & Job | 事务 Outbox、幂等 Inbox、Job/Attempt、租约、重试、死信和 Worker 配额 | 模块故障不丢任务且不重复产生业务副作用 |
| Policy & Human Gate | 权限、数据范围、成本、风险、审批和 PendingCommand | Agent 不能因模块不同而获得更大权限 |
| Usage & Billing | UsageEvent、资源单位、冲正、RateCardVersion、预算和对账 | 新模块只注册 meter，不自建计费表 |
| Audit & Decision | AuditEvent、DecisionEvent、证据引用、correlation_id 和导出审计 | 可从结果追到 Run、人/模型、输入、规则、成本和历史版本 |
| Experience Shell | 统一登录、全局上下文、导航插槽、通知、人工待办、Run/证据抽屉 | 模块只提供页面和操作声明，不自建第二管理端 |
| Configuration & Operations | 统一配置、密钥引用、feature flag、health、metrics、trace、backup | 可以独立观测/停用单模块，不影响其他模块 |

底座通过的核心验收不是“页面能打开”，而是一个新 Domain Pack 可仅提交 Manifest、自有 schema/迁移、Capability、API、事件、UI 插槽、meter 和测试，即被同一平台发现、授权、编排、计费、审计和运维。

### 6.2 Domain Pack 强制契约

每个模块必须交付一份版本化 ModuleManifest：

| Manifest 部分 | 必填内容 |
|---|---|
| Identity | module_id、display_name、semantic_version、owner、license/open-source tier |
| Compatibility | platform_api_range、contract_versions、dependency modules 及版本范围 |
| Data Ownership | 拥有的 schema/table family、保留分类、可发布 DataProduct；禁止声明其他模块表 |
| Capabilities | capability_id、input/output schema、effect level、permission、timeout、cost unit、idempotency |
| Commands & Events | DomainCommand、发布/订阅事件、schema version、失败与补偿语义 |
| API & UI | OpenAPI route namespace、菜单/工作台插槽、页面权限、空状态和故障状态 |
| Workers | worker_type、queue、resource profile、concurrency、retry/dead-letter 策略 |
| Billing | Usage meter、业务量单位、成本类别和免费/冲正事件 |
| Operations | config schema、secret references、feature flags、health check、metrics、alerts |
| Verification | contract tests、migration tests、tenant-isolation tests、disable/upgrade/failure behavior、performance gate |

模块状态为 discovered → validated → migrated → enabled ↔ degraded/disabled → upgrading；失败进入 failed 并保留诊断。disabled 只停止新命令、导航和 Worker，不删除数据，历史 Run 仍可阅读。

首版采用“受审查的代码包 + 启动时注册 + 租户 feature flag”，不做任意代码热加载。这样既能像积木一样组合，又不会把客户上传插件变成远程代码执行风险。

### 6.3 模块独立维护的真正含义

独立维护不等于独立系统或独立数据真相。每个 Domain Pack 应拥有：

- 独立代码目录、模块负责人和 CODEOWNERS 边界；
- 独立 schema 与只向前迁移，但由统一 Migration Orchestrator 检查顺序和备份；
- 独立契约、回归集、性能门、发布版本和回滚/前向修复策略；
- 独立 Worker 资源档位、队列、并发上限和故障隔离；
- 可按 tenant/project 启用或锁定版本，但继续复用统一权限、证据、账本和审计。

禁止通过共享 Python 内部函数或跨 schema SQL 形成隐式依赖。高频同进程调用也必须经过稳定的领域接口，以便未来不改变消费者即可将重 Worker 拆为独立进程或设备。

本机模块化单体阶段的“独立发布”，是指模块拥有独立语义版本、迁移、契约回归、feature flag 和前向修复边界；应用主进程仍可作为一个受控发布物升级。只有当独立扩缩容、硬件或故障域已产生真实收益时，才拆出独立进程/数据面，不在本机初期为了“微服务化”增加运维成本。

### 6.4 目标代码边界（逻辑目录）

后续实施计划必须将当前代码渐进映射到以下逻辑边界，不要一次性搬家：

~~~text
src/platform/                 # 内核和全局共享底座，禁止 import src/modules
  kernel/                     # Graph / Loop / Checkpoint / Evaluation
  modules/                    # Module SDK / Manifest / Registry / lifecycle
  iam/                        # identity / tenant / policy scopes
  data/                       # unit of work / outbox / migration orchestration
  assets/                     # CAS / evidence / retention
  jobs/                       # job / attempt / queue / worker control
  billing/                    # usage ledger / RateCard
  audit/                      # audit / decision / export trails
  api/                        # gateway / shared error and idempotency semantics
  observability/              # logs / metrics / traces / health

src/modules/
  fmcg_vision/                # 识别、商品、包装、场景
  annotation_review/          # Label Studio、任务、审核、仲裁
  dataset_training/           # 数据集、训练、评估、模型注册和发布门
  geo_field/                  # Geo Foundation + Field Operations
  questionnaire/             # 问卷 Domain Pack
  bi/                        # BI / DataProduct Domain Pack

contracts/                    # 跨模块稳定 schema，不放领域实现
migrations/platform/          # 平台底座迁移
migrations/modules/{module_id}/ # 各模块自有迁移
web/src/platform/             # Web 壳、权限、Run/待办/证据共享 UI
web/src/modules/{module_id}/  # 模块页面和导航插槽
tests/contract/               # 平台与模块必过契约测试
~~~

实施时必须保留当前 `src/recognize`、`src/labeling`、`src/training`、`src/ls_platform` 等现有入口的兼容性，先用 Adapter 接入新底座，验收后再逐步迁移；禁止为了目录整齐一次性重写现有识别和训练线。

### 6.5 领域积木目录与依赖方向

| Domain Pack | 自有事实 | 允许依赖 | 降级/未安装语义 |
|---|---|---|---|
| FMCG Vision | 识别 Job/Attempt/Result、商品/包装和路由策略 | Platform Asset/Evidence、Model Capability | 不提供商品识别，其他模块仍可上传/审核证据 |
| Annotation & Review | 标注任务、提交、审核和仲裁 | Platform HumanTask/Evidence；可选订阅 Vision/Questionnaire 对象 | 业务 Graph 可转客户自有复核或明确停在 waiting_human |
| Dataset / Training / Model | DatasetSnapshot、TrainingRun、Evaluation、ModelVersion | Platform Asset/Job；可选消费冻结 Annotation/Review | 不能新建训练，已发布模型仍按注册状态供其他能力使用 |
| Geo + Field Operations | Location、Campaign、Task、Assignment、Route、Execution | Platform Evidence/Job；可选调用 Storefront Vision | Vision 未安装或不健康时转基础质量 + 人工复核，不停止整个外勤系统 |
| Questionnaire | Questionnaire、Response、Assignment、Validation | Platform Task/Human/Evidence；可选引用 Location ResourceRef | 不提供问卷任务，不影响识别或外勤 |
| BI / DataProduct | MetricDefinition、SemanticModel、ReportSnapshot | 只消费经授权 DataProduct/事件 | BI 停用不阻断交易写入，历史报表仍作为 DerivedArtifact 可读 |
| Customer Graph Pack | GraphDefinition/Version 与客户策略 | 只调用已安装且授权 Capability/DataProduct | 依赖缺失时禁止发布或运行，不自动替换工具 |

依赖可以是 required 或 optional，但必须在 Manifest 中明示。required 缺失时模块不允许 enabled；optional 缺失时必须有已测试的降级语义，不得在运行时才临时猜测。

## 7. 智能工作台与管理端

### 7.1 信息架构

统一 Web 的默认入口不是传统功能菜单，而是智能工作台。页面仍采用“顶部全局上下文 + 左侧能力导航 + 主工作区 + 右侧运行/证据抽屉”，同时提供两种使用方式：

- 目标模式：用户描述目标、选择数据范围和预算，系统匹配或建议 Graph，实时展示节点、循环、成本和人工检查点。
- 直接模式：专业人员直接进入识别、标注、审核、训练、数据或模型页面，进行确定性操作和人工接管。

这两种模式调用同一能力与领域服务；目标模式不是套在传统页面外面的聊天框。

- 顶部：租户、客户、项目、环境、全局搜索、通知、用户菜单。
- 智能工作台：首页目标输入、推荐 Graph、运行中任务、待人工决定和最近成果。
- Graph 中心：模板、版本、可视化结构、输入输出、成本预算、发布和回归。
- Run 中心：节点时间线、循环次数、检查点、证据、费用、暂停、恢复和终止。
- 能力中心：领域能力、工具、数据产品、模型、健康、权限和价格单位。
- 人工任务中心：审核、补充信息、审批、仲裁和任务链接。
- 运营总览：吞吐、失败和积压、审核待办、训练状态、磁盘容量、服务档位用量。
- 识别中心：创建作业、批次进度、结果浏览、证据链、重跑和导出。
- 标注中心：平台任务列表、Label Studio 嵌入入口、预标注状态、插件配置。
- 审核中心：我的任务、任务分配、分享链接、盲审、仲裁、质量统计。
- 数据中心：照片、URL 下载、批次、数据集快照、保留策略、导入导出。
- 训练中心：实验、资源门禁、实时指标、评估、模型候选、对照实验。
- 模型中心：模型卡、兼容硬件、许可证、版本、发布和路由策略。
- 位置中心：公共地点、客户私有覆盖层、地址/坐标版本、出入口、围栏和候选查重。
- 调度中心：工作中员工、任务池、不可达原因、路线方案、冻结窗口和动态重排。
- 普查活动中心：地图区块、道路/POI 基线、覆盖热力、Agent 建议、管理协调和补扫闭环。
- 现场证据中心：门头必拍、多轮匹配、新门头/位置变化候选、补拍和人工复核。
- 用量计费：不可变用量、套餐消耗、估算成本、对账和异常。
- 系统管理：身份、租户、角色、模块、Worker、健康、容量、审计。
- 问卷与 BI：本阶段显示模块状态和未来接入契约，不伪造已实现能力。

### 7.2 当前页面的迁移策略

现有 review.html、workbench.html、dashboard.html 和 monitor.html 不直接拼接成最终产品。它们先由统一壳通过路由或受控嵌入承载，再逐页迁移到共享组件、统一身份和领域 API。

必须设置兼容适配器：

- LegacyCascadeAdapter：包装当前级联识别接口。
- LegacyBundleRegistryAdapter：把现有模型包映射到新模型注册中心。
- LegacyTrainingAdapter：把现有训练运行和日志映射到训练中心。
- LabelStudioAdapter：屏蔽 Label Studio 任务、标注和预测的内部结构差异。

适配器只承担迁移，不允许成为新的永久业务事实源。

## 8. 身份、租户与权限

### 8.1 租户层级

建议层级为 Platform → Tenant → Customer → Project。Tenant 是合同与数据隔离主体，Customer 可表达同一合同下的业务客户或品牌，Project 是权限、任务和模型策略的最小常用范围。

所有业务表至少包含：

- tenant_id；
- customer_id，可为空的系统级记录除外；
- project_id，按领域需要；
- created_at、created_by；
- version 或不可变事件序号；
- source_system 和 correlation_id。

任何查询必须由服务端根据身份注入数据范围，禁止相信浏览器或 Agent 自报的 tenant_id。

### 8.2 角色

| 角色 | 主要权限 |
|---|---|
| 平台超级管理员 | 平台配置、租户开通、全局健康；高风险操作需二次确认 |
| 客户管理员 | 本租户成员、项目、套餐、客户映射和导出 |
| 项目/任务经理 | 数据接入、任务分配、识别作业、模型策略申请 |
| 标注员 | 指定任务的标注与提交 |
| 审核员 | 独立判断、退回、错误分类；不可改写原标注 |
| 只读分析员 | 授权数据、报表和证据只读 |
| Agent/API 服务身份 | 仅被授予的 API scope、预算和项目范围 |

RBAC 负责角色，ABAC 负责 tenant、customer、project、task、数据敏感级别和链接范围。最终授权必须同时满足两者。

### 8.3 分享链接

任务链接必须签名、短时有效、可撤销、限定任务和动作，首次访问使用一次性验证码。链接不能承载长期会话凭证，不能允许浏览其他任务，也不能通过修改参数扩大范围。

分享链接生命周期：创建 → 待领取 → 首次验证码 → 已绑定审核身份 → 已提交或过期 → 撤销归档。所有状态变化写审计事件。

## 9. 统一数据契约

### 9.1 核心对象

| 对象 | 说明 | 关键不可变性 |
|---|---|---|
| GraphDefinition | 一种业务目标的图结构、输入输出和约束 | 已发布定义不可原地修改 |
| GraphVersion | 可执行的冻结 Graph 版本 | 保存节点、边、策略和能力版本快照 |
| CapabilityDefinition | 一个可被编排的领域能力、工具或数据产品 | 名称、schema、权限、成本和副作用明确 |
| LoopRun | 客户目标的一次有界执行 | 关联 GraphVersion、预算、身份和终态 |
| NodeExecution | 一个节点的一次执行尝试 | 重试追加 attempt，不覆盖旧结果 |
| Checkpoint | 可恢复的持久运行状态 | 包含状态哈希和前序事件位置 |
| PolicyDecision | 一次权限、预算、路由或审批判断 | 保存规则版本、输入证据和结果 |
| HumanTask | Graph 暂停后交给人的审核、补充或审批 | 人工决定独立保存，不改写节点历史 |
| PendingCommand | 建议对领域状态执行的受控命令 | 执行前重新校验权限和目标版本 |
| WorkItemProjection | 跨模块统一待办/调度视图 | 只是可重建投影；业务命令必须返回 owner module |
| DerivedArtifact | 报告、解释、追踪结果等系统衍生产物 | 保存输入引用、生成链和适用范围 |
| Asset | 一份原始照片、下载内容或衍生内容 | content_hash 指向唯一内容；原始对象不可覆盖 |
| AssetRelation | 原图与纠偏图、裁剪图、缩略图之间的关系 | 必须记录算法、参数和父对象 |
| IngestionBatch | 一次文件或 URL 批量输入 | 保存请求快照、来源和幂等键 |
| QualityAssessment | 一次质量评估 | 保存模型、阈值、指标、证据区域和结论 |
| RecognitionJob | 客户请求的一次识别作业 | 保存档位、策略版本和验收口径 |
| RecognitionAttempt | 一个模型或路由节点的执行 | 不因重试覆盖，attempt_no 递增 |
| RecognitionResult | 融合后的候选、框、SKU、场景、价签结论 | 保存证据引用和决策版本 |
| AnnotationTask | 平台标注任务 | 平台 ID 与 Label Studio ID 分离 |
| AnnotationSubmission | 标注员一次提交 | 提交后不可原地修改；修订生成新版本 |
| ReviewDecision | 审核员独立判断 | 不可覆盖其他人的决定 |
| DatasetSnapshot | 冻结的数据集成员、标签和切分 | 通过 manifest 哈希可复现 |
| TrainingRun | 训练配置、代码、数据、环境和输出 | 运行结束后只允许追加评估和审计 |
| ModelVersion | 权重、配置、许可证、指标和兼容性 | 权重哈希唯一，发布状态走审批 |
| Place / LocationVersion | 稳定地点身份与地址/坐标/出入口版本 | 任务和历史事件始终引用当时版本 |
| FieldSession / PositionSample | 员工主动开始的工作会话与短期精确位置 | 会话结束后的新位置必须拒绝 |
| GeofenceVersion / GeoEvent | 版本化围栏与到店、离店、偏航等派生事件 | 不以单漂移点形成重大结论 |
| Campaign / TerritoryBlockVersion | 明确地点、普查或抽样活动及地图区块 | 进行中不静默修改范围和验收规则 |
| TaskCandidate / Task / Assignment | 多来源候选、正式任务和已确认派单 | Agent 只能写候选/建议，不能越过领域命令 |
| RoutePlanCandidate / RoutePlanVersion | 候选方案与已发布的矩阵、约束、站点、未分配原因和成本 | 发布/重排创建新版本，不覆盖旧方案 |
| EvidenceArtifact / ValidationRun | 门头照、自拍等现场证据与多轮验证 | 原件不覆盖，模型不直接定性员工 |
| UsageEvent | 一次可计费或可核算资源使用 | 只追加，冲正通过反向事件 |

### 9.2 状态机原则

状态变化必须由命令触发并写入审计事件。LoopRun 主状态机：

created → validating → ready → running ↔ waiting_external / waiting_human → completed

异常和控制终态为 failed、cancelled、budget_exhausted、policy_blocked、expired。paused 是可恢复状态，不是终态。每次循环、重试和恢复都产生新的 NodeExecution 或 RunEvent，不能重写历史。

FMCG 识别能力内部仍有独立 RecognitionJob 状态机：

created → validating → queued → running → awaiting_review → completed

异常分支为 rejected、failed、cancelled。failed 允许创建新的 attempt，但不能把旧失败改写成成功。completed 后若重跑，生成新的作业版本或派生作业。

### 9.3 文件和证据

文件对象路径不作为身份，content_hash 才是内容身份。数据库至少记录 SHA-256、字节数、MIME、宽高、EXIF 摘要、来源、下载时间、父对象和存储后端。

预处理不是覆盖原图：

original Asset → derived Asset → algorithm version → parameters → metrics → reviewer decision

导出结果应同时包含稳定对象 ID 和可验证哈希。外部 URL 只保存为来源，下载后的内容必须落为独立 Asset；同 URL 内容变化时形成新版本。

### 9.4 统一数据系统底座

“统一数据底座”指统一数据身份、治理、访问、事件、血缘、保留、备份和读模型规则，不是把所有业务字段塞进一张通用表。本机阶段使用一个 PostgreSQL 实例和一套统一存储管理，内部按 schema 明确事实所有权。

数据底座分为四层：

1. **Authoritative Facts**：平台和各 Domain Pack 的权威事实表，每个事实只有一个拥有者。
2. **Immutable Assets & Evidence**：图片、文档、模型、数据集 manifest 和报表进入 CAS，数据库保存哈希、引用和血缘。
3. **Events & Change Log**：领域事件通过事务 Outbox 发布，供 Graph、其他模块和读模型幂等消费。
4. **Derived Read Models**：搜索、向量、BI、热力图、报表和 Agent Retrieval 都是可重建派生物，不得反向写为业务真相。

对“全系统都会用到”的概念，必须区分平台事实与领域事实：

| 通用概念 | 统一底座拥有 | Domain Pack 拥有 |
|---|---|---|
| 人与组织 | User/ServiceIdentity/Tenant/Customer/Project 及授权 | WorkerProfile、ReviewerProfile、问卷对象等领域角色扩展 |
| 文件与证据 | Asset/EvidenceArtifact、哈希、存储、保留和访问审计 | “这份证据证明什么”的任务要求和验证结论 |
| 任务与待办 | HumanTask、PendingCommand 和跨模块 WorkItemProjection | AnnotationTask、FieldTask、QuestionnaireAssignment 等业务状态机 |
| 运行与调度 | LoopRun、NodeExecution、Job/Attempt、Checkpoint | RecognitionJob、TrainingRun、RoutePlan 等领域执行语义 |
| 费用与审计 | UsageEvent、RateCardVersion、AuditEvent、DecisionEvent | 模块 meter 和业务量计量方法 |

WorkItemProjection 只用于统一待办箱和调度视图，保存 owner_module、ResourceRef、assignee、due_at、risk、display_status 和 deep_link。它不是所有业务任务的通用真相；接受、退回、完成等命令必须路由回拥有该任务的 Domain Pack。

所有模块对象共用一个标准 ResourceRef：`resource_type + resource_id + resource_version + tenant_id + project_id`。跨域引用保存当时版本，不通过复制其他模块字段建立影子真相。

交易边界：

- 一个 DomainCommand 在自有 schema 内修改事实并写 Outbox，必须使用同一个数据库事务；
- 跨 Domain Pack 的长流程由 Graph/Saga 协调，不使用跨 schema 直接写和超长数据库事务；
- 跨模块只读分析使用授权 DataProduct 或版本化读模型，Agent 不获得任意 SQL；
- 全局数据导出必须通过 Export Service 并记录字段范围、用途、数量、对象哈希和审计事件。

数据底座可以在增长后将轨迹、分析或对象存储拆到不同物理设备，但 ResourceRef、DataProduct、事件、权限、保留和审计契约不变，因此客户和 Domain Pack 仍然看到一套统一数据系统。

## 10. 数据输入、下载与预处理

### 10.1 两种输入

1. 文件直传：支持单文件、批量和压缩包清单。服务先登记批次和上传会话，完成后校验哈希与媒体类型。
2. URL 输入：支持单 URL 和清单。下载 Worker 处理超时、跳转、大小上限、域名策略、重试、限速和内容校验。

两者最终都进入同一个 Asset API，因此后续质量、识别、标注和计费不区分入口。

### 10.2 URL 安全

- 阻止 localhost、私网、链路本地、云元数据地址和非允许协议，防止 SSRF。
- DNS 解析和实际连接地址都要校验，重定向每一跳重新校验。
- 设置连接、读取、总时长、最大响应体和最大像素数。
- MIME 声明与文件魔数同时校验；解码在隔离 Worker 内完成。
- 失败保留错误类型、响应摘要和关联 ID，不在日志泄露认证参数。

### 10.3 预处理流水线

预处理按配置执行，结果版本化：

1. 解码和方向归一；
2. EXIF 与元数据抽取；
3. 缩略图生成；
4. 清晰度、曝光、反光、透视、翻拍与构图分析；
5. 可选的透视纠正、局部增强和颜色归一；
6. 场景和商品区域候选；
7. 质量策略决定通过、警告或拒绝；
8. 保存所有证据与指标。

增强只服务于后续识别，不能被当成原始证据。任何影响视觉内容的操作都必须记录参数。

## 11. 照片质量与证据链

### 11.1 评估维度

| 风险 | 检测信号 | 处置 |
|---|---|---|
| 严重斜拍 | 货架线、矩形透视、相机姿态和 OCR 文本方向 | 可纠正则警告并生成纠偏图；不可恢复才拒绝 |
| 严重反光 | 高光饱和区域、商品关键区域覆盖率、纹理损失 | 局部可用则警告；关键识别证据被遮蔽才拒绝 |
| 严重翻拍 | 屏幕摩尔纹、边框、像素栅格、二次压缩、反射 | 标记来源风险；不自动等同于无效 |
| 大头照误导 | 单商品占比、背景缺失、场景覆盖、脸部或非货架构图 | 区分“可做 SKU 识别”和“不可做场景/陈列验收” |
| 模糊/抖动 | 拉普拉斯、频谱、边缘方向与局部清晰度 | 关键区域不可辨认才拒绝 |
| 遮挡/裁切 | 商品和价签候选越界、遮挡比例 | 进入警告或人工复核 |
| 无商品证据 | 商品候选、OCR、视觉特征均不足 | 拒绝并给出可操作的重拍原因 |

### 11.2 三级结论

- 通过：满足当前任务的证据要求。
- 警告：存在风险，但仍可完成部分任务；结果必须声明适用范围。
- 拒绝：当前任务需要的商品证据不可恢复，继续识别只会制造误导。

拒绝结论不得只由一个分数决定。规则应组合任务类型、关键区域、模型指标和可恢复性。所有阈值按版本保存，可对历史照片做影子重算，但不能改写旧结论。

### 11.3 证据链字段

每次评估至少保存：

- 原图哈希和衍生图哈希；
- 任务类型；
- 质量模型与规则版本；
- 每项原始指标、归一化分数和阈值；
- 风险区域框或掩码；
- 自动结论、原因码和面向人的解释；
- 人工复核结论、人员、时间和理由；
- 重跑关联、申诉和仲裁结果。

质量证据未来用于员工考核时，必须展示原图、风险区域、当时规则和人工复核，不能只展示一个总分。

## 12. 场景与价签识别

场景标签采用分层多标签，不强制一张照片只能属于一种场景：

- 一级：零售场景、非零售场景、未知；
- 二级：货架、冰柜、冷风柜、地堆、堆箱、小货架、端架、其他；
- 属性：开放/封闭、单面/多面、拥挤度、可见层数；
- 价签：有、无、不可判断，并保存价签区域。

“无价签”必须满足场景可见范围足够且价签检测可靠；否则是“不可判断”，避免把大头照或局部裁切误判为无价签。

场景结果进入后续路由：冰柜反光阈值、地堆检测尺度、小货架目标密度和价签 OCR 策略应各自配置。

## 13. 标注平台总体设计

### 13.1 Label Studio 边界

Label Studio 作为独立标注引擎，提供成熟的标注 UI、项目配置、任务和标注能力。平台拥有客户、数据、任务编排、证据、审核、计费和模型治理。

平台不把 Label Studio 数据库作为业务事实库，不 fork 上游核心，也不依赖其 Webhook 实现 exactly-once。Webhook 事件先进入 inbox 表，以 event_id 或内容哈希去重，再由同步任务通过 API 对账。

上游开源版和企业版能力不同。SSO、细粒度权限和团队治理必须由平台网关承担，不能假设社区版天然具备所有企业功能。

“Label Studio 100% 完成”的验收定义如下：

- 所选并锁定的上游开源版本，其任务创建、标注配置、数据导入、标注 UI、预测展示、导出、Webhook 和 ML Backend 等公开能力可以正常使用；
- 平台统一身份、租户范围、任务分配、审核、证据、计费和外挂数据通过集成层补齐；
- 上游企业版专属能力不冒充开源能力重新实现；确需采用时通过合法商业授权接入；
- 任何平台插件都通过兼容性测试，升级 Label Studio 前在副本环境完成迁移和回归；
- 验收以能力矩阵和端到端用例为准，不以“页面能打开”作为完成标准。

### 13.2 统一标注适配层

AnnotationProvider 接口至少包含：

- create_project；
- push_tasks；
- pull_annotations；
- push_predictions；
- create_share_context；
- validate_label_schema；
- health；
- export_snapshot。

LabelStudioProvider 是第一实现。未来新的多模态标注模式只需实现相同接口，并把供应商格式转换为平台统一 AnnotationDocument。

### 13.3 多模态外挂数据库

外挂层用于管理 Label Studio 不适合承担的内容：

- 图片、视频帧、文本、商品主档和包装版本关系；
- 模型候选、相似商品、OCR 结果和场景上下文；
- 多轮对话式标注、审核理由和证据；
- 客户字段扩展；
- 标注 schema 版本和转换器；
- 数据集血缘与计费事件。

Label Studio 任务只携带完成 UI 所需的短期引用。下载实际媒体必须经过签名代理，代理校验任务、租户和到期时间。

### 13.4 自动画框与辅助模型

预标注流水线：

1. 质量和场景模型选择候选路由；
2. 检测器生成商品和价签框；
3. SAM 根据框或点细化掩码；
4. 检索/分类器生成 SKU Top-K；
5. OCR 和 VLM 提供文字、属性和解释；
6. 规则引擎解决硬冲突并标记不确定项；
7. 以 Prediction 形式送入 Label Studio；
8. 标注员确认、修改或拒绝，形成新的 AnnotationSubmission。

预标注永远是建议，不可伪装成人工金标准。模型版本、置信度和来源必须随结果保存。

### 13.5 标注和识别审核

常规任务采用“一名执行者 + 一名独立审核者”。金标准、模型发布验收和计费争议采用双盲两人审核；不一致时进入第三人仲裁。

统一错误分类：

- 正确；
- 错标；
- 漏标；
- 重复标注或多标；
- 框或掩码不合格；
- unknown 错误放行；
- 照片本身不合格；
- 任务规则不明确。

审核者提交的是独立 ReviewDecision。退回后执行者产生新提交版本，原提交和原审核均保留。

### 13.6 任务分配

任务池支持按项目、技能、负载、盲审规则和截止时间分配。分享链接只是一种领取方式，不是权限系统。

为防止选择性审核和串通，金标准任务应随机混入、隐藏来源，并记录打开时间、停留时间、修改轨迹和最终提交。考核指标需要排除规则变更和模型建议差异造成的非人员责任。

## 14. 识别系统与多模型路由

### 14.1 识别不是单模型

推荐流水线：

Asset → Quality → Scene → Detector → SAM 可选细化 → Embedding Retrieval → SKU Classifier/OCR → VLM Challenger → Rules/Fusion → Reject/Review/Publish

各组件职责：

| 组件 | 主职责 | 不应承担 |
|---|---|---|
| 检测器 | 找出商品、价签和场景目标 | 单独判定近似包装 SKU |
| SAM | 在提示框/点基础上分割商品，改善裁切与遮挡 | 直接提供稳定 SKU 身份 |
| Embedding | 在客户目录中召回相似商品和新包装候选 | 覆盖条码等硬冲突 |
| SKU 分类器 | 对已知目录做高效细粒度判别 | 对分布外商品强制选类 |
| OCR | 条码、品牌、规格、价格和文字证据 | 对无清晰文字的对象猜测 |
| VLM | 长尾属性、语义校验、冲突挑战、解释 | 对所有照片无条件调用 |
| 规则/融合 | 硬约束、版本化阈值、拒识和升级 | 隐藏证据或抹平模型冲突 |

条码、客户商品主键和明确规格冲突属于硬冲突，不能被视觉相似度静默覆盖。

### 14.2 客户四档服务

| 档位 | 默认路由 | 客户体验 | 资源策略 |
|---|---|---|---|
| 低 | 质量 + 场景 + 检测 + 轻量分类/检索 | 最快、成本最低、较高拒识与复核率 | 小模型、批处理、低优先级 |
| 中 | 低档 + SAM 条件细化 + OCR + 更强分类融合 | 速度与准确性平衡 | 中等预算、冲突升级 |
| 高 | 中档 + VLM 挑战者 + 多视角/新包装规则 + 更严审核 | 更高准确性和解释性 | 高预算、优先队列 |
| 极高 | 高档 + 模型集成 + 客户专属模型 + 必要人工复核 | 客户冻结验收集上的最高目标 | 独占或保留算力、最严路由 |

档位不是固定模型名，而是版本化 Policy。模型升级后可以保持客户合同不变。每个 Policy 明确目标延迟、最大模型调用、最大 token、人工复核条件、降级行为和计费单位。

准确率只能针对客户专属、版本冻结、双方确认的验收集承诺；同时报告覆盖率、拒识率、复核率和延迟，防止通过大量拒识虚增准确率。

### 14.3 路由决策

路由输入包含：

- 客户档位和项目策略；
- 硬件能力与当前负载；
- 场景和质量风险；
- 客户商品目录规模；
- 检测数量与候选熵；
- 模型之间是否冲突；
- 新包装/未知概率；
- SLA 剩余时间和预算。

路由输出必须可解释：调用了什么、为何升级或降级、跳过了什么、最后为何发布或复核。

### 14.4 失败与降级

- SAM 不可用：保留检测框，标记未做掩码细化。
- VLM 不可用：不伪造 VLM 结果；按档位进入重试、降级或人工复核。
- 客户专属模型不可用：禁止暗中切换为通用模型并保持相同 SLA；必须记录降级。
- 队列积压：优先按 SLA、客户档位、到期时间和公平份额调度，防止极高档垄断全部资源。
- 模型输出格式异常：结果进入失败或复核，原始响应按安全策略留存。

## 15. 本地多模态模型方案

### 15.1 模型角色

7B 以内本地 VLM 的第一目标不是替代检测器和 SKU 分类器，而是：

- 在 Top-K 候选中做语义挑战；
- 提取包装上的品牌、规格、口味和促销属性；
- 解释模型冲突；
- 判断未知商品、新包装和场景异常；
- 生成可供审核的结构化证据。

高频 SKU 继续由高效检测、检索和分类承担，VLM 只处理需要语义推理的少数样本，才能保证每日十万张照片目标下的效率。

### 15.2 候选基线

| 候选 | 适用角色 | 选择建议 |
|---|---|---|
| Qwen3-VL 2B / 4B | 中文包装、多图理解、结构化输出 | 作为首选基线；先比较 2B 与 4B 的准确性/延迟增益 |
| Gemma 3 4B | 通用视觉语言对照 | 作为第二模型对照，尤其验证跨语言和部署生态 |
| Florence-2 large | 轻量检测、描述、OCR 类任务对照 | 作为专项轻量基线，不作为通用问答主模型 |
| SigLIP 2 / DINOv3 | 向量检索、表征和新包装聚类 | 不作为生成式 VLM；用于召回和主动学习 |
| SAM 2.1 | 本机与跨硬件分割主线 | 先采用 tiny/small 做吞吐测试，再按收益升级 |
| SAM 3.x | 文本概念分割专项研究 | 单独验证许可证、Apple 路径和性能后再进入生产 |

模型选择以真实客户数据上的 Pareto 前沿为准，不因参数更大自动升级。

### 15.3 Apple Silicon 约束

- 正式 VLM 生产最低建议 Apple Silicon 统一内存 32GB；更小内存只允许低并发实验。
- 优先使用 MPS、Core ML、MLX 或 ONNX 可验证路径；每个模型版本声明 supported_backend。
- 训练启动前必须通过内存、磁盘、温度、供电、MPS 算子和恢复能力门禁。
- DataLoader、图像解码和增强不能无界并发，避免 CPU 和统一内存争用。
- 训练与在线识别默认互斥大资源时段；若并行，必须设置内存和并发配额。
- CPU 只提供低速兼容路径，不承诺生产吞吐。

NVIDIA 生产最低建议 16GB 显存。跨硬件发布前必须分别验证数值差异、量化行为和吞吐，不把 Apple 验证结果直接外推到 CUDA。

### 15.4 微调策略

分阶段执行：

1. 零样本基线：冻结提示模板、输出 schema 和验收集，测清模型本身能力。
2. 监督微调：使用经过双重审核的商品属性、候选比较、拒识和冲突解释样本。
3. LoRA/QLoRA：优先微调语言与跨模态投影的少量层；在真实收益不足时才扩大可训练参数。
4. 困难样本回灌：只从错误簇、包装变化、强相似 SKU、反光和遮挡中选择高价值样本。
5. 偏好或排序训练：在有可靠成对判断后，训练候选排序和拒识偏好。
6. 蒸馏：把高档模型或人工确认结果蒸馏到中低档模型，降低长期成本。

训练数据必须包含正例、近邻负例、unknown、证据不足和不应回答样本。只增加相似正例会让模型更敢猜，不会自然提升拒识能力。

### 15.5 训练样本结构

每个训练样本建议包含：

- 原图和必要的商品裁切；
- 场景与质量元数据；
- 客户目录中的候选 Top-K；
- 平台商品、包装版本和客户映射；
- 结构化目标：是否可识别、SKU/unknown、属性、证据区域、理由码；
- 审核状态和可靠性权重；
- 数据来源、时间、门店/批次分组键；
- 禁止进入训练的合规标记。

样本切分必须以商品版本、门店、拍摄批次和时间分组，防止同一连拍或近重复图片同时落入训练和测试。

## 16. FMCG 商品与包装版本

### 16.1 三层主数据

1. CanonicalProduct：平台稳定商品概念，例如品牌、品类和基础产品族。
2. PackagingVersion：某一时间段的包装、条码、规格、图片特征和上市状态。
3. CustomerProductMapping：客户如何命名、编码和合并该商品或包装版本。

客户对新包装可选择：

- 沿用旧商品名称和客户 SKU；
- 更换名称，但仍映射同一个稳定商品；
- 把新包装视为新的客户 SKU；
- 暂不确认，进入新包装候选池。

### 16.2 识别结果的版本语义

结果同时保存：

- platform_product_id；
- packaging_version_id；
- customer_mapping_id 与 mapping_version；
- 当时展示名称和客户 SKU 的快照；
- 判定证据；
- 新包装候选状态。

历史结果不得因客户后来改名而变化。查询时可选择“按当时口径”或“按当前映射重述”，两者必须明确区分。

### 16.3 新包装发现

新包装候选由以下信号组合：

- 与已知 SKU 语义接近但视觉嵌入偏移；
- 条码、规格或关键文字变化；
- 同一门店/时间段集中出现；
- 分类器置信度下降但 VLM/检索指向同一产品族；
- 审核员多次选择 unknown 或包装变化。

候选先聚类，再由商品管理员确认“版本更新、客户新 SKU、错误图片或真正新品”。确认会新增实体和映射，不会覆盖旧数据。

### 16.4 时间有效性

PackagingVersion 和 CustomerProductMapping 都包含 valid_from、valid_to 和 transaction_time。这样既能回答“照片拍摄当时应识别为什么”，也能回答“平台何时获知这项变化”。

## 17. 数据集、训练和模型治理

### 17.1 数据集快照

训练只能引用 DatasetSnapshot，不允许读取不断变化的查询结果。快照 manifest 至少包含：

- 每个 Asset 和 AnnotationSubmission 的稳定 ID 与哈希；
- 标签 schema 版本；
- 训练/验证/测试/金标准切分；
- 分组和去重规则；
- 质量风险和样本权重；
- 商品与包装映射版本；
- 创建人、审批人和用途限制。

### 17.2 数据质量门禁

训练前必须检查：

- 文件可读性、重复和近重复；
- 标签 schema 合法性；
- 错标、漏标、框质量和 unknown 比例；
- 商品、包装、场景和质量维度的长尾覆盖；
- 训练/验证泄漏；
- 客户数据授权和模型用途；
- 与上一版本的数据分布漂移；
- 金标准样本是否被训练污染。

门禁失败必须 fail-closed，不允许训练脚本静默跳过异常后继续产出可发布模型。

### 17.3 训练运行

每个 TrainingRun 冻结：

- 数据集 snapshot_id 与 manifest_hash；
- 代码 commit、工作区脏状态和依赖锁；
- 训练配置哈希、随机种子；
- 硬件、执行后端、内存与系统版本；
- 基础权重哈希和许可证；
- 开始/结束时间、失败原因和恢复点；
- 指标、日志、样例预测和权重产物。

训练允许断点恢复，但恢复必须生成新的 attempt 并关联原运行。不能以覆盖日志的方式伪装连续成功。

### 17.4 评估矩阵

最低评估维度：

- SKU Top-1、Top-K、unknown 精确率/召回率；
- 检测 mAP、召回率和小目标表现；
- 场景多标签 F1；
- 价签有/无/不可判断混淆矩阵；
- 包装版本和新包装召回；
- 按斜拍、反光、翻拍、大头照、模糊分桶；
- 按客户、门店、场景、品类、头部/长尾 SKU 分桶；
- 覆盖率、拒识率、人工复核率；
- P50/P95 延迟、吞吐、峰值内存、能耗代理指标；
- 单张照片、单个对象和每千次调用的成本。

任何总分必须同时给出分桶指标。不得用头部 SKU 的提升掩盖长尾退化。

### 17.5 发布门禁

模型状态：

draft → evaluated → approved → shadow → canary → active → deprecated → archived

发布条件包括：

- 客户冻结验收集达标；
- 关键安全与拒识指标不退化；
- Apple/NVIDIA 目标后端性能通过；
- 模型卡、许可证和数据用途完整；
- 影子运行和小流量 canary 无重大异常；
- 回滚包和前一稳定版本可用。

训练完成只产生 ModelVersion 候选，不能直接切换生产路由。

### 17.6 训练未达预期时的方法论

后续优化不再以“继续多跑几轮”为默认动作，而使用误差驱动闭环：

1. 冻结一个不会参与训练的客户验收集和一个长期回归集。
2. 把失败样本按原因聚类：数据错误、框错误、近邻混淆、unknown 放行、质量问题、包装变化、域偏移、路由错误。
3. 判断瓶颈位于检测、裁切、表征、分类、VLM、融合还是标签体系。
4. 每个实验只改变一个主要变量，并设置最大 epoch、最大时间和停止条件。
5. 优先修复贡献最大的错误簇，记录预期收益和实际收益。
6. 只有跨分桶稳定提升且资源成本可接受，才进入影子发布。
7. 把新错误回灌到金标准或困难集，保持回归测试累积而非重建。

这套方法把“训练次数”改成“可证伪的假设数”，避免在错误标签、数据泄漏或错误路由上浪费 Mac 资源。

### 17.7 现有训练线的承接规则

docs/training-history-and-decisions.md 是当前训练事实与已批准动作的专门记录；本总体设计不覆盖它，也不构成新的训练启动授权。实施时必须遵守其中 2026-08-04 已确认结论：

- 不恢复 sku_v6 phase2；旧 v6 只作历史对照。
- 新 detector lineage 从 v4 或 COCO 初始化，先比较 class-agnostic product detector。
- 当前端到端首要瓶颈是检测覆盖，不先盲目扩大 classifier。
- 先运行 2,000 train + 300 val、3 epoch、MPS、batch 4 的 pilot；胜出后再做单 seed 10 epoch，有明确收益才扩三 seed。
- classifier 先完成 true-box、predicted-box、unknown 的分层 oracle 诊断，再决定是否换骨干。
- active protocol 的样本 ID、哈希、规范门店、别名和 session 必须全部零交集，数据集新目录构建且 fail-closed 防覆盖。

当前 Apple M3 Max 的 arm64 Python、MPS 张量和级联推理已经通过基础验证，硬件不是本轮阻断项；但每个新的 detector、VLM 和量化版本仍需单独完成 MPS 算子、峰值内存和吞吐门禁。

本智能内核路线对当前训练的直接帮助是把这些门禁固化为 DatasetSnapshot、TrainingRun、Capability 和发布状态机，而不是立即改变已经确认的训练实验。

## 18. 用量、计费与服务商品化

### 18.1 双层模型

内部层是不可变 UsageLedger，记录真实资源消耗；客户层是 ProductCatalog、Plan、PriceVersion 和 Invoice，把资源组合成可售套餐。

不能直接拿日志做账单，也不能以客户套餐名称反推底层模型调用。

用量事实以 LoopRun 和 NodeExecution 为主关联，recognition_job、training_run、review_task 等只是领域级可选关联。这样未来问卷、BI 或客户专属 Graph 不需要另建一套计费系统。

### 18.2 原始用量事件

每个 UsageEvent 至少包含：

- tenant、customer、project、loop_run、node_execution；
- graph_version、capability_id、service_tier 与 policy_version；
- event_type；
- 领域工作量，例如照片数、对象数、问卷数、记录数或报表数；
- 模型 ID/版本、调用次数、输入/输出 token；
- 推理毫秒、设备类型、内存峰值代理；
- SAM、OCR、VLM、人工复核等资源单位；
- 定位样本、地理编码/POI/道路调用、路线矩阵 pair、规划计算、动态重排和围栏事件；
- 正式外勤任务、普查区块/覆盖复杂度、门头验证阶段、现场证据和人工复核时长；
- 幂等键、发生时间、入账时间；
- 成功、失败、降级和冲正关联。

账本只追加。系统错误导致的重复计费通过冲正事件处理，不修改历史。

### 18.3 客户计价

建议客户购买统一 Credit 或 Token 包，但账单仍展示可理解的业务单位：

- Graph Run 启动、节点执行和 Loop 轮次；
- Agent 输入/输出 token、记忆和工具调用；
- 基础照片处理；
- 商品对象识别；
- 高级模型升级；
- 人工复核；
- 长期存储和导出；
- 专属训练与模型托管。
- 地址/路线/围栏基础能力、外勤任务、EDS 普查、门头验证和 Agent 调度。

低、中、高、极高档的价格来自版本化价格表。价格、赠送额度、最低消费和 SLA 属于客户合同配置，不写死在识别代码中。

### 18.4 计费正确性

- 请求创建时预估并可预留额度，任务结束按实际用量结算。
- 超预算行为按策略拒绝、降级或申请追加，不允许静默超支。
- 失败是否收费由 event_type 和合同规则决定，并保留失败原因。
- 账单聚合必须可回溯到每个 UsageEvent、NodeExecution 和领域 attempt。
- 价格调整只创建新 PriceVersion，不重算已结算账单。
- 人工复核争议进入独立仲裁，不允许运营人员直接改底层事件。

## 19. Graph+Loop 智能内核

### 19.1 架构定位

Graph+Loop 是系统的业务运行内核，不是传统 SaaS 之外附加的 Agent 功能，也不是平台内部数据库管理员。任何跨能力、需要判断、反馈或人工介入的业务流程，都应表达为版本化 Graph，并由有边界的 Loop 推进。

不同业务可组装不同 Graph，节点和 Loop 不是写死的统一流程。

这里的定义必须明确：

- Graph 是可版本化的业务控制图，节点可以是确定性规则、领域服务、模型、数据查询、人工任务、事件等待或子图。
- Loop 是“观察状态 → 判断差距 → 选择动作 → 执行能力 → 验证结果 → 更新状态或停止”的有界循环。
- LLM/Planner 只是可选节点，不是 Graph Runtime 本身；确定性问题优先使用确定性节点。
- Agent 是用户与内核交互的一种界面或执行参与者，不再等同于整个 Graph+Loop 架构。
- 智能性来自可观察反馈、动态选择、记忆、评估和持续闭环，不来自无限调用大模型。

系统对客户分三层提供能力：

1. 基础层：平台内部使用固定 Graph 保证识别、标注和审核闭环，客户不需要理解 Graph。
2. 标准智能层：客户选择预构建行业 Graph，配置数据范围、档位、频率和输出。
3. 高级定制层：按 token/credit 售卖客户专属 Graph、长期 Loop、专属工具、客户数据产品和服务目标。

因此，Graph+Loop 同时是统一技术内核和高级商业产品。二者共享运行时，但开放的模板、编辑能力、预算和工具范围不同。

### 19.2 核心执行语义

GraphDefinition 必须声明：

- 输入与输出 schema；
- 节点、边、条件和可循环区域；
- 每个节点绑定的 CapabilityDefinition；
- 数据范围、工具白名单和最小角色；
- token、费用、时间、轮数和并发预算；
- 人工检查点、审批级别和超时处置；
- 成功、部分成功、拒绝、失败和预算耗尽的终态；
- 补偿、恢复和幂等策略；
- 评估器、证据要求和结果质量门槛。

Loop 不是无限重复。每一轮必须有可观察的新状态、明确的继续条件和停止理由。若连续两轮没有新增事实、风险下降或任务推进，应触发停滞检测，转人工或终止。

Graph 的“可变”必须同时满足智能性和可治理性：

- 已发布 GraphVersion 在运行中不可自我修改，保证同一次 Run 可复现。
- 客户差异优先通过配置、条件边、Policy 和已批准子图表达，不复制整套流程。
- Planner 可以根据目标提出新的 Draft Graph，但 Draft 必须通过 schema、权限、成本、环路、终态和测试验证后才能发布。
- 高级客户可在授权沙箱内执行临时 Graph；任何有副作用节点仍受 Policy 和审批约束。
- 运行反馈进入 Evaluation，优化器只生成下一 GraphVersion 候选，不能静默改变正在执行或已经结算的历史版本。

### 19.3 Capability Contract

每个能力必须像受控产品而非任意函数一样注册：

- capability_id、版本和提供者；
- 输入/输出 JSON schema；
- read_only、system_write、domain_command 等副作用等级；
- 所需权限、数据分类和允许租户范围；
- 预计/最大成本、超时、并发和资源类型；
- 幂等、重试、补偿和健康检查；
- 审计字段、证据输出和错误分类；
- 数据保留和许可证约束。

识别、Label Studio、审核、训练、问卷、BI、数据库查询、导出和通知都通过这一契约进入 Graph。模型不是直接暴露给任意 Agent，而是包装为受策略约束的能力。

### 19.4 数据权限与写入边界

Graph/Agent 可以：

- 调用经过批准的只读领域查询；
- 读取客户授权的数据产品、识别结果、问卷结果和 BI 指标；
- 生成衍生报告、解释、追踪任务和待审批建议；
- 自动写入系统自身的 Run、NodeExecution、Checkpoint、会话、用量、审计、反馈和衍生产物；
- 在 Policy 已预授权时，通过领域命令创建低风险系统任务，例如识别作业或人工审核任务。

Graph/Agent 不可以：

- 执行任意 SQL；
- 读取任意文件路径；
- 写客户源数据和核心业务表；
- 直接更改商品主档、标注、模型路由、价格或账单；
- 绕过租户、项目和字段级权限；
- 在未获批准时调用超预算模型或导出敏感数据。

“Graph 是核心”不等于“Graph 可以直接写所有数据库”。智能化来自受控编排、状态反馈和持续决策，不来自绕过业务规则。

### 19.5 待审批命令

需要改变业务状态时，Agent 只创建 PendingCommand，包含：

- 建议动作；
- 目标对象和预期版本；
- 理由和证据；
- 风险、成本和回滚方案；
- 提交人、审批角色和有效期。

人类批准后，由相应领域服务重新校验权限和版本再执行。审批不是 Agent 直接拿到写权限。

### 19.6 记忆、评估与学习

运行时状态、客户长期记忆和业务事实必须分开：

- Run State：当前 Graph 的临时状态和检查点，可恢复且随 Run 结束归档。
- Customer Memory：客户明确授权保存的偏好、术语和已确认规则，版本化、可查看、可撤销。
- Business Fact：商品、问卷、识别结果、账单等领域事实，只能由对应领域服务管理。
- Retrieval Index：事实的派生索引，可重建，不能反向成为事实源。

每个 GraphVersion 必须配套评估集，至少衡量任务完成率、事实正确性、证据完整率、人工接管率、平均循环数、P95 时间、成本、越权阻断和停滞率。智能内核升级必须先影子运行，不能只用主观聊天体验判断。

### 19.7 FMCG 首个参考 Graph

第一条参考 Graph 为“照片识别并形成可审计结果”：

接收照片/URL → 校验权限和预算 → 下载/入库 → 质量/场景判断 → 选择识别档位 → 多模型识别 → 冲突与 unknown 判断 → 必要时人工审核 → 发布结果 → 记录用量 → 收集反馈 → 判断是否进入数据集候选

它验证内核的关键能力：条件路由、模型升级、循环重试、人工节点、证据、预算、恢复和反馈。后续问卷追踪或 BI 异常分析复用相同内核，但拥有完全不同的 Domain Pack。

### 19.8 位置与外勤第二 Domain Pack

第二领域包用三条参考 Graph 进一步验证内核不被识别流程绑定：

1. Point Task Planning & Execution：候选任务 → 可行性/路线 → 自动或人工派单 → 工作会话/到店 → 门头和业务证据 → 复核/结案。
2. Territory Census：活动范围 → 地图区块 → Agent 推荐/管理协调 → 新地点候选 → 覆盖评估 → 未达标补扫。
3. Dynamic Replanning：延误/偏航/临时任务 → 冻结执行中与临近任务 → 重算剩余方案 → 低风险自动或高影响人工 → 新路线版本。

Agent 在这三条 Graph 中负责解释、推荐、协调和追踪；PostGIS/地图供应商/约束优化器负责空间事实与可行路线；领域服务负责正式任务、派单和决定。

## 20. 性能、容量与本机资源

### 20.1 每日十万张的含义

十万张/天平均约 1.16 张/秒，但真实流量会集中到数小时。按 10 小时活跃窗口约 2.78 张/秒，设计至少按 5 倍峰值约 14 张/秒的接入能力评估。接入吞吐不等于所有照片都能调用 VLM；必须依靠分层路由和异步队列。

### 20.2 8TB 容量模型

容量预算不能只看原图。每张照片还可能产生缩略图、纠偏图、多个裁切、掩码、模型中间产物和日志索引。系统每天计算：

- 原始对象字节；
- 衍生对象字节；
- 模型与训练产物；
- 数据库、索引、备份；
- 临时下载与队列工作区；
- 各保留策略即将到期和预计耗尽天数。

必须正视一个容量事实：8TB 能作为本机开发和近期生产起点，但不可能同时承载十万张/天和多年全量留存。即使平均原图只有 1MB，十万张也约为 100GB/天、36.5TB/年；半年原图约 18.25TB，2 年约 73TB，7 年约 255.5TB，尚未计入衍生物、模型和备份。8TB 在此假设下仅能保存约 80 天原图。

因此，“半年/2 年/7 年”是客户生命周期策略能力，不代表都存放在单块 8TB 本机盘。进入持续十万张/天前必须至少选择一种已验收方案：扩展本地存储池、分层归档到对象存储、按客户部署数据面，或只保留长期所需原图并依据合同管理衍生物。任何方案仍不得绕过删除审批和证据保留规则。

容量水位建议：

- 70%：预警并给出增长预测；
- 80%：限制非必要衍生物和新训练缓存；
- 90%：停止低优先级批次和大规模训练，等待管理员处理；
- 95%：只允许必要的恢复、导出和管理操作。

水位策略不是删除授权。开发阶段即使到期，也只标记 eligible_for_retention_action 并报警。

### 20.3 保留策略

客户套餐支持半年、2 年和 7 年。RetentionPolicy 分别作用于：

- 原图；
- 衍生图和模型中间物；
- 识别结果；
- 标注与审核；
- 用量账本；
- 训练和模型；
- 审计。

财务和审计数据可能有独立更长期要求，不能被照片保留期连带删除。未来执行删除前必须做 legal hold、引用关系、备份和双人审批检查。

### 20.4 性能策略

- 下载、解码、质量、检测、分割、VLM 和导出使用独立队列与并发上限。
- 批量推理按模型、尺寸和档位微批处理；交互请求设置最大等待时间。
- 模型常驻由热度和内存预算控制，不能同时把所有权重装入统一内存。
- 训练在低峰运行，并为在线识别保留资源。
- PostgreSQL 使用连接池、分页、适当索引和分区；大对象不进数据库。
- UI 使用虚拟列表、缩略图和按需加载，禁止列表页下载原图。
- 高重复 URL/文件通过内容哈希去重，但租户授权和计费关系独立保存。

### 20.5 性能验收

每个版本至少测试：

- 单照片交互延迟；
- 100、1,000、10,000 和目标规模批次；
- 5 倍峰值接入与队列恢复时间；
- Apple MPS、NVIDIA 和 CPU 降级路径；
- VLM 冷启动、热启动和模型切换；
- 训练与在线推理并发干扰；
- 8TB 容量水位与磁盘接近满载；
- PostgreSQL 连接耗尽、队列中断和 Worker 崩溃恢复。

十万张/天也不能解释为“一台 Mac 可让全部照片运行极高档模型”。正式容量承诺必须基于客户档位分布、每张商品数、VLM 升级比例和人工复核比例的加权负载模型。若单机测试未达标，通过增加独立 Mac/NVIDIA Worker 水平扩展；不得让 API 主进程承担重模型来伪造吞吐。

### 20.6 位置与外勤容量

第二 Domain Pack 以“单客户 1,000 名活跃外勤、10 万地点、每天 5 万任务”为容量目标，不把未压测的目标写成 SLA。PositionSample 按 tenant hash + 日期分区，规划 Worker 按城市/活动分片，H3 用于粗筛与覆盖聚合，PostGIS 负责精确几何。规划必须限时、先过滤硬约束，并返回可行方案或“当前运力不可达”，不运行无界全局优化。

## 21. API 与集成

### 21.1 统一端口

建议对外只暴露一个 HTTPS 入口：

- /api/graph/v1：Graph 定义、版本和发布；
- /api/runs/v1：启动、查询、暂停、恢复和终止 LoopRun；
- /api/capabilities/v1：能力目录、schema、健康和授权；
- /api/v1：领域业务 API；
- /api/agent/v1：自然语言目标、授权只读查询和待审批命令 API；
- /events/v1：受控事件订阅；
- /app：统一 Web；
- /label-studio：反向代理后的标注入口；
- /media：短时签名媒体代理。

内部服务端口只监听回环或私有网络，不直接向客户暴露。

位置与外勤在 `/api/v1` 下提供 locations/location-versions/geofences、field-sessions/position-batches/geo-events、campaigns/territory-blocks/coverage、task-candidates/tasks/assignments、route-plans/replanning 和 evidence/storefront-validations 等领域资源。Web、App、API 和 Agent 必须共用相同的命令与权限语义。

### 21.2 API 原则

- OpenAPI 是接口事实源，SDK 从规范生成。
- 命令使用 Idempotency-Key；Graph 启动返回 run_id，领域异步命令返回 job_id。
- 列表使用游标分页，不使用不稳定的深 offset。
- 错误包含稳定 error_code、面向人的 message、correlation_id 和可选 field_errors。
- 所有版本变更遵循兼容窗口；破坏性变化进入新主版本。
- Web、Agent 和未来 App 不复制 Graph、策略或领域业务规则。

### 21.3 事件

系统事件分为 Run 事件和领域事件。Run 事件包括 RunStarted、NodeCompleted、CheckpointCreated、HumanRequested、BudgetExhausted、RunCompleted；领域事件包括 AssetIngested、QualityAssessed、AnnotationSubmitted、ReviewResolved、RecognitionCompleted、ModelActivated、UsageRecorded，以及 LocationVersionConfirmed、FieldSessionStarted/Ended、PositionBatchAccepted/Rejected、GeofenceEntered/Exited、TaskFormalized、AssignmentProposed/Confirmed、RoutePlanPublished、EvidenceCaptured/Validated、CoverageEvaluated 和 CampaignCompleted。

事务采用 outbox：领域写入和 outbox 同一数据库事务提交，发布器异步投递。消费者使用 inbox 幂等去重，避免 Webhook 或队列至少一次语义造成重复处理。

## 22. 安全、审计与故障处理

### 22.1 安全基线

- 本机也必须使用最小权限服务账号、密钥分离和可轮换凭证。
- 密码使用现代自适应哈希；会话短期、可撤销、CSRF 防护完整。
- 敏感字段和导出按客户策略加密或脱敏。
- 精确位置只能在员工主动开始的工作会话中采集；管理端默认看派生事件，查看历史精确轨迹需额外 scope、目的和审计。
- 自拍与未来人脸数据属独立高敏能力；首版不自动比对人脸，启用前必须完成必要性、单独同意、替代方式、影响评估、最短保留和访问门。
- 上传、URL 下载、媒体解码和模型文件加载均视为不可信输入。
- 模型权重只从批准注册中心加载，并校验哈希。
- 日志禁止记录完整 token、密码、签名 URL 和不必要的原始客户数据。
- 关键操作要求二次确认或双人审批。

### 22.2 审计

审计事件与普通日志分离，记录 who、when、tenant、scope、action、object、before/after 摘要、reason、correlation_id 和结果。对追加型对象，before/after 使用版本引用，不复制大对象。

以下操作必须审计：登录失败、授权变更、Graph 发布、Run 启停/恢复、Capability 注册、工具调用、PolicyDecision、Checkpoint、人工检查点、分享链接、数据导出、质量人工推翻、审核仲裁、数据集冻结、训练启动、模型发布/回滚、价格版本、账单冲正和 PendingCommand。

### 22.3 故障语义

| 故障 | 系统行为 |
|---|---|
| PostgreSQL 不可用 | 停止所有业务写入，不退化到 SQLite 假装成功 |
| 文件写入失败 | 数据库事务不得标记 Asset 已就绪；临时对象等待回收审批 |
| 队列不可用 | 命令保持 pending 并报警，不同步执行重模型绕过配额 |
| Label Studio 不可用 | 平台任务保持可见；暂停推送并继续对账，不丢状态 |
| Worker 崩溃 | 租约超时后重试新 attempt，旧 attempt 标记 lost/failed |
| 模型 OOM | 记录硬件和输入，按策略减小批次、降级或转人工 |
| 账本写入失败 | 作业不得进入最终可结算状态，走 outbox 重试 |
| Graph 超预算 | 立即停止新节点，保存检查点，返回已完成部分和预算终态 |
| Graph Runtime 重启 | 从最后持久检查点恢复；不重复执行已提交的有副作用节点 |
| Capability 不可用 | 按 Graph 策略重试、降级、转人工或部分完成，不允许无限循环 |

## 23. 测试与验收策略

### 23.1 测试层级

- 契约测试：Graph、Capability、DataProduct、OpenAPI、AnnotationProvider、StorageAdapter、ModelRunner 和 Queue。
- 单元测试：Graph 状态机、循环终止、权限、预算、补偿、阈值、价格版本和映射时间语义。
- 集成测试：PostgreSQL、文件存储、队列、Label Studio、模型注册和 outbox/inbox。
- 端到端：目标/Graph → 文件或 URL → 质量 → 识别 → 审核 → 发布 → 用量 → 导出。
- 模型回归：冻结金标准和困难集，按客户、场景、包装、质量分桶。
- 性能测试：吞吐、延迟、内存、磁盘、队列恢复和混合负载。
- 安全测试：越权、SSRF、签名链接、恶意媒体、导出和 Agent 工具。
- 恢复测试：数据库备份恢复、对象校验、模型回滚和未完成任务续跑。
- 智能内核回归：Graph 版本兼容、检查点恢复、停滞检测、预算耗尽、人工接管和工具越权。
- 位置外勤：坐标系、工作会话边界、离线幂等补传、围栏迟滞、不可达、冻结窗口、普查覆盖和租户隔离。

### 23.2 关键验收用例

1. 用户从 Web 与 API 以相同目标启动同一 GraphVersion，节点、预算和结果语义一致。
2. Graph Runtime 在有副作用节点完成后崩溃，恢复时不重复写入或重复计费。
3. 连续两轮无新增事实，Loop 触发停滞检测并转人工，而不是继续消耗 token。
4. Graph 请求未授权数据或工具，被 Policy Engine 拒绝且无法通过改提示词绕过。
5. 同一 URL 内容变化，两次输入生成不同 Asset 版本且来源关系完整。
6. 严重反光但商品文字仍可读，系统给警告而非无条件拒绝。
7. 大头照可完成 SKU 判断，但场景与价签结论为不可判断。
8. 标注员漏标，审核员独立指出并形成新修订，历史不被覆盖。
9. 两名盲审者冲突，第三人仲裁后结果可追溯。
10. 新包装被聚类后，客户 A 沿用旧名、客户 B 使用新名，历史结果不变化。
11. VLM 不可用时高档任务明确降级或转人工，账单不按成功 VLM 调用计费。
12. 相同幂等键重复提交，不产生重复节点、重复识别和重复用量。
13. Agent 尝试任意 SQL 或越租户查询，被网关拒绝并写审计。
14. 磁盘超过 90% 时停止低优先级训练，不自动删除任何原图。
15. FieldSession 结束后的新位置被拒绝，非工作时不形成轨迹。
16. 离线批次含乱序和重复事件时可幂等恢复，不重复到店、任务和计费。
17. 电动车续航、返程或时间窗不满足时返回“当前运力不可达”及约束原因。
18. 每次任务都具有门头原图、位置/围栏、验证版本和人工决定证据链；新门头不被直接定性为员工问题。
19. 无门店清单的 TerritoryCampaign 可按地图区块派发，并通过覆盖、POI、新发现证据和抽检门形成补扫 Loop。

## 24. 实施路线图

### 24.0 底座先行总门

Stage 0 和 Stage 1 组成一个不可拆开的 Foundation Milestone。实施 Agent 先完成统一数据底座、平台服务、Module SDK/注册表、Graph+Loop Kernel、Web 壳和运维基线，再开始 Stage 2 以后的任何完整业务模块。

底座必须用两个“最薄插件”验证：

1. FMCG Recognition Bridge：只把现有单图级联推理包装为 Capability，不重写模型线。
2. Reference Work Pack（契约测试包）：位于测试 fixture，只提供候选工作项 → 人工确认 → 完成的虚拟闭环，不创建正式外勤事实，不提前实现定位、地图或路线算法。

两个验证包必须共用相同 IAM、ModuleManifest、PostgreSQL、CAS、Outbox/Inbox、UsageLedger、Audit、Web 导航插槽和 Run 时间线。如果为第二个包增加功能时需要改写 Kernel 内部的领域特例，Foundation Milestone 直接判定失败。

### Stage 0：契约与治理冻结

交付：

- GraphDefinition、GraphVersion、LoopRun、NodeExecution、Checkpoint 状态机和统一 ID；
- Capability、DataProduct、DomainCommand、HumanTask、PolicyDecision 契约；
- ModuleManifest、模块状态机、UI 插槽、Usage meter、Worker profile 和兼容矩阵；
- 领域词汇表和 FMCG 首个参考 Graph；
- OpenAPI 基线；
- tenant/customer/project 权限模型；
- Asset、Evidence、UsageEvent、DatasetSnapshot 契约；
- 内核/能力/领域边界、开源边界和许可证清单；
- 现有系统适配器清单；
- 平台底座与 Domain Pack 的 import/data ownership 依赖规则；
- 统一 ResourceRef、跨域事件、读模型和交易边界。

退出门禁：原始 15 项与新增位置外勤需求都能映射到平台底座或 Domain Pack；无两个模块同时拥有同一事实；任何副作用节点的授权和幂等语义明确；新模块不需修改 Kernel 即可声明全部插槽。

### Stage 1：本机统一底座与最小智能内核

交付：

- Module SDK、Module Registry、Manifest 校验、依赖/兼容检查、模块状态机和租户 feature flag；
- Graph Registry、Capability Registry 和版本冻结；
- Loop Runtime、Node Executor、持久 Checkpoint、暂停/恢复和终态；
- Policy/Permission/Budget Engine 与人工检查点；
- FastAPI 统一 Gateway、React Web 壳、导航插槽、人工待办、Run/证据/用量共享抽屉；
- PostgreSQL 统一事实库、platform/module 迁移编排、Unit of Work、Outbox/Inbox、身份、租户、审计和备份恢复；
- 本机 CAS、Evidence/Retention、Job/Attempt、队列、Worker 管理和健康页；
- UsageLedger、meter 注册、预算预留/结算、RateCard 接口和冲正语义；
- 统一配置、结构化日志、备份与恢复演练；
- FMCG Recognition Bridge：单图输入 → 现有级联识别适配器 → 结果与用量记录；
- Reference Work Pack（契约测试包）：虚拟候选工作项 → 人工确认 → 完成与用量记录，不写正式外勤表；
- 模块启用、停用、故障、升级、不兼容拒绝和历史可读的端到端契约测试。

退出门禁：两个最薄验证包均只靠 Manifest 和稳定契约注册；它们共用同一身份、数据、证据、事件、账本、Web 壳和 Graph Runtime；停用/破坏一个模块不影响另一个；跨进程重启可从检查点恢复；幂等节点不重复执行；预算、权限、停滞和人工门可验证；无 SQLite 双事实源；备份恢复和迁移失败演练通过。

Stage 1 未通过前，实施 Agent 不得通过复制新服务、新数据库、新管理端或模块专用 Agent 底座来提前搭建 Stage 2–9。

### Stage 2：FMCG 首个参考 Graph

交付：

- 文件和 URL 批次接入；
- SSRF 与媒体安全；
- 质量三级结论和完整证据；
- 场景多标签、价签有/无/不可判断；
- 容量水位与保留策略预警；
- 将 Stage 1 的最薄 Recognition Bridge 扩展为生产级 RecognitionCapability；
- “照片识别并形成可审计结果”Graph 的第一版；
- Graph 节点、领域作业和 UsageEvent 的全链路关联。

退出门禁：同一参考 Graph 可由 Web、API 和 Agent 启动；每个结论可回看 Graph、节点、原图、衍生物、指标和版本；错误重试不重复执行或入账。

### Stage 3：标注 100% 闭环

交付：

- Label Studio 网关、Provider、同步 inbox/outbox；
- Annotation、Review 和 HumanTask 注册为可编排能力；
- 多模态外挂数据库；
- 预标注和自动画框；
- 任务分配、签名链接、验证码；
- 单审、双盲、仲裁与错误分类；
- 统一标注导入导出。

退出门禁：从 Graph 创建任务到冻结数据集全程可追溯；人工任务可暂停和恢复原 Run；Label Studio 短暂中断不丢状态。

### Stage 4：生产级识别能力包

交付：

- 识别能力的统一 schema、版本和健康声明；
- 检测、检索、分类、OCR、SAM 适配器；
- 多模型融合、unknown 和人工升级；
- 作业、attempt、证据和导出；
- 低/中/高/极高 Policy 框架。

退出门禁：每一档有真实性能基线、降级策略和可审计用量；识别能力可被不同 Graph 复用而不复制业务规则。

### Stage 5：数据集、训练与模型中心

交付：

- DatasetSnapshot、污染和泄漏门禁；
- TrainingRun、Apple/NVIDIA 资源门禁和恢复；
- 模型卡、评估矩阵、影子、canary、回滚；
- 训练监控统一接入。

退出门禁：任何生产模型可从结果追到权重、训练、数据、标注和原图。

### Stage 6：FMCG 增强

交付：

- 商品主档、包装版本、客户映射；
- 新包装候选聚类与人工确认；
- Qwen3-VL 2B/4B 等 7B 内模型对照和 LoRA；
- SAM 吞吐优化；
- 困难样本、主动学习和分档蒸馏。

退出门禁：客户冻结验收集上的提升具有统计和业务意义，成本处于目标 Pareto 前沿。

### Stage 7：智能服务商品化与客户定制

交付：

- 完整用量账本、价格版本、套餐和对账；
- 客户 Graph Studio、模板库、版本发布和回归评估；
- 标准智能层和高级定制层的能力/预算/工具分级；
- 客户授权记忆、只读数据产品和 PendingCommand；
- 客户级成本、SLA 和争议审计。

退出门禁：账单能逐项回溯到 Run 和 Node；客户定制 Graph 不能扩大授权，Agent 无法直接写客户源数据或越权读取。

### Stage 8：位置与外勤第二 Domain Pack

交付：

- 按独立规格 L0–L6 实施 Geo Foundation 和 Field Operations；
- PostgreSQL/PostGIS、位置版本、地图适配、员工 App、工作会话、离线补传和围栏；
- 明确门店任务调度、路线规划、门头多轮证据和动态重排；
- EDS 类 TerritoryCampaign、Agent 区块建议、管理协调、新地点候选、覆盖验收和补扫 Loop；
- 位置、地图、规划、任务、证据和人工的用量账本。

退出门禁：点任务、区域普查和动态重排三条 Graph 均可恢复且可审计；非工作时不定位；路线无可行解时明确失败；门头、轨迹和任务跨租户读取全部拒绝；容量门达标或标记 NOT ACCEPTED。

### Stage 9：问卷、BI 与混合部署

交付：

- QuestionnaireProvider 和 BI DataProduct 契约实现；
- “问卷执行 → 数据分析 → 异常追踪 → 人工确认”的独立参考 Graph；
- 云控制面/本地数据面设备注册、策略下发和脱敏遥测；
- 小程序轻量入口、客户保留期执行流程和商业运维。

退出门禁：问卷/BI 可复用同一内核；本机部署无重写地拆分控制面和能力执行面；数据主权和离线行为清楚。

各 Stage 必须单独编写实施计划、测试清单、回滚方案和验收报告。未通过退出门禁不得用“功能已展示”代替完成。

## 25. 数据库与索引建议

### 25.1 Schema 分域

建议使用逻辑 schema 隔离所有权：

| Schema | 主要表族 |
|---|---|
| iam | tenants、customers、projects、users、service_identities、roles、grants |
| graph | definitions、versions、runs、node_executions、checkpoints、run_events |
| capability | definitions、versions、tool_bindings、data_products、health_states |
| policy | decisions、budgets、human_tasks、pending_commands、customer_memories |
| work | work_item_projections、projection_offsets（可由领域事件重建） |
| assets | assets、asset_relations、ingestion_batches、retention_policies |
| quality | assessments、signals、evidence_regions、manual_overrides |
| catalog | canonical_products、packaging_versions、customer_product_mappings、new_package_candidates |
| annotation | projects、tasks、provider_links、submissions、reviews、arbitrations |
| recognition | jobs、attempts、detections、candidates、results、routing_decisions |
| datasets | datasets、snapshots、snapshot_members、split_manifests |
| training | runs、run_attempts、metrics、artifacts、evaluations |
| models | models、versions、deployments、routing_policies、model_cards |
| billing | usage_events、plans、price_versions、subscriptions、invoice_lines、adjustments |
| intelligence | evaluations、tool_calls、derived_artifacts、feedback_events |
| geo | places、place_candidates、location_versions、access_points、geofence_versions、provider_references、position_samples、geo_events |
| field | field_sessions、campaigns、territory_block_versions、task_candidates、tasks、assignment_proposals、assignments、route_plan_versions、executions、visits |
| evidence | artifacts、requirements、storefront_validation_runs、review_tasks、decision_events |
| audit | audit_events、outbox、inbox、exports |

应用层仍应通过领域服务访问，schema 不是绕过模块接口的理由。

### 25.2 主键、唯一性与时间

- 主键使用全局稳定 UUID 或可排序 UUID，不暴露连续自增 ID 给外部。
- 所有时间保存 UTC，界面按客户时区显示。
- 外部提供方映射以 provider、external_id、tenant_id 建唯一约束。
- 幂等命令以 tenant_id、operation、idempotency_key 建唯一约束。
- UsageEvent 以 ledger_event_id 和 source_idempotency_key 防重。
- DatasetSnapshot、ModelVersion 和文件对象以内容哈希加强不可变性。
- 可变主数据使用 optimistic version；双时间数据使用有效时间和事务时间。

### 25.3 索引与分区

- 高频查询索引必须以 tenant_id 开头，再接 project_id、status、created_at。
- graph.run_events、graph.node_executions、recognition.jobs、usage_events、audit_events 和 metrics 按月或规模阈值分区。
- geo.position_samples 按 tenant hash + 日期分区；几何列使用经压测的 GiST/SP-GiST，H3 cell 只用于粗筛、分区和覆盖聚合。
- JSONB 只用于真正可扩展的模型元数据和证据详情；核心过滤字段必须正规化。
- 列表采用 created_at + id 的稳定游标。
- 模糊商品搜索使用受控全文或 trigram 索引；向量召回使用独立 pgvector/向量服务适配器，不能把向量当商品事实。
- 索引设计必须通过目标规模的 EXPLAIN 和读写压测验证，不能一次性添加所有可能索引。

## 26. Git、版本与发布治理

### 26.1 仓库策略

- 保持单仓库优先，目录按 frontend、backend、workers、contracts、adapters、docs 和 deployment 划分。
- main 始终可验证；功能在短生命周期分支开发。
- 每个变更对应一份明确规格或 issue，提交只包含单一逻辑意图。
- 禁止把模型权重、客户原图、数据库、密钥和大训练产物提交到 Git。
- 模型、数据集和大文件由注册中心/CAS 管理，Git 只保存 manifest、哈希和工具配置。

### 26.2 提交与审查

提交前最低门禁：

1. 工作区差异检查，确认不混入其他 Agent 或用户改动；
2. 格式、静态检查和单元测试；
3. 数据库迁移的正向/回退或前向修复策略；
4. OpenAPI 和 SDK 兼容性检查；
5. 安全、权限、计费和证据链专项测试；
6. 文档和变更记录；
7. 评审者确认范围与回滚方案。

提交信息使用类型与范围，例如 feat(recognition)、fix(billing)、docs(architecture)。发布使用语义化版本；数据库 schema、API、模型路由和价格表分别有自己的版本，不用一个应用版本代替全部版本。

### 26.3 代码与模型发布分离

代码发布、模型发布、路由发布和价格发布是四类独立变更：

- 代码发布：服务与前端版本；
- 模型发布：ModelVersion 状态和目标硬件；
- 路由发布：Policy 选择模型、阈值与升级规则；
- 价格发布：PriceVersion 和生效时间。

任何一类都必须能独立回滚。禁止通过重新部署代码暗中改变客户模型档位或历史价格。

### 26.4 开源边界

拟开源层采用 Apache-2.0：

- 最小 Graph+Loop Runtime、Graph Contract 和 Checkpoint 语义；
- Capability SDK、示例 Graph 和本地单租户智能工作台；
- 通用数据契约和 SDK；
- Storage、Queue、AnnotationProvider、ModelRunner 等适配器接口；
- 本地单租户社区版基础闭环；
- 部分通用预处理和模型集成；
- 示例数据和开发文档。

商业闭源层：

- 多租户与客户管理；
- 用量计费、价格和合同；
- 高级路由、企业级审核与争议处理；
- 企业级 Graph Studio、客户专属模板、策略包、评估运营和高级工具；
- 商业问卷、BI、运营和跨客户治理；
- 托管控制面和企业部署能力。

商标、Logo、商业模块接口和模型/数据许可证单独声明。正式发布前进行法律审查，确认 Apache-2.0 依赖不代表其模型权重也采用同一许可证。

## 27. 已确认决策登记

| 编号 | 决策 |
|---|---|
| D-00 | 系统核心是 Graph+Loop 智能业务操作系统；识别只是首个领域能力包 |
| D-01 | 第一阶段 100% 本机运行，成熟后演进为云智能控制面 + 本地能力执行面 |
| D-02 | 采用 Graph+Loop 内核 + 模块化能力单体 + 隔离 Worker |
| D-03 | PostgreSQL 是业务事实库；SQLite 不作为并行业务真相 |
| D-04 | 从第一版建立 tenant/customer/project 边界 |
| D-05 | 六类用户角色，并为 Agent/API 设置服务身份 |
| D-06 | 分享链接签名、过期、可撤销、任务限权、首次验证码 |
| D-07 | 保留上游 Label Studio，平台通过网关和适配层扩展 |
| D-08 | 照片结论为通过/警告/拒绝，拒绝只用于证据不可恢复 |
| D-09 | 证据链是未来考核和争议处理依据，原始证据不可覆盖 |
| D-10 | 客户提供低/中/高/极高四档，内部使用不可变用量账本 |
| D-11 | 第一发布先完成统一 Foundation Milestone 和两个最薄验证包，再逐个完整实施领域模块 |
| D-12 | 问卷与 BI 当前冻结 Capability/DataProduct 契约，后续作为可插拔领域包验证内核通用性 |
| D-13 | Python 3.12 + FastAPI；TypeScript + React PWA；统一 API |
| D-14 | VLM 生产最低建议 Apple Silicon 32GB 或 NVIDIA 16GB；CPU 不承诺吞吐 |
| D-15 | 准确性承诺只针对客户确认的冻结验收集 |
| D-16 | Graph/Agent 读取授权数据，可写系统运行状态和衍生物；不能直接写客户源数据，高风险写操作走待审批命令 |
| D-17 | 常规单审；金标准、发布和计费争议双盲 + 第三人仲裁 |
| D-18 | 本地 8TB、目标十万张/天；保留期半年、2 年、7 年 |
| D-19 | 开发期实现保留生命周期但不自动删除 |
| D-20 | 商品主档、包装版本、客户映射分离，支持客户不同命名策略 |
| D-21 | 开源层拟用 Apache-2.0，商业能力闭源，发布前法律复核 |
| D-22 | 基础客户使用固定 Graph，高级客户购买可定制 Graph、持续 Loop、专属工具和预算 |
| D-23 | Geo Foundation + Field Operations 是同一系统的第二个已确认 Domain Pack，在统一底座上按自有 L0–L6 计划实施 |
| D-24 | 定位只在员工主动工作会话中开启；原始精确轨迹默认 90–180 天，派生证据按客户策略保留 |
| D-25 | 每次外勤任务门头照必选，新门头/位置变化与员工异常分开处理 |
| D-26 | 自拍证据接口和风险触发保留，首版不自动进行人脸身份比对 |
| D-27 | 派单默认人工确认；低风险自动化可由客户策略开启，高风险/跨区仍需人工 |
| D-28 | 路线按 SLA、安全可达、技能、效率、均衡顺序优化；无解时返回“当前运力不可达” |
| D-29 | EDS 类无清单普查使用地图区块，Agent 推荐、管理人员协调，覆盖未达标进入补扫 Loop |
| D-30 | 位置、轨迹、任务和照片租户隔离；公共 Place 与客户私有 Overlay 分层 |
| D-31 | 整个产品只有一套系统；本文是唯一总架构事实源，领域规格全部从属 |
| D-32 | Domain Pack 可独立开发、测试、发布、启停和维护，但不得复制身份、数据、事件、证据、账本、审计、Web 和 Agent 底座 |
| D-33 | 先建 Foundation Milestone：Module SDK + 统一数据底座 + Graph+Loop + Web 壳 + 运维，通过后再完整开发业务模块 |
| D-34 | 统一数据底座是统一治理与 schema 所有权，不是一张通用大表；跨域只用 API、命令、事件、DataProduct 和 ResourceRef |
| D-35 | 首版模块是受审查代码包 + 启动注册 + 租户 feature flag，不支持任意代码热插件 |

以上是基线。后续改变任何一项必须记录新的 Architecture Decision Record，并列出影响模块、迁移方案和兼容窗口。

## 28. 用户原始 15 项要求覆盖矩阵

### 28.1 原始 15 项要求

| 原始要求 | 设计响应 | 主要实施阶段 |
|---|---|---|
| 1. 统一 Web 管理界面 | 第 7 章智能工作台、Run/Graph/能力中心及直接模块入口 | Stage 1-5 |
| 2. Label Studio 全功能 + 多模态外挂 + 扩展 | 第 13 章独立上游、Provider、外挂数据库 | Stage 3 |
| 3. 标注/识别人工审核、链接分配、错漏标 | 第 8、13 章分享链接、盲审、仲裁、错误分类 | Stage 3 |
| 4. 现有模型辅助、自动画框 | 第 13.4 节预标注流水线 | Stage 3-4 |
| 5. 斜拍、反光、翻拍、大头照过滤 | 第 10-11 章任务相关质量与证据链 | Stage 2 |
| 6. 货架等场景、价签有无 | 第 12 章多标签与不可判断 | Stage 2 |
| 7. 标注输入输出统一、未来分客户 | 第 8-9、13 章租户和统一文档契约 | Stage 0-3 |
| 8. 照片和 URL 两种输入 | 第 10 章统一 Asset 接入和 URL 安全 | Stage 2 |
| 9. 7B 内本地 VLM 微调 | 第 15、17 章模型角色、LoRA 与治理 | Stage 5-6 |
| 10. SAM 与更优 FMCG 多模型方案 | 第 14-16 章路由、SAM、检索、包装版本 | Stage 4-6 |
| 11. API、Web、内部 Agent 三种识别 | 三种入口启动同一 GraphVersion 或能力，见第 7、19、21 章 | Stage 2、4 |
| 12. 每次识别任务计费 | 第 18 章从 Run/Node 到领域 attempt 的不可变用量 | Stage 1 起、Stage 7 商品化 |
| 13. 智能系统底座、问卷、数据库、BI、管理/客户端 | 第 4-8、19、24 章智能内核和领域能力包 | Stage 1、8 |
| 14. 完全模块化，降低升级成本 | 第 6、19、21 章内核、能力、领域命令和事件边界 | Stage 0 起持续 |
| 15. 可变 Graph+Loop Agent | 第 19 章系统核心；第 24 章 Stage 0-1 即建设，Stage 7 商业定制 | Stage 0-1、7 |

覆盖不等于已经实现。每个条目只有在对应 Stage 的退出门禁、自动化测试和验收报告全部通过后，才能标记为完成。

### 28.2 新增位置与外勤模块覆盖

| 新增要求 | 设计响应 | 主要实施阶段 |
|---|---|---|
| 地址管理、地图适配、多入口和客户私有名称 | Place/LocationVersion/AccessPoint + CustomerLocationOverlay | Stage 8 / L1 |
| 工作时位置、电子围栏和弱网 | FieldSession + PositionBatch + GeoEvent + 离线幂等补传 | Stage 8 / L2 |
| 基于员工位置荐任务、路线和动态重排 | TaskCandidate/AssignmentProposal/RoutePlanVersion + 冻结窗口 | Stage 8 / L3、L6 |
| 每任务门头照、多轮匹配、可选自拍 | EvidenceArtifact + StorefrontValidationRun + Human Review | Stage 8 / L2、L4 |
| EDS 类无门店清单普查 | TerritoryCampaign + H3/业务区块 + 覆盖验收 + 补扫 Loop | Stage 8 / L5 |
| 初期模块成本、后期 token | UsageEvent 明细 + 版本化 RateCard | Stage 8 / L0–L6 |

## 29. 外部技术依据

以下是设计阶段采用的官方或项目一手资料，实际实施时必须锁定具体版本并再次验证：

- Label Studio 开源项目与许可证：https://github.com/HumanSignal/label-studio
- Label Studio ML Backend 集成：https://labelstud.io/guide/ml.html
- Label Studio 自定义 ML Backend：https://labelstud.io/guide/ml_create
- Label Studio Webhook 行为：https://labelstud.io/guide/webhooks.html
- Label Studio Prediction 机制：https://labelstud.io/guide/predictions.html
- Label Studio 企业功能差异：https://labelstud.io/guide/enterprise_features
- Qwen3-VL 官方仓库：https://github.com/QwenLM/Qwen3-VL
- Qwen3-VL 2B 模型卡：https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct
- Gemma 官方文档：https://ai.google.dev/gemma/docs/get_started
- SAM 2 官方仓库：https://github.com/facebookresearch/sam2
- SAM 3 官方仓库：https://github.com/facebookresearch/sam3
- DINOv3 官方仓库：https://github.com/facebookresearch/dinov3
- SigLIP 2 官方说明：https://github.com/google-research/big_vision/blob/main/big_vision/configs/proj/image_text/README_siglip2.md
- Florence-2 官方模型卡：https://huggingface.co/microsoft/Florence-2-large
- 高德 Web Service 路径规划：https://lbs.amap.com/api/webservice/guide/api/direction
- Google OR-Tools Routing：https://developers.google.com/optimization/routing
- H3 网格库概述：https://h3geo.org/docs/library/index/cell/
- PostGIS 官方手册：https://postgis.net/stuff/postgis-3.6.1-en.pdf
- Apple 后台位置更新：https://developer.apple.com/documentation/corelocation/handling-location-updates-in-the-background
- Android 后台位置限制：https://developer.android.com/about/versions/oreo/background-location-limits?hl=en
- 《中华人民共和国个人信息保护法》官方全文：https://www.samr.gov.cn/wljys/gzzd/art/2023/art_3ef1e889c1e644d4b65b5f5c7f432386.html
- 人脸识别技术应用安全管理办法：https://www.cac.gov.cn/2025-03/21/c_1744174262342111.htm

## 30. 对实施 Agent 的约束

在本文被产品负责人确认之前，任何 Agent 都不得根据本文开始大规模实现。确认后仍需先为每个 Stage 编写独立实施计划，精确到文件、数据库迁移、测试、命令、验收和回滚。

实施 Agent 必须遵守：

1. 先读取本设计、位置与外勤专项规格、当前仓库状态、现有手册和 training-history-and-decisions。
2. 不覆盖其他 Agent 或用户的未提交改动。
3. 先写契约和测试，再迁移现有功能。
4. 每次只跨越一个 Stage 的最小可验收切片。
5. 不以 UI 展示代替数据一致性、权限、证据和计费正确性。
6. 不以模型“能运行”代替准确性、吞吐、内存和成本达标。
7. 任何训练先通过 Apple/NVIDIA 资源门禁和数据门禁。
8. 任何发布都能回滚，并能追溯到 commit、数据、模型和路由版本。
9. 任何自动删除、生产部署、云端上传或客户数据迁移都需单独授权。
10. 每个阶段结束提交证据包：测试报告、性能报告、架构差异、风险、剩余问题和下一阶段准入判断。
11. 位置与外勤在统一底座上按专项 L0–L6 计划实施；不得把员工 App、轨迹、地图、路线和普查功能偷塞进 Foundation Milestone。
12. 不以单个 GPS、围栏、门头模型或自拍信号直接形成员工处罚、工资或身份结论。
13. 任何新 Domain Pack 必须先通过 Manifest 和契约测试接入；不得因新模块而修改 Kernel 的领域特例或新建第二数据真相。
14. Stage 0–1 实施计划必须先达到 Foundation Milestone 退出门，未达标前不得宣布“大架构已搭好”或启动后续完整模块实施。

## 31. 下一步

当前下一步是由产品负责人复核本次“唯一总纲 + 从属 Domain Pack”修订。通过后：

1. 使用 writing-plans 重写现有 Stage 0–1 详细计划，将交付目标升级为完整 Foundation Milestone；
2. 计划严格映射现有仓库，采用 Adapter 保留现有识别/训练入口，不做一次性重写；
3. Foundation 计划经用户单独批准后，实施 Agent 才可修改底座代码；
4. Foundation 实施和退出门验收完成后，再为各 Domain Pack 编写并审批独立的积木式实施计划。

在 Stage 0-1 计划获批前，训练 Agent 可继续执行已经单独批准的训练工作，但不得提前创建新的系统事实库、Graph Runtime、全局身份或替换现有生产入口。
