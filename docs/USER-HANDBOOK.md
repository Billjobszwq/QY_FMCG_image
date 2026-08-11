# 统一工作台 · 系统使用手册

> **临时手册说明（2026-08-11）：** 本文件记录当前过渡版界面，不能证明系统已经完成。现场审计发现部分页面、导航、Agent 控制和识别 Profile 尚未真正贯通，且会变化的项目 ID/任务数被硬编码。正式可操作手册将按 [`agentic-business-os-workbench-v1/07-SYSTEM-MANUAL-REQUIREMENTS.md`](./implementation/agentic-business-os-workbench-v1/07-SYSTEM-MANUAL-REQUIREMENTS.md) 重建；实施入口见 [`AGENT-EXECUTION-PROMPT.md`](./implementation/agentic-business-os-workbench-v1/AGENT-EXECUTION-PROMPT.md)。

> 定位：Agent 驱动的智能经营操作系统（非 SaaS）。
> 模块：数据仓库 / 问卷 / 地理分析 / 线库规划 / BI 报表 / 数据告警 /
> 数据深度对话 / 图像识别 / 工作流编排 / 财务对账 / 策略分析。
> 每个一级模块 = 一个色系 + 一个 Agent；二级为模块内功能页签；
> 三级为页内具体操作。新模块通过 manifest 注册扩展，不改底层数据架构。

## 0. 登录
- 工作台 http://127.0.0.1:8400 （admin / 见 .env 或管理员分发）
- Label Studio http://127.0.0.1:8300 （admin@local / 见 .env）

## 1. 总览（01 紫）
主页 = 系统定位 + Gate + Cycle + micro-gold + Agent 矩阵 + 候选模型状态。
右下紫色 ✦ = 主管 Agent 对话（DeepSeek 驱动，可问进度/候选/缺口，
可下命令创建计划，高风险操作需批准）。

## 2. 图像识别（02 蓝）
- 拖拽/点击上传货架照片 → 返回商品框叠加图 + SKU + 置信度 + needs_review；
- 批量识别 / URL 识别计入任务历史；
- 模型选择卡：production_legacy 可用；候选模型待 micro-gold 人工金标准后解禁；
- 适用场景：全场景货架图（近景单品图会 fail-closed 返回 0，属预期）。

## 3. 标注中心（03 绿）
- LS 项目 22 = micro-gold 唯一有效人工入口（200 条）；
- 四步操作：打开任务 → 点区域选 SKU（可搜索）→ 标状态
  （matched/unknown/conflict/new_packaging_*/bad_crop/background）→ Submit；
- 主审后确定性抽 40 条二盲，分歧仲裁 → human_final → gold_verified；
- 项目 21 已失效（SUPERSEDED），禁止审核。

## 4. 数据仓库（04 黄）
数据资产 / 质量门禁 / 血缘 / forbidden identity index（泄漏门禁）。

## 5. 模型训练（05 橙）
训练计划 / 候选模型 / 独立评估报告 / 资源租约。训练需计划+授权+门禁。

## 6. 工作流（06 薰衣草）
n8n 风格画布：数据→SAM→训练→评估→人工金标准→服务；节点状态实时。

## 7. 经营智能（07 红）
BI/告警/财务/地理/线库/问卷/深度对话/策略 —— 模块矩阵，
每个模块一个 Agent，后续逐个定义；新模块注册不改库。

## 8. 系统（08 绿）
服务健康 / Graph Runs / API 文档（/docs · /api/v1/openapi.json）/
模块注册表（/api/v1/modules）。

## 9. API 预留
- 所有模块 API 前缀 /api/v1/<module>/；新模块注册即得前缀；
- OpenAPI：http://127.0.0.1:8400/docs；
- Agent API：/api/agent/v1/*（sessions/chat/commands）；
- 识别契约：POST /v2/recognize（8091）/ Web/API/Agent 同 Profile 同 Service。

## 10. 自我迭代
系统基于 Agent + Workflow：黑板事件/记忆/Graph checkpoint 持久化，
Agent 可基于证据提议计划，人工批准后执行；每轮执行沉淀为文档与记忆。
