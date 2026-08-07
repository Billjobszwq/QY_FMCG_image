# Project Logic Chain V3 · MIGRATION-AND-COMPATIBILITY

## 数据库迁移计划
- migration 019：review_queue_ledger_v1 + review_task_invalidation_v1（追加式，
  触发器禁删改；ledger 字段：queue_version/status/root_cause/discovered_at/
  impact_summary/git_commit/evidence_path/superseded_by/created_at）。
- migration 020：gold_region_v1 追加 image_width/image_height/coord_version 列；
  submission 组支持（原子提交证据表 gold_region_submission_v1）。
- 迁移前置：store.backup（sqlite3 backup API）→ 备份 integrity_check → 再迁移。
- 迁移后：主库 integrity_check + 对账（任务数/事件数/账本行数）。

## 兼容策略（不删除历史代码/制品）
- diagnostic_v1.json：只读保留；其 photo_ids/sha256 数组仅作集合成员校验，
  配对一律走 canonical mapping。
- review_queue_diag_v1.json：只读保留；仅在账本中标记 invalid。
- review_task_v1 的 rq_v1 行：不改行；活动查询过滤 queue_version。
- scripts/build_review_queue.py：保留（v1 历史构建器），新脚本 build_review_queue_v2.py。
- src/labeling legacy：保留只读入口，不再产生正式事实（待现场复核后定稿）。
- 旧 ls_payload（9 张）：保留作证据，不进 V2。

## Legacy 适配器边界
- LS 对接收敛到 src/ls_platform（待 PLC3-006 现场复核确认）；
- 统一 Web 只经 8400 API；不允许前端直连 LS DB。
