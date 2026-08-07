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

## 2026-08-08 Task 1–11 实施记录

- **Task 1**（commit "feat: freeze four-lane v2 contracts..."）：
  `src/modules/training_control/{contracts,vocabulary}.py`：TrainingLane 冻结四通道、
  PlanV2 lineage（parent 只允 public: base；teacher 与 parent 结构分离）、
  18 态状态机（无 CANCELLED 捷径）、13 Hook、Event/Artifact/Lease/Snapshot 契约；
  migration 021（training_plan_v2/training_run_v2/training_event_v1/
  training_artifact_v1/resource_lease_v1，事件与 artifact 触发器禁删改）。24 测试绿。
- **Task 2**（commit "feat: isolate legacy models..."）：`legacy.py` 只读 inventory +
  分类 + LegacyInferenceCapability（仅 recognition/assisted_proposal/baseline）；
  migration 022 legacy_model_registry_v1（禁删改）。真实执行
  `scripts/register_legacy_models.py`：备份 `.platform/backups/platform_before_legacy_registry_20260807T165*`
  （integrity ok）→ 14 模型登记（prod_20260805_v5_r1=production_legacy，
  sku_v7_sam=experimental_ended，其余 historical）；文件零移动；
  证据 `.platform/legacy_model_inventory.json`（含逐权重 sha256）。
- **Task 3**（commit "feat: dataset factory..."）：`src/modules/dataset_factory/service.py`：
  共同准入（human_final/gold_verified；rq_v1/frozen/model-only 拒入）、
  五键 split 守卫、staging→原子发布、exclusion ledger/quality histogram/
  source hashes/manifest hash、D3 无 mask gold 只 calibration、
  D4 build_candidate_set 签名禁 GT 不足 k 不补。14 测试绿。
- **Task 4**（commit "feat: connect assisted proposals..."）：
  修复 LS 分页（尾斜杠端点 + 末页 404 容忍）；`_is_assisted` 识别 diag_v2_assisted、
  blind 永不进入；零检出标 no_proposal（幂等）。真实回填：
  dry-run 200/200 → apply **added=1125 predictions / errors=0**（200 任务，
  186 有 taxonomy 建议 SKU，13 零检出 no_proposal）；
  model_version 唯一 `legacy.recognition.v2@cascade_v3@visible-sku-v2`；
  项目 20 全量 50 任务 **prediction=0、模型 meta=0**；
  proposal 未写 gold_region（gold 仍 0）。
  审计 `reports/backfill_visible_sku/apply_20260808_011153.json`。
- **Task 5**（commit "feat: four lane adapters..."）：四 adapter 统一接口；
  参数白名单、目标目录防覆盖、VLM 禁 Ollama 量化 base、segmenter 无 mask gold
  拒 train、结构化 TrainingEventV1、safe-stop 只发 stop_requested。11 测试绿。
- **Task 6**（commit "feat: training control graph..."）：TrainingControlGraph
  （非法跃迁拒绝+审计）、HookRegistry（13 hook 只推进合法状态、人工 gate
  checkpoint 可 restore 回放）、AgentCommandGate（白名单；approve/launch/publish
  仅人类）。8 测试绿。
- **Task 7**（commit "feat: reliable worker..."）：ReliableWorker：提交重跑 G0、
  heavy lease 并发 1/MPS-MLX 互斥（失败回滚无残留）、冻结 env/command/data/code/
  config hash、PID/heartbeat/attempt、safe-stop 证据链（无进程退出证据不得写终态）、
  orphan 恢复（PID 不在/心跳过期→FAILED+释放租约）。7 测试绿。
- **Task 8**（commit "feat: unified training control api..." +
  "fix: mount ... via composition root"）：lanes/readiness/overview/legacy-models/
  runs-v2 只读投影 + datasets/{lane}/build（session+CSRF）。依赖方向修复：
  router 移至 src/modules/training_control/api.py，经组合根注入
  （架构守卫 test_platform_does_not_import_domain_modules 绿）。
- **Task 9**（commit "feat: unified web training console..."）：
  TrainingControl.tsx（当前生产 Legacy 卡与 nextgen 四 lane 卡视觉隔离、blocker
  中文化、按钮算力/权限语义、租约与 gold 投影、旧模型账本折叠区）；
  Training.tsx 原单 YOLO 区降为 Legacy 折叠区。tsc 干净、vite build 成功。
- **Task 10**（commit "feat: freeze lane evaluation metrics..."）：
  LANE_MIN_METRICS 四 lane 冻结；candidate 必须 frozen_set_hash+error ledger+晋级门；
  production_switch 恒 False。5 测试绿。
- **Task 11**（commit "test: verify end-to-end four-lane control chain..."）：
  端到端链 smoke（factory→adapter→graph→worker→evaluation，全程 mock G0 无真实训练）；
  故障演练覆盖：worker 崩溃 orphan 恢复、目标目录已存在、G0 失败、租约冲突、
  safe-stop 无证据拒绝、LS 末页 404 容忍（均以测试固化）。
  浏览器 QA（只读，Browser subagent）：`/#/training` 全部区块正确渲染、
  blocker 如实显示、控制台无 JS 错误（仅未登录 /auth/me 401 预期）、
  刷新状态保持；截图 `reports/gltc_web_qa_training_console.png`。

## 2026-08-08 最终验证

- 默认 hermetic suite：**1010 passed, 1 skipped, 5 deselected**（基线 914 → +96）。
- host MPS suite：`pytest -m host_mps` **5 passed**（普通 Terminal，AC 电源）。
- web：`tsc --noEmit` 干净；vite build 成功。
- DB：integrity_check=ok；migration 至 022；gold_region_v1=0；
  training_run（旧）4 行未动（supersession 账本 4 行）；training_run_v2 生产库 0 行（未提交任何真实训练）。
- 服务：8091 /v2/health ok（prod_20260805_v5_r1 未切换）；8092 200；
  8300 LS 存活；8400 healthy（ml_backend=disabled，GLTC D1）。
- LS：项目 19 = 1125 proposals（append-only）+ 13 no_proposal；项目 20 零泄漏；
  项目 1/10~13 未动。
- 无训练进程；本轮未启动任何真实训练；未切换生产 bundle；未删除任何文件。
