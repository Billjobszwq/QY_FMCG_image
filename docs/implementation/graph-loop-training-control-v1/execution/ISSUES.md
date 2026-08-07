# Graph+Loop Training Control V1 · ISSUES

## GLTC-ISSUE-001（Task 0 复现分类）Codex 受限环境 10 个 MPS 测试失败
- 状态：REOPENED。2026-08-08 fresh 仍有 8 个默认 suite 失败，说明分层未完全固化。
- 事实：普通 Terminal 全量 914 passed 全绿；Codex 受限进程中
  `torch.backends.mps.is_available()==False` 且 `sysctl hw.memsize` 不可读，
  host 探针类测试因此失败。产品逻辑无缺陷，但默认 suite 依赖宿主权限属于设计缺陷。
- 处置：GLTC-000（HardwareGateProvider 注入 + host_mps marker + 错误优先级契约）。

## GLTC-ISSUE-002 历史 dry-run 含禁用 CLI 参数
- 状态：CLOSED_BY_SUPERSESSION（migration 020；历史不可变保留）
- 事实：training_run 4 行 dry_run 的 command 含 `--dataset/--budget-minutes`
  （当前 train_v1 CLI 已禁用）。
- 处置：追加式 supersession 账本（D2），禁批准/入队；不删历史行。

## GLTC-ISSUE-003 8400 degraded（ML backend 8301 不可用）
- 状态：CLOSED_BY_DECISION_D1
- 处置：ml_backend 标 disabled（不探测不计 degraded）；proposal 正式写入口收敛到
  平台识别能力；8301 代码保留不删。

## GLTC-ISSUE-004 LS 项目 19 无 proposal
- 状态：CLOSED_WITH_RESIDUAL_MANUAL_CASES
- 事实：200 tasks 中 187 有 prediction，186 有 taxonomy，13 `no_proposal`；1 个低置信框需人工 SKU。blind 20 仍零泄漏。

## GLTC-ISSUE-005 V2 Dataset API 固定空 rows
- 状态：CONFIRMED_OPEN
- 影响：build 端点不读取真实 gold/坐标/质量事实，不能构建真实 snapshot。

## GLTC-ISSUE-006 Graph 仅进程内状态
- 状态：CONFIRMED_OPEN
- 影响：API/Worker 未以持久化 Graph 为唯一状态源，服务重启不能恢复真实控制图。

## GLTC-ISSUE-007 四 Lane 缺写控制面
- 状态：CONFIRMED_OPEN
- 影响：缺 V2 plan/approve/launch/safe-stop/resume/artifact/evaluation/candidate API；Web V2 仅只读。

## GLTC-ISSUE-008 Recognition 无 Profile 选择
- 状态：CONFIRMED_OPEN
- 影响：五个入口固定 adapter；页面 bundle 文案过期，无法审计选择的模型链。

## GLTC-ISSUE-009 工作树交付描述不准确
- 状态：DOCUMENTED
- 事实：除 4 个受保护目录外，还有 3 个 backfill JSON 和 1 张 Web QA 截图未跟踪；禁止删除，应分类保留。
