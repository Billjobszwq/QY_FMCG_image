# Graph+Loop Training Control V1 · ACCEPTANCE

> 验收门对应 `03-ACCEPTANCE-GATES.md` 的 G0–G9。每项记录证据路径与判定。

## G0 基线可信度
- [x] branch/HEAD/工作树/服务/DB/bundle/进程实时记录（EXECUTION-LOG T0）
- [x] 普通 Terminal 全量 914 passed（hermetic 分层待 GLTC-000 固化）
- [ ] host_mps suite 独立结果
- [x] 四个受保护未跟踪目录未触碰

## G1–G8
- 见 IMPLEMENTATION-LIST 各 Task 的验收证据栏；完成后逐项回填。

## G8 机器侧完成门
- 满足 G0–G7 后仅可声明：`FRAMEWORK_READY_AWAITING_GOLD_AND_TRAINING_AUTHORIZATION`

## G9 真实训练门
- 本轮默认不执行；需 human gold + DatasetSnapshot 冻结 + 用户显式批准具体 TrainingPlan。
