# Project Logic Chain V3 · ISSUES

## PLC3-ISSUE-001（P0，已复现）diagnostic ID/SHA 错配
- 状态：CONFIRMED_OPEN
- 复现：协议 zip 2/500；rq_v1 队列 0/250；double 0/200；blind 0/50。
- 根因：protocol_sets.py L230-231 独立排序；build_review_queue.py L28-29 位置 zip。
- 影响：250/250 任务 ID/SHA 不一致；未产生 gold_region，未污染人工真值。
- 处置：PLC3-001/002/003。

## PLC3-ISSUE-002 双状态源漂移
- JSON 250 pending vs DB 249 pending + 1 claimed。处置：PLC3-004。

## PLC3-ISSUE-003 旧 ls_payload 不可冒充 V2
- .sam_runs/ls_import_20260804_195327/ls_payload.json 仅 9 张，与 226 交集 0。
  保留作历史证据，禁止导入 V2 项目。

## PLC3-ISSUE-004 8091 /health 返回 not found
- 8091 存活但健康端点路径待核（recognize v2）。不阻断本轮；列入服务健康复核。

## PLC3-ISSUE-005 region box 校验拒绝 x1/y1=0 且无图像边界校验
- review.py `_validate_and_store_region` 用 `any(float(v) <= 0 ...)`，且无 width/height。
  处置：PLC3-005。

## PLC3-ISSUE-006 一个 arbiter region 覆盖整任务
- gold_region_report 中 `if arbs:` 对全部 key 走 superseded 轨道。处置：PLC3-005。

## PLC3-ISSUE-007（收尾复核发现，已关闭）API/批次门禁未收敛到 active 队列
- 状态：CLOSED（S12b）
- 现象：`/api/v1/review/status` 与 `batch_report` 统计全部 500 任务（含失效
  rq_v1）；运行中 8400 进程为旧代码。若 rq_v2 完成，失效 V1 的 pending 将永久
  阻断批次阶梯（§八红线）。
- 处置：红测试 3 条 → `/review/status` 走 `review_progress`（active/invalid
  分开）；新增 `/review/tasks-active`（默认）与 `/review/tasks-history`（失效
  证据，逐条 invalidated）；`batch_report` 改 `list_review_tasks_active()`；
  8400 graceful 重启。真实 API 对账 active=250/invalid=250 与 DB 一致。
- 证据：EXECUTION-LOG S12b；commit「fix: keep review api and batch gate on
  active queue only」；全量 914 passed。
