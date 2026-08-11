# Agent 连续执行提示词：Agentic Business OS 可运营工作台 V3

把以下整段原样交给实施 Agent。

---

你现在接管 `/Users/zhangweiqi/Documents/QY/项目/LLM-Image`。你的任务不是继续添加演示页面，而是把当前系统改造成用户可以从首页开始，独立导入数据、配置业务、运行任务、查看进度并由 Agent 协助完成工作的 Agentic Business OS。

你必须持续执行完整任务，不得在 T0、T1 或任一阶段结束后停下来询问“是否继续”。阶段门是你的内部质量控制，不是用户确认点。只在以下情况向用户提问：需要 Secret/外部账号或地图 Key；需要删除/覆盖真实资产；需要远程部署/付费；需要启动未授权的长时间训练；存在两种会永久改变业务口径且无法从现场判断的选择。一个外部阻断不得阻止你继续完成其他独立任务。

## 一、绝对目标

最终让用户能只通过 8400 Web 完成：

1. 在首页看待办、日历、日程、进度、活动日志、容量和 Agent 提醒；
2. 配置主管和 Domain Agent 的 soul、prompt、Skill、知识库、工具、模型、记忆和审批；
3. 下载 CSV/XLSX 模板并导入客户、项目、SKU、员工、地址、用户和权限；
4. 从空白搭建问卷；
5. 获取地址坐标、在地图展示、设置规则并规划外勤路线；
6. 用拖拽画布搭建和真实运行 Workflow；
7. 默认用 V4 best 识别，同时能选择真实可加载的实验 Profile；
8. 打开 Label Studio、管理数据集并自主创建训练计划、观察进度和制品；
9. 自定义 BI 数据集、指标、公式、图表和 Dashboard；
10. 按客户查看 storage/photo/model/token Usage；
11. 让 Supervisor 查询全局事实、委派 Agent、弹出界面、预览命令并在批准后执行；
12. 在 Agent 不可用时，用相同页面人工完成所有关键动作。

最终系统 Gate 只能是 `READY_FOR_REAL_DATA_UAT`。没有完成真实用户路径不得写 READY、COMPLETE 或 PRODUCTION_READY。

## 二、开工前必须完整阅读

先建立 `READING-LIST.md` 并逐项记录已读 hash/结论，完整阅读：

1. `/Users/zhangweiqi/.local/share/ai-workflow/routing/GLOBAL_AGENT_ROUTING.md`；
2. 仓库/父目录所有适用 `AGENTS.md`；
3. `docs/CODEX-PROJECT-HANDBOOK.md`；
4. `docs/README.md`、`docs/USER-HANDBOOK.md`、`docs/OPERATOR-RUNBOOK.md`、`docs/MODULE-AGENT-DEV-GUIDE.md`；
5. `docs/implementation/agentic-business-os-domain-packs-v2/` 全部文件；
6. `docs/implementation/agentic-business-os-operational-workbench-v3/` 全部文件，最后读本提示词；
7. 当前 Module/Agent/Capability Registry、控制平面、Workflow、IAM、Survey、Analytics、Geo、Finance、Recognition、Training、Web 路由和相关测试；
8. 最近至少 30 个 commits 和当前真实数据库 schema/API/服务/进程。

不得只根据旧最终报告工作。开工时重新验证 HEAD、branch、worktree、服务、模型、迁移、DB integrity、production 和测试。

## 三、工程纪律

1. 遵循全局工作流：先使用 report-only QA/调查，再实施；复杂功能先写可执行设计或更新本目录决定。
2. TDD：每个 Bug/功能先有能证明 before 失败的测试，再实现，再跑局部和全量。
3. 小步 commit；明确列文件，禁止 `git add -A`/`git add .`；不暂存用户未跟踪训练/数据资产。
4. 不 merge、不 push、不远程 deploy；不删除历史数据库、模型、任务、截图和证据。
5. 迁移追加、幂等、有 hash；改 DB 前创建 SQLite backup，前后 `integrity_check=ok`。
6. 不能直接写 SQLite 完成业务 fixture；必须走与用户相同的 API/Domain Service。
7. 禁止假数据冒充真实结果、静态图冒充 BI/地图、Manifest 注册冒充 Agent healthy、mock 加载冒充模型上线。
8. 任何长期进程可恢复；页面刷新和服务重启后状态不丢。
9. 不启动新的长时间 YOLO/SAM/Classifier/QLoRA 训练。本轮只允许 preflight、dry-run、最小 smoke 和现有制品真实加载/推理。
10. 用户已经授权本机 V4 best 受控切换；其他 production switch、弱模型晋级和远程发布仍无授权。

## 四、先关闭数据一致性 P0

先为以下问题写红测试和浏览器复现，不修完不得继续扩 UI：

1. `workflow.succeeded` 未被投影器识别，完成 WorkItem 被 rebuild 成 todo；
2. 首页 `/workitems`、WorkItemV2、Taskboard、Supervisor、Calendar 是多套当前任务；
3. failed→retry→succeeded 后 current error 未清除；
4. BI `list_report_specs` 对每个版本再次取 latest，造成 v2 重复、v1 消失；
5. 旧 250 只能存在 history，不得进入任何 current count、日历和进度；
6. IAM 多客户用户只能看到第一个 customer；
7. Agent health 只验证 Manifest，invoke 对多数 Agent 只返回 `ok=true`；
8. Module 标 live 却没有 health/capability/manual E2E。

修复后执行事件清空投影重建对账。必须证明同一 Work 在 DB、API、首页、任务板、主管、日历和项目进度中的 status/owner/due/blocker 相同。`reconcile consistent=true` 必须同时对照 BusinessRun 业务事实，不能只和错误 reducer 自洽。

## 五、按 T0–T12 连续实施

### T0：现场审计和任务治理

- 更新本目录 `STATUS/ISSUES/IMPLEMENTATION-LIST/EXECUTION-LOG`；
- 记录 before 截图：无首页总控、主管布局、数据资产、问卷、位置、识别训练、BI、Workflow/Agent、IAM、主数据、财务、系统文档；
- 对所有不可用按钮、空页、假状态、断链建立可重复契约/浏览器测试；
- 建立一个 `operational_workbench_v3` Cycle 和每个 T 的 WorkItem；这些 WorkItem 必须立即在首页/任务板同源可见。

### T1：统一控制面

- 修复本提示词第四节全部问题；
- 当前错误与历史 attempt/error 分离；
- 日历、进度和活动日志建立在统一事件/Work 主线上；
- current/history/superseded 语义一致；
- 不新建另一套 Task 真相。

### T2：首页和主管工作台

按 `01-TARGET-OPERATING-MODEL-AND-MODULES.md` 实现首页八类真实卡片。

主管区桌面可调宽且不遮挡，1024 为底部可关闭工作区，768 为全屏对话。所有回答引用真实对象；命令预览显示影响、成本、权限、幂等、回滚和证据。快速目标、日程、便签和对话服务端持久化。

### T3：Import Center、IAM 与主数据

- 共用 Import Center；生成 `03` 文档列出的全部 CSV/XLSX 模板；
- 模板下载后必须能被同一系统重新解析；
- 实现上传、映射、dry-run、逐行错误、提交、幂等、Evidence 和安全补偿；
- 用户/角色/权限/成员关系可视化 CRUD 和权限模拟；
- 客户/项目/SKU/包装/门店/员工/地址可视化 CRUD、导入、停用、合并建议和历史；
- 多客户授权和跨客户拒绝测试。

### T4：真实 Agent Runtime

- 将 Agent Definition、Soul、Prompt、Skill、KB、Memory、Tool、Budget、Approval 建成版本化 Registry 和 Web 工作台；
- 至少完成 Supervisor、ModelOps、Data Steward、Survey、Analytics、Field、Finance 七个 Agent 的真实运行；
- 每个 Agent health 做 bounded probe，不以“注册存在”为健康；
- Supervisor 使用 Provider SPI + tool calling/planning loop；本地模型不可用时显示 degraded fallback；
- 至少真实执行：查进度、查最少 SKU、打开问卷、创建工作流 draft、查询地址缺坐标、调用识别、创建 BI draft、查询客户 Usage；
- 所有 Agent run 写 Work/Run/Event/Evidence/Usage；
- Prompt/Skill/KB 编辑只生成 draft，测试、批准、发布和回滚完整；Secret 不进 Prompt/DB 明文。

### T5：可视化 Workflow Studio

- 使用 `@xyflow/react` 的 MIT 开源画布；保留 ABOS canonical graph/runtime；
- 默认页面必须是拖拽画布，JSON 仅高级视图；
- 完成 Palette、Canvas、Inspector、Toolbar、Run Panel、版本和模板；
- Node Palette 从 Registry 投影；至少覆盖 trigger/data/condition/transform/loop/parallel/join/wait/approval/agent/model/capability/subflow/end；
- wait 使用持久化 timer；parallel 真并发且受租约；join 支持 all/any/quorum；Agent 调指定 Agent；
- 支持 lint、simulate、test run、approve、publish、新版本、暂停、恢复、取消、重试、人工接管；
- 重启 8400 后 timer/checkpoint/run 恢复；
- Node-RED 只预留 Adapter SPI 和许可证说明，不把它设成本轮硬依赖；不得集成 n8n/Dify 前端。

### T6：从空白自定义问卷

- 实现题型库、拖拽画布、属性面板、选项、分组/分页、复制、排序、删除；
- 支持 SKU/客户/项目绑定、单选、多选、填空、数字、日期、打分、矩阵、拍照；
- 支持必填/校验/自动评分/维度/权重/跳题图/lint；
- 照片题支持门头必拍、自拍可选、质量门、识别 Profile 和 suggestion→human final；
- 从空白创建、移动预览、发布、分配、填写、修改新版本 E2E；固定样板只保留为模板。

### T7：地址、地理编码、地图与外勤

- 地址模板导入、单条 CRUD、字段映射和重复检测；
- “获取坐标”按钮调用 Provider SPI；无 Key 时给配置入口并允许导入/手工坐标，不写假经纬度；
- 使用 MapLibre 类开源地图组件和可配置瓦片源；显示点位、围栏、路线、未分配任务和冲突；
- 建员工/班次/技能/起终点/容量/时间窗/区域/费用/多项目规则界面；
- 首版启发式必须诚实标注，提供 OR-Tools/求解器 Adapter 口；
- 路线版本、人工拖动调整、电子围栏、门头照、自拍口、普查网格和 Agent 建议派发；
- 无 Provider/瓦片时其他模块仍可用，位置模块显示 degraded 和人工路径。

### T8：识别、标注、数据集和自主训练

1. 精确定位 `best/sku_v4_best.pt`，记录 SHA、大小、来源和兼容性；
2. 建不覆盖旧 bundle 的新 V4 运行制品/profile；
3. 先 shadow 跑既有样板和失败样本，比较当前 production 的输出、延迟、错误和资源；
4. 验证 rollback 后，在本机原子切换默认 standard profile 到 V4 best；
5. 失败即自动回滚并登记 blocker，不得造成 8091/8400 长时间不可用；
6. 将已有 detector/segmenter/classifier/VLM artifact 按实际兼容性组装为 experimental/local profiles，真实加载、真实推理、真实 health；
7. 不可独立处理原图的 classifier 不伪装独立模型，必须与 detector/profile 组合；
8. M1/M2 等低指标制品必须标实验，不自动成为商业默认；
9. Recognition 页面解释 Profile/模型/档位，提供单图/批量/URL/API/Agent 和结果证据；
10. Label Studio 页面检查 taxonomy、项目、assisted/blind、任务、同步和跳转；
11. Dataset 页面支持照片池、过滤、去重、标注、snapshot、split、泄漏和 manifest；
12. Training 页面支持四 Lane 的数据集/基础模型/参数/preflight/dry-run/批准/队列/日志/指标/资源/制品/评估/发布计划；
13. 执行一个最小可撤销 smoke 证明输入→Job→日志→artifact→evaluation，不启动长训练。

### T9：BI 工作台

- 数据产品/字段/血缘浏览；
- 指标、维度、过滤、时间窗和受限公式 DSL；禁止任意 SQL；
- 使用 Apache ECharts 等真实图表库实现 Dashboard 画布、布局、筛选、钻取、联动和保存；
- Analytics Agent 生成 draft，必须显示数据源、公式和预览后人工发布；
- 修复 v1/v2 版本列表、比较、发布和历史；
- 异常→追问→回答→评价→刷新新版本；
- 每个数字可下钻到响应/识别/导入证据。

### T10：财务与客户 Usage

- 本轮不扩建完整会计；页面改为客户级 Usage/费用日志工作台；
- storage/photo/model_compute/token/agent/human_review 等类型按客户/项目/日期统计；
- 每条下钻 run/task/evidence/model/rate version；
- 趋势、预算、异常、未归属和 CSV 导出；
- 已结算追加调整，不原地改；不让 settled invoice 显示必然失败的动作。

### T11：帮助文档、系统管理和全局 UX

- 将“系统与开发者”拆为“帮助与文档”和管理员“系统管理/开发者”；
- 用户手册按角色/任务组织，包含首次登录、导入、问卷、外勤、识别、训练、BI、Workflow、Agent、Usage；
- UI 内全文搜索、模块状态、模板说明、API Explorer 和故障排查；
- 所有页面处理 loading/empty/error/permission/degraded/success；
- 删除假页签、不可点击卡片、透明按钮和重复导航；
- 模块色与状态色分离；四视口、键盘、焦点、对比度、reduced motion 验收。

### T12：端到端和收口

严格执行 `05-REAL-DATA-END-TO-END-UAT.md`，使用 API/UI 创建 `uat_fixture_v3`，不得直接写数据库。生成自动 reconciliation、浏览器截图、console、性能、安全、资源、服务恢复和许可证清单。

更新所有治理文档、`docs/README.md`、`docs/CODEX-PROJECT-HANDBOOK.md`、用户手册和运行手册。旧入口标 superseded-for-current-execution，但不删除。

## 六、持续自检 Loop

每个 Task 完成前都问自己并提供证据：

- 用户能否从导航找到？
- 不用终端能否创建第二个对象，而不只是看 fixture？
- 有输入、处理、输出、错误和恢复吗？
- 人工路径与 Agent 路径是否写同一事实？
- 页面显示的 live/healthy/enabled 能否真实运行？
- 刷新和重启后是否仍在？
- 客户/项目权限是否贯穿？
- 是否产生 run/event/evidence/usage？
- 是否有浏览器真实点击和 DB/API 对账？

任何答案为否，Task 不得标 VERIFIED_LOCAL，继续修复。

## 七、测试与浏览器验收

至少执行并报告：

- 新增 P0/P1 红测试 before/after；
- hermetic full suite；
- host_mps 独立 suite；
- TypeScript typecheck 和 production build；
- SQLite integrity、迁移幂等、备份 integrity；
- OpenAPI/Module/Agent/Capability/UI Route/Import Template 契约；
- Playwright/真实浏览器 1440/1280/1024/768；
- 首页→导入→问卷→地图→工作流→识别→BI→Usage 全链；
- console error/warn、网络 4xx/5xx、断链、横向滚动和不可用按钮扫描；
- 登录/CSRF/IDOR/SSRF/rate limit/prompt injection/公式注入/文件上传安全；
- 8091/8092/8300/8400 stop/start/restart/doctor 和工作流恢复。

不要把 mock、deselected、截图失败或“代码看起来正确”写成 pass。

## 八、完成状态

只有以下全部满足才可停止：

- T0–T12 全部 `VERIFIED_LOCAL`，或只剩不影响 UAT 的明确 `BLOCKED_EXTERNAL`；
- G0–G8 全部通过；
- P0=0、P1=0；
- V4 best 默认 profile 真实可用且回滚验证完成；
- 其他本机 Profile 状态真实；
- 用户能从空白创建问卷/Workflow/BI/角色/客户/地址；
- Agent 和人工双通道全链；
- 最终 Gate=`READY_FOR_REAL_DATA_UAT`。

如果资源或外部 Provider 阻断位置地图/地理编码，只能将相关模块标 `degraded`，完成全部其他工作并给用户一个最短配置动作；不得把整轮任务停在“等待用户确认”。

## 九、最终报告格式

最终一次性报告至少包含以下 55 项，不得只给摘要：

1. HEAD/branch/worktree；2. commit 链；3. 阅读清单；4. 初始服务/进程/DB/production；5. before 截图；6. P0/P1 台账；7. 每个根因/红测试/修复/证据；8. 迁移与备份；9. SQLite integrity；10. 统一 projection 对账；11. current/history/旧250；12. 首页卡片；13. 日历；14. 日程；15. 进度；16. 活动日志；17. 主管四视口；18. Supervisor 八个真实工具意图；19. Agent Definition；20. Soul/Prompt/Skill/KB/Memory；21. Agent health；22. React Flow 画布；23. wait/parallel/join/loop；24. 人工批准/恢复；25. Import Center；26. CSV/XLSX 模板清单；27. IAM 自定义；28. 多客户隔离；29. 客户/项目/SKU/员工主数据；30. 空白问卷 E2E；31. 跳题/评分/照片；32. 地址导入；33. geocoder；34. 地图；35. 路线/围栏；36. V4 artifact/hash；37. shadow/切换/回滚；38. 其他模型 Profile 真实状态；39. 识别五入口；40. Label Studio；41. Dataset/Snapshot；42. Training dry-run/smoke；43. BI 指标/公式；44. Dashboard；45. BI 版本与异常追问；46. 客户 Usage；47. 人工备援矩阵；48. 全链 ID/reconciliation；49. hermetic；50. host MPS；51. typecheck/build；52. 浏览器/console/四视口；53. 安全/rate limit；54. 性能/容量；55. 服务恢复；56. 文档/手册；57. production/训练/部署声明；58. 未关闭外部 blocker；59. 当前 Gate；60. 用户下一步仅需执行的真实数据 UAT。

报告中的每个“完成”必须附 API、DB、浏览器或制品路径。不能使用“已实现”“应该可用”而没有证据。

现在开始执行。不要在中间阶段等待用户确认，持续工作直到满足停止条件或只剩明确外部阻断。

