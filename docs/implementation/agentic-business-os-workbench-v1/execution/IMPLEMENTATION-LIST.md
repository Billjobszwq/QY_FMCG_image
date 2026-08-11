# Implementation List（Graph 节点 → 实施项）

> 状态图例：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成并验证 · `[!]` 受阻/降级

## T0 BaselineAndSafetyAudit
- [x] Git HEAD/branch/worktree 核验（7c2eab62 @ feat/nextgen-training-cycle-v2，单 worktree）
- [x] 服务探测：8091/8092/8300/8400 均在运行且 /api/v1/health 聚合 healthy（与 00 文档 8-11 上午快照不同，以现场为准）
- [x] 无训练进程证据（ps 仅 monitor/serve/recognize/yolo_backend）
- [x] SQLite integrity=ok，63 表；agent_manifest=4；profile_def=11；recognition_task=5
- [x] production bundle = prod_20260805_v5_r1（CURRENT.json），未切换
- [x] 未跟踪资产清单登记（.datasets_nextgen/*、.micro_gold_*、.superpowers/ 等，不碰）
- [x] 证据：execution/evidence/T0-services-probe.txt

## T1 CurrentUXBreakageReproduction
- [ ] 红测试：平台级 SKU 文案（App.tsx 登录/页脚、supervisor prompt）
- [ ] 红测试：modules_api 第二份 MODULES 常量
- [ ] 红测试：多二级菜单同 route（/biz 系、ModuleTabs）
- [ ] 红测试：Profile 未进入识别请求
- [ ] 红测试：UIIntent/evidence/command 未被前端消费
- [ ] 红测试：CSS 未定义 variable/class
- [ ] 红测试：m3bars 读训练报告冒充 BI

## T2 ProductIdentityCorrection
- [ ] 登录页/页脚/TopBar 品牌改为 Agentic Business OS
- [ ] Supervisor system prompt 去 SKU 化
- [ ] 平台品牌配置单一源（后端 /api/v1/platform/identity + 前端消费）
- [ ] footer production 硬编码改为 API 实时值

## T3 ModuleManifestV2AndRegistryProjection
- [ ] registry.py 扩展 ModuleManifestV2（navigation/agents/capabilities/commands/data_products/ui_slots/permissions/flags/deps/billing/health/status）
- [ ] module_catalog.py 只读投影 + 9 一级模块 + reference.echo
- [ ] modules_api.py 消费 registry，删除第二份常量
- [ ] route/module/capability/agent 冲突 fail-closed 校验
- [ ] reference.echo 注册、导航、API、健康验证
- [ ] 前端 moduleRegistry.ts 从 API 读取，App.tsx 不持有一级清单

## T4 DesignSystemAndAppShell
- [ ] tokens.css（模块 accent + 状态色分离 + 全部变量定义）
- [ ] AppShell/TopBar/PrimaryNav/SecondaryNav/PageHeader 组件
- [ ] Status/Empty/Error 组件；移除跑马灯/巨型 footer
- [ ] 未定义 variable/class 清零审计

## T5 ThreeLevelNavigationMigration
- [ ] 一级=Registry 投影；二级=独立 route（/vision/* 六条等）
- [ ] 三级=页面工具栏/操作
- [ ] 旧 route redirect（/recognition→/vision/recognize 等）
- [ ] 深链接/刷新/前进后退验证

## T6 SupervisorAndDomainAgentRuntime
- [ ] 移除过期硬编码答案；查询走 Query Tool/store
- [ ] 修复 Path 未导入、不可达 M4 分支、宽泛异常
- [ ] 统一响应契约（message/evidence_refs/ui_intents/command_previews/tasks/delegations/requires_approval/trace_id）
- [ ] 前端消费 UIIntent（navigate/show_evidence/highlight 白名单执行）
- [ ] CommandPreview + approve/reject 落库审计
- [ ] EvidenceDrawer；Supervisor 工作台（便签/待办）

## T7 RecognitionProfileContract
- [ ] 请求契约加 recognition_profile_id/service_tier/source/project_id/idempotency_key
- [ ] 服务端 profile resolve（只接受已注册 ID，fail-closed）
- [ ] 任务行/响应回显冻结 profile/bundle
- [ ] 前端单图/批量/URL 三入口传 profile

## T8 RecognitionEndToEndVerticalSlice
- [ ] 样板照片真实识别（Web/API/Agent 同源）
- [ ] 任务历史/证据对账
- [ ] 0 检出/URL 失败/8091 停止 degraded 诚实返回

## T9 HomeCommandCenter
- [ ] 首页待办/审批/运行/异常/完成/笔记/健康全部来自 API
- [ ] 清除硬编码 200/19/19/项目 22 类数字

## T10 FutureDomainSlots
- [ ] planned 模块骨架注册（survey/geo/bi/finance 等）
- [ ] 移除 /biz/m3bars 假 BI
- [ ] planned 页诚实插槽

## T11 LocalStackRecoveryAndRunbook
- [ ] status/start/stop/restart/doctor 脚本（幂等、PID 精确、不启动训练）
- [ ] 冷启动验证实测

## T12 FullAutomatedVerification
- [ ] pytest hermetic（not host_mps）
- [ ] pytest host_mps
- [ ] npm typecheck + build
- [ ] SQLite/migration/四服务对账

## T13 BrowserHumanAcceptance
- [ ] 1440/1280/1024/768 四视口
- [ ] 登录/导航/首页/Agent/识别/planned/系统
- [ ] console/network/键盘/空错态

## T14 DocumentationAndFinalReconciliation
- [ ] 用户手册重写
- [ ] 运维 Runbook
- [ ] 模块与 Agent 开发指南
- [ ] Quick Start + Troubleshooting Matrix + API 示例
- [ ] 50 项最终报告

---

## 收口状态（2026-08-11 17:3x）

- T1–T14 全部完成；红测试 12→0，新增测试 13+16+10+11 全绿。
- hermetic 1173 passed/1 skipped/6 deselected；host_mps 6 passed；
  npm typecheck/build 零错误；SQLite integrity ok（30 迁移）。
- 四服务 bin/abos 冷启动实测通过；production 未切换；未启动训练。
- 遗留见 ISSUES EX-005/EX-006（不阻断本 Gate）。
- 最终状态：READY_FOR_NEXT_DOMAIN_PACK（FINAL-REPORT.md 50 项）。
