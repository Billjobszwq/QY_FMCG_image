# Graph+Loop Training Control V1 · ISSUES

## GLTC-ISSUE-001（Task 0 复现分类）Codex 受限环境 10 个 MPS 测试失败
- 状态：CLASSIFIED（环境限制）+ 待 hermetic 固化
- 事实：普通 Terminal 全量 914 passed 全绿；Codex 受限进程中
  `torch.backends.mps.is_available()==False` 且 `sysctl hw.memsize` 不可读，
  host 探针类测试因此失败。产品逻辑无缺陷，但默认 suite 依赖宿主权限属于设计缺陷。
- 处置：GLTC-000（HardwareGateProvider 注入 + host_mps marker + 错误优先级契约）。

## GLTC-ISSUE-002 历史 dry-run 含禁用 CLI 参数
- 状态：CONFIRMED_OPEN
- 事实：training_run 4 行 dry_run 的 command 含 `--dataset/--budget-minutes`
  （当前 train_v1 CLI 已禁用）。
- 处置：追加式 supersession 账本（D2），禁批准/入队；不删历史行。

## GLTC-ISSUE-003 8400 degraded（ML backend 8301 不可用）
- 状态：CONFIRMED_OPEN → 决策 D1
- 处置：ml_backend 标 disabled（不探测不计 degraded）；proposal 正式写入口收敛到
  平台识别能力；8301 代码保留不删。

## GLTC-ISSUE-004 LS 项目 19 无 proposal
- 状态：CONFIRMED_OPEN（Task 4 处置）
- 事实：项目 19 全部 200 任务 predictions=0；设计要求接当前生产 bundle 追加 provisional proposal。
