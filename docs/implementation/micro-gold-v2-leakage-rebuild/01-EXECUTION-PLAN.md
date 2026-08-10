# Micro-Gold V2 泄漏纠偏实施计划

> **For implementation agent:** Execute this plan node by node with TDD and fail-closed gates. Do not train, publish, delete history, or switch production.

**Goal:** 撤销项目 21 和 M4 v2 的错误独立性结论，建立统一来源身份门禁；仅在数据真实满足独立性时生成并导入 Micro-Gold V2，否则收口为可解释阻断态。

**Architecture:** 使用 Graph+Loop 的事件历史与当前投影分离模式。`ForbiddenIdentityIndex` 是数据独立性唯一领域服务；Micro-Gold 与 M4 holdout 构建器只消费冻结索引和版本化 manifest，不自行实现另一套泄漏判断。数据库保存不可变 supersession/审计事实，Cycle、Taskboard、Blackboard、Profile、Web 和 Supervisor 读取同一投影。

**Stack:** Python 3.11、SQLite、FastAPI、React/TypeScript、Label Studio API、pytest、Apple MPS/MLX（本轮只允许测试和既有权重只读评估）。

## Graph nodes

1. `BaselineAudit`：冻结 Git、进程、服务、DB、项目 21、M4 v2、现有 manifest 证据。
2. `Project21Supersession`：先写红测试，再追加失效事实和当前投影；项目 21 保留、退出活动入口。
3. `UnifiedForbiddenIdentityIndex`：TDD 建立版本化多键索引、来源适配器、缺失字段 fail-closed、账本与 hash。
4. `MicroGoldV2SamplingPolicy`：冻结 120/40/20/20 分层规则及来源组约束。
5. `MicroGoldV2BuilderTDD`：测试目录防覆盖、确定性、完整 manifest、hard/negative 证据、盲审字段隔离。
6. `MicroGoldV2LeakageAudit`：在真实资产上构建；身份不足或样本不足则停止并登记缺口。
7. `MicroGoldV2ManifestFreeze`：仅成功数据进入 staging→atomic publish；否则只发布审计报告，不发布数据集。
8. `LabelStudioV2Import`：仅成功后先导入 10 条验收批，验证再幂等放量；未过门禁不得建项目。
9. `M4HoldoutV3Builder`：消费相同 Forbidden Index，冻结候选分数与来源身份，不使用 `/tmp` 事实源。
10. `M4HoldoutV3LeakageAudit`：任何 QLoRA/M3/retriever/KB/协议集/Micro-Gold 同源即停止。
11. `M4ThreeVersionRealEvalV3`：仅 holdout 有效时执行 bounded smoke 和三版本同协议推理；否则保持阻断。
12. `EvaluationRegistryCorrection`：旧 0.828 追加降级事实，保留原报告；新证据另建版本。
13. `CycleTaskboardBlackboardConvergence`：事件 append-only、当前投影幂等更新，重启恢复。
14. `WebSupervisorAcceptance`：移除项目 21 活动入口，显示唯一下一步和真实阻断原因。
15. `FinalVerification`：Hermetic、host MPS、TS、Vite、SQLite、API/DB/Web、四服务和无训练/未切生产检查。

## Stop conditions

- 任一候选缺 `photo_id/original_sha/store/session/leakage_group/source_identity`：进入 `identity_unresolved`，不得纳入正式数据集。
- 不能证明 canonical38、hard 或 negative 真实性：不得用命名替代证据。
- Micro-Gold V2 不足 200 或少于 150 个独立来源照片：不导入 Label Studio，Gate=`MICRO_GOLD_REBUILD_BLOCKED_INSUFFICIENT_INDEPENDENT_DATA`。
- M4 V3 holdout 不满足规模或来源零重叠：不运行三版本评估；旧 0.828 保持 `EXPERIMENTAL_GROUP_LEAKED_EVALUATION`。
- 任何步骤不得改动 `prod_20260805_v5_r1`。

## Verification sequence

1. 新增测试先红后绿；相关模块定向测试。
2. 全量 hermetic 与 host MPS 分开执行。
3. `tsc --noEmit`、Vite build、SQLite integrity。
4. API/DB/Web/Label Studio 现场对账和浏览器 QA。
5. 检查无训练进程、production bundle 唯一 enabled、工作树只含本任务文件和既有受保护资产。

