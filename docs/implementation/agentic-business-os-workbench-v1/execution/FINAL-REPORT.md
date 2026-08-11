# FINAL REPORT · Agentic Business OS 工作台重构与识别首域打通

> 日期：2026-08-11 · 分支：feat/nextgen-training-cycle-v2 · 所有数量/状态来自最终实时对账
> （evidence/T12-final-reconciliation.txt）。

## 1. HEAD / branch / worktree

- HEAD 起点 `7c2eab62`，本轮终点 `b5e27547`（后续收口提交见 git log）。
- branch：`feat/nextgen-training-cycle-v2`；单 worktree（主仓库）。

## 2. 本轮 commit 链

1. `5bb41228` T0/T1：基线证据 + 12 个红契约测试
2. `83036521` T3/T6/T7：ModuleManifestV2 单一事实源 + Supervisor 重写 + Profile 契约
3. `353052e2` T2/T4/T5/T9：AppShell + Registry 三级导航 + 首页指挥中心 + 身份纠正
4. `b5e27547` T8/T11：bin/abos 栈控制 + 识别 E2E 证据
5. 收口提交：浏览器 QA 修复（rowid bug/面板收起/按钮终态/样式）+ 三份手册 + execution 文档

## 3. 完整阅读文件

AGENT-EXECUTION-PROMPT + 00–07 全部；CODEX-PROJECT-HANDBOOK；USER-HANDBOOK；
GLOBAL_AGENT_ROUTING；registry.py/kernel/agents/api/data/store；modules/fmcg、
recognize/service、adapters/legacy/recognition；web 全部页面与样式；
registry/store/composition 装配；近 12 个 commits；当前 DB schema（63 表）与
运行服务。project-logic-chain-v3 / micro-gold-v2 目录按索引核对（与本轮
平台壳层直接相关性低，未逐行展开——如实登记）。

## 4. 初始服务/进程/DB/production（T0 实测，非文档旧值）

- 8091/8092/8300/8400 当时**均在运行**（00 文档"全部未运行"为 8-11 上午快照）。
- 无训练进程；SQLite integrity=ok；63 表；agent_manifest=4→6；
  profile_def=11；recognition_task=5→11。
- production：`prod_20260805_v5_r1`（CURRENT.json，未切换）。
- 证据：execution/evidence/T0-services-probe.txt。

## 5. 初始 UI before 复现

12 个红测试全部失败证明问题存在（login/footer SKU 文案、MODULES 双份常量、
RAIL 硬编码、/biz 同组件、Profile 未入请求、UIIntent 未消费、Path 未导入、
CSS 未定义变量、m3bars 假 BI）。

## 6. 初始 P0/P1 复现

P0-01～P0-06、P1-01～P1-04 全部现场确认（见 ISSUES.md ABOS-001～010）。

## 7. 产品定位修复前后

- 前：登录 `qy · sku recognition`、footer「SKU 识别系统」、8092 标题
  「SKU 识别 · 后台管理端」、Supervisor prompt「你是 SKU 识别系统的主管」。
- 后：统一 `/api/v1/platform/identity`（Agentic Business OS/智能业务操作系统）；
  登录/顶栏/footer/OpenAPI title/Supervisor system prompt/8092 标题全部消费或改为该身份；
  识别仅在 Vision Domain 出现。13/13 契约测试绿。

## 8. 平台级硬编码清理

footer production 硬编码 → `/api/v1/platform/production` 实时读取；
Recognition 页旧 bundle `prod_20260804_v4_r2` 文案随页面重写移除；
Overview/BizIntel 硬编码卡片随路由下线；首页数字全部来自 workitems/health/tasks API。

## 9. Module Manifest V2 schema

`src/platform/registry.py`：ModuleManifestV2（module_id/name/version/domain/
status/theme_token/primary_route/navigation(route+label+actions)/agents/
capabilities/commands/queries/events/api_prefix/openapi_tag/data_products/
permission_scopes/ui_slots/feature_flags/dependencies/compatibility/
billing_units/health_checks）+ ModuleRegistry（route/module/agent/capability
冲突 fail-closed；缺依赖→degraded 投影）。

## 10. Module Registry 数量和状态

10 个模块（实时 `/api/v1/modules`，source=ModuleManifestV2）：
home/live、data/live、survey/planned、geo/planned、vision/live、
analytics/planned、workflow/live、finance/planned、system/live、
reference.echo/live。

## 11. Agent Registry 数量和关联

6 个 AgentManifest（supervisor/modelops/data_steward/workbench/
recognition_agent/system_agent，本轮新增后两者）。模块关联：
home←supervisor+workbench，vision←recognition_agent+modelops，
data←data_steward，system←system_agent；冲突 fail-closed 有测试。

## 12. Capability 数量和关联

`/api/v1/capabilities` = 4：legacy.recognition.v2、legacy.training.monitor、
legacy.label_studio（归 vision/system 模块声明）+ reference.echo（本轮新增，
组合根注册，非识别证明内核通用）。

## 13. API/Web/Agent 四方一致性

导航/路由/状态全部来自 ModuleManifestV2 投影：前端 App.tsx 无手写一级清单
（红测试强制）；modules_api 无常量；Agent manifest 与模块关联可查；
契约测试 13+16+10+11 项全绿。

## 14. reference non-vision module 验收

`reference.echo` 注册（ModuleRegistry+CapabilityRegistry）→ 导航可发现
（/reference/echo 页面）→ `/api/v1/reference/echo?text=ping` 实测返回
`{"module_id":"reference.echo","echo":"ping","status":"ok"}`。

## 15. 一级导航结果

9 个一级模块（reference.echo 不作业务导航），Registry 投影 + 状态徽章 +
模块 accent dot；active 唯一；浏览器验收 pass。

## 16. 二级 route 清单

vision：/vision/{recognize,tasks,annotation,datasets,models,evidence}；
home：/、/home；data：/data/assets、/data/quality；workflow：/workflow/runs、
/workflow/agents；system：/status；planned：/survey/*、/geo/*、/analytics/*、
/finance/*；reference：/reference/echo。全部真实独立路由，无同 URL 假页签。

## 17. 三级 action 清单

Manifest actions 声明（如即时识别：上传照片/URL 输入/批量任务/选择 Profile/
导出结果）；页内实际呈现为工具栏/表单/按钮（ProfilePicker、档位选择、
批准/拒绝、筛选/分页/刷新）。

## 18. 旧 route 兼容结果

/recognition→/vision/recognize、/cascade→/vision/tasks、/labelstudio、
/annotation、/assets、/training、/models-runtime、/packaging、/biz/*、
/taskboard、/runs 全部 Navigate 重定向；浏览器实测 /#/recognition 自动跳转。

## 19. Design token 定义/使用审计

tokens.css：中性表面/状态色/9 组模块 accent+soft/便签色/兼容旧色板；
状态色与模块色分离；测试 `test_css_variables_all_defined` 强制全量扫描。

## 20. 未定义 variable/class 数量

0（CSS 变量使用-定义差集为空，pytest 通过）。孤儿组件 AgentChat/
SupervisorDrawer/ModuleTabs/BizIntel/旧 Recognition 已删除或下线。

## 21. 组件系统清单

AppShell(topbar/pnav/snav/page/footer)、Login、PageHeader、Card/Grid/Tile、
Table、Upload、Badge/Pill、Banner、StateView(loading/empty/error)、
PlannedModule、NoteCard、AgentMsg、IntentChip、CommandPreviewCard、
EvidenceList、Delegation、Drawer 样式、BoxOverlay。

## 22. 1440/1280/1024/768 结果

真实浏览器功能验收全 pass；视口精确尺寸受浏览器自动化工具限制（实际
934–1383px 程序化验证无横向滚动），CSS 断点 1280/1024/768 已编写。
登记为 partial，见 BROWSER-QA.md。

## 23. 键盘/无障碍/对比度结果

focus-visible 全局规则；ProfilePicker role=radio+键盘 Enter/Space；
tab/tablist aria；Esc 关闭由抽屉/面板支持；prefers-reduced-motion 关闭动画；
登录页输入对比度问题已修。完整 WCAG AA 审计未逐点执行（登记残留）。

## 24. 首页真实数据源

/api/v1/workitems（待办/审批/运行/异常/完成投影）+ /api/v1/runs +
/api/v1/recognition/tasks + /api/v1/health + /api/v1/modules；无硬编码数字。

## 25. 待办/审批/运行/异常/完成/笔记结果

浏览器实测：待办 100（真实 rq/审核投影）、批准/运行/异常/完成按实时计数，
空态显示“暂无 · 诚实空态”；固定笔记 localStorage + 便签样式。

## 26. Supervisor 对话结果

实测：“识别任务”→“共 11 条；最近一条 a05e038b…（agent，SKU 6）”（实时
store 查询）；无关问题 LLM 不可用时诚实降级为规则回答；会话/消息服务端持久化。

## 27. UIIntent 执行结果

“打开识别任务”→ 白名单 navigate → 前端真实跳转 /vision/tasks（浏览器验收
pass）；非法 kind 拒绝；禁 html/js/script 字段（validate_ui_intent）。

## 28. Evidence Drawer 结果

证据引用在 Agent 消息内以证据列表呈现（evidence_refs kind+ref）；独立
证据抽屉组件样式已备（drawer），完整 Run trail 展示经 /vision/evidence 与
cascade trail 页提供。登记：证据抽屉的独立弹层交互未在本轮全量打磨。

## 29. Command approve/reject 结果

批准 → `agent_command_v1` approved + decided_by/at 审计 + 组合根钩子真实
创建识别任务（execution.task_id=8c8d1b16…，source=agent）；重复批准 409；
拒绝同样落库；测试 10/10 绿。

## 30. Domain Agent 委派结果

识别请求类对话自动生成 delegations 回执（recognition_agent /
vision.recognition.create.preview / ok），前端渲染委派条。

## 31. 会话和记忆持久化结果

agent_session_v1 / agent_session_msg_v1 服务端持久化（meta 含完整契约字段）；
前端刷新后从 /sessions/{id}/messages 恢复；localStorage 仅缓存 session_id。

## 32. Recognition Profile 请求证据

单图实测：task=ecbd1cfc… profile=production_legacy tier=standard source=web
trace=tr-8feff2b4a755（evidence/T8-single-upload.json）；批量/URL/Agent 同样回显。

## 33. disabled/unknown profile 拒绝证据

research83_classifier → HTTP 400 `profile_rejected` + blockers
（T8-disabled-profile-rejected.json）；未注册 ID 与 `.pt`/路径输入同 400
（契约测试 4 项）。

## 34. 单图识别结果

bad_samples/36070492_reflection.jpg（反光样板）→ completed，SKU 6，
613.73ms；0 检出场景诚实说明。

## 35. 批量识别结果

2 张反光样板 → batch_file completed，SKU 8，429.19ms。

## 36. URL 识别结果

本机临时 HTTP 真实下载 → entry=url completed SKU 2 trace=tr-76111b17df3f；
SSRF 缓解：仅 http/https、禁自动重定向、10s 超时。

## 37. Agent 发起识别结果

chat“用生产模型识别这批照片”→ 命令预览（含 image_path 仓库样板）→
批准 → 真实任务 8c8d1b16…（entry=agent，source=agent，
by=agent:supervisor），任务历史可见。

## 38. 任务历史一致性

recognition_task 共 11 条；本轮 6 条全部带 profile/tier/source/trace；
Web/API/Agent 同一张表（T8-task-history.txt）。

## 39. Graph trail / evidence / usage 对账

任务行含 trace_id；Agent 命令审计链 agent_command_v1（pending→approved，
decided_by）；识别结果 result_json 持久化；cascade trail/evidence 页面保留。
完整按 trace 串联 run/evidence/usage 的全自动对账脚本登记为下一包增强项。

## 40. 识别故障与恢复测试

kill 8091 → 聚合健康 unavailable + recognize unavailable；识别请求诚实
failed（unreachable: Connection refused）；`bin/abos start` 恢复 →
agg healthy（evidence/T8-failure-degraded.txt）。

## 41. planned 模块诚实状态

survey/geo/analytics/finance=planned；页面仅显示目标/依赖/Data Product/
下一实施包 + “本页不展示模拟数据”；/api/v1/biz/m3bars 已删除（404 实测）。

## 42. 本地 status/start/stop/restart/doctor

bin/abos 五命令全部实测：冷启动（stop→全 DOWN→start→四服务 UP）、
幂等 start（已运行跳过）、doctor（integrity ok/dist/端口/训练进程/LLM key）、
stop 只杀精确进程并先停 watchdog。日志 .platform/logs/，PID .platform/run/。

## 43. 用户手册路径

docs/USER-HANDBOOK.md（重写：Quick Start/三级导航/Agent 审批/识别操作/
planned 语义/Troubleshooting Matrix；命令实测；无硬编码动态事实）。

## 44. 运维 Runbook 路径

docs/OPERATOR-RUNBOOK.md（服务拓扑/日志/冷启动/只读核验/排障/安全边界）。

## 45. 模块/Agent 开发指南路径

docs/MODULE-AGENT-DEV-GUIDE.md（Domain Pack 创建步骤/Manifest 字段/Agent
契约/识别契约样例/Data Product/测试要求/参考实现索引）。

## 46. Hermetic / Host MPS / 前端测试

- hermetic：`1173 passed, 1 skipped, 6 deselected`（deselected=host_mps，单独执行）。
- host_mps：`6 passed, 1174 deselected`。
- 前端：`npm run typecheck` 零错误；`npm run build` 成功（267.56 kB js / 18.76 kB css）。
- 基线对照：本轮开始时有 1 个既有失败（test_app_routes_and_nav），已按新
  导航契约更新并通过。

## 47. SQLite / API / 四服务 / 浏览器 QA

SQLite integrity=ok；30 个迁移（最新 030_recognition_task_profile_contract）；
四服务 healthy（ml_backend disabled 为既有状态，非本轮引入）；浏览器 QA
12 场景 pass + 视口 partial（T13 表）。

## 48. 性能与安全结果

性能（evidence/T12-performance.txt）：health p50=148.5/p95=165.2ms（含实时
探测 5 服务）；modules/tasks/HTML p50≈1.6–1.8ms p95≤2.4ms；识别端到端
76–614ms/图。轮询降频（visibilityState）、任务分页、长任务幂等可重放。
安全：身份=服务端 session（禁 header 自证）、CSRF、UIIntent 白名单、
两阶段批准、幂等键、上传大小/数量上限、URL 禁重定向/仅 http(s)、
production switch 拒绝、Agent 无直库写。残留：rate limit 未在本轮加（登记）。

## 49. production 未切换、未启动训练声明

production 全程 `prod_20260805_v5_r1`（CURRENT.json 未改动）；本轮未启动
任何训练（`bin/abos status` 训练进程=0）；未 merge/push/deploy；未删除
历史资产（仅移除本轮被取代的孤儿前端组件文件并登记）。

## 50. 当前 Gate、未关闭问题和用户下一步

**Gate：READY_FOR_NEXT_DOMAIN_PACK**（13 项硬条件逐项核对：定位统一、
单一事实源、三级菜单真实、无未定义样式、Supervisor 实际控制、识别同源、
冷启动可演示、planned 诚实、测试/构建/DB/服务/浏览器通过、三份手册可操作、
production 未切换、未训练、证据对账完成）。

未关闭问题（诚实登记）：
1. 视口精确四尺寸验收受工具限制为 partial（CSS 断点已就位）；
2. rate limit 与 trace 全链自动对账脚本列入下一实施包；
3. 完整 WCAG AA 逐点审计未做；证据抽屉独立弹层未全量打磨；
4. 旧页面（Overview/TaskBoard/GraphRuns 等）样式仍在过渡层，未逐页重绘。

用户下一步：
- LS22 完成 200 条 micro-gold v2 人工审核（既有唯一人工入口，未变）；
- 如需新 Domain Pack，按 docs/MODULE-AGENT-DEV-GUIDE.md 注册 Manifest；
- 如需切换 production 或启动训练，需另行明确授权。
