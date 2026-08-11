# 当前状态与根因

## 结论

现有系统不是“没有代码”，而是“代码和页面很多，但没有一个统一的用户工作面”。此前按 API 数量、测试数量和垂直样板判定完成，忽略了用户能否从首页开始，不接触数据库和终端，连续完成一项真实业务。

## 已经可以复用

- FastAPI + React 统一 Web Shell；
- SQLite 迁移、客户隔离、CSRF/session 和追加式审计基础；
- 识别任务及 profile/trace/evidence/usage 详情；
- BusinessRun/WorkItem/Event/Evidence/Usage 控制面 schema；
- Workflow 定义生命周期和基础节点执行器；
- 问卷、BI、外勤、财务的首个真实纵向样板；
- Module/Agent/Capability Manifest 与 API/UI 路由投影；
- Label Studio 及历史训练/模型制品。

## 为什么会“自我卡住”

1. **以模块完成代替任务完成**：每个模块有页面，不代表页面之间能传递同一客户、项目、任务和证据。
2. **以测试通过代替用户可用**：测试验证了函数和 API，却没有验证用户能否找到入口、填写配置、看到输出并继续下一步。
3. **平行事实源**：旧 WorkItems、Taskboard、WorkItemV2 和业务表分别表达“当前任务”，主管无法得到唯一答案。
4. **Manifest 过度乐观**：注册即 healthy、声明 live 即 live，缺少最小业务 E2E 健康探针。
5. **Agent 只有身份没有运行时**：有 Agent 名称和 allowlist，但没有可编辑配置、工具调用循环、知识检索、预算和失败接管。
6. **Domain Pack 只做样板**：问卷、BI、外勤和财务各跑通一次固定 fixture，却没有给用户创建第二个实例的工具。
7. **UI 按开发者对象组织**：用户看到 profile、artifact、manifest 和 JSON，却看不到“我下一步要做什么”。

## 重新打开的事实问题

- `workflow.succeeded` 没被工作投影器识别；
- 首页聚合 API 没有消费 WorkItemV2；
- 成功 run 可能保留旧 error；
- BI 版本列表返回重复 latest；
- Supervisor/Domain Agent 的健康只代表注册存在；
- Workflow wait/parallel/join/agent 节点没有达到描述的运行能力；
- IAM 非平台用户多客户作用域只取第一项；
- `STATUS.md` 的现场 HEAD/表数/迁移曾长期滞后。

## 本轮范围边界

本轮要完成“真实数据 UAT 之前的可运营工作台”，不是一次性完成全部商业功能：

- 要完成真实 CRUD、导入、配置、运行、追踪和人工备援；
- 要让一个客户/项目/地址/问卷/外勤/识别/BI/Usage 场景端到端贯通；
- 不做完整会计、工资、税务、CRM 营销或海量云部署；
- 不启动长时间新模型训练；只把自主训练控制面和现有模型运行时做成可操作；
- 不删除历史数据库、任务、模型或训练证据。

