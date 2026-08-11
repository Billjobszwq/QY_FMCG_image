# Agentic Business OS 可运营工作台 V3

更新时间：2026-08-12  
基线：`feat/nextgen-training-cycle-v2`，编写时现场 HEAD `47c01c43`。  
性质：本目录是下一轮唯一实施入口；只取代旧目录的“当前执行入口”地位，不删除任何历史证据。

## 目标

把目前“每个模块都有页面，但用户无法完成工作”的演示系统，改造成可由真实用户持续操作的 Agentic Business OS：

1. 首页能看到待办、日历、日程、进度、活动日志、系统资源和 Agent 提醒；
2. 主管 Agent 能查询事实、规划、委派、弹出界面并执行已批准命令；
3. 每个业务模块既能由 Agent 调用，也有完整人工操作路径；
4. 工作流可拖拽搭建、运行、暂停、恢复、审批、追踪证据和用量；
5. 客户、SKU、项目、地址、员工、问卷和角色可以由用户自行维护；
6. 所有批量数据均可下载 CSV/XLSX 模板、预检、导入和导出错误报告；
7. 使用一套 Work/Run/Event/Evidence/Usage 主线贯穿真实业务实验。

## 阅读顺序

实施 Agent 必须完整阅读，不得只读提示词：

1. `docs/GLOBAL_AGENT_ROUTING.md`（若存在）及仓库根目录/全局 `AGENTS.md`；
2. `docs/CODEX-PROJECT-HANDBOOK.md`；
3. `docs/implementation/agentic-business-os-domain-packs-v2/` 全部治理文档；
4. 本目录 `00` 至 `05`；
5. `ISSUES.md`、`DECISIONS.md`、`IMPLEMENTATION-LIST.md`、`STATUS.md`；
6. 最后执行 `AGENT-EXECUTION-PROMPT.md`。

## 文件地图

| 文件 | 用途 |
|---|---|
| `00-CURRENT-STATE-AND-ROOT-CAUSES.md` | 当前事实、重新打开的 Bug、为什么系统会自我卡住 |
| `01-TARGET-OPERATING-MODEL-AND-MODULES.md` | 目标产品结构、首页与 10 个模块的可操作要求 |
| `02-WORKFLOW-AGENT-RUNTIME-DECISION.md` | 可视化工作流、Agent/Skill/Prompt/知识库和开源选型 |
| `03-DATA-IMPORT-MANUAL-FALLBACK-AND-CONTRACTS.md` | 导入模板、人工备援、统一 ID/API/审计契约 |
| `04-IMPLEMENTATION-GRAPH-GATES-ACCEPTANCE.md` | 连续实施顺序、门禁、循环修复规则和完成状态 |
| `05-REAL-DATA-END-TO-END-UAT.md` | 用户下一轮真实客户/地址/问卷贯穿实验脚本 |
| `IMPLEMENTATION-LIST.md` | 唯一任务清单 |
| `ISSUES.md` | 问题台账 |
| `DECISIONS.md` | 冻结设计决定 |
| `STATUS.md` | 唯一 Gate 与现场状态 |
| `EXECUTION-LOG.md` | 追加式执行日志 |
| `AGENT-EXECUTION-PROMPT.md` | 可直接交给实施 Agent 的完整指令 |

## 当前 Gate

`OPERATIONAL_WORKBENCH_V3_NOT_STARTED`

旧报告的 `READY_FOR_USER_ACCEPTANCE` 已撤销。原因不是测试数量不足，而是首页、任务投影、工作流、Agent 和多个 Domain Pack 尚不能让用户独立完成真实工作。

