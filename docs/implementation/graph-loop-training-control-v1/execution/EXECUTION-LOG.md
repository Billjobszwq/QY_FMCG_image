# Graph+Loop Training Control V1 · EXECUTION-LOG

## 2026-08-08 T0 现场基线复核（Task 0）

- Git：HEAD=`c1d1d6fe5980b84bfd85ec851dd7194936205200`（与任务书基线一致），
  分支 `feat/unified-workbench-training-readiness`；工作树仅 docs 变更（用户提供
  的任务书目录与 handbook/README/CURRENT-LOGIC-CHAIN 修订）+ 4 个受保护未跟踪目录。
- DB：`.platform/platform.sqlite` PRAGMA integrity_check=ok；schema_migrations 至
  019_review_queue_ledger_v1；training_run=4（全部 dry_run，含 `--dataset/--budget-minutes`）；
  job/job_attempt 表存在。
- Bundle：`.models/bundles/CURRENT.json` → `prod_20260805_v5_r1`（previous=prod_20260804_v4_r2）。
- 测试（普通 Terminal）：全量 **914 passed, 1 skipped**（21.6s）——无 MPS 失败；
  Codex 受限环境 10 失败归类为宿主探针环境限制（GLTC-ISSUE-001），仍需 hermetic 固化。
- 服务：8091 /v2/health ok（cascade_v3，prod_20260805_v5_r1）；8092 /api/live 200；
  8300 LS 302（存活）；8400 /api/v1/health degraded——唯一非 healthy 项为 ml_backend
  （127.0.0.1:8301 不可用），recognize/monitor/label_studio/omlx 均 healthy。
- 训练进程：无 YOLO/classifier/SAM/Qwen 训练进程（仅 omlx-server 与 8092 monitor）。
- 人工链现状：rq_v2 active 250；LS 项目 19（200）predictions=0 / 20（50）零 prediction；
  gold_region_v1=0；Gate=AWAITING_HUMAN_ACCEPTANCE（project-logic-chain-v3）。
- 源码侦察：`src/platform/{api,jobs,worker,kernel,data,model_runtime}`、
  `src/modules/{training_gov,fmcg,labeling,system_health}`、`src/composition/serve.py`、
  `src/training/vlm/`、`src/ls_ml_backend/`；training_gov service 的
  `_require_g0()` 先于授权校验（错误优先级待冻结，D3）。
- 建立 execution/ 账本 6 文件（本目录），只追加不覆盖。

## 2026-08-08 T0-fix（GLTC-000 实现）

- 红测试 11 条（tests/platform/test_gltc000_baseline_fixes.py，commit "test: reproduce
  training control baseline gaps"）→ 全绿。
- 修复：
  1. 错误优先级冻结（D3）：start_training/approve_plan/enqueue 顺序 = 计划有效性
     → supersession → training_authorized flag → IAM → G0；enqueue 重跑真实 G0
     （launch 禁信旧报告）。
  2. HardwareGateProvider 注入（D4）：TrainingGovernanceService(hardware_gate=...)；
     `_resolve_gate()` 晚绑定默认真实 run_mps_g0；mock 仅限测试注入。
  3. legacy dry-run（D2）：migration 020 `training_run_supersession_v1`（触发器禁删改）+
     store.supersede_training_run/is_training_run_superseded；
     `scripts/mark_legacy_training_runs.py` 真实执行：备份
     `.platform/backups/platform_before_legacy_run_supersession_20260807T165110Z.sqlite`
     （integrity ok）→ 4/4 条含 `--dataset/--budget-minutes` 的 dry_run 追加标记
     reason=cli_args_removed，superseded_by=training_control_v2；历史行未改；
     证据 `.platform/training_run_legacy_supersession.json`；幂等（证据存在即拒绝覆盖）。
  4. health disabled（D1）：ServiceSpec.disabled；ml_backend legacy/disabled 不探测；
     aggregate 忽略 disabled；8400 graceful 重启后 /api/v1/health=**healthy**
     （recognize/monitor/label_studio/omlx healthy，ml_backend disabled）。
- 测试分层（D4）：pyproject addopts `-m 'not host_mps'` + markers；
  test_umt005 TestG0RealChecks 标 host_mps。
  默认 hermetic suite：**920 passed, 1 skipped, 5 deselected**；
  host suite（普通 Terminal，AC 电源）：`pytest -m host_mps` **5 passed**。
- 全量（分层后）：920 + host 5 = 925 口径全绿；分层前一次性全量 925 passed。
