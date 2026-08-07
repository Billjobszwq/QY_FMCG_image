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
