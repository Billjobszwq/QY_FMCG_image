# 统一 Graph+Loop 系统之位置与外勤 Domain Pack 详细规格

> 文档日期：2026-08-04
>
> 文档状态：业务设计已确认，已纳入统一系统总纲
>
> 文档性质：从属 Domain Pack 详细规格；不定义独立系统、独立平台底座或第二数据事实源
>
> 当前约束：100% 本机优先；只形成设计和实施依据，不修改项目实现代码
>
> 唯一上位总纲：`docs/superpowers/specs/2026-08-04-fmcg-vision-saas-platform-design.md`

## 1. 执行摘要

本文定义的不是第二套系统。位置与外勤是统一 Graph+Loop 智能业务操作系统内的一个可插拔 Domain Pack，必须在总纲定义的统一身份、数据、证据、事件、任务、审计、计费、Web 壳和 Graph Runtime 之上运行。它可以独立维护和启停，但不得自建平行底座。

该 Domain Pack 不是在任务页面上增加一张地图，而是继 FMCG 识别之后的第二个重要业务能力包。它由两个边界清晰的部分组成：

1. **Geo Foundation**：通用位置主数据、地址版本、地图适配、工作时轨迹、电子围栏、空间事件、路线矩阵和规划引擎接口。
2. **Field Operations Domain Pack**：外勤工作会话、普查活动、候选任务、正式任务、派单、地图区块、路线计划、现场执行、门头证据、动态重排和异常闭环。

Graph+Loop 仍是整个系统的智能运行核心。Agent 可以基于授权数据生成候选任务、路线建议、普查区块分配和重排方案，但不能直接写正式任务、门店、位置版本或员工处分结论。正式事实必须经过领域服务、权限、策略和必要的人工确认。

已确认的首版业务边界：

- 仅在员工主动开始的工作会话中定位，默认 2–5 分钟自适应采样，并结合显著位移和围栏事件；非工作时间禁止定位。
- 默认由管理人员确认派单；客户可对低风险任务启用自动派单，高风险和跨区调整必须人工确认。
- 首版支持步行、电动车和汽车；公共交通通过未来适配器接入。
- 电子围栏生成到店、离店、偏航、越界和异常停留证据，但不直接决定工资、处罚或最终绩效。
- 系统内提供多门店路线、下一站、剩余任务和偏航提醒；逐路口导航交给高德等第三方地图。
- 精确原始轨迹短期保存 90–180 天；围栏事件、任务证据和汇总数据按客户半年、2 年或 7 年策略保存。
- 不要求保存员工家庭地址；路线从员工开始工作时的位置或客户集合点出发。
- 优化优先级为：业务优先级与时限 → 安全可达性 → 技能与权限 → 路线效率 → 负载均衡。
- 动态重排设置冻结窗口，执行中和临近任务不能被随意迁移。
- 中国大陆首版默认高德地图，但所有能力通过可替换 Map Provider Adapter。
- 弱网时 App 加密缓存位置与任务事件，恢复后幂等补传并标明离线来源。
- 防作弊使用 GPS 精度、速度突变、时间连续性、设备可信状态、路线一致性和现场证据组合判断；异常只进入人工复核。
- 每次任务必须提交门头照。门头深度验证采用质量、区域检测、OCR、Logo、历史向量和地理一致性的多轮机制。
- 自拍作为可选高敏证据类型保留；风险规则可触发补拍和示警，首版不自动进行人脸身份比对。
- 支持没有门店清单的 EDS 类普查任务，由 Agent 在管理人员协调下按员工位置和运力推荐地图区块。
- 公共位置主索引与客户私有覆盖层分离，客户的任务、轨迹、照片和业务观察默认互不可见。
- 初期按模块真实成本形成总报价；底层从第一天记录明细用量，后期通过版本化费率折算平台 token。
- 单客户目标为 1,000 名活跃外勤、10 万地点、每天 5 万任务，并预留分区和横向扩展基础。
- 管理端使用 Web；员工端使用 iOS/Android 跨平台原生 App，小程序只作为轻量补充。

## 2. 设计目标与非目标

### 2.1 设计目标

- 建立可复用的位置主数据和空间能力，不把 EDS、FMCG 或某个地图供应商写入通用地理底座。
- 同时支持已有明确地点的 PointTask 和没有完整门店清单的 TerritoryCampaign。
- 基于员工工作时位置、交通方式、技能、班次和运力推荐任务与路线。
- 让任务从推荐、审批、执行、证据、异常、重排到结案形成可恢复的 Graph+Loop。
- 通过门头照片、位置事件和人工决定形成可用于争议处理的完整证据链。
- 在保护员工隐私的前提下支持工作时定位、离线补传、围栏与风险示警。
- 让地址、围栏、路线矩阵、任务、派单和证据全部版本化，历史运行可以重放。
- 首版本机低成本运行，未来可以拆分位置接入、围栏、路线矩阵和规划 Worker，而不改变领域契约。

### 2.2 明确非目标

- 首版不自建地图、道路网络、地理编码或逐路口语音导航。
- 首版不建设完整离线地图和离线路线重算，只支持离线事件缓存与恢复。
- 首版不自动做人脸身份比对，也不把自拍设为所有客户的强制项。
- 位置、照片或模型风险不能直接生成工资扣减、处罚、作弊或解雇结论。
- 不以直线距离冒充真实道路距离，不在地图服务失败时生成虚假路线。
- 不承诺对大规模车辆路径问题求得数学上的全局最优，只承诺在限定时间内返回可验证的可行方案或明确失败。
- 不允许 Agent 绕过领域服务直接创建正式任务、修改门店坐标、派单或结束普查活动。
- 不采集非工作时间位置，不把员工家庭地址设为默认必需数据。

## 3. 总体架构

~~~mermaid
flowchart TB
    subgraph SHARED["统一系统底座（本 Domain Pack 只复用）"]
        SHELL["Web 壳 / API Gateway / Agent 入口"]
        KERNEL["Graph+Loop Kernel / Policy / Human Gate"]
        IAM["Identity / Tenant / Project"]
        DATA[("PostgreSQL Unified Fact Store")]
        EVENT["Outbox / Inbox / Job / Worker Control"]
        CAS[("CAS / Evidence Storage")]
        LEDGER["Usage / Billing / Audit"]
        SHELL --> KERNEL
    end

    subgraph PACK["Geo + Field Operations Domain Pack"]
        MANIFEST["ModuleManifest / Capability / API / UI Slots"]
        GF["Geo Foundation"]
        FO["Field Operations"]
        ING["Position / Evidence Ingest"]
        FENCE["Geofence Engine"]
        MATRIX["Route Matrix Cache"]
        PLAN["Planning Workers"]
        EVID["Evidence Validation Workers"]
        GF --> FENCE
        GF --> MATRIX
        FO --> PLAN
        FO --> EVID
    end

    APP["员工 App"] --> SHELL
    KERNEL --> MANIFEST
    MANIFEST --> GF
    MANIFEST --> FO
    APP --> ING
    GF --> MAP["Map Provider Adapter"]
    PLAN --> OPT["Constraint Optimizer"]
    EVID --> VIS["Storefront Vision Capability"]
    ING --> EVENT
    ING --> DATA
    GF --> DATA
    FO --> DATA
    EVID --> CAS
    MANIFEST --> LEDGER
    MANIFEST --> IAM
~~~

依赖规则：

1. Experience 只能调用统一 API 和 Capability，不能直接访问空间表或任务表。
2. Graph+Loop 只能通过 Geo/Field Operations 领域服务执行写命令。
3. Geo Foundation 不依赖 Field Operations；Field Operations 可以引用 Geo Foundation 的版本化位置对象。
4. 地图、规划和视觉都是可替换能力提供者，不拥有业务任务状态。
5. 统一 PostgreSQL 中的 `geo`/`field` schema 保存本模块结构化事实；照片原件进入平台 CAS，本模块只保存哈希和 ResourceRef。
6. 本模块复用平台 Outbox/Inbox、Job/Attempt、UsageLedger、Audit 和 Checkpoint，禁止再建一套队列真相、账本或审计表。
7. Redis 只可加速缓存和队列；统一数据底座中的 Outbox、幂等键、Job 和 Checkpoint 才是恢复事实。

### 3.1 本 Domain Pack 复用与自有的边界

| 必须复用统一底座 | 本 Domain Pack 自有 |
|---|---|
| Identity/Tenant/Project、Policy、HumanTask | Location、Geofence、Campaign、Task、Assignment、RoutePlan 领域规则 |
| ModuleManifest、Capability Registry、Graph Runtime | Geo/Field Capability、DomainCommand、Graph 模板和事件 schema |
| PostgreSQL 连接、Unit of Work、Migration Orchestrator | `geo`/`field` schema 及模块迁移 |
| CAS、Evidence、Retention、Export | 门头/自拍证据要求、地理一致性和验证策略 |
| Outbox/Inbox、Job/Attempt、Worker Control | Position、Geofence、Planning、Coverage、Evidence Worker 声明 |
| UsageLedger、RateCard、Audit、Observability | 地图、定位、规划、任务、普查和证据 meter |
| Web 壳、全局上下文、Run/证据抽屉 | 位置、调度、普查、现场证据页面插槽和员工 App 业务界面 |

只有右列能在本模块中实现。左列如果尚未由 Foundation Milestone 提供，本模块应标记 blocked，不得为赶进度在 `geo_field` 内建临时永久替代品。

## 4. 模块职责

| 模块 | 核心职责 | 禁止行为 |
|---|---|---|
| Location Master | Place、LocationVersion、地址候选、坐标、出入口、楼层、来源和有效期 | 原地覆盖历史坐标或地址 |
| Customer Location Overlay | 客户私有名称、关系、属性、可见性和业务映射 | 把客户私有观察写入公共地点事实 |
| Map Provider Adapter | 地理编码、POI、路线、距离矩阵和导航跳转 | 在领域层暴露供应商专属字段 |
| Position Ingest | 工作会话位置批次、离线补传、去重、乱序和完整性校验 | 接受已结束工作会话的新位置 |
| Geofence Engine | 到店、离店、停留、越界、偏航和空间置信度 | 用单个漂移点直接判定违规 |
| Campaign | Point、Territory 和 Sample 活动策略、范围、门槛与状态 | 在活动进行中静默修改验收规则 |
| Task & Assignment | 候选任务、正式任务、推荐、确认、退回和冻结窗口 | Agent 直接写正式派单 |
| Route Planning | 可行性过滤、矩阵、优化、方案比较、路线版本和未分配原因 | 用无上限全局求解阻塞业务 |
| Field Execution | 工作会话、到店、执行、证据、异常和结案 | 在证据未同步时伪装最终完成 |
| Evidence Validation | 门头质量、OCR、Logo、历史向量、地理一致性和人工复核 | 用模型分数自动处罚员工 |
| Coverage Evaluation | 网格、道路、POI 核查、新发现和普查补扫 | 只以地图供应商 POI 作为真实世界全集 |
| Agent Coordination | 解释方案、协调区块、提出重排和补扫建议 | 伪造距离、扩大权限或绕过人工门 |

## 5. 核心领域对象

### 5.1 公共位置与客户覆盖层

| 对象 | 身份与版本语义 | 关键字段 |
|---|---|---|
| Place | 稳定公共地点身份 | place_id、place_type、public_status |
| PlaceCandidate | 尚未进入主索引的候选 | source、evidence_refs、duplicate_candidates、review_status |
| LocationVersion | Place 的地址/坐标版本 | normalized_address、geometry、coordinate_system、valid_from/to、source、confidence |
| AccessPoint | 门店或建筑出入口 | location_version_id、point、access_type、instructions |
| GeofenceVersion | 版本化点/圆/多边形围栏 | geometry、entry_rule、exit_rule、dwell_rule、accuracy_policy |
| CustomerLocationOverlay | 客户私有地点覆盖 | tenant/customer/project、place_id、private_name、attributes、visibility |
| ProviderReference | 地图供应商引用 | provider、provider_place_id、provider_payload_hash、observed_at |

地点身份与版本必须分离。任务、路线、围栏事件和历史报告引用当时的 LocationVersion/GeofenceVersion，不允许查询“当前坐标”后改变历史含义。

公共位置主索引只保存公开可验证的基础事实。客户的拜访、经营信息、照片、问卷、审核和私有名称映射位于客户覆盖层，不因公共 Place 相同而跨租户共享。

### 5.2 员工、工作会话与位置

| 对象 | 作用 | 关键字段 |
|---|---|---|
| WorkerProfile | 工作能力，不含默认家庭地址 | worker_id、skills、permissions、mobility_profile_id、active |
| MobilityProfile | 交通和运力 | mode、measured_range、safety_margin、capacity、return_requirement |
| FieldSession | 员工主动开始的工作会话 | session_id、worker、device、consent_version、start/end、start_point、status |
| PositionSample | 短期精确轨迹 | event_time、received_time、point、accuracy、speed、heading、source、sequence |
| OfflineBatch | 离线补传批次 | device、session、sequence_range、payload_hash、signature、received_at |
| GeoEvent | 长期派生空间事件 | type、location/geofence_version、confidence、evidence、rule_version |
| DeviceTrustObservation | 设备可信信号 | attestation_status、mock_signal、clock_skew、observed_at |

FieldSession 状态：off_duty → active → suspended/offline_active → active → ended。只有 active/offline_active 可以产生合法位置样本；ended 后的新数据必须拒绝并记录原因。

### 5.3 活动、任务和路线

| 对象 | 作用 | 关键字段 |
|---|---|---|
| Campaign | 活动顶层定义 | type、boundary_version、objective、completion_policy、time_window、status |
| TerritoryBlockVersion | 普查区块版本 | geometry、H3 cells、road_segments、known_pois、coverage_targets |
| TaskCandidate | 多来源候选任务 | producer、reason、dedupe_key、priority、risk、suggested_location |
| Task | 正式任务事实 | task_type、location/block version、SLA、service_duration、skills、evidence_policy |
| AssignmentProposal | 推荐方案 | worker、task、score_breakdown、constraints、route_delta、expires_at |
| Assignment | 已确认派单 | task、worker、decision_source、policy_version、accepted_at、status |
| RoutePlanCandidate | 尚未发布的候选路线 | stops、matrix_version、score_breakdown、unassigned_reasons、expires_at |
| RoutePlanVersion | 不可变路线方案 | worker/session、stops、matrix_version、objective、cost、feasibility、created_by |
| RouteStop | 路线中的停靠点 | task、sequence、ETA window、service_duration、freeze_status |
| TaskExecution | 任务实际执行 | assignment、arrival/departure、actions、result、sync_status |
| Visit | 地点拜访事实 | location_version、geofence_events、dwell、evidence_refs |

TaskCandidate 可以来自管理人员、客户 API、问卷、识别异常、BI 规则和 Graph+Loop 分析。只有领域服务经过权限、去重、策略和必要的人工决定后，才能生成正式 Task。

### 5.4 证据、决策与用量

| 对象 | 作用 |
|---|---|
| EvidenceArtifact | 门头照、自拍、扫码、文档等原始证据及内容哈希 |
| EvidenceRequirement | 客户/任务类型对证据的版本化要求 |
| StorefrontValidationRun | 多轮门头验证运行、模型/规则版本、分项结论和置信度 |
| EvidenceReviewTask | 补拍、低置信度、冲突或抽检形成的人工任务 |
| DecisionEvent | 推荐、人工确认、拒绝、重排和例外决定 |
| UsageEvent | 定位、地图、规划、任务、视觉、人工、Agent 和存储明细 |
| AuditEvent | 谁在何时查看/修改/决定了什么以及原因 |

其中 EvidenceArtifact、DecisionEvent、UsageEvent、AuditEvent 和用于复核的 HumanTask 都是统一底座对象。本 Domain Pack 通过 ResourceRef、module_id、meter 和决策类型填充领域语义，不另建同名事实表。

原始证据不可覆盖。重新拍摄创建新 EvidenceArtifact，并通过 supersedes 关系连接旧证据；旧证据继续保留。

## 6. 地址管理与地理编码

### 6.1 地址输入

地址可以来自：

- 客户主数据/API；
- 手工创建或 Excel/CSV 导入；
- 地图 POI 搜索；
- 普查现场发现；
- 识别、问卷或其他 Graph 生成的候选；
- 已有门店的地址变更申请。

所有输入先成为候选，不直接覆盖正式 LocationVersion。

### 6.2 地理编码策略

统一 Map Provider Contract 至少提供：

- geocode_address；
- search_poi；
- reverse_geocode；
- route_matrix；
- route_detail；
- navigation_deeplink；
- provider_health/cost。

中国大陆首版默认高德。地址地理编码失败时可以使用城市/区域限制的 POI 搜索回退，但必须保留原始地址、候选列表、供应商、分数和人工选择。不能只保留最终坐标。

### 6.3 坐标系统

每个几何对象显式保存 coordinate_system。供应商适配器负责坐标转换，领域服务只接收声明清楚的标准对象。WGS84、GCJ-02、BD-09 等坐标混用必须在契约测试中失败，禁止靠“看起来差不多”通过。

### 6.4 多入口和商场内地点

一个 Place 可以存在多个 AccessPoint，并允许记录商场、楼层、柜台、园区门、卸货口等访问说明。路线规划指向访问点，不一定指向建筑几何中心；围栏可以覆盖商场范围，同时用照片、停留和业务证据确认具体门店。

## 7. 工作时定位与离线补传

### 7.1 采集策略

- 员工在前台主动开始 FieldSession 后才请求定位权限。
- 默认 2–5 分钟自适应采样，结合 distance filter、显著位置变化和围栏监控。
- 运动中可适当提高频率，静止时降低频率；不能承诺秒级连续轨迹。
- App 持续显示工作定位状态，结束工作后立即停止位置服务。
- 员工可以查看自己的工作会话和定位摘要。

Apple 建议只在确有必要时使用后台定位并明确告知；系统还可能暂停 App 或批量交付事件。Android 对后台位置频率也存在限制。因此服务器必须接受延迟、批量和缺失，不能假定每个点实时到达：

- https://developer.apple.com/documentation/corelocation/handling-location-updates-in-the-background
- https://developer.android.com/about/versions/oreo/background-location-limits?hl=en

### 7.2 离线协议

设备为每个 FieldSession 生成单调 sequence。OfflineBatch 包含 sequence 范围、事件哈希、设备时间、服务端最近确认序列和签名。服务端处理：

1. 验证 session、设备、租户和授权；
2. 按 event_id/sequence 幂等去重；
3. 保留 event_time 和 received_time；
4. 标记 clock_skew、out_of_order 和 offline_replayed；
5. 写入原始位置后异步计算 GeoEvent；
6. 返回连续确认点和缺失序列；
7. 不因补传而改写已经冻结的历史决定，必要时创建更正事件。

### 7.3 保留策略

- PositionSample 默认 90–180 天，客户只能在合规审核后缩短或延长。
- GeoEvent、TaskExecution、EvidenceArtifact、DecisionEvent 按客户半年、2 年或 7 年策略。
- 争议、诉讼或调查触发 legal hold 时停止到期动作。
- 到期只标记 eligible_for_retention_action；真实删除沿用总体规格的审批与可恢复规则。

## 8. 电子围栏

### 8.1 围栏类型

- 门店到店/离店围栏；
- Campaign/任务责任区；
- 禁入区域；
- 路线走廊和偏航区域；
- 集合点、仓库或服务中心；
- 临时事件围栏。

### 8.2 判断语义

单点落入多边形不能直接等于到店。判断至少考虑：

- 坐标精度半径；
- 连续点或最短停留；
- 进入与离开的迟滞范围；
- AccessPoint 与建筑中心差异；
- 设备时间连续性；
- 工作会话与任务上下文；
- 门头和现场业务证据。

GeoEvent 输出 confidence 和 reason_codes。GPS 弱或边缘漂移时输出 uncertain，需要额外证据或人工复核，而不是自动失败。

### 8.3 业务边界

围栏用于任务到离店、偏航、异常停留和越界告警。它不是工资、处罚、考勤或作弊的唯一事实。任何对员工有重大影响的结论必须经过明确规则、完整证据和人工程序。

## 9. 路径规划

### 9.1 交通方式

首版支持 walking、electric_bike 和 car。公共交通作为未来 provider capability。电动车续航使用员工/车辆实测值，不使用宣传续航；可用里程必须扣除返程和安全余量。

### 9.2 优化顺序

冲突时按以下顺序：

1. 任务 SLA、时间窗和业务优先级；
2. 员工、交通方式、续航、返程和安全可达性；
3. 技能、权限和客户要求；
4. 总道路时间、距离和成本；
5. 员工工作量和最长路线均衡。

无安全可行解时输出“当前运力不可达”及具体约束，不通过降低安全余量或伪造距离填满任务。

### 9.3 算法分层

1. Hard Feasibility Filter：移除班次、权限、技能、时间窗、交通方式、续航、容量和冻结规则不满足的组合。
2. Spatial/Cost Layer：PostGIS 精确空间判断、H3 分区、地图供应商道路时间/距离矩阵。
3. Constraint Optimizer：车辆路径时间窗、容量、服务时长、任务优先级、未分配惩罚、均衡目标和求解时间上限。
4. Agent/Human Layer：解释方案、比较取舍、协调例外和请求决策。

OR-Tools 支持带时间窗、容量和资源约束的车辆路径问题，但大规模问题计算复杂度会快速增长，因此必须设置求解时间或解数量上限：

- https://developers.google.com/optimization/routing
- https://developers.google.com/optimization/routing/vrptw
- https://developers.google.com/optimization/routing/cvrp

### 9.4 路线矩阵版本

MatrixCacheKey 至少包含：provider、provider contract version、mobility mode、origin/destination LocationVersion、AccessPoint、departure time bucket、strategy 和 coordinate system。

保存请求哈希、响应哈希、observed_at、expires_at、成本和 provider status。同一地点随道路、路况和供应商算法变化可能返回不同结果，因此 RoutePlanVersion 必须引用当时 MatrixVersion：

- https://lbs.amap.com/api/webservice/guide/api/direction

### 9.5 动态重排

触发条件包括延误、偏航、临时任务、任务取消、人员退出、车辆/电量异常和地图不可达。

重排步骤：

1. 冻结执行中、已到店和进入临近时间窗的任务；
2. 只对剩余可变任务重新做可行性和优化；
3. 比较旧/新方案的 SLA、成本、里程、影响人员和未分配任务；
4. 低风险变化按客户策略自动发布；
5. 跨区、高价值、大面积改变或影响多人时请求管理人员确认；
6. 生成新的 RoutePlanVersion，旧版本不覆盖。

## 10. EDS 类无清单普查

### 10.1 活动模型

TerritoryCampaign 只有范围、目标、时间和完成策略，不要求预先拥有完整门店清单。支持：

- census：全面普查；
- sample：抽样；
- verify：已有 POI 核查；
- discover：重点发现新地点；
- revisit：历史地点复访。

### 10.2 地图区块

PostGIS 保存法定/业务边界精确几何；H3 保存多分辨率单元，用于切片、覆盖统计和并行调度。H3 具有分层网格索引，适合父子区域聚合，但区块最终边界仍以版本化业务几何为准：

- https://h3geo.org/docs/library/index/cell/
- https://h3geo.org/docs/api/hierarchy/

区块生成同时考虑：道路可达性、自然边界、已知 POI 密度、员工交通方式、预计服务量和相邻区共享。不得只按面积平均切块。

### 10.3 区块派发

Agent 基于员工当前工作位置、剩余工时、交通方式、实测续航、技能、历史覆盖率和当前负载生成 AssignmentProposal。管理人员可以调整边界、合并/拆分区块并确认派发。所有调整记录旧/新区块版本和原因。

### 10.4 现场发现

员工在区块中发现新门店时创建 PlaceCandidate，并提交位置、门头照、店名/OCR、业态和必要问卷。系统执行：

1. 与公共 Place、客户 Overlay、供应商 POI 和本活动候选查重；
2. 计算空间、名称、Logo 和历史照片相似度；
3. 高置信重复关联已有 Place；
4. 新地点或冲突进入 Location Steward 审核；
5. 审核通过后生成 Place/LocationVersion；
6. 不允许 Agent 或员工 App 直接污染公共主索引。

### 10.5 完成门

全面普查同时检查：

- H3/业务网格覆盖率；
- 道路或可访问片段覆盖率；
- 已知 POI 核查率；
- 新发现地点证据完整率；
- 空间分布和空白区解释；
- 抽检/人工审核通过率。

抽样活动按样本量、业态、品牌、空间分布和置信区间策略验收。任何指标未达门槛时，Loop 生成补扫建议，而不是静默把活动设为完成。

## 11. 门头照片多轮验证

### 11.1 采集要求

- 每次任务必须提交门头照片。
- 默认优先使用 App 相机实时采集；若允许相册，必须记录 source=gallery 并提高风险等级，但不能仅凭来源自动判造假。
- App 在现场先做轻量质量提示，严重模糊、遮挡或非门头时要求重拍。
- 弱网时原图加密保存，任务状态只能是 completed_pending_sync；服务端收到并验证后才能最终 completed。
- 原图、重拍图和处理结果都保留独立内容哈希。

### 11.2 验证流水线

1. Evidence Integrity：文件可读、哈希、时间、设备、FieldSession、任务和重复证据检查。
2. Quality：模糊、反光、遮挡、翻拍风险、取景范围和门头可见性。
3. Storefront/Sign Detection：门头、店招和出入口区域定位。
4. OCR：店名、地址、楼层或分店标识。
5. Brand/Logo：连锁品牌或渠道标志。
6. Visual Retrieval：与当前和历史门头参考图做向量检索。
7. Geo Consistency：与 LocationVersion、AccessPoint、GeofenceVersion 和任务上下文交叉验证。
8. Fusion：输出 accepted、retake_required、location_change_candidate 或 review_required。
9. Human Review：低置信、硬冲突、新门头和抽检进入人工复核。

不得把单个 OCR、Logo、向量或 GPS 结果设为最终唯一依据。新装修、改名、商场多入口和门头遮挡必须与员工不当行为区分。

### 11.3 自拍预留

`employee_selfie` 是独立 EvidenceType。客户策略或风险规则可以请求补拍并示警；首版不执行自动人脸身份比对。

未来启用人脸能力必须：

- 独立 Capability 和 feature flag；
- 证明特定目的、充分必要性和最小影响；
- 单独告知和同意；
- 提供非人脸替代验证方式；
- 独立加密、访问控制和最短保留；
- 事前个人信息保护影响评估；
- 评估是否触发备案等监管要求。

现行官方规则参考：

- https://www.cac.gov.cn/2025-03/21/c_1744174262342111.htm
- https://www.samr.gov.cn/wljys/gzzd/art/2023/art_3ef1e889c1e644d4b65b5f5c7f432386.html

本文是技术架构约束，不替代项目上线前的法律合规意见。

## 12. 风险信号、告警与人工复核

### 12.1 风险信号

- GPS accuracy 过低或长时间无定位；
- 不可能速度、瞬移或时间倒退；
- 设备 mock location/可信状态异常；
- 轨迹与交通方式明显冲突；
- 到店围栏与门头证据冲突；
- 同一照片跨任务复用；
- EXIF/采集来源和工作会话不一致；
- 门头与历史位置高度不匹配；
- 离线补传序列断裂或签名失败。

### 12.2 告警等级

| 等级 | 语义 | 默认动作 |
|---|---|---|
| L0 Info | 正常业务提示 | 提示下一任务、到店或同步状态 |
| L1 Warning | 可继续但需注意 | 偏航、精度下降、轻微延误 |
| L2 Action Required | 必须补充或复核 | 重拍、异常停留、位置/任务不一致 |
| L3 Critical Review | 高风险证据冲突 | 暂停结案、通知管理人员和审计员 |

告警保存 rule_version、输入证据、阈值和触发时间。L2/L3 可以阻止任务最终结案，但不能自动生成工资、处罚、作弊或解雇结论。

## 13. 三条核心 Graph

### 13.1 Point Task Planning & Execution

候选任务 → 权限/去重 → 硬约束可行性 → 路线矩阵 → 约束优化 → Agent 解释 → 自动/人工确认 → Assignment → App 接受 → 导航 → 围栏/到店 → 门头照/业务动作 → 证据验证 → 异常或结案 → Usage/Audit。

### 13.2 Territory Census

CampaignBoundaryVersion → 区块/道路/POI 基线 → 员工位置与运力 → Agent 推荐区块 → 管理确认 → 现场发现 PlaceCandidate → 查重/地点审核 → 覆盖评估 → 未达标补扫 Loop → 活动验收和冻结。

### 13.3 Dynamic Replanning

延误/偏航/临时任务/人员退出 → 冻结执行中和临近任务 → 重算剩余可变任务 → 比较新旧方案 → 低风险自动/高影响人工 → 新 RoutePlanVersion → 通知员工 → 追踪执行影响。

## 14. 管理 Web 与员工 App

### 14.1 管理端

| 中心 | 页面/能力 |
|---|---|
| 位置中心 | 地点地图/列表、候选查重、地址与坐标版本、出入口、围栏和公共/私有覆盖层 |
| 调度中心 | 工作中员工、候选/未分配/不可达任务、路线、推荐解释、冻结窗口和动态重排 |
| 普查活动中心 | 范围、H3/业务区块、道路/POI、覆盖热力图、区块派发、发现审核和补扫 |
| 现场证据中心 | 门头验证、重拍、门头变化候选、自拍请求、人工复核和冲突证据 |
| 成本与用量中心 | 地图、定位、规划、任务、区块、视觉、人工、Agent 和存储用量 |

调度中心采用左侧任务池、中间地图、右侧 Agent/方案抽屉和下方审计时间线。地图不是单纯展示，而是与候选任务、冻结状态、路线差异、成本和决策证据联动。

### 14.2 员工 App

- 主动开始/结束工作并显示定位状态；
- 今日路线、下一站、ETA、剩余任务和异常；
- 第三方导航跳转；
- 到店提示、任务表单、门头拍摄和补拍；
- 可选自拍证据请求；
- 任务接受、退回、异常上报和联系调度；
- 待同步事件和离线队列状态；
- 本人工作会话与定位摘要。

技术建议为 React Native/TypeScript 共享业务层，Swift/Kotlin 实现定位、相机、加密存储和设备可信适配器。不能使用普通 PWA 承担可靠后台定位。

## 15. 权限与隐私

### 15.1 角色

| 角色 | 主要权限 |
|---|---|
| Tenant Admin | 客户策略、角色、模块和保留期限 |
| Dispatcher | 工作中员工、派单、路线和重排确认 |
| Location Steward | 地点、地址、坐标、出入口和围栏审核 |
| Campaign Manager | 普查活动、区块和完成门 |
| Evidence Reviewer | 门头、自拍拍摄请求和证据复核 |
| Field Worker | 只查看和执行自己的工作任务 |
| Auditor | 只读审计；精确轨迹访问需原因 |
| Billing Admin | 用量、费率版本和账单 |
| Agent Principal | 授权读取、候选与建议，不能正式业务写入 |

### 15.2 高敏访问

- 管理人员默认只看工作中状态、任务相关位置和派生 GeoEvent，不看完整精确轨迹。
- 历史精确轨迹需要单独 scope、填写目的和审计。
- break-glass 是限时权限，必须自动通知和事后复核。
- 自拍原图、人脸相关数据和轨迹使用独立加密、访问范围和保留策略。
- 任何导出都写 DataExportAudit，并限制租户、项目、时间和用途。

### 15.3 员工透明度

- 开始工作时显示定位目的、采集范围和保留策略；
- App 持续显示定位是否运行；
- 结束工作后停止定位；
- 员工可以查看自己的会话、任务和定位摘要；
- 员工可以对异常/证据结论发起申诉或补充说明。

## 16. API、Capability 与事件

### 16.1 领域 API

建议统一在 `/api/v1` 下提供：

- `/locations`、`/location-candidates`、`/location-versions`、`/geofences`；
- `/field-sessions`、`/position-batches`、`/geo-events`；
- `/campaigns`、`/territory-blocks`、`/coverage`；
- `/task-candidates`、`/tasks`、`/assignments`；
- `/route-plans`、`/route-proposals`、`/replanning`；
- `/evidence`、`/storefront-validations`、`/evidence-reviews`；
- `/usage`、`/rate-cards`、`/alerts`。

Web、App、API 和 Agent 使用同一领域服务。所有命令支持 Idempotency-Key；批次使用 client_event_id、device sequence 和 batch hash。

### 16.2 Capability

| Capability | Effect | 说明 |
|---|---|---|
| geo.geocode | system_write | 只写候选与 provider evidence |
| geo.route_matrix | read_only/system_cache | 返回版本化道路成本 |
| geo.evaluate_geofence | system_write | 写 GeoEvent，不写处罚 |
| field.propose_assignment | system_write | 只写 Proposal |
| field.optimize_route | system_write | 写 RoutePlanCandidate |
| field.publish_assignment | domain_command | 正式派单，需策略/人工门 |
| field.evaluate_coverage | system_write | 写覆盖评估 |
| evidence.validate_storefront | system_write | 写验证结果和人审请求 |
| evidence.request_selfie | domain_command | 触发高敏证据请求，受策略约束 |

### 16.3 领域事件

- LocationCandidateCreated / LocationVersionConfirmed；
- FieldSessionStarted / Suspended / Ended；
- PositionBatchAccepted / Rejected；
- GeofenceEntered / Exited / DwellReached / DeviationDetected；
- TaskCandidateCreated / TaskFormalized；
- AssignmentProposed / Confirmed / Rejected / Accepted；
- RoutePlanPublished / ReplanRequested；
- EvidenceCaptured / StorefrontValidated / EvidenceReviewRequested；
- PlaceDiscovered / CoverageEvaluated / CampaignCompleted；
- UsageRecorded / AlertRaised / AppealSubmitted。

事件通过事务 Outbox 发布，消费者 Inbox 幂等；事件不得替代领域事实表。

## 17. 计费设计

### 17.1 初期

初期按模块成本核算总费用：位置主数据、工作时定位、电子围栏、路线规划、EDS 普查、门头验证、Agent 调度和存储可以组合报价。

### 17.2 明细账本

从第一天记录：

- active_location_employee_day；
- position_sample_ingested；
- geocode/poi/reverse_geocode/map_route_call；
- route_matrix_pair；
- route_optimization_compute_ms；
- dynamic_replan；
- formal_task / completed_task；
- territory_area / coverage_complexity；
- storefront_validation_stage；
- evidence_review_minutes；
- agent_input/output_tokens、tool_call；
- evidence_storage_byte_day、track_storage_byte_day。

### 17.3 后期 token

版本化 RateCard 将原始用量折算为平台 token。客户看到简化 token 产品，内部仍保留真实成本项。每个账单引用 RateCardVersion，费率变化不能回算历史 UsageEvent。

## 18. 性能与扩展

### 18.1 目标规模

- 单客户 1,000 名活跃外勤；
- 10 万地点；
- 每天 5 万任务；
- 按租户、城市、活动和日期分区；
- 不运行一次无界的全客户全局优化。

### 18.2 数据与 Worker

- PositionSample 按 tenant hash + 日期原生分区；
- GeoEvent、Task、Assignment 按 tenant/project/time 索引；
- PostGIS GiST/SP-GiST 索引用于几何查询；
- H3 cell 用于粗筛、覆盖和分区，不代替精确几何；
- 路线矩阵按 provider/mode/location version/time bucket 缓存；
- 规划 Worker 按 city/campaign shard 横向扩展；
- Evidence Worker 按模型、档位和客户预算隔离；
- 大照片进入 CAS，不进 PostgreSQL；
- 分析读模型未来可以从事实库异步构建。

### 18.3 演进路径

1. 本机：单 PostgreSQL/PostGIS、一个控制面、多个独立 Worker。
2. 商业：位置接入、围栏、规划、证据 Worker 独立进程，仍共享契约。
3. 增长：高频轨迹冷热分层、区域分片、分析库和读副本。
4. 超大客户：按 tenant/region 数据面部署，控制面继续统一。

领域 ID、版本、API 和 Graph 不因拆分改变。

## 19. 性能门槛

| 门 | 条件 |
|---|---|
| 位置批次 | 100 点请求 p95 ≤300ms |
| 围栏处理 | 服务端收到位置后 p95 ≤2s 生成 GeoEvent |
| 常规规划 | 200 人/10,000 原始候选任务先经城市/H3/硬约束粗筛，端到端 60s 内返回可行方案或明确失败 |
| 动态重排 | 100 人/2,000 剩余任务在 30s 内返回方案比较 |
| 离线恢复 | 10,000 乱序/重复事件幂等恢复，无覆盖 |
| 证据链 | 每任务可追溯门头原图、验证版本、位置事件和决定 |
| 隐私关闭 | FieldSession 结束后位置写入被拒绝 |
| 租户隔离 | 位置、轨迹、证据、路线和任务跨租户查询全部失败 |
| 不可达 | 无可行解返回约束原因，不生成虚假路线 |

这些是 Stage 级验收目标，正式 SLA 必须以目标硬件和真实地图调用压测结果为准。

## 20. 故障与降级

| 故障 | 行为 |
|---|---|
| 地图服务不可用 | 只用未过期的同版本缓存并标 stale；否则暂停规划 |
| 地理编码多候选 | 保留候选，要求 Location Steward 确认 |
| 求解超时 | 返回当前最佳可行解、gap/评分和未分配原因 |
| 无可行解 | 标记当前运力不可达，进入管理协调 Graph |
| GPS 漂移 | 扩大不确定性并要求额外证据，不直接失败 |
| App 离线 | 保持已冻结任务，本地加密排队，恢复后补传 |
| Worker 崩溃 | 从持久 Job/Checkpoint 恢复，幂等键不变 |
| 门头模型不可用 | 保存原图并进入人工队列，不伪造通过 |
| 人工积压 | 限流高风险自动结案，按 SLA/风险排序 |
| 存储接近满载 | 停止低优先级衍生处理，不自动删除证据 |

## 21. 测试策略

### 21.1 单元与属性测试

- 坐标系统转换和禁止混用；
- point/line/polygon 围栏、边界、迟滞和精度；
- FieldSession 状态和结束后拒绝；
- sequence 去重、乱序和时钟漂移；
- 续航、安全余量、时间窗和返程可行性；
- RoutePlanVersion、LocationVersion 和 GeofenceVersion 不可变；
- 普查覆盖率、道路/网格/POI 门；
- 门头融合不得由单信号直接处罚。

### 21.2 集成与契约测试

- 高德 geocode、POI、matrix、route 和 deeplink 契约；
- 地图录制响应回放，测试同输入不同 observed_at；
- PostGIS 空间索引和租户过滤；
- Position Ingest → GeoEvent → Assignment/Alert；
- TaskCandidate → 人工/策略 → Task/Assignment；
- Evidence → 多轮验证 → Human Review；
- Usage/Audit 与业务写入同事务。

### 21.3 端到端场景

1. 明确门店任务正常执行；
2. 门店坐标漂移但门头证据一致；
3. 新门头触发 LocationVersionCandidate；
4. 弱网补传且不重复到店事件；
5. 电动车续航不足返回不可达；
6. 临时任务触发冻结窗口重排；
7. EDS 普查未达覆盖门自动补扫；
8. 新地点查重与人工确认；
9. 跨租户读取全部拒绝；
10. FieldSession 结束后停止定位；
11. 自拍请求可触发但不自动人脸比对；
12. 地图/规划/视觉不可用时失败关闭。

### 21.4 真机与压力测试

- iOS/Android 前后台切换、系统终止、权限撤回；
- 2–5 分钟采样和显著位移的耗电；
- 相机拍照、压缩、加密和弱网恢复；
- 1000 员工/10 万地点/5 万任务合成城市；
- 规划 Worker 扩容、崩溃和积压恢复；
- 轨迹分区、索引、保留水位和导出审计。

## 22. 实施阶段建议

本模块是统一系统内的独立可维护 Domain Pack，因此需要自有 L0–L6 计划周期，但绝不是建第二套系统。总纲 Stage 0–1 Foundation Milestone 必须先通过；本模块之后只在已有 ModuleManifest、数据、Graph、Web、事件、证据、账本和审计插槽中实现领域能力。

### L0：契约与治理冻结

- 前置验收：统一 Foundation Milestone 的 Module SDK 和 Reference Echo Pack 契约测试已通过；
- Location、FieldSession、PositionBatch、Geofence、Campaign、Task、Assignment、RoutePlan、Evidence 契约；
- 坐标系统、版本、不变性、租户和保留策略；
- Map Provider、Planner、Evidence Capability；
- 隐私影响评估清单和禁用的人脸能力。

### L1：位置主数据与地图适配

- PostgreSQL/PostGIS；
- Place/LocationVersion/AccessPoint/GeofenceVersion；
- 公共主索引与客户 Overlay；
- 高德地理编码/POI/route matrix/deeplink 适配；
- 候选和人工确认。

### L2：员工 App、工作会话与围栏

- iOS/Android App 基础；
- FieldSession、位置批次和离线补传；
- GeoEvent 与围栏；
- 权限、透明度、短期轨迹保留；
- 门头照必选上传和基本质量检查。

### L3：明确门店任务与调度

- TaskCandidate/Task/Assignment；
- 步行、电动车、汽车 MobilityProfile；
- 硬约束与路线矩阵；
- 规划 Worker、人工确认和导航跳转；
- Point Task Graph。

### L4：门头多轮验证与证据审核

- 门头检测、OCR、Logo、历史向量和地理融合；
- 新门头/地址变化候选；
- 证据人工复核；
- 自拍请求接口，保持人脸比对禁用。

### L5：EDS 普查

- TerritoryCampaign、H3/业务区块、道路与 POI 基线；
- Agent 区块推荐和管理协调；
- PlaceCandidate 查重；
- 覆盖评估和补扫 Loop。

### L6：动态重排、规模与 token

- 冻结窗口和增量重排；
- 位置/围栏/规划 Worker 横向扩展；
- 目标规模压力测试；
- 真实成本拆分和 RateCard token 转换。

每个阶段独立写实施计划、验收证据和停止点；上一阶段未通过不得自动进入下一阶段。

## 23. 验收总表

| 编号 | 验收条件 |
|---|---|
| GEO-01 | LocationVersion/GeofenceVersion 历史不可覆盖 |
| GEO-02 | 坐标系统显式且混用测试失败 |
| GEO-03 | 地图供应商可替换，领域数据无高德专属依赖 |
| GEO-04 | 非工作会话位置被拒绝 |
| GEO-05 | 离线补传幂等、乱序可重放 |
| GEO-06 | 围栏不以单漂移点做重大结论 |
| FIELD-01 | PointTask 从候选到证据结案闭环 |
| FIELD-02 | 自动/人工派单策略可配置且可审计 |
| FIELD-03 | 不可达任务给出原因而非虚假路线 |
| FIELD-04 | 动态重排遵守冻结窗口 |
| CENSUS-01 | 无门店清单活动可按区块派发 |
| CENSUS-02 | 覆盖、POI、新发现和抽检门可配置 |
| CENSUS-03 | 新地点先候选查重，不能直接写公共主档 |
| EVID-01 | 每任务门头原图和处理链完整 |
| EVID-02 | 门头变化与员工异常被区分 |
| EVID-03 | 自拍可触发但人脸比对默认禁用 |
| PRIV-01 | 精确轨迹短期、派生证据分层保留 |
| PRIV-02 | 历史精确轨迹访问需要专门权限和原因 |
| TENANT-01 | 公共位置与客户私有 Overlay 分层 |
| TENANT-02 | 跨租户轨迹/照片/任务/路线全部拒绝 |
| SCALE-01 | 达到本规格性能门或明确 NOT ACCEPTED |
| BILL-01 | 原始成本事件可追溯到模块报价和 RateCard token |

## 24. 风险与挑战

- 地图服务配额、价格和道路结果会变化，必须做缓存版本、成本监控和供应商适配。
- 电动车路线和续航数据很难完全由地图供应商提供，必须依赖实测 MobilityProfile 和安全余量。
- 室内、商场和高楼环境 GPS 不稳定，必须用多入口、停留、门头和业务动作组合证明。
- 门头频繁变化会导致历史向量误报，需要 LocationVersionCandidate 和人工审核。
- 普查覆盖率不能只看 GPS 轨迹，否则会奖励无效绕行；必须结合道路、POI、证据和抽检。
- 位置和自拍均涉及敏感个人信息；上线前必须完成员工告知、单独同意、影响评估、权限和保留审查。
- VRP 大规模求解无法保证全局最优；产品必须展示可行性、未分配原因和求解限制，而不是“AI 最优路线”。
- 自动派单会影响员工工作安排，必须提供解释、退回、申诉和管理协调通道。
- 1,000 员工/5 万任务是目标容量，不等于未经压测即可作为 SLA 销售。

## 25. 已确认决策登记

| 决策 | 结论 |
|---|---|
| 定位强度 | 工作任务期间 2–5 分钟自适应采样 + 位移/围栏事件 |
| 派单权 | 默认人工确认；客户可配置低风险自动派单 |
| 交通方式 | 首版步行、电动车、汽车 |
| 电子围栏 | 任务证据和告警，不直接影响工资处罚 |
| 导航 | 系统内多点路线，第三方逐路口导航 |
| 轨迹保留 | 原始 90–180 天；派生事件按半年/2年/7年 |
| 家庭地址 | 非必需；使用开始工作位置或集合点 |
| 优化顺序 | SLA/优先级 → 可达 → 技能权限 → 效率 → 均衡 |
| 动态重排 | 异常触发 + 冻结窗口 + 高影响人工确认 |
| 地图 | 统一适配层，中国大陆首版高德 |
| 离线 | 加密缓存、序列补传、明确离线来源 |
| 防作弊 | 多信号 + 现场证据 + 人工复核 |
| 门头照片 | 每次任务必选，多轮验证 |
| 自拍 | 接口和风险触发保留，人脸比对暂不自动启用 |
| 位置模型 | 版本化 Location、多候选、多入口、多围栏 |
| 路线约束 | 班次、时间窗、服务时长、技能、续航、容量、休息和返程 |
| 任务来源 | 人工/API/问卷/识别/BI/Graph 统一进入候选池 |
| EDS 普查 | Agent 推荐地图区块，管理人员协调派发 |
| 普查完成 | 覆盖、POI、新发现和抽样策略组合门 |
| 多租户地点 | 公共位置主索引 + 客户私有 Overlay |
| 计费 | 初期模块成本报价，后期 RateCard 折算 token |
| 规模 | 单客户 1000 外勤、10万地点、5万任务/日，预留横向扩展 |
| 员工端 | iOS/Android 跨平台 App，Web 管理端，小程序补充 |

## 26. 对实施 Agent 的约束

1. 本规格确认前不得编写实现代码。
2. 位置与外勤运营必须在统一 Foundation Milestone 验收后再单独拆分 L0–L6 模块计划，不得与底座实施混写或一次完成。
3. 每次计划先写失败测试、再实现最小行为、再运行验收并保存证据。
4. 不修改或覆盖现有识别、训练、SQLite 历史、原图、模型和审核结果。
5. 不删除 `.superpowers`、测试产物、失败证据、数据库或业务文件；清理必须另行获得明确批准。
6. 不在代码中硬编码高德 Key、客户坐标、员工身份或费率。
7. 不以模型结果、单个 GPS 点或围栏事件自动处罚员工。
8. 不启用人脸比对，除非后续独立规格和合规门明确批准。
9. 不在没有真实道路矩阵时用直线距离冒充路线规划。
10. 不声明“最优”或目标吞吐达成，除非相应验收证据通过。
11. 不自建身份、数据库连接层、CAS、队列真相、Graph Runtime、人工任务、账本、审计或第二 Web 管理壳。
12. 不直接写其他 Domain Pack schema；跨域交互只使用总纲规定的 API、DomainCommand、事件、DataProduct 和 ResourceRef。

## 27. 下一步

用户复核本次“单一系统”修订后：

1. 先重写 Stage 0–1 计划，使其交付统一 Foundation Milestone，包括 Module SDK、统一数据底座、Web 壳、Graph+Loop 内核与两个最薄验证包；
2. Foundation 计划获批并实施验收后，再分别编写/执行识别、标注训练和位置外勤等 Domain Pack 计划；
3. 位置外勤 L0–L6 只实现本文右列的领域语义，不重复平台底座；
4. 任何实施代码仍需对应计划单独获批。
