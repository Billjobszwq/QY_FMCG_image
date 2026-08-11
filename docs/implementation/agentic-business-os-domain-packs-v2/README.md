# Agentic Business OS · 连续任务底座与 Domain Packs V2

> 状态：设计与执行任务书已完成，尚未授权 Agent 修改业务代码。
>
> 现场基线：2026-08-11，`feat/nextgen-training-cycle-v2`，HEAD `e5c4236d`。
>
> 范围：任务连续性、智能工作流、账号与权限、主数据、问卷、BI、位置外勤、财务计费，以及现有 UI/识别链的收口。

## 1. 本轮结论

当前系统已经有模块注册、Graph+Loop、Agent 清单、识别 API 和统一外壳，但还不是一套“能够连续运转的智能业务操作系统”。主要原因不是页面数量不足，而是运行事实被拆成了多套互不连接的记录：

- 首页和主管 Agent 读取 `/api/v1/workitems`，仍将旧 250 项审核显示为当前待办；
- `/api/v1/taskboard` 保存的是较新的训练投影，但首页请求后直接丢弃；
- 识别任务、Graph Run、Agent Command、人工任务和 Usage Ledger 没有统一 `work_id/run_id/correlation_id`；
- Workflow 页面只是运行列表和固定 Graph 启动器，不是可组合的工作流搭建器；
- 模块 Manifest 能生成导航，却不能自动绑定真实 Capability、页面和执行契约；
- Supervisor 主要是关键词路由器，还不能规划、调用工具、追踪执行并闭环。

因此实施顺序必须是：

1. 修复 P0 UI 与任务事实源断裂；
2. 建立统一 Work/Event/Usage 控制平面；
3. 建设原生 Workflow Studio；
4. 建立 IAM 与主数据；
5. 再依次插入问卷、BI、位置外勤、财务 Domain Pack。

不得在任务主键、权限、客户/项目作用域和计量账本尚未统一时，大规模堆叠业务页面。

## 2. 架构判断

系统核心继续是原生 Graph+Loop，不把 n8n 或 Dify 变成第二个系统核心：

- ABOS 保存唯一工作流定义、版本、权限、审批、运行状态、事件、证据和计费；
- n8n 是可选的外部连接器执行适配器；
- Dify 是可选的 AI/RAG/LLM 子流程适配器；
- 客户在 ABOS 的 Workflow Studio 中操作，不直接依赖第三方 UI；
- 外部引擎故障或替换时，ABOS 的业务定义和历史不丢失。

详见 [02-WORKFLOW-STUDIO-AND-N8N-DIFY.md](02-WORKFLOW-STUDIO-AND-N8N-DIFY.md)。

## 3. 文件导航

| 文件 | 用途 |
|---|---|
| [00-LIVE-AUDIT-AND-BUG-LIST.md](00-LIVE-AUDIT-AND-BUG-LIST.md) | 现场测试、Bug、断链和根因 |
| [01-UNIFIED-WORK-EVENT-USAGE-CONTROL-PLANE.md](01-UNIFIED-WORK-EVENT-USAGE-CONTROL-PLANE.md) | Work/Event/Usage/证据统一底座 |
| [02-WORKFLOW-STUDIO-AND-N8N-DIFY.md](02-WORKFLOW-STUDIO-AND-N8N-DIFY.md) | 智能工作流与第三方边界 |
| [03-DOMAIN-PACKS-SPEC.md](03-DOMAIN-PACKS-SPEC.md) | IAM、主数据、问卷、BI、位置外勤、财务规格 |
| [04-UI-UX-RECOVERY-PLAN.md](04-UI-UX-RECOVERY-PLAN.md) | 人类友好 UI、信息架构和响应式验收 |
| [05-IMPLEMENTATION-GRAPH-GATES-ACCEPTANCE.md](05-IMPLEMENTATION-GRAPH-GATES-ACCEPTANCE.md) | 分阶段实施、门禁和验收 |
| [AGENT-EXECUTION-PROMPT.md](AGENT-EXECUTION-PROMPT.md) | 可直接交给实施 Agent 的完整提示词 |
| [STATUS.md](STATUS.md) | 当前状态、决定和未关闭项 |

## 4. 权限边界

本轮 Codex 只做了只读审计和文档设计，没有修改业务代码、数据库 schema、运行配置或模型；没有启动训练、切换 production、merge、push 或 deploy。

实施 Agent 必须把“修复现有连续性”与“新增 Domain Pack”拆成独立 Gate。任何阶段未通过，不得用假数据、占位按钮或静态图表宣称完成。
