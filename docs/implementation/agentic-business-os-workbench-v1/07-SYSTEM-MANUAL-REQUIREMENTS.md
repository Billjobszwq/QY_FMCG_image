# 系统手册交付要求

## 一、必须交付三份手册

### 1. 用户使用手册

面向业务用户，至少包含：

- 系统是什么、不是什​​么；
- 登录、租户/客户/项目切换；
- 三级导航；
- 首页主管 Agent、待办、审批、笔记；
- 识别任务完整操作；
- 标注、数据、模型、工作流页面的业务用途；
- planned/degraded/blocked 含义；
- 结果、证据、导出和人工复核；
- 常见错误与下一步；
- 权限与高风险审批。

不得硬编码会变化的项目 ID、Gate、任务数和 production；通过“系统状态页面查看”引导用户。

### 2. 本机运维 Runbook

面向开发/运营，至少包含：

- Apple Silicon 与依赖检查；
- `status/start/stop/restart/doctor`；
- 8091/8092/8300/8400 的职责、日志和健康；
- DB backup/integrity/migration；
- 模型与 production 只读核验；
- 无训练进程核验；
- 冷启动演示；
- 服务失败、端口冲突、模型不可用、Label Studio 不可用、Agent provider 不可用的排障；
- 安全停止和恢复，不使用宽泛 kill。

### 3. 模块与 Agent 开发指南

面向后续 Agent，至少包含：

- 如何创建 Domain Pack；
- ModuleManifestV2 字段；
- Capability/Command/Query/Event/DataProduct 契约；
- AgentManifest、scope、memory、UIIntent；
- 如何注册一级/二级/三级 UI；
- 数据迁移和 tenant/project 边界；
- API、OpenAPI、客户端类型；
- Graph/Loop、checkpoint、human gate；
- 计费、审计、证据和健康；
- reference module 示例；
- 测试、版本、兼容、停用和升级。

## 二、手册形式

- 所有操作命令必须实际验证；
- 页面截图标注 route、版本和日期；
- 术语首次出现有中文解释；
- 每个流程包含“前置条件 / 操作 / 预期结果 / 失败处理”；
- 提供一页 Quick Start 和一页 Troubleshooting Matrix；
- Web 的“帮助”入口直接打开与当前模块对应的手册章节；
- OpenAPI 地址应为运行态发现，不写错 `/docs` 与 `/api/v1/docs`。

## 三、系统内帮助

- 顶栏有全局帮助；
- 每个页面有“本页怎么用”；
- Agent 能回答“这里能做什么”“下一步怎么做”，答案引用手册和实时状态；
- error/empty/blocked state 直接链接故障排查；
- 手册版本与平台版本关联，过期时提示而不是静默展示。
