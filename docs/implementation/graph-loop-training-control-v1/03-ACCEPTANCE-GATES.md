# 验收门与停止线

## G0 基线可信度

- 当前分支/HEAD/工作树、服务、DB、bundle、进程已实时记录；
- 全量测试在普通 Terminal 与 hermetic 环境分别有证据；
- MPS host test 不再污染默认单元测试；
- 不碰四个受保护未跟踪目录。

## G1 旧模型隔离

- 所有现有模型 hash inventory 完整，无删除、移动、覆盖；
- `prod_20260805_v5_r1` 继续 serving；
- nextgen plan 传入旧 checkpoint/resume/EMA/optimizer 时 fail-closed；
- proposal teacher 与 training parent 字段不可混用；
- production switch=false。

## G2 标注和过滤闭环

- 项目 19 proposal 可见、canonical、可修改、可追溯；
- 项目 20 prediction/meta 泄漏为 0；
- 模型零检出不删除任务；
- 质量四级结论、证据、人工覆盖和误拒绝抽检可在 Web 查看；
- proposal 不进入 gold，blind 不被回填。

## G3 四数据集

- D1–D4 各自 immutable manifest、hash、builder、split、exclusion ledger；
- active protocol/frozen/rq_v1/model-only proposal 命中为 0；
- 派生 crop 与原图 split 一致；
- D3 无 mask gold 时 trainable=false；
- D4 CandidateSet 构造不接收 GT，registry escape 可审计。

## G4 Graph+Loop 控制面

- 四 lane 使用同一 TrainingControlGraph，不复制四套状态机；
- 人工 approval、safe stop、failure、evaluation、publish hooks 可恢复重放；
- Agent 无任意 SQL/shell/文件写权限；
- 状态机非法跃迁全部拒绝并写审计。

## G5 Worker 与 Apple 资源

- heavy accelerator lease 并发上限 1；
- MPS/MLX 冲突提交被拒绝；
- G0 在 Worker 实际环境重跑；
- PID/heartbeat/log/progress/exit/lease 可对账；
- safe stop 不伪造 cancelled；
- 8091/8400/8300 健康保护和 swap/memory/disk 停止线有效。

## G6 统一 Web

- 首页明确隔离当前 production legacy 与 nextgen；
- 四 lane 均能查看 readiness、blocker、snapshot、计划、进度、日志、制品和评估；
- 生成计划、批准、启动、停止、发布的算力和权限语义清楚；
- 数据、标注、训练和 Graph run 可通过 ResourceRef 相互跳转；
- 页面刷新、多标签页和重复点击不产生重复 Job。

## G7 测试与恢复

- 默认 suite 全绿；host/integration suite 有独立结果；
- TypeScript、Vite build、API contract、浏览器 QA 全绿；
- SQLite integrity=ok，备份可读；
- Worker 崩溃、服务重启、MPS 不可用、磁盘不足、输出目录已存在、LS 不可用均有演练；
- 历史表、模型、任务和审核记录数量前后一致。

## G8 机器侧完成门

满足 G0–G7 后只可声明：

```text
FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION
```

此时允许用户在 Web 中查看四条训练通道并准备计划，但启动按钮应根据真实 blocker 保持禁用。

## G9 真实训练门（本轮默认不执行）

每次训练必须单独满足：

- 对应 lane 的 human gold 数量与质量线；
- DatasetSnapshot 冻结且 hash 已批准；
- 实验假设、单变量、预算、epoch、停止线；
- Apple G0 和资源租约；
- 用户/管理员对具体计划的显式批准；
- 无活动重训练冲突；
- candidate-only、production switch=false。

## 立即停止条件

- 发现旧模型被用作 nextgen parent/resume；
- blind 项目出现 prediction 或模型 meta；
- frozen/active protocol/rq_v1 进入训练 snapshot；
- 训练未授权却产生真实重计算进程；
- MPS/MLX 同时持有 heavy lease；
- 输出覆盖既有数据集、模型或日志；
- gold 被 proposal/模型结果直接写入；
- production bundle 被切换；
- SQLite integrity 失败或历史记录被删除/改写。
