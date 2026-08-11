# Execution Log（append-only）

## 2026-08-11 16:0x · T0 BaselineAndSafetyAudit
- git：HEAD=7c2eab62，branch=feat/nextgen-training-cycle-v2，单 worktree；未跟踪资产登记在 IMPLEMENTATION-LIST（不碰）。
- 服务实测：8091(recognize)、8092(monitor)、8300(LS /health UP)、8400(composition serve) 全部在运行；/api/v1/health 聚合 healthy（recognize/monitor/label_studio 均 healthy）。证据 evidence/T0-services-probe.txt。
- 无训练进程（ps 仅 monitor/serve/recognize/yolo_backend 四个 python）。
- DB：integrity ok；63 表；agent_manifest_v1=4（supervisor/modelops/data_steward/workbench）；recognition_profile_def_v1=11；recognition_task=5；graph_run=8。
- production：CURRENT.json=prod_20260805_v5_r1（previous prod_20260804_v4_r2）。
- 确认 P0 问题现场存在：App.tsx 登录 kicker `qy · sku recognition`、footer `SKU 识别系统`+硬编码 production；modules_api.MODULES 第二份常量；/biz 四路由渲染同一 BizIntel；supervisor.py 硬编码过期回答 + Path 未导入 + M4 分支前置吞后续；Recognition.tsx profile 仅 local state；AgentChat 不消费 ui_intents/commands；styles.css 变量缺口。

## 2026-08-11 16:1x–17:3x · T1–T14 实施（详见 git 5bb41228..收口）
- T1：12 红测试复现全部 P0/P1。
- T2：/api/v1/platform/identity 单一身份；登录/顶栏/footer/OpenAPI/8092 标题去 SKU。
- T3：ModuleManifestV2 + ModuleRegistry（fail-closed）+ module_catalog（10 模块）
  + modules_api 纯投影 + reference.echo（/api/v1/reference/echo 实测 ok）。
- T4/T5：tokens.css/shell.css + AppShell；一级=Registry、二级=真实路由
  （vision 六条等）、三级=页内操作；旧路由 Navigate 重定向；删除
  AgentChat/SupervisorDrawer/ModuleTabs/BizIntel/旧 Recognition/Workflow 孤儿件。
- T6：Supervisor 重写（QueryTool 实时事实、统一契约、UIIntent 白名单、
  委派回执、高风险拒绝）；agent_runtime_api 增加 on_approved 钩子；
  前端 SupervisorWorkspace 消费 intents/commands/evidence/delegations。
- T7：迁移 030（任务行冻结契约）；upload/url 必带 profile/tier/source；
  服务端 resolve fail-closed；响应回显。
- T8：四入口实测（single 6 SKU / batch 8 SKU / url 2 SKU / agent 6 SKU），
  幂等重放、disabled 拒绝、8091 停止 degraded+恢复。
- T9：Home 指挥中心全实时数据；T10：planned 诚实插槽、m3bars 404。
- T11：bin/abos 五命令实测；watchdog 与 grep/探测两处 bug 修复后冷启动通过。
- T12：hermetic 1173/1s/6d、host_mps 6、typecheck/build 零错误、DB/服务对账。
- T13：浏览器 12 场景；修复 rowid bug/面板遮挡/按钮终态/溢出/对比度 5 项。
- T14：USER-HANDBOOK 重写 + OPERATOR-RUNBOOK + MODULE-AGENT-DEV-GUIDE。
