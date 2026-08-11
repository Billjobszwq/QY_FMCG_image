# Domain Packs 规格

## 1. 账号、角色与权限 Pack（必须先做）

### 1.1 对象

- Tenant、Account、Customer、Project；
- User、ServiceAccount、AgentIdentity、Team；
- Membership、Role、Permission、Policy、DataScope；
- Invite、Session、API Key、Credential Reference；
- Approval Matrix、Audit Event。

### 1.2 角色

内置角色仅作模板：Owner、Platform Admin、Customer Admin、Project Manager、Survey Designer、Field Manager、Reviewer、Analyst、Finance Operator、Read Only、Agent Service。

允许客户创建自定义角色，但权限只能从版本化 permission bundle 组合；必须支持 tenant/customer/project/record/field scope。Agent 是独立身份，不借用管理员账号。

### 1.3 门禁

- session/header 不能自证角色；
- 所有 Domain API 使用同一个 principal/policy context；
- 敏感动作需要两阶段预览与批准；
- 客户数据采用行级作用域，敏感字段可列级限制；
- 权限变化、登录、导出、批量修改均写审计。

## 2. 主数据 Pack（共享底座，不从属于问卷）

### 2.1 SKU 库

`sku_id`、package/version、品牌、品类、容量、条码、别名、客户显示名、有效期、新旧包装关系、参考图、状态。支持客户选择沿用旧名或启用新名，不覆盖历史问卷答案。

### 2.2 客户库

客户、组织、合同、联系人、数据保留期（半年/2 年/7 年）、结算规则、服务档位、数据作用域。

### 2.3 项目库

项目关联客户、时间范围、区域、SKU 范围、问卷、任务、员工、识别 Profile、预算、报表、结算合同。

所有主数据版本化、可追溯；批量导入必须预检、差异预览、幂等和错误行回执。

## 3. 问卷 Pack

### 3.1 必备题型

- 单选题；
- 多选题；
- 填空题（文本/数字/日期可配置）；
- 打分题；
- 跳题逻辑；
- 拍照绑定题目。

预留矩阵、排序、地址、签名、录音/视频等扩展类型，但首阶段不伪造已实现。

### 3.2 数据模型

- Questionnaire、QuestionnaireVersion（发布后不可改）；
- Section、Question、Option；
- LogicRule/LogicEdge、ValidationRule、ScoringRule；
- Assignment、Respondent/FieldVisit；
- Response、Answer、MediaBinding；
- DerivedScore、RecognitionSuggestion、Correction、Audit。

编辑草稿和已发布问卷分离；修改已发布问卷生成新版本，历史 Response 绑定原版本。

### 3.3 跳题与评分

跳题逻辑保存为可验证 DAG：检测循环、不可达题、冲突条件、缺失默认分支。评分规则版本化，输出保存公式版本、输入答案和计算证据；不得只保存最终分数。

### 3.4 拍照题与识别

拍照题定义最少数量、必拍门头/员工自拍开关、照片类型、质量规则、拍摄时间/位置/设备证据和识别 Profile。上传后触发：

`媒体入库 → 质量过滤 → 识别 → suggestion → 人工接受/修正 → final answer → score/report`

模型结果永远是 suggestion，不得覆盖人工答案；拒绝/修改结果反向进入评估与标注候选池，但不能自动进入训练真值。

### 3.5 后台修改

后台不能直接 UPDATE 已提交答案。采用 correction event：原值、新值、原因、操作者、批准人、时间、影响的评分/报表重算版本全部留痕。

## 4. Analytics / BI Pack

### 4.1 先建语义层

对象：DataProduct、DatasetVersion、Metric、Dimension、JoinPolicy、SemanticModel、ReportSpec、Dashboard、Widget、Filter、Schedule、Snapshot、Lineage。

Agent 不能直接对任意表生成 SQL。自然语言需求先解析为受权限约束的 Metric/Dimension/Filter/ReportSpec，显示预览、口径、样例、成本和血缘，经批准后发布。

### 4.2 功能

- 按客户/项目创建 dashboard 和细分报告；
- 维度拆分、钻取、筛选、对比、导出、定时生成；
- 指标快照和数据版本追踪；
- 异常规则、趋势/分布异常、数据新鲜度和质量告警；
- 异常自动创建追问 WorkItem，分配给人员或 Agent；
- 回答、证据、反馈和数据评价回写异常事件；
- 修正数据或规则后生成新报告版本，不覆盖旧报告。

### 4.3 BI Agent

负责需求澄清、语义映射、报告草稿、解释和追问，不可绕过 RLS、预算与发布批准。沉淀的是可复用 ReportSpec/Workflow Template/Metric，不是不可审计的聊天文本。

## 5. 位置与外勤 Pack

### 5.1 对象

- Employee、Team、Skill、Availability、Shift、Vehicle；
- Address、Place、GeocodeCandidate、Store、Territory；
- FieldTask、Visit、RoutePlan、RouteStop；
- Geofence、LocationPing、GeofenceEvent；
- TravelRate、TravelCost、ExpenseEvidence；
- MapLayer、CoverageGrid、AreaAssignment。

### 5.2 地址与地图

地址导入后通过 `GeocoderAdapter` 获取候选经纬度、置信度和规范地址；低置信度必须人工确认。地图通过 `MapProviderAdapter`，避免绑定单一供应商。位置数据必须有员工授权、工作时段、精度、保留期和访问审计。

### 5.3 路径规划

用可替换的 OR Solver 处理 VRP：时间窗、人员技能、容量、优先级、服务时长、交通方式、区域边界、差旅费、门店营业时间。支持：

- 用户设置条件或客户规则；
- 多项目合并规划，但硬隔离条件不得合并；
- 无门店清单的普查任务，以地图网格/区块分配；
- 管理人员协调下 Agent 提议分配，人工批准后派发；
- 规划版本、目标函数、约束、未分配原因和成本解释。

### 5.4 到店与证据

电子围栏只作为证据之一；结合 GPS 精度、停留时间、门头多轮识别、任务门头必拍和可选自拍。人脸比对默认不自动触发，保留受权限和人工批准的示警接口。

## 6. 财务与计费 Pack

### 6.1 对象

Contract、Subscription、RateCard、Meter、UsageEvent、CostAllocation、Invoice、InvoiceLine、Settlement、Adjustment、Payment、TaxProfile。

### 6.2 收费模式

- 月度订阅；
- 按识别照片/区域；
- 按平台 token；
- 混合阶梯、最低消费、超额费、客户折扣；
- 本地初期可按模块成本汇总，后期由后台成本拆分后折算 token。

### 6.3 原则

- TTL/总费用应称 `total`，避免与数据库 TTL 混淆；
- 分开记录资源成本、内部成本、客户售价；
- 按 tenant/customer/project/contract 分摊；
- 价格版本与 Usage 发生时绑定，后改价格不重算历史；
- 账单调整使用 adjustment/reversal，不删除 Usage；
- 账单能下钻到 workflow run/node/model/photo/token/外勤里程证据。

## 7. Domain Agent 体系

第一阶段至少注册：Supervisor、Workflow Agent、IAM Agent、Data Steward、Survey Agent、Analytics Agent、FieldOps Agent、Finance Agent、Recognition Agent、ModelOps Agent、Workbench Agent、System Agent。

每个 Agent 有独立 identity、capability allowlist、数据 scope、预算、记忆 ACL 和健康状态；允许交叉协作，但跨 Agent 写入和高风险命令必须经过共享黑板事件与人工批准。
