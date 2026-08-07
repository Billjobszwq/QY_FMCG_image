# Project Logic Chain V3 · EXECUTION-LOG

追加式，不覆盖历史。

## 2026-08-07 基线与复现

- `git rev-parse --short HEAD` → 7b2e268；分支 feat/unified-workbench-training-readiness。
- `git status --porcelain` → 仅 4 个受保护未跟踪目录（.quality/.sam_checkpoints/.sam_runs/.superpowers/）。
- 服务探测：8092=200、8400=200、8300=302（LS 登录跳转）、8091 / 根路径 404、/health {"error":"not found"}。
- 训练进程扫描：无 YOLO/QLoRA/classifier/finetune 训练进程（仅 oMLX 应用与 8092 monitor）。
- pytest tests/ → **819 passed, 1 skipped**（21.33s，miniconda python3）。
- P0 复现脚本（python3 内联）：
  - diagnostic_v1.json：photo_ids 500 / sha256 500，两数组各自 sorted=True；
  - 按位置 zip 对照 clean_manifest 真值：2/500 正确；
  - review_queue_diag_v1.json：250 项（double_review 200 + blind_manual 50），
    ID/SHA 配对 0/250 正确，唯一照片 226。
- sqlite3 .platform/platform.sqlite：integrity_check=ok；schema_migrations 001–018；
  review_task_v1：rq_v1 blind_manual 50 + double_review 200；review_event_v1=1；gold_region_v1=0。
- 阅读：GLOBAL_AGENT_ROUTING.md、CODEX-PROJECT-HANDBOOK.md、platform-v2/STATUS.md、
  sam-reannotation/STATUS.md、protocol_sets.py、build_review_queue.py、human_review_queue.py、
  import_u4_review_queue.py、review.py、store.py。
- 建立本档案目录与实施计划（纯文档基线，随后提交）。
