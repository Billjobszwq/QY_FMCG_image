# EXECUTION-LOG — operational-scope-v5-correction-v1

时间均为本地时间（UTC+8），按顺序追加。

## 2026-08-13 开工基线

- 16:20 确认基线：branch=feat/nextgen-training-cycle-v2 HEAD=8e31708d584459fb38fedefe21b070bede36db57，tracked 工作树干净（32 个未跟踪目录均为数据/模型产物，不触碰）。
- 16:21 abos status：app/recognize/monitor/label_studio 全 UP；production=prod_v4_best_r1；训练进程 0。
- 16:23 sqlite backup API 备份 → .platform/backups/platform_pre_osv51_correction_20260813T162315.sqlite；备份与原库 integrity_check 均 ok。
- 16:26 BEFORE-STATE.md 落盘（HEAD/worktree/服务/进程/CURRENT/迁移/Gate/批次数量/导入作用域）。
- 16:27 快照五份证据到 before-snapshots/（gate.json、uatv7_report.json、test_report.json、browser_evidence.json、gate_negative_tests.json）。
- 16:28 启动全量 hermetic pytest 后台基线运行（记录真实失败，不采用静态 test_report.json 的 0 failed 口径）。
- 并行理解阶段：10 路阅读器（handbook/runbooks/scope 治理/gate 证据/import 管线/并行引擎/IAM users_v1/前端/registry 报告/DB 血缘）。
  - 并行引擎（已完成）：确认 run finalize 无条件 UPDATE 覆盖 timeout→cancelled 为根因，共 6 处竞态点。
  - scope 治理（已完成）：V5 自记 2 项未关闭 P1（UAT 批次残留、import 历史缺客户作用域），与本轮任务吻合。
  - registry/报告（已完成）：确认 gate_negative_tests.json 为手工静态文件、osv5_gate_evaluate.py 会覆写 UAT report.json（13 份过期报告漂移源头）、"42 checks"为 V5 生成时真值后被代码新增 10 条 check 漂移、Registry 125→126 漂移源头在 scope_registry.json 追加 md_customer_v1 后报告未同步。
