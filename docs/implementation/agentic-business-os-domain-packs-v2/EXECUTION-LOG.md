# EXECUTION-LOG · Domain Packs V2（append-only）

> 任务书：`docs/implementation/agentic-business-os-domain-packs-v2/AGENT-EXECUTION-PROMPT.md`
> 时间均为本机 Asia/Shanghai。本文件只追加，不回改历史条目。

## 2026-08-11 · T0 现场冻结与安全基线

- 阅读完成：GLOBAL_AGENT_ROUTING.md、CODEX-PROJECT-HANDBOOK.md、docs/README.md、
  USER-HANDBOOK.md、OPERATOR-RUNBOOK.md、MODULE-AGENT-DEV-GUIDE.md、
  agentic-business-os-workbench-v1/（00–07 + README/STATUS/ISSUES/ACCEPTANCE）、
  project-logic-chain-v3/（STATUS/SOURCE-OF-TRUTH/CURRENT-LOGIC-CHAIN）、
  agentic-business-os-domain-packs-v2/ 全部文件。
- Git：branch `feat/nextgen-training-cycle-v2`，HEAD `d00953ad`
  （`docs: define continuous workflow and domain packs v2`，前一业务提交 `e5c4236d`）。
- worktree：仅主 worktree，无附加 worktree。tracked 工作树干净。
- 未跟踪资产（全部保护，不删不覆盖不移动不暂存）：`.datasets_nextgen/*`、
  `.micro_gold_v1/`、`.micro_gold_v2/`、`.micro_gold_v2_attempt1/`、`.quality/`、
  `.sam_checkpoints/`、`.sam_runs/`、`.superpowers/`、`adapter_config.json`、
  `cropped_images/`、`reports/nextgen_v2/*`。
- 服务：`./bin/abos status` → recognize/monitor/label_studio/app 全部 UP
  （recognize pid=59310 本脚本管理）；看门狗未运行。
- 训练进程：无（ps 核验仅有 8092 monitor 与 8301 yolo_backend 历史进程）。
- DB：`.platform/platform.sqlite` integrity_check=ok；63 张表；最新迁移
  `030_recognition_task_profile_contract`（028 state_projections_v2、029 profile_def_v1）。
- production：`.models/bundles/CURRENT.json` = `prod_20260805_v5_r1`（本轮不切换）。
- 运行事实快照（后续对账基准）：识别任务 11、Graph Runs 8、Agent Commands 5、
  Usage Event 1（来自 v2 审计文档，进入 Phase A 前将实时复核）。
- 声明：未 merge/push/deploy；未启动训练；未切换 production；未触碰用户资产。

## 下一动作

- Phase A-1：实时复现 ABOSV2-P0-001（主页旧 250 复活），写红测试。
