# Graph+Loop Training Control V1 · ACCEPTANCE

> 验收门对应 `03-ACCEPTANCE-GATES.md` 的 G0–G9。每项记录证据路径与判定。

## G0 基线可信度
- [x] branch/HEAD/工作树/服务/DB/bundle/进程实时记录（EXECUTION-LOG T0）
- [ ] 默认 hermetic suite 真正全绿（fresh 仍有 8 个宿主 MPS 耦合失败）
- [x] 交付报告提供 host_mps 5 passed；新周期启动前需现场重验
- [x] 四个受保护未跟踪目录未触碰

## G1–G8
- [x] 契约、迁移、旧模型隔离、proposal、Worker 原语和只读 Web 投影已实现。
- [ ] Dataset API 从真实事实源读取，而不是固定 `rows=[]`。
- [ ] Graph 状态持久化并与 API/Worker 使用唯一写事实源。
- [ ] 四 Lane 计划/批准/启动/停止/恢复/制品/评估 API 与 Web 可真实操作。
- [ ] Recognition Profile 在 Web/API/Agent 五入口同口径。

## G8 机器侧完成门
- V1 只能声明：`V1_CONTRACT_BASELINE_COMPLETE`。完整机器门转由 V2 目录验收。

## G9 真实训练门
- 本轮默认不执行；需 human gold + DatasetSnapshot 冻结 + 用户显式批准具体 TrainingPlan。
