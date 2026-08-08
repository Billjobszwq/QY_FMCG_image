# 04 多 Agent / 黑板 / 记忆（通用内核，不绑定 FMCG）

## Agent Kernel + AgentManifest
注册字段：agent_id/version/domain/capability scopes/command schemas/allowed data scopes/
memory policy/UI slots/Graph templates/risk level/approval rules/billing unit/health endpoint。

## 四 Agent
- Supervisor：目标→Graph 拆解→调领域 Agent→汇总证据→待办/阻塞→命令预览→UIIntent；
  只读/低风险可逆自动执行；发布/生产/删除/客户数据写必须人工。
- ModelOps：LS/Registry/过滤/SAM/Snapshot/计划/租约/Run/评估/Candidate/发布提案；
  可发起有界实验，不可切 production。
- Data Steward：质量/血缘/查询/审计/纵向打通/横向关联/口径/保留；默认只读客户数据；
  更正走 DataCorrection command+审批+审计。
- Workbench：任务板/黄色笔记抽屉/导航/待办/阻塞/已解决/运行/命令预览/UIIntent；
  UIIntent 仅限 navigate/open_panel/filter/highlight/compare/pin_card/show_evidence，
  禁注入任意 HTML/JS。

## Shared Blackboard（typed append-only）
事件类型：Question/Finding/Decision/Task/Blocker/EvidenceRef/DataQueryResultRef/
ModelRunRef/PendingCommand/Approval/Resolution/Note。
卡片投影：tenant/project/owner/watchers/priority/status/due/version/correlation_id/
graph_run_id/linked entities/evidence refs/created_by/resolved_by/acceptance。
Agent 只追加自己的结论/证据/命令提案，不覆盖他人或人工结论。

## Memory Hierarchy
L0 scratchpad（不持久）/ L1 Graph checkpoint / L2 Project / L3 Tenant（ACL）/
L4 Global（不含客户原始数据）/ Archive（不可变审计）。
每条持久记忆：source/evidence/scope/ACL/confidence/valid_from/valid_to/retention/
version/supersedes/entity links。

## Context Index
metadata filter + entity graph + full-text + vector；向量仅为可重建派生物，非事实源。
