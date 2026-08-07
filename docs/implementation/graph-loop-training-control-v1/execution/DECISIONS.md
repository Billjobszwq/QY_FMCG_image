# Graph+Loop Training Control V1 · DECISIONS

## D1 assisted proposal 唯一正式写入口 = 平台识别能力（8091 cascade_v3 prod bundle）
- 背景：8400 degraded 唯一原因是 LS ML backend（8301，src/ls_ml_backend）不可用；
  任务书要求二选一，不得保留两条不一致的 proposal 写链。
- 决定：Task 4 的 proposal 回填经 8091 生产 bundle 推理 + LS predictions API append-only 写入；
  ML backend（8301）声明 legacy/disabled：健康探测标为 disabled（不探测、不计 degraded），
  保留代码不删，不再作为正式 proposal 来源。
- 否决替代：恢复受治理 ML backend（需要第二套模型加载链与 MPS 争抢，违背单写入口原则）。

## D2 历史 4 条 dry-run 失效方式 = 追加式 supersession 账本
- training_run 历史行不改不删；新增 `training_run_supersession_v1`（migration 021）
  追加记录 run_id + reason + superseded_by + git_commit；approve/enqueue 一律先查账本拒绝。

## D3 错误优先级冻结 = 计划有效性 → 授权 → 硬件 G0
- approve/enqueue：run 存在与状态校验最先；其次 training_authorized flag + IAM
  （AuthorizationRequired）；最后硬件 G0。理由：授权是人工决策门，必须先于机器
  环境结论暴露给人；G0 仍 fail-closed 且在真实提交路径重跑，不被降低。
- launch 路径（enqueue 后 Worker 实际启动前）必须重跑真实 G0，禁用 dry-run 时的旧报告启动。

## D4 测试分层 = hermetic 默认 + host_mps marker
- 默认 suite 经可注入 HardwareGateProvider 运行，不依赖宿主 MPS/sysctl 权限；
- 真实 MPS 探针测试标 `@pytest.mark.host_mps`，默认 `-m "not host_mps"` 排除，
  独立命令执行并单独报告；两类结果都进最终报告。

## D5 新 lineage = fmcg_nextgen_v1，parent 只允许 public/foundation base
- `.models/sku_*`、旧 classifier、E2、prod bundle 权重禁作 parent/resume/EMA/optimizer/teacher；
- proposal_teacher_bundle 是独立字段（仅产 provisional proposal），与 parent 结构不可互换。
